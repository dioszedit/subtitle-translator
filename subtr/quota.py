#!/usr/bin/env python3
"""
gemini_quota.py — Gemini API napi kérésszám nyilvántartása (gépszinten, kulcs szerint)

MIÉRT KELL: a Gemini API NEM adja vissza a maradék kvótát. Kipróbálva:
  - Service Usage API (consumerQuotaMetrics) → 403, API kulccsal tiltott (OAuth kell)
  - Cloud Quotas API                        → API kulccsal nem elérhető
  - models.get()                            → csak token-limitek, kvóta nincs
  - HTTP válaszfejlécek                     → EGYETLEN ratelimit-* fejléc sincs
Vagyis a napi limitbe csak akkor futunk bele, amikor már megtörtént (429).
Ez a modul ezért helyben számolja a hívásokat, és a futás ELŐTT megmondja,
belefér-e a tervezett munka.

A SZÁMLÁLÓ ALSÓ BECSLÉS — a maradék tehát FELSŐ korlát:
Csak azok a hívások kerülnek a naplóba, amelyek ezeken a scripteken keresztül
mentek ki ÉS sikeresen vissza is tértek. Kimarad ezért:
  - az API kulcs használata máshol (AI Studio webUI, curl, másik eszköz)
  - az 5xx-szel elhalt hívás, ami a szerveren már fogyaszthatott
  - a válasz megérkezése előtt megszakított (Ctrl-C) futás
Ami helyesen marad ki: a 429-cel elutasított kérés nem fogyaszt kvótát.
A kiírásokban ezért "legalább ennyit használtál" / "legfeljebb ennyi maradt"
szerepel — a valódi maradék ennél kevesebb is lehet.

A NAPLÓ GÉPSZINTŰ, NEM PROJEKTSZINTŰ — ez lényeges:
A napi kvóta az API KULCSHOZ (a mögötte lévő Google-projekthez) tartozik, nem
a munkakönyvtárhoz. Ha egy gépen több felirat-projekt fut ugyanazzal a kulccsal,
akkor MIND ugyanabból a napi keretből fogyaszt. Ezért a napló egyetlen közös
helyen él:

    ~/.gemini_quota/usage.json        (felülírható: GEMINI_QUOTA_FILE env-vál.)

és belül a kulcs UJJLENYOMATA szerint van bontva (sha256 első 12 hex jegye —
maga a kulcs SOHA nem kerül a fájlba). Így:
  - ugyanaz a kulcs több projektben  → közös számláló (helyesen)
  - más kulcs egy másik projektben   → külön számláló (helyesen)
A modul azt is följegyzi, melyik projektmappából mennyi hívás ment el, így
visszakereshető, hol fogyott a napi adag.

FONTOS — a nap nem helyi éjfélkor vált:
A Google ingyenes napi kvótája csendes-óceáni idő (America/Los_Angeles) szerint
nullázódik, nem magyar idő szerint. A modul ezért PT-dátum szerint könyvel.
(Ha a tzdata csomag nincs telepítve, fix UTC-8-ra esik vissza — ilyenkor a DST
miatt legfeljebb 1 óra csúszás lehet a napváltás körül.)

A LIMITEK ÖNTANULÓK — DE CSAK A NAPI LIMIT:
A napi limitet nem tippeljük: a 429-es hiba tartalmazza a `quotaValue`-t, és
amikor egy modell először belefut, a modul kiolvassa és elmenti. Innentől arra
a modellre pontos limitet ismer. Amíg nincs mért adat, a KNOWN_LIMITS /
DEFAULT_LIMIT becslést használja, és ezt jelzi is.

FONTOS: a Gemini TÖBBFÉLE 429-et ad, és csak az egyik jelenti azt, hogy mára
elfogyott a keret:
  - ...PerDay...    napi kérés-limit  → tényleg elfogyott, ezt tanuljuk meg
  - ...PerMinute... percenkénti limit → MÚLÓ, a retry-logika átvészeli
  - ...Tokens...    token-alapú limit → nem kérésszám, nem érdekel
A modul ezért a hiba `quotaId` mezője alapján osztályoz, és CSAK a napi
kérés-limitet jegyzi meg. Enélkül egy múló percenkénti 429 (amit magas
--agents értéknél rutinszerűen kapunk) örökre rossz napi limitet tanulna be,
és a nap hátralévő részére hamisan „kimerült"-nek jelölné a modellt.

PÁRHUZAMOS FUTÁS: a translate_with_gemini.py több agenttel dolgozik, és több
projekt is futhat egyszerre. Az írás ezért lock-fájllal védett, hogy a
párhuzamos növelések ne írják egymást felül.

HASZNÁLAT (parancssorból):
    py gemini_quota.py                 # mai fogyás modellenként
    py gemini_quota.py --days 7        # utolsó 7 nap
    py gemini_quota.py --projects      # mai fogyás projektmappa szerint is
    py gemini_quota.py --where         # hol van a napló
    py gemini_quota.py --reset         # mai számlálók nullázása (ha félrement)
    py gemini_quota.py --forget-limit gemini-3.6-flash   # rossz limit elfelejtése

HASZNÁLAT (kódból):
    import gemini_quota as gq
    gq.preflight("gemini-3.6-flash", needed=4)          # futás előtt: belefér?
    gq.record("gemini-3.6-flash")                        # SIKERES hívás után
    gq.note_limit_from_error("gemini-3.6-flash", exc)    # 429 esetén

A modul SOHA nem dob kivételt kifelé: ha a napló sérült vagy nem írható,
csendben tovább engedi a hívást. A kvótakövetés kényelmi funkció, nem lehet
oka annak, hogy egy fordítás vagy review elhaljon.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from subtr import config  # noqa: F401  (a .env betöltéséért)

KEEP_DAYS = 14
LOCK_TIMEOUT = 10.0     # másodperc — ennyit várunk a lock-ra
LOCK_STALE = 60.0       # ennél régebbi lock-ot elhagyottnak tekintünk

# Becsült ingyenes napi kérésszám (RPD), amíg 429-ből nem tanultunk pontosat.
# A "-lite" modellek jellemzően bőkezűbbek, de ez CSAK becslés.
KNOWN_LIMITS = {
    "gemini-3.1-flash-lite": 1000,
    "gemini-3.5-flash-lite": 1000,
    "gemini-2.5-flash-lite": 1000,
    "gemini-flash-lite-latest": 1000,
}
DEFAULT_LIMIT = 20


# --------------------------------------------------------------------------
# Napló helye + kulcs-ujjlenyomat
# --------------------------------------------------------------------------

def ledger_path() -> str:
    """A gépszintű napló útvonala. GEMINI_QUOTA_FILE-lal felülírható."""
    override = os.environ.get("GEMINI_QUOTA_FILE")
    if override:
        return os.path.abspath(override)
    return os.path.join(os.path.expanduser("~"), ".gemini_quota", "usage.json")


def _api_key() -> str:
    """API kulcs beolvasása — env-változókból.

    A .env betöltése a subtr.config dolga (import-időkor lefut), ide már
    csak az os.environ-ba került érték olvasása tartozik.
    """
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        v = os.environ.get(var)
        if v:
            return v.strip()
    return ""


def key_fingerprint() -> str:
    """A kulcs rövid, visszafejthetetlen ujjlenyomata. A kulcs sosem kerül fájlba."""
    k = _api_key()
    if not k:
        return "nincs-kulcs"
    return hashlib.sha256(k.encode("utf-8")).hexdigest()[:12]


def _project_name() -> str:
    """A hívó projekt azonosítója a bontáshoz (mappanév + szülő)."""
    try:
        cwd = os.getcwd()
        parent = os.path.basename(os.path.dirname(cwd))
        return f"{parent}/{os.path.basename(cwd)}" if parent else os.path.basename(cwd)
    except Exception:
        return "?"


# --------------------------------------------------------------------------
# Dátum (csendes-óceáni idő szerint)
# --------------------------------------------------------------------------

def pacific_now():
    """Aktuális idő csendes-óceáni zónában. tzdata nélkül fix UTC-8-ra esik vissza."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(timezone.utc).astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception:
        return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-8)))


def today_key() -> str:
    return pacific_now().strftime("%Y-%m-%d")


def _pacific_is_exact() -> bool:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/Los_Angeles")
        return True
    except Exception:
        return False


def hours_to_reset() -> float:
    """Hány óra a következő PT-éjfélig (a kvóta nullázásáig)."""
    try:
        now = pacific_now()
        nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(0.0, (nxt - now).total_seconds() / 3600.0)
    except Exception:
        return float("nan")


# --------------------------------------------------------------------------
# Lock (párhuzamos írás ellen)
# --------------------------------------------------------------------------

class _Lock:
    """Egyszerű fájl-alapú lock. Windows-on is működik (O_EXCL)."""

    def __init__(self, target: str):
        self.lock_path = target + ".lock"
        self.fd = None

    def __enter__(self):
        deadline = time.time() + LOCK_TIMEOUT
        while True:
            # Elhagyott lock felszabadítása
            try:
                if os.path.isfile(self.lock_path) and \
                        time.time() - os.path.getmtime(self.lock_path) > LOCK_STALE:
                    os.remove(self.lock_path)
            except Exception:
                pass
            try:
                self.fd = os.open(self.lock_path,
                                  os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if time.time() > deadline:
                    # Nem várunk tovább — a könyvelés nem állíthatja meg a munkát.
                    return self
                time.sleep(0.05)
            except Exception:
                return self

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                os.close(self.fd)
                os.remove(self.lock_path)
        except Exception:
            pass
        return False


# --------------------------------------------------------------------------
# Napló írás/olvasás
# --------------------------------------------------------------------------

def _empty() -> dict:
    return {"keys": {}}


def _load() -> dict:
    p = ledger_path()
    if not os.path.isfile(p):
        return _empty()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("keys", {})
        return data
    except Exception:
        # Sérült napló nem állíthatja meg a munkát.
        return _empty()


def _save(data: dict) -> None:
    try:
        cutoff = (pacific_now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        for bucket in data.get("keys", {}).values():
            if isinstance(bucket.get("days"), dict):
                bucket["days"] = {d: v for d, v in bucket["days"].items() if d >= cutoff}

        p = ledger_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        pass


def _bucket(data: dict) -> dict:
    """A jelenlegi API kulcshoz tartozó rész a naplóban."""
    b = data.setdefault("keys", {}).setdefault(key_fingerprint(), {})
    b.setdefault("limits", {})
    b.setdefault("days", {})
    return b


# --------------------------------------------------------------------------
# Publikus API
# --------------------------------------------------------------------------

def record(model: str, n: int = 1) -> None:
    """Egy (vagy n) SIKERES API hívás könyvelése.

    Csak olyan hívást könyvelj, ami tényleg lefutott a modellen. A 429-cel
    elutasított kérés nem fogyaszt kvótát, azt NE add ide.
    """
    try:
        with _Lock(ledger_path()):
            data = _load()
            b = _bucket(data)
            day = b["days"].setdefault(today_key(), {})
            rec = day.setdefault(model, {})
            rec["calls"] = int(rec.get("calls", 0)) + n
            by_proj = rec.setdefault("by_project", {})
            proj = _project_name()
            by_proj[proj] = int(by_proj.get(proj, 0)) + n
            _save(data)
    except Exception:
        pass


def note_limit(model: str, limit: int) -> None:
    """Megtanult NAPI limit elmentése. Tartós — nem évül a napi számlálókkal."""
    try:
        if not limit or limit <= 0:
            return
        with _Lock(ledger_path()):
            data = _load()
            b = _bucket(data)
            b["limits"][model] = int(limit)
            _save(data)
    except Exception:
        pass


def forget_limit(model: str) -> bool:
    """Egy megtanult limit törlése. True, ha volt mit törölni.

    Azért kell, mert a limitek tartósak: ha egyszer rossz érték került be
    (korábbi verzió a percenkénti 429-et is napi limitnek vette, vagy teszt
    közben keletkezett bejegyzés), az magától soha nem javulna ki.
    """
    try:
        with _Lock(ledger_path()):
            data = _load()
            b = _bucket(data)
            if model not in b.get("limits", {}):
                return False
            del b["limits"][model]
            _save(data)
            return True
    except Exception:
        return False


def note_exhausted(model: str) -> None:
    """A mai nap megjelölése: ez a modell belefutott a NAPI limitbe."""
    try:
        with _Lock(ledger_path()):
            data = _load()
            b = _bucket(data)
            day = b["days"].setdefault(today_key(), {})
            day.setdefault(model, {})["exhausted"] = True
            _save(data)
    except Exception:
        pass


# A hibaszövegben a violation-ök sorrendje: quotaMetric, quotaId, quotaValue.
# A quotaId mondja meg, MILYEN limitbe futottunk bele — ez a lényeg, mert a
# percenkénti 429 múló, a napi nem.
_QUOTA_ID_RE = re.compile(r"quotaId['\"]?\s*:\s*['\"]?([\w.\-]+)")
_VIOLATION_RE = re.compile(
    r"quotaId['\"]?\s*:\s*['\"]?([\w.\-]+).{0,300}?"
    r"quotaValue['\"]?\s*:\s*['\"]?(\d+)", re.DOTALL)


def _is_daily_request_quota(quota_id: str) -> bool:
    """Napi KÉRÉS-limit? (a percenkénti és a token-alapú kvóta nem az)"""
    q = quota_id.lower()
    return "perday" in q and "token" not in q


def _is_429(s: str) -> bool:
    return "429" in s or "RESOURCE_EXHAUSTED" in s


def _parse_quota_value(exc) -> "int | None":
    """A 429-ből a NAPI kérés-limit. Percenkénti/token-limitnél None."""
    s = str(exc)
    if not _is_429(s):
        return None
    for quota_id, value in _VIOLATION_RE.findall(s):
        if _is_daily_request_quota(quota_id):
            return int(value)
    return None


def _is_daily_exhaustion(exc) -> bool:
    """Tényleg a napi keret fogyott el, vagy csak percenkénti rate limit?"""
    s = str(exc)
    if not _is_429(s):
        return False
    quota_ids = _QUOTA_ID_RE.findall(s)
    if quota_ids:
        return any(_is_daily_request_quota(q) for q in quota_ids)
    # Nincs strukturált violation a hibában — a nyers szövegre esünk vissza.
    # Ha az sem árulkodik, NEM tekintjük napi kimerülésnek: a téves riasztás
    # (a nap hátralévő részére letiltjuk a modellt) rosszabb, mint ha egy
    # valódi kimerülést csak a következő 429-nél veszünk észre.
    return bool(re.search(r"per\s*day|daily|napi", s, re.IGNORECASE))


def note_limit_from_error(model: str, exc) -> "int | None":
    """429 feldolgozása: a NAPI limit megtanulása + a mai nap megjelölése.

    Visszatér: a kiolvasott napi limit, vagy None (ha a 429 nem napi, vagy
    nincs benne érték). A percenkénti (RPM) és token-alapú 429-et szándékosan
    figyelmen kívül hagyja — azokat a hívó retry-logikája kezeli, és nem
    jelentik azt, hogy a napi keret elfogyott.
    """
    try:
        if not _is_daily_exhaustion(exc):
            return None
        note_exhausted(model)
        limit = _parse_quota_value(exc)
        if limit:
            note_limit(model, limit)
        return limit
    except Exception:
        return None


def status(model: str) -> dict:
    """Mai állapot egy modellre (a jelenlegi API kulcs szerint).

    A `used` ALSÓ becslés, a `remaining` ezért FELSŐ korlát — lásd a modul
    docstringjében, mi marad ki a könyvelésből.
    """
    fallback = KNOWN_LIMITS.get(model, DEFAULT_LIMIT)
    try:
        data = _load()
        b = data.get("keys", {}).get(key_fingerprint(), {})
        rec = b.get("days", {}).get(today_key(), {}).get(model, {})
        used = int(rec.get("calls", 0))
        exhausted = bool(rec.get("exhausted", False))
        measured = model in b.get("limits", {})
        limit = int(b["limits"][model]) if measured else fallback
        # Ha ma már volt napi 429, a maradék nulla — függetlenül attól, mit
        # mutat a számláló. (A számláló alulszámolhat, ezért fordulhatna elő
        # a "maradék 5, de belefutott a limitbe" önellentmondás.)
        remaining = 0 if exhausted else max(0, limit - used)
        return {"used": used, "limit": limit, "limit_measured": measured,
                "exhausted": exhausted, "remaining": remaining,
                "by_project": dict(rec.get("by_project", {}))}
    except Exception:
        return {"used": 0, "limit": fallback, "limit_measured": False,
                "exhausted": False, "remaining": fallback, "by_project": {}}


def preflight(model: str, needed: int = 0, quiet: bool = False) -> bool:
    """Futás előtti kvóta-jelzés. Visszatér: belefér-e a tervezett munka.

    NEM állítja meg a futást — csak jelez. A megfogalmazás szándékosan
    "legalább" / "legfeljebb": a számláló alsó becslés (lásd a modul
    docstringjét), így a valódi maradék ennél kevesebb is lehet.
    """
    try:
        st = status(model)
        src = "mért" if st["limit_measured"] else "becsült"
        line = (f"Kvóta ({model}): ma legalább {st['used']}/{st['limit']} "
                f"elhasználva ({src} limit), maradék legfeljebb {st['remaining']}")
        if needed:
            line += f", ez a futás {needed} kérés"
        if not quiet:
            print(line)
            others = {p: n for p, n in st["by_project"].items() if p != _project_name()}
            if others:
                detail = ", ".join(f"{p}: {n}" for p, n in sorted(others.items()))
                print(f"  ebből más projektből: {detail}")

        if st["exhausted"]:
            if not quiet:
                print(f"  [!] Ez a modell ma MÁR belefutott a napi limitbe (429). "
                      f"Válts modellt, vagy várj ~{hours_to_reset():.1f} órát "
                      f"(PT-éjfél).")
            return False

        if needed and needed > st["remaining"]:
            if not quiet:
                print(f"  [!] Valószínűleg NEM fér bele ({needed} kérés kell, "
                      f"legfeljebb {st['remaining']} maradt). Válts modellt, vagy "
                      f"futtasd darabolva (--start-chunk/--end-chunk + --suffix).")
            return False
        return True
    except Exception:
        return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_table(days: int, show_projects: bool) -> None:
    data = _load()
    fp = key_fingerprint()
    b = data.get("keys", {}).get(fp, {})
    limits = b.get("limits", {})
    all_days = sorted(b.get("days", {}).keys(), reverse=True)[:days]

    zone = "PT (pontos)" if _pacific_is_exact() else "PT (közelítő, UTC-8 — tzdata nincs)"
    print(f"Gemini kérésszám — a napok {zone} szerint váltanak")
    print(f"Napló:      {ledger_path()}")
    print(f"API kulcs:  {fp} (ujjlenyomat — a kulcs nem kerül a fájlba)")
    print(f"Mai nap:    {today_key()}  (nullázásig ~{hours_to_reset():.1f} óra)")
    other_keys = [k for k in data.get("keys", {}) if k != fp]
    if other_keys:
        print(f"Megjegyzés: a naplóban {len(other_keys)} másik kulcs is szerepel "
              f"(azoknak külön kvótájuk van).")
    if limits:
        # A megtanult limitek tartósak, ezért látszódjanak: így derül ki, ha
        # egy rossz érték ragadt be (--forget-limit <modell> törli).
        print("Megtanult napi limitek: "
              + ", ".join(f"{m}={limits[m]}" for m in sorted(limits)))
    print()

    if not all_days:
        print("Ehhez a kulcshoz még nincs könyvelt Gemini-hívás.")
        return

    print("A számláló ALSÓ becslés: csak az ezekkel a scriptekkel indított, sikeres")
    print("hívások kerülnek bele. Ha ugyanezt a kulcsot máshol is használod (AI Studio,")
    print("curl, másik eszköz), az láthatatlanul fogyaszt — a valódi maradék kevesebb.")
    print()

    for d in all_days:
        print(f"[{d}]")
        entries = b["days"][d]
        for model in sorted(entries):
            rec = entries[model]
            used = int(rec.get("calls", 0))
            measured = model in limits
            limit = int(limits[model]) if measured else KNOWN_LIMITS.get(model, DEFAULT_LIMIT)
            src = "mért" if measured else "becs"
            exhausted = bool(rec.get("exhausted"))
            flag = "  <-- belefutott a limitbe (429)" if exhausted else ""
            remaining = 0 if exhausted else max(0, limit - used)
            print(f"   {model:26s} {used:4d}/{limit:<5d} ({src}) "
                  f"maradék max {remaining:<5d}{flag}")
            if show_projects:
                for p, n in sorted(rec.get("by_project", {}).items(),
                                   key=lambda kv: -kv[1]):
                    print(f"      {p:38s} {n:4d}")
        print()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="Gemini API napi kérésszám nyilvántartása gépszinten, API kulcs "
                    "szerint bontva. A maradék kvóta az API-ból NEM kérdezhető le, "
                    "ezért számoljuk helyben.")
    ap.add_argument("--days", type=int, default=1,
                    help="hány nap jelenjen meg (default: 1 = csak ma)")
    ap.add_argument("--projects", action="store_true",
                    help="projektmappa szerinti bontás is")
    ap.add_argument("--where", action="store_true",
                    help="csak a napló útvonalát írja ki")
    ap.add_argument("--reset", action="store_true",
                    help="a MAI számlálók nullázása (ha félrement a könyvelés)")
    ap.add_argument("--model", type=str, default=None,
                    help="csak ezt a modellt írja ki (a --reset is csak erre hat)")
    ap.add_argument("--forget-limit", type=str, default=None, metavar="MODELL",
                    help="egy megtanult NAPI limit törlése (a limitek tartósak, "
                         "a --reset nem érinti őket)")
    args = ap.parse_args()

    if args.where:
        print(ledger_path())
        return

    if args.forget_limit:
        if forget_limit(args.forget_limit):
            print(f"Megtanult limit törölve: {args.forget_limit}")
        else:
            print(f"Ehhez a modellhez nincs megtanult limit: {args.forget_limit}")
        return

    if args.reset:
        with _Lock(ledger_path()):
            data = _load()
            b = _bucket(data)
            day = b.get("days", {}).get(today_key())
            if not day:
                print("Ma nincs mit nullázni.")
                return
            if args.model:
                if args.model in day:
                    del day[args.model]
                    print(f"Nullázva: {args.model} ({today_key()})")
                else:
                    print(f"Ma nincs könyvelt hívás erre: {args.model}")
            else:
                b["days"][today_key()] = {}
                print(f"Minden mai számláló nullázva ({today_key()})")
            _save(data)
        return

    if args.model:
        st = status(args.model)
        src = "mért" if st["limit_measured"] else "becsült"
        print(f"{args.model}: ma {st['used']}/{st['limit']} ({src} limit), "
              f"maradék ~{st['remaining']}"
              + ("  [ma belefutott a limitbe]" if st["exhausted"] else ""))
        return

    _print_table(max(1, args.days), args.projects)


if __name__ == "__main__":
    main()
