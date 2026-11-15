#!/usr/bin/env python3
"""
subtr.py models — Gemini API: modellek, limitek, kivezetések EGY helyen

MIÉRT KELL: a Gemini-modellek kínálata és a free tier limitjei néhány hetente
változnak (új modell jön, régit átirányítanak, a napi keret módosul). Eddig ezek
több helyen voltak beégetve. Innentől egyetlen GENERÁLT fájl tartja őket:

    subtr/gemini_models.json      ← `subtr.py models refresh` írja, kézzel ne szerkeszd

Ez CSAK nyilvános adatot tartalmaz: a Gemini API FREE TIER limitjeit (ami
mindenkinek elérhető — a repo nyilvános), név → kód, státusz, kivezetések. A
refresh más tier oldalát nem írja bele. Ami a saját API-kulcsodtól függ, az
gépszinten, a kvótanapló mellett él:

    ~/.gemini_quota/models.json   (felülírható: GEMINI_MODELS_LOCAL_FILE)

kulcs-ujjlenyomat szerint bontva (maga a kulcs nem kerül bele):
  - mely modelleket kínálja neked a `models.list`,
  - a saját (fizetős) tiered limitjei — `models refresh --local`; ezek a
    kulcsodra felülírják a repó Free tier adatait (`models reset-local` törli).
A kulcsodra 429-ből tanult napi limit (kvótanapló) mindkettőnél erősebb —
lásd quota.limit_for.

Ezt olvassa:
  - a quota.py           a napi limitekhez (preflight, `subtr.py quota`),
  - a config.py          a kivezetett / átirányított modellek cseréjéhez,
  - a providers/gemini   a napi limit elérésekor a modellváltáshoz.

HONNAN JÖNNEK AZ ADATOK (refresh):
  1. Limitek (RPM / TPM / RPD) és tier — az AI Studio rate-limit oldaláról.
     API-kulccsal ez NEM kérdezhető le (lásd quota.py docstring), ezért a
     felhasználó kimásolja az oldalt:
        https://aistudio.google.com/rate-limit  →  „All models” kapcsoló BE
        →  Ctrl+A, Ctrl+C  →  py subtr.py models refresh
     A script a vágólapról olvas (vagy --file / --stdin).
  2. Név → modellkód, státusz (Stable / Preview / New), leállított modellek —
     a nyilvános docs-oldalról: https://aistudio.google.com/docs/models
  3. Kivezetések (leállás dátuma, utód, átirányítás és annak kezdete) —
     https://aistudio.google.com/docs/deprecations
  4. Mely modelleket kínálja ténylegesen az API a kulcsodnak — `models.list`
     (GEMINI_API_KEY kell) → a gépszintű fájlba.
A 2–4. forrás hibája nem állítja meg a frissítést: ami nem jött le, az a
korábbi adatból marad, és a kimenet jelzi.

MODELLVÁLTÁS NAPI LIMITNÉL (providers/gemini.call_json):
    SUBTR_GEMINI_ON_QUOTA=off | ask | auto        (defaults.env: ask)
    SUBTR_GEMINI_FALLBACK_MODELS=a,b,c            (sorrend = preferencia)
  ask:  terminálban felkínálja a listából a még használható modelleket
        (maradék kerettel), és megkérdezi, melyikre váltson. Nem interaktív
        futásnál (pl. ha Claude Code futtatja) kérdés nélkül úgy vált, mint az auto.
  auto: kérdés nélkül az első még használható modellre vált, és kiírja.
  off:  nem vált — a futás a napi limitnél megáll.
Csak olyan modellre vált, amelyik a gemini_models.json-ban szöveges modellként
szerepel, a tieren nem 0 a limitje, a kulcsod API-listáján rajta van (ha ez
ismert), és ma még nem merült ki. A váltás folyamatszintű.

HASZNÁLAT:
    py subtr.py models                  # szöveges modellek, limitek, mai fogyás
    py subtr.py models --all            # minden kategória
    py subtr.py models refresh          # frissítés a vágólapról
    py subtr.py models refresh --open   # előbb megnyitja a rate-limit oldalt
    py subtr.py models refresh --file oldal.txt [--dry-run]
    py subtr.py models refresh --no-limits   # csak modellek/kivezetések, limitek maradnak
    py subtr.py models refresh --local       # saját (fizetős) tier limitjei, csak a gépedre
    py subtr.py models reset-local           # vissza a repó Free tier adataira
"""

import argparse
import copy
import html
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from datetime import date, datetime
from pathlib import Path

from subtr import config

DATA_PATH = Path(__file__).with_name("gemini_models.json")
RATE_LIMIT_URL = "https://aistudio.google.com/rate-limit"
DOCS_MODELS_URL = "https://aistudio.google.com/docs/models"
DOCS_DEPRECATIONS_URL = "https://aistudio.google.com/docs/deprecations"
STALE_DAYS = 30              # ennél régebbi adatnál frissítést javasol
TEXT_CATEGORY = "Text-out models"
ON_QUOTA_MODES = ("off", "ask", "auto")
MIN_EXPECTED_ROWS = 10       # „All models” nélkül csak 2-3 sor látszik
UNLIMITED = "unlimited"      # file_limit visszatérése korlátlan RPD-nél

ON_QUOTA_KEY = "SUBTR_GEMINI_ON_QUOTA"
FALLBACK_KEY = "SUBTR_GEMINI_FALLBACK_MODELS"

# A modellváltás kérdése (párhuzamos fordításnál worker-szálon fut) erre az
# eseményre megszakad — a fő szál Ctrl+C-nél állítja be (providers.gemini.cancel_prompts).
CANCEL = threading.Event()


# ──────────────────────────────────────────────────────────────────────────
# Az adatfájlok olvasása
# ──────────────────────────────────────────────────────────────────────────

_CACHE = {}


def _empty() -> dict:
    return {"models": {}, "deprecations": {}}


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        return loaded if isinstance(loaded, dict) else default
    except (OSError, ValueError):
        return default


def load(path=None) -> dict:
    """A repóbeli adatfájl (folyamatonként egyszer olvasva). Hiányzó vagy
    sérült fájlnál üres szerkezet — a hívók ilyenkor a régi viselkedésre esnek
    vissza (becsült limit, nincs csere)."""
    p = str(path or DATA_PATH)
    if p not in _CACHE:
        data = _read_json(p, _empty())
        data.setdefault("models", {})
        data.setdefault("deprecations", {})
        _CACHE[p] = data
    return _CACHE[p]


def local_path() -> Path:
    """A gépszintű, kulcsfüggő adatok fájlja (a kvótanapló mellett)."""
    override = os.environ.get("GEMINI_MODELS_LOCAL_FILE")
    if override:
        return Path(override).resolve()
    from subtr import quota
    return Path(quota.ledger_path()).with_name("models.json")


def _local() -> dict:
    key = f"local:{local_path()}"
    if key not in _CACHE:
        data = _read_json(local_path(), {})
        data.setdefault("keys", {})
        _CACHE[key] = data
    return _CACHE[key]


def clear_cache() -> None:
    _CACHE.clear()


REPO_TIER = "Free tier"        # a repóbeli fájl EZT a tiert tartja — mindenkinek elérhető


def local_limits():
    """A jelenlegi kulcshoz `models refresh --local`-lal mentett saját (fizetős
    tier) limitek: {"tier", "updated", "models"} — vagy None."""
    from subtr import quota
    entry = _local()["keys"].get(quota.key_fingerprint())
    lim = entry.get("limits") if isinstance(entry, dict) else None
    return lim if isinstance(lim, dict) and isinstance(lim.get("models"), dict) else None


def model_info(model: str):
    """A modell adatai: a repóbeli (Free tier) adat, a kulcsodhoz mentett saját
    limitekkel (refresh --local) felülírva, ha vannak."""
    info = load()["models"].get(model)
    own = local_limits()
    if own and model in own["models"]:
        merged = dict(info or {})
        merged.update(own["models"][model])
        return merged
    return info


def all_model_ids() -> list:
    own = local_limits()
    return sorted(set(load()["models"]) | set(own["models"] if own else {}))


def limits_source(model: str = "") -> str:
    """A limit forrás-címkéje a kiírásokhoz."""
    own = local_limits()
    if own and (not model or model in own["models"]):
        return f"saját limit: {own.get('tier') or '?'} {own.get('updated') or ''}".strip()
    return f"AI Studio {load().get('tier') or REPO_TIER} {data_date()}".strip()


def api_models():
    """A jelenlegi kulcs `models.list`-je (halmaz) a gépszintű fájlból, vagy
    None, ha ehhez a kulcshoz még nem futott refresh."""
    from subtr import quota
    entry = _local()["keys"].get(quota.key_fingerprint())
    if not isinstance(entry, dict) or not isinstance(entry.get("models"), list):
        return None
    return set(entry["models"])


def in_api(model: str):
    """True / False: kínálja-e a kulcsod API-ja; None: nem ismert."""
    models = api_models()
    return None if models is None else model in models


def file_limit(model: str):
    """A repóbeli adatfájl napi limitje (RPD): int, UNLIMITED, vagy None, ha a
    modell nem szerepel benne. 0: ezen a tieren nem használható."""
    info = model_info(model)
    if not info or "rpd" not in info:
        return None
    rpd = info["rpd"]
    if rpd is None:
        return UNLIMITED
    return int(rpd) if isinstance(rpd, (int, float)) else None


def data_date() -> str:
    return str(load().get("updated") or "")


def _parse_iso(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _routing_since(dep: dict):
    """Az átirányítás kezdete (date), None, ha nincs átirányítás."""
    if not dep.get("routes"):
        return None
    return _parse_iso(dep.get("routes_from")) or date.min


def active_replacement(model: str, today=None, data=None):
    """Ha a modellt a Google MÁR átirányítja / leállította: (utód, ok), különben
    None. Láncot is követ (a → b → c), legfeljebb 5 lépésig. `data`: más
    adatfájl-tartalom a betöltött helyett (refresh közben az új)."""
    today = today or date.today()
    deps = (data or load())["deprecations"]
    current, reasons, seen = model, [], {model}
    for _ in range(5):
        dep = deps.get(current)
        if not dep or not dep.get("replacement"):
            break
        routing = _routing_since(dep)
        shutdown = _parse_iso(dep.get("shutdown"))
        if routing is not None and routing <= today:
            reason = f"a Google a {current} hívásait a {dep['replacement']} modellre irányítja át"
        elif shutdown and shutdown <= today:
            reason = f"a {current} {shutdown.isoformat()}-én leállt"
        else:
            break
        nxt = dep["replacement"]
        if nxt in seen:
            break
        reasons.append(reason)
        seen.add(nxt)
        current = nxt
    if current == model:
        return None
    return current, "; ".join(reasons)


def upcoming_shutdown(model: str, today=None, data=None):
    """Bejelentett, de még el nem jött leállás / átirányítás: (dátum, utód) vagy None."""
    today = today or date.today()
    dep = (data or load())["deprecations"].get(model)
    if not dep or active_replacement(model, today, data):
        return None
    dates = [d for d in (_routing_since(dep), _parse_iso(dep.get("shutdown")))
             if d and d > today]
    if dates:
        return min(dates).isoformat(), dep.get("replacement") or ""
    return None


# ──────────────────────────────────────────────────────────────────────────
# Modellváltás napi limitnél
# ──────────────────────────────────────────────────────────────────────────

def on_quota_mode() -> str:
    value = config.setting(ON_QUOTA_KEY, "off").lower() or "off"
    if value not in ON_QUOTA_MODES:
        print(f"FIGYELEM: érvénytelen {ON_QUOTA_KEY}={value!r} "
              f"(lehet: {' | '.join(ON_QUOTA_MODES)}) — nem váltok modellt.")
        return "off"
    return value


def fallback_models() -> list:
    raw = config.setting(FALLBACK_KEY, "")
    out = []
    for name in re.split(r"[,\s]+", raw):
        if name and name not in out:
            out.append(name)
    return out


def fallback_candidates(exhausted: str, tried=(), skipped=None) -> list:
    """A beállított tartaléklistából a még használható modellek, sorrendben:
    [{"model", "remaining", "limit", "source"}]. Csak az lehet tartalék, ami a
    gemini_models.json-ban szöveges modellként szerepel — elírt vagy ismeretlen
    névre váltani azt jelentené, hogy a futás hátralévő része 404-gyel bukik.
    A kihagyott modellek okát a `skipped` listába teszi: [(modell, ok)]."""
    from subtr import quota
    note = skipped.append if skipped is not None else (lambda item: None)
    skip = {exhausted, *tried}
    ledger = quota.load_ledger()
    out, seen = [], set()
    for name in fallback_models():
        rep = active_replacement(name)
        model = rep[0] if rep else name
        if model in skip or model in seen:
            continue
        seen.add(model)
        info = model_info(model)
        if not info:
            note((name, "nincs a gemini_models.json-ban (elírás, vagy frissítés kell)"))
            continue
        if info.get("category") != TEXT_CATEGORY:
            note((model, f"nem szöveges modell ({info.get('category')})"))
            continue
        if in_api(model) is False:
            note((model, "a kulcsod API-listáján nincs"))
            continue
        # A 0-s limitet is a kulcsodra érvényes limitből nézzük (429-ből tanult >
        # fájl): a fájl egy tier adata, egy másik tierű kulcsnál lehet keret.
        st = quota.status(model, ledger=ledger)
        if st["limit"] == 0:
            note((model, f"nem használható (napi limit 0, {st.get('limit_source')})"))
            continue
        if st["exhausted"] or st["remaining"] <= 0:
            note((model, "ma már kimerült"))
            continue
        out.append({"model": model, "remaining": st["remaining"],
                    "limit": st["limit"], "source": st.get("limit_source", "")})
    return out


def _ask(prompt: str, input_fn):
    """input() úgy, hogy worker-szálon se ragadjon be: a fő szál Ctrl+C-je
    (CANCEL) megszakítja. A fő szálon simán hív — ott a Ctrl+C magától jön."""
    if threading.current_thread() is threading.main_thread():
        return input_fn(prompt)
    box = queue.Queue()

    def reader():
        try:
            box.put((True, input_fn(prompt)))
        except BaseException as e:      # EOFError, KeyboardInterrupt is
            box.put((False, e))
    threading.Thread(target=reader, daemon=True).start()
    while True:
        if CANCEL.is_set():
            raise KeyboardInterrupt
        try:
            ok, value = box.get(timeout=0.2)
        except queue.Empty:
            continue
        if not ok:
            raise value
        return value


def choose_fallback(exhausted: str, *, tried=(), mode=None, input_fn=input,
                    interactive=None):
    """A napi limitbe futott modell helyett választott modell, vagy None.
    `mode` nélkül a SUBTR_GEMINI_ON_QUOTA dönt. A Ctrl+C (KeyboardInterrupt)
    NEM „ne váltson” válasz: továbbmegy, hogy a futás megszakadjon."""
    mode = mode or on_quota_mode()
    if mode == "off":
        print(f"  A {exhausted} napi kerete elfogyott. Automatikus modellváltás: "
              f"{ON_QUOTA_KEY}=ask vagy auto (.env).")
        return None
    skipped = []
    cands = fallback_candidates(exhausted, tried, skipped)
    if not cands:
        print(f"  A {exhausted} napi kerete elfogyott, és a {FALLBACK_KEY} listán "
              f"nincs más használható modell ({', '.join(fallback_models()) or 'üres'}).")
        for model, reason in skipped:
            print(f"    kihagyva: {model} — {reason}")
        return None

    if mode == "ask" and interactive is None:
        # A kérdés csak akkor látszik, ha a kimenet is terminál: átirányított
        # stdout-nál (… > run.log) a prompt a fájlba menne, a futás pedig várna.
        try:
            interactive = sys.stdin.isatty() and sys.stdout.isatty()
        except (AttributeError, ValueError):
            interactive = False
    from subtr.quota import fmt_limit
    if mode == "auto" or not interactive:
        c = cands[0]
        why = (f"{ON_QUOTA_KEY}=auto" if mode == "auto"
               else f"{ON_QUOTA_KEY}=ask, de nem interaktív a futás — nincs kit kérdezni")
        print(f"  Automatikus váltás ({why}): {exhausted} → {c['model']} "
              f"(ma még legfeljebb {fmt_limit(c['remaining'])} kérés).")
        return c["model"]

    print(f"\n  A {exhausted} napi kerete elfogyott. Használható modellek:")
    for i, c in enumerate(cands, 1):
        print(f"    {i}. {c['model']:28s} ma még legfeljebb {fmt_limit(c['remaining'])} "
              f"kérés (napi limit {fmt_limit(c['limit'])}, {c['source']})")
    print("    0. ne váltson — a futás a limitnél megáll")
    while True:
        try:
            ans = _ask("  Melyikre váltsak? [1]: ", input_fn).strip()
        except EOFError:
            print()
            return None
        if ans == "":
            return cands[0]["model"]
        if ans.lower() in ("0", "n", "q"):
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(cands):
            return cands[int(ans) - 1]["model"]
        if ans in [c["model"] for c in cands]:
            return ans
        print(f"  Adj meg egy számot 0 és {len(cands)} között.")


# ──────────────────────────────────────────────────────────────────────────
# Az AI Studio rate-limit oldal (kimásolt szöveg) feldolgozása
# ──────────────────────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([KMB]?)$", re.I)
_THOUSANDS_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")
_TIER_RE = re.compile(r"^(free tier|tier \d+|paid tier.*)$", re.I)
_MULT = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def parse_amount(text: str):
    """'250K' → 250000, '14.4K' → 14400, '1,500' → 1500 (ezres tagolás),
    '14,4K' → 14400, 'Unlimited' → None. Más: ValueError."""
    s = text.strip()
    if s.lower() in ("unlimited", "korlátlan"):
        return None
    if _THOUSANDS_RE.match(s):
        return int(s.replace(",", ""))
    m = _AMOUNT_RE.match(s)
    if not m:
        raise ValueError(s)
    return int(round(float(m.group(1).replace(",", ".")) * _MULT[m.group(2).upper()]))


def _ratio(token: str):
    if token.count("/") != 1:
        return None
    used, limit = token.split("/")
    try:
        return parse_amount(used), parse_amount(limit)
    except ValueError:
        return None


def parse_rate_limit_page(text: str) -> dict:
    """A kimásolt oldal → {"tier", "rows": [{label, category, rpm, tpm, rpd,
    used: {rpm, tpm, rpd}}]}. Soronként vagy tabulátorral tagolt másolatot is
    elfogad; a „Tools” (grounding) szakasznál megáll."""
    tokens = [c.strip() for line in text.splitlines()
              for c in line.split("\t") if c.strip()]
    tier = next((t for t in tokens if _TIER_RE.match(t)), None)
    rows, i = [], 2
    while i + 2 < len(tokens):
        if tokens[i] == "Tools" and rows:
            break
        r = [_ratio(tokens[i + k]) for k in range(3)]
        label, category = tokens[i - 2], tokens[i - 1]
        if all(r) and not _ratio(label) and not _ratio(category):
            rows.append({
                "label": label, "category": category,
                "rpm": r[0][1], "tpm": r[1][1], "rpd": r[2][1],
                "used": {"rpm": r[0][0], "tpm": r[1][0], "rpd": r[2][0]},
            })
            i += 3
        else:
            i += 1
    return {"tier": tier, "rows": rows}


# ──────────────────────────────────────────────────────────────────────────
# A docs-oldalak (nyilvános HTML, benne a Markdoc-forrás) feldolgozása
# ──────────────────────────────────────────────────────────────────────────

_TABLE_RE = re.compile(r"\{% table[^%]*%\}(.*?)\{% /table %\}", re.S)
_ROW_SPLIT_RE = re.compile(r"\n\s*---\s*\n")
_CELL_SPLIT_RE = re.compile(r"(?m)^\s*\*(?:[ \t]|$)")
_DOC_DATE = r"[A-Z][a-z]+ \d{1,2}, \d{4}"


def _tables(text: str):
    for m in _TABLE_RE.finditer(text):
        rows = _ROW_SPLIT_RE.split(m.group(1))
        yield rows[0], rows[1:]


def parse_docs_models(page: str) -> dict:
    """docs/models → {"names": {megjelenített név: kód}, "status": {kód: Stable|
    Preview|New}, "shut_down": [kód]}"""
    t = html.unescape(page)
    names, status, shut_down = {}, {}, set()
    for _, rows in _tables(t):
        for row in rows:
            link = re.search(r"\[([^\]]+)\]\(/docs/[^)]*\)", row)
            codes = re.findall(r"`([^`\s]+)`", row)
            if not (link and codes):
                continue
            names[" ".join(link.group(1).split())] = codes[-1]
            if "Shut down" in row:
                shut_down.add(codes[-1])
    for m in re.finditer(r"\{% card ([^%]*?)/?%\}", t):
        attrs = m.group(1)
        title = re.search(r'title="([^"]+)"', attrs)
        href = re.search(r'href="/docs/models/([^"#?]+)"', attrs)
        badge = re.search(r'badge="([^"]+)"', attrs)
        if title and href:
            names.setdefault(title.group(1), href.group(1))
            if badge:
                status[href.group(1)] = badge.group(1)
    return {"names": names, "status": status, "shut_down": sorted(shut_down)}


def _parse_doc_date(text: str):
    text = " ".join(text.split())
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _cells(row: str) -> list:
    return [" ".join(c.split()) for c in _CELL_SPLIT_RE.split(row)[1:]]


def _column(header: list, *words):
    """Az első oszlop indexe, amelynek a fejlécében mind a `words` szerepel."""
    for i, name in enumerate(header):
        if all(w in name.lower() for w in words):
            return i
    return None


def parse_deprecations(page: str) -> dict:
    """docs/deprecations → {kód: {"replacement", "shutdown", "routes",
    "routes_from", "note"}}. Csak a leállással vagy utóddal rendelkező sorok
    kerülnek bele. Az oszlopokat a fejléc neve alapján keresi (egy új vagy
    áthelyezett oszlop ne csússzon el). Az átirányítás kezdete az
    „Effective <dátum>” kitételből jön; jövő idejű („will automatically
    route”) dátum nélkül a leállás napja."""
    t = html.unescape(page)
    out = {}
    for header_row, rows in _tables(t):
        header = _cells(header_row)
        # az első oszlop a modell (az ügynök-táblákban „Agent” a neve)
        col_model = _column(header, "model")
        if col_model is None and header:
            col_model = 0
        col_shutdown = _column(header, "shutdown")
        col_repl = _column(header, "replacement")
        if None in (col_model, col_shutdown, col_repl):
            continue
        for row in rows:
            cells = _cells(row)
            if len(cells) <= max(col_model, col_shutdown, col_repl):
                continue
            code = re.search(r"`([^`\s]+)`", cells[col_model])
            if not code:
                continue
            repl_cell = cells[col_repl]
            repl = re.search(r"`([^`\s]+)`", repl_cell)
            shutdown = _parse_doc_date(cells[col_shutdown])
            if not (repl or shutdown):
                continue
            routes = bool(re.search(r"automatically rout(?:es|e)\b", repl_cell, re.I))
            effective = re.search(rf"[Ee]ffective ({_DOC_DATE})", repl_cell)
            routes_from = _parse_doc_date(effective.group(1)) if effective else None
            if routes and not routes_from and re.search(r"will automatically route",
                                                        repl_cell, re.I):
                routes_from = shutdown
                routes = bool(shutdown)
            out[code.group(1)] = {
                "replacement": repl.group(1) if repl else None,
                "shutdown": shutdown,
                "routes": routes,
                "routes_from": routes_from,
                "note": repl_cell,
            }
    return out


# ──────────────────────────────────────────────────────────────────────────
# Név → modellkód
# ──────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = re.sub(r"[(\[].*?[)\]]", " ", s or "")
    return " ".join(s.lower().replace("-", " ").split())


def _prefer(ids):
    return sorted(ids, key=lambda i: ("preview" in i, "latest" in i, len(i), i))[0]


def match_label(label: str, docs_names: dict, api_models,
                known: dict | None = None) -> "str | None":
    """Az AI Studio-beli megjelenített név modellkódja. Sorrend: a docs-oldal
    táblázata → az API displayName-je → a korábbi adatfájl párosítása
    (`known`: {név: kód}) → a névből képzett kód (csak ha az API nem volt
    elérhető, vagy ott tényleg van ilyen)."""
    n = _norm(label)
    for name, code in docs_names.items():
        if _norm(name) == n:
            return code
    api_models = api_models or {}
    by_display = {}
    for mid, disp in api_models.items():
        by_display.setdefault(_norm(disp), []).append(mid)
    if n in by_display:
        return _prefer(by_display[n])
    stripped = [mid for d, ids in by_display.items()
                if re.sub(r" (preview|it|latest)$", "", d) == n for mid in ids]
    if stripped:
        return _prefer(stripped)
    prefixed = [mid for d, ids in by_display.items() if d.startswith(n + " ") for mid in ids]
    if len(prefixed) == 1:
        return prefixed[0]
    for name, code in (known or {}).items():
        if _norm(name) == n:
            return code
    slug = "-".join(n.split())
    if not api_models or slug in api_models:
        return slug
    return None


# ──────────────────────────────────────────────────────────────────────────
# Letöltés
# ──────────────────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 30) -> str:
    import ssl
    import urllib.request
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "subtr-models-refresh"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_api_models() -> dict:
    """{modellkód: displayName} a generateContent-képes modellekre (API-kulccsal)."""
    from subtr.providers import gemini
    if not gemini.DEPS_OK:
        raise RuntimeError(f"google-genai nincs telepítve ({gemini.DEPS_ERROR})")
    client = gemini.make_client()
    out = {}
    for m in client.models.list(config={"page_size": 1000}):
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" not in actions:
            continue
        mid = (m.name or "").removeprefix("models/")
        out[mid] = getattr(m, "display_name", "") or mid
    return out


def read_clipboard() -> str:
    if sys.platform == "darwin":
        cmds = [["pbpaste"]]
    elif sys.platform.startswith("win"):
        cmds = [["powershell", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"]]
    else:
        cmds = [["wl-paste", "--no-newline"], ["xclip", "-o", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--output"]]
    for cmd in cmds:
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=15)
            if proc.returncode == 0:
                return proc.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()
        finally:
            root.destroy()
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────
# Az új adatfájl összeállítása, összevetés
# ──────────────────────────────────────────────────────────────────────────

def build_data(old: dict, page, docs, deprecations, api_models, today=None) -> dict:
    """Az új (repóbeli, csak nyilvános adatot tartalmazó) adatfájl. Ami nem jött
    le (None), az a régiből marad — a modellenkénti státusz is. Az `api_models`
    csak a név → kód párosításhoz kell; a kulcsfüggő eredmény a gépszintű
    fájlba megy (save_local_api)."""
    today = today or date.today()
    old_models = old.get("models") or {}
    new = {
        "_comment": "GENERÁLT FÁJL — `py subtr.py models refresh` írja, kézzel ne "
                    "szerkeszd. Csak nyilvános adat; leírás: subtr/gemini_models.py",
        "updated": old.get("updated"),
        "tier": old.get("tier"),
        "sources": {k: v for k, v in (old.get("sources") or {}).items() if k != "api"},
        "models": copy.deepcopy(old_models),
        "deprecations": copy.deepcopy(old.get("deprecations") or {}),
        "unmatched_labels": list(old.get("unmatched_labels") or []),
    }
    docs_names = (docs or {}).get("names", {})
    if page is not None:
        models, unmatched = {}, []
        # API nélkül a korábbi párosítás jobb a névből képzett kódnál
        # (pl. „Gemma 4 31B” → gemma-4-31b-it, nem gemma-4-31b).
        known = {i["label"]: mid for mid, i in old_models.items() if i.get("label")}
        # Amit egy korábbi (API-s) futás nem tudott párosítani, azt API nélkül
        # se találgassuk a névből.
        unmatched_before = set(old.get("unmatched_labels") or []) if api_models is None else set()
        for row in page["rows"]:
            mid = (None if row["label"] in unmatched_before
                   else match_label(row["label"], docs_names, api_models, known))
            if not mid or mid in models:      # ütközés: az első párosítás marad
                unmatched.append(row["label"])
                continue
            entry = {"label": row["label"], "category": row["category"],
                     "rpm": row["rpm"], "tpm": row["tpm"], "rpd": row["rpd"]}
            for keep in ("status", "shut_down"):     # docs nélkül a régi marad
                if keep in old_models.get(mid, {}):
                    entry[keep] = old_models[mid][keep]
            models[mid] = entry
        new["models"], new["unmatched_labels"] = models, unmatched
        new["tier"] = page.get("tier") or new["tier"]
        new["updated"] = today.isoformat()
        new["sources"]["limits"] = f"{RATE_LIMIT_URL} ({today.isoformat()})"
    if docs is not None:
        for mid, info in new["models"].items():
            info["status"] = docs["status"].get(mid, info.get("status"))
            info["shut_down"] = mid in docs["shut_down"]
        new["sources"]["names"] = f"{DOCS_MODELS_URL} ({today.isoformat()})"
    if deprecations is not None:
        new["deprecations"] = deprecations
        new["sources"]["deprecations"] = f"{DOCS_DEPRECATIONS_URL} ({today.isoformat()})"
    return new


def _update_local(change, path=None) -> Path:
    """A gépszintű fájl jelenlegi kulcshoz tartozó részének módosítása."""
    from subtr import quota
    p = Path(path or local_path())
    data = _read_json(p, {})
    entry = data.setdefault("keys", {}).setdefault(quota.key_fingerprint(), {})
    change(entry)
    p.parent.mkdir(parents=True, exist_ok=True)
    _write_json(p, data)
    clear_cache()
    return p


def save_local_api(api: dict, today=None, path=None) -> Path:
    """A kulcsod `models.list`-je a gépszintű fájlba (kulcs-ujjlenyomat szerint)."""
    def change(entry):
        entry["updated"] = (today or date.today()).isoformat()
        entry["models"] = sorted(api)
    return _update_local(change, path)


def save_local_limits(models: dict, tier, today=None, path=None) -> Path:
    """Saját (fizetős) tier limitjei a gépszintű fájlba — a repóbeli Free tier
    adatot a kulcsodra felülírják, a repó fájlja érintetlen marad."""
    keep = ("label", "category", "rpm", "tpm", "rpd")

    def change(entry):
        entry["limits"] = {
            "tier": tier, "updated": (today or date.today()).isoformat(),
            "models": {m: {k: v for k, v in i.items() if k in keep}
                       for m, i in models.items()},
        }
    return _update_local(change, path)


def reset_local_limits(path=None) -> bool:
    """A saját limitek törlése: a kulcsodra újra a repó Free tier adatai érvényesek."""
    if local_limits() is None:
        return False

    def change(entry):
        entry.pop("limits", None)
    _update_local(change, path)
    return True


def diff_lines(old: dict, new: dict) -> list:
    lines = []
    if old.get("tier") and new.get("tier") and old["tier"] != new["tier"]:
        lines.append(f"tier: {old['tier']} → {new['tier']}")
    om, nm = old.get("models", {}), new.get("models", {})
    for mid in sorted(set(nm) - set(om)):
        i = nm[mid]
        lines.append(f"+ új: {mid} ({i.get('category')}; RPD {_fmt(i.get('rpd'))})")
    for mid in sorted(set(om) - set(nm)):
        lines.append(f"- eltűnt: {mid}")
    for mid in sorted(set(om) & set(nm)):
        changes = [f"{k.upper()} {_fmt(om[mid].get(k))} → {_fmt(nm[mid].get(k))}"
                   for k in ("rpm", "tpm", "rpd") if om[mid].get(k) != nm[mid].get(k)]
        if changes:
            lines.append(f"~ {mid}: " + ", ".join(changes))
    od, nd = old.get("deprecations", {}), new.get("deprecations", {})
    for mid in sorted(set(nd) - set(od)):
        d = nd[mid]
        lines.append(f"+ kivezetés: {mid} → {d.get('replacement') or '–'} "
                     f"(leállás: {d.get('shutdown') or 'nincs dátum'})")
    for mid in sorted(set(od) - set(nd)):
        lines.append(f"- kivezetés törölve a listáról: {mid}")
    return lines


def configured_models() -> dict:
    """{modell: [honnan]} — a Gemini API-val futó funkciók modelljei, a
    provider-szintű SUBTR_GEMINI_MODEL és a tartaléklista."""
    found = {}
    for task in config.TASKS:
        try:
            if config._task_provider(task)[0] != "gemini":
                continue
            model, _ = config._lookup("MODEL", "gemini", task)
        except Exception:
            continue
        if model:
            found.setdefault(model, []).append(task)
    gemini_model = config.setting("SUBTR_GEMINI_MODEL")
    if gemini_model:
        found.setdefault(gemini_model, []).append("SUBTR_GEMINI_MODEL")
    for i, m in enumerate(fallback_models(), 1):
        found.setdefault(m, []).append(f"{FALLBACK_KEY} #{i}")
    return found


def config_warnings(data: dict, api=None, learned=None) -> list:
    """A beállított modellek gondjai. `api`: a kulcs modell-listája (halmaz)
    vagy None; `learned`: a kulcsodra 429-ből tanult napi limitek."""
    out = []
    models = data.get("models", {})
    data = {"deprecations": data.get("deprecations", {}), **data}
    today = date.today()
    for model, where in configured_models().items():
        info = models.get(model)
        problems = []
        replaced = active_replacement(model, today, data)
        if replaced:
            problems.append(f"{replaced[1]} — a pipeline helyette ezt hívja: {replaced[0]}")
        else:
            up = upcoming_shutdown(model, today, data)
            if up:
                problems.append(f"leállás / átirányítás {up[0]} → {up[1] or '?'}")
        if info is None:
            problems.append("nincs a rate-limit listán")
        else:
            if info.get("rpd") == 0:
                problems.append("ezen a tieren nem használható (RPD 0)")
            if info.get("category") != TEXT_CATEGORY:
                problems.append(f"nem szöveges modell ({info.get('category')})")
        if api is not None and model not in api:
            problems.append("a kulcsod API-listáján nincs")
        if problems:
            out.append(f"{model} [{', '.join(where)}]: {'; '.join(problems)}")
    for model, value in sorted((learned or {}).items()):
        known = (models.get(model) or {}).get("rpd")
        if isinstance(known, int) and known != int(value):
            out.append(f"{model}: a kulcsodra 429-ből tanult napi limit {value}, az AI "
                       f"Studio szerint {known} — a tanult érték az erősebb; ha elavult: "
                       f"py subtr.py quota --forget-limit {model}")
    return out


def _fmt(n) -> str:
    if n is None:
        return "∞"
    if n >= 1_000_000 and n % 100_000 == 0:
        return f"{n / 1_000_000:g}M"
    if n >= 1_000 and n % 100 == 0:
        return f"{n / 1_000:g}K"
    return str(n)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def save(data: dict, path=None) -> None:
    _write_json(Path(path or DATA_PATH), data)
    clear_cache()


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def _copy_instructions() -> str:
    return (f"  1. Nyisd meg: {RATE_LIMIT_URL}  (a projekt, amelyikhez a GEMINI_API_KEY tartozik)\n"
            f"  2. Kapcsold BE az „All models” kapcsolót (különben csak 2-3 modell látszik)\n"
            f"  3. Ctrl+A, Ctrl+C (Macen Cmd+A, Cmd+C) — a szöveg a vágólapra kerül,\n"
            f"     sehova nem kell beilleszteni\n"
            f"  4. Futtasd újra: py subtr.py models refresh --local (a vágólapról olvas;\n"
            f"     fájlból: --file oldal.txt)")


def _learned_limits() -> dict:
    from subtr import quota
    try:
        bucket = quota.load_ledger().get("keys", {}).get(quota.key_fingerprint(), {})
        return dict(bucket.get("limits", {}))
    except Exception:
        return {}


def cmd_refresh(args) -> int:
    old = load()
    page = None
    if args.local and args.no_limits:
        print("HIBA: a --local a limiteket menti — a --no-limits-szel nincs értelme.")
        return 1
    if not args.no_limits:
        if args.open:
            import webbrowser
            webbrowser.open(RATE_LIMIT_URL)
            input("Másold ki az oldalt (lásd lent), majd nyomj Entert...\n"
                  + _copy_instructions() + "\n")
        if args.file == "-" or args.stdin:
            text = sys.stdin.read()
        elif args.file:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = read_clipboard()
        page = parse_rate_limit_page(text)
        text_rows = [r for r in page["rows"] if r["category"] == TEXT_CATEGORY]
        if not page["rows"] or not text_rows:
            print("HIBA: a bemenetben nincs rate-limit táblázat (szöveges modellekkel).\n"
                  + _copy_instructions()
                  + "\n  (Ha csak a modell-listát / kivezetéseket frissítenéd: --no-limits)")
            return 1
        if len(page["rows"]) < MIN_EXPECTED_ROWS and not args.force:
            print(f"HIBA: csak {len(page['rows'])} modell-sor jött át — valószínűleg "
                  f"nincs bekapcsolva az „All models”. A fájlt NEM írom felül, mert a "
                  f"többi modell limitje és adata elveszne.\n" + _copy_instructions()
                  + "\n  (Ha tényleg ennyi modell van: --force)")
            return 1
        print(f"Rate-limit oldal: {len(page['rows'])} modell, tier: {page['tier'] or '?'}")
        tier = page["tier"] or ""
        if not args.local and tier and tier.lower() != REPO_TIER.lower():
            print(f"HIBA: ez a(z) „{tier}” limitje. A programba épített adat a mindenkinek "
                  f"elérhető {REPO_TIER} limitjeit tartja.\n"
                  f"  A saját előfizetésed limitjeit a gépedre mentsd (minden fordítási "
                  f"mappádra érvényes): py subtr.py models refresh --local")
            return 1

    docs = deprecations = api_list = None
    if not args.no_docs:
        try:
            docs = parse_docs_models(_http_get(DOCS_MODELS_URL))
            print(f"docs/models: {len(docs['names'])} név → kód")
        except Exception as e:
            print(f"FIGYELEM: a docs/models nem jött le ({e}) — a nevek az API-ból / "
                  f"heurisztikával párosulnak, a státusz a régi marad")
        try:
            deprecations = parse_deprecations(_http_get(DOCS_DEPRECATIONS_URL))
            print(f"docs/deprecations: {len(deprecations)} kivezetés")
        except Exception as e:
            print(f"FIGYELEM: a docs/deprecations nem jött le ({e}) — a régi lista marad")
    if not args.no_api:
        try:
            api_list = fetch_api_models()
            print(f"API models.list: {len(api_list)} generateContent-képes modell")
        except Exception as e:
            print(f"FIGYELEM: az API modell-listája nem jött le ({e}) — a gépszintű "
                  f"lista a régi marad")

    new = build_data(old, page, docs, deprecations, api_list)

    if new.get("unmatched_labels"):
        print("Nem párosítható nevek (kimaradnak): " + ", ".join(new["unmatched_labels"]))
    if api_list is not None:
        missing = sorted(m for m in new["models"] if m not in api_list
                         and new["models"][m].get("category") == TEXT_CATEGORY)
        if missing:
            print("A kulcsod API-listáján nincs (szöveges): " + ", ".join(missing))
    changes = diff_lines(old, new)
    print("\nVáltozások a korábbi fájlhoz képest:" if changes
          else "\nNincs változás a korábbi fájlhoz képest.")
    for line in changes:
        print("  " + line)

    if page is not None:
        _print_usage_crosscheck(page, new)

    effective = new
    if args.local:
        # a figyelmeztetésekhez: a repó adatai a saját limitekkel felülírva
        effective = {**new, "models": {**load()["models"], **new["models"]}}
        own_diff = diff_lines({"models": load()["models"]}, {"models": new["models"]})
        print(f"\nSaját limitek a beépített ({REPO_TIER}) adatokhoz képest:" if own_diff
              else "\nA saját limitek megegyeznek a beépített adatokkal.")
        for line in own_diff:
            print("  " + line)
    warns = config_warnings(effective,
                            set(api_list) if api_list is not None else api_models_or_none(),
                            _learned_limits())
    if warns:
        print("\nBeállítások, amelyekre figyelni kell (.env / defaults.env):")
        for w in warns:
            print("  [!] " + w)

    if args.dry_run:
        print("\n--dry-run: a fájlok nem íródtak felül.")
        return 0
    if args.local:
        path = save_local_limits(new["models"], page["tier"])
        print(f"\nMentve a gépedre (minden fordítási mappádra, ehhez a kulcshoz): {path}")
        print(f"Vissza a beépített ({REPO_TIER}) adatokra: py subtr.py models reset-local")
        if api_list is not None:
            save_local_api(api_list)
        return 0
    save(new)
    print(f"\nÍrva: {DATA_PATH}")
    if api_list is not None:
        print(f"Írva (gépszintű, kulcsfüggő): {save_local_api(api_list)}")
        clear_cache()
    print("Ez csak ennek a mappának a programpéldányát frissítette. Ha a limiteket "
          "minden fordítási\nmappádra érvényesen akarod beállítani: py subtr.py "
          "models refresh --local\n(Ha a programot fejleszted: a fájlt commitold.)")
    return 0


def api_models_or_none():
    try:
        return api_models()
    except Exception:
        return None


def _print_usage_crosscheck(page: dict, data: dict) -> None:
    """Az AI Studio csúcs-használata vs. a helyi napló — a láthatatlan fogyás
    (más eszköz, másik kulcs ugyanabban a projektben) így derül ki."""
    from subtr import quota
    label_to_id = {i["label"]: mid for mid, i in data["models"].items()}
    ledger = quota.load_ledger()
    lines = []
    for row in page["rows"]:
        used = row["used"]["rpd"]
        mid = label_to_id.get(row["label"])
        if not used or not mid:
            continue
        local = quota.status(mid, ledger=ledger)["used"]
        lines.append(f"  {mid:28s} AI Studio: {used}/{_fmt(row['rpd'])}   helyi napló ma: {local}")
    if lines:
        print("\nHasználat (AI Studio: az oldalon választott időszak csúcsa; helyi: ma, PT):")
        print("\n".join(lines))


def cmd_show(args) -> int:
    from subtr import quota
    data = load()
    if not data["models"]:
        print(f"Még nincs adat ({DATA_PATH.name}). Frissítés:\n" + _copy_instructions())
        return 1
    updated = _parse_iso(data.get("updated"))
    age = (date.today() - updated).days if updated else None
    own = local_limits()
    print(f"Gemini-modellek — {data.get('tier') or '?'}, adat: {data.get('updated') or '?'}"
          + (f" ({age} napos)" if age is not None else ""))
    if own:
        print(f"  Saját limitek a kulcsodra: {own.get('tier') or '?'} ({own.get('updated')}) "
              f"— ezek érvényesek a beépített {REPO_TIER} adatok helyett "
              f"(visszaállás: py subtr.py models reset-local)")
    own_age = None
    if own and _parse_iso(own.get("updated")):
        own_age = (date.today() - _parse_iso(own["updated"])).days
    if own_age is not None and own_age > STALE_DAYS:
        print(f"  [!] A saját limitek {own_age} naposak — frissítsd: "
              f"py subtr.py models refresh --local")
    elif not own and (age is None or age > STALE_DAYS):
        print("  [!] Régi adat — a program új verziója frisset hoz; addig is: "
              "py subtr.py models refresh --local")
    api = api_models_or_none()
    if api is None:
        print("  (A kulcsod modell-listája még nincs letöltve: py subtr.py models refresh)")
    roles = configured_models()
    ledger = quota.load_ledger()
    print(f"\n  {'modell':30s} {'RPM':>5s} {'TPM':>6s} {'RPD':>6s} {'ma':>7s}  megjegyzés")
    rows = sorted(((mid, model_info(mid) or {}) for mid in all_model_ids()),
                  key=lambda kv: (kv[1].get("category") != TEXT_CATEGORY,
                                  kv[1].get("category", ""), kv[0]))
    for mid, info in rows:
        if not args.all and info.get("category") != TEXT_CATEGORY:
            continue
        notes = []
        if info.get("rpd") == 0:
            notes.append("ezen a tieren nem használható")
        rep = active_replacement(mid)
        if rep:
            notes.append(f"→ {rep[0]}")
        up = upcoming_shutdown(mid)
        if up:
            notes.append(f"leáll {up[0]} → {up[1] or '?'}")
        if api is not None and mid not in api:
            notes.append("a kulcsod API-listáján nincs")
        if info.get("status") and info["status"] != "Stable":
            notes.append(info["status"])
        if mid in roles:
            notes.append("beállítva: " + ", ".join(roles[mid]))
        today = ""
        if info.get("rpd"):
            st = quota.status(mid, ledger=ledger)
            today = f"{st['used']}/{quota.fmt_limit(st['limit'])}" + ("!" if st["exhausted"] else "")
        cat = f"[{info.get('category')}] " if args.all else ""
        print(f"  {mid:30s} {_fmt(info.get('rpm')):>5s} {_fmt(info.get('tpm')):>6s} "
              f"{_fmt(info.get('rpd')):>6s} {today:>7s}  {cat}{'; '.join(notes)}")
    print("\n  „ma”: a helyi napló szerint (alsó becslés; ! = ma már 429-et kapott) — "
          "lásd: py subtr.py quota")
    print(f"\nNapi limitnél: {ON_QUOTA_KEY}={on_quota_mode()}, "
          f"tartaléklista: {', '.join(fallback_models()) or '(üres)'}")
    for w in config_warnings(data, api, _learned_limits()):
        print("  [!] " + w)
    return 0


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="Gemini-modellek, free tier limitek és kivezetések egy helyen "
                    f"({DATA_PATH.name}). Frissítés: az AI Studio rate-limit oldalának "
                    "kimásolt szövegéből + a nyilvános docs-oldalakból + az API-ból.")
    ap.add_argument("action", nargs="?", default="show",
                    choices=("show", "refresh", "reset-local"),
                    help="show (alapértelmezett): táblázat; refresh: limitek frissítése "
                         "(--local: a gépedre); reset-local: a saját limitek törlése")
    ap.add_argument("--all", action="store_true",
                    help="show: minden kategória (nem csak a szöveges modellek)")
    ap.add_argument("--file", metavar="FÁJL",
                    help="refresh: a kimásolt oldal fájlból ('-' = stdin) a vágólap helyett")
    ap.add_argument("--stdin", action="store_true", help="refresh: a kimásolt oldal stdin-ről")
    ap.add_argument("--open", action="store_true",
                    help="refresh: előbb megnyitja a rate-limit oldalt a böngészőben")
    ap.add_argument("--no-limits", action="store_true",
                    help="refresh: limitek nélkül (csak docs + API); a régi limitek maradnak")
    ap.add_argument("--no-docs", action="store_true",
                    help="refresh: a docs-oldalak (nevek, kivezetések) letöltése nélkül")
    ap.add_argument("--no-api", action="store_true",
                    help="refresh: az API modell-listája nélkül (nem kell kulcs)")
    ap.add_argument("--local", action="store_true",
                    help="refresh: a limiteket a gépedre menti (minden fordítási mappádra, "
                         "ehhez az API-kulcshoz) — saját tierhez vagy a beépített adat "
                         "frissítéséhez; a program fájljai érintetlenek")
    ap.add_argument("--force", action="store_true",
                    help=f"refresh: kevesebb mint {MIN_EXPECTED_ROWS} modell-sorral is írjon")
    ap.add_argument("--dry-run", action="store_true",
                    help="refresh: csak kiírja a változásokat, nem ír fájlt")
    args = ap.parse_args()
    if args.action == "reset-local":
        if reset_local_limits():
            print(f"A saját limitek törölve — a kulcsodra újra a programba épített "
                  f"{REPO_TIER} adatok érvényesek.")
        else:
            print("Ehhez a kulcshoz nincsenek saját limitek.")
        sys.exit(0)
    sys.exit(cmd_refresh(args) if args.action == "refresh" else cmd_show(args))


if __name__ == "__main__":
    main()
