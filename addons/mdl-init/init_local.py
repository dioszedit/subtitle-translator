#!/usr/bin/env python3
"""
TRANSLATION.local.md inicializáló — új sorozat indításához futtatandó add-on.

Mit csinál?
  A megadott MyDramaList-adatlapról letölti a sorozat adatait (cím, ország,
  epizódszám, hossz, műfajok, tagek, szinopszis, szereplők), és ebből
  megírja a projekt gyökerében a `TRANSLATION.local.md` fájlt — abban a
  formában, amit a `TRANSLATION.md` "Aktuális sorozat adatai" szakasza vár.

  Ezen felül felveszi a sorozat címeit a `glossary.json`-ba, hogy a fordító
  később ne próbálkozzon a lefordításukkal (`--no-glossary` kikapcsolja).

  Amit a script NEM tud kitölteni, azt `TODO:` jelöléssel hagyja benne:
    - a magyar cím (LLM-mel vagy kézzel fordítandó, vagy add meg: --hu-title)
    - a megszólítási regiszter (nézés/olvasás alapján, kézzel)
  A regiszterhez a főszereplők neveit példasorként beleírja, hogy legyen
  miből indulni — de szándékosan nem talál ki viszonyokat.

Használat:
  python addons/mdl-init/init_local.py https://mydramalist.com/70241-ni-ye-you-jin-tian
  python addons/mdl-init/init_local.py <url> --hu-title "A főnököm"
  python addons/mdl-init/init_local.py <url> --force        # meglévő fájl felülírása
  python addons/mdl-init/init_local.py <url> --stdout       # csak kiírja, nem ír fájlt

Kimenet (a munkakönyvtárhoz képest):
  ./TRANSLATION.local.md   (gitignore-olt, a --out felülbírálja)
  ./glossary.json          (a sorozat- és forrásmű-cím bekerül; --no-glossary kikapcsolja)

Függőségek: cloudscraper, beautifulsoup4  →  pip install -e ".[addons]"
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mdl_scrape import scrape  # noqa: E402


# A kimenetek CWD-relatívak — ugyanaz a konvenció, mint a `subtr/config.py`-ban:
# a pipeline-t mindig a SOROZAT projektmappájából futtatjuk. A script helyéből
# számolni azért rossz, mert minden sorozatnak SAJÁT másolata van a repóból: ha
# az egyik mappából a másik példány scriptjét hívod, a script-relatív út csendben
# a MÁSIK sorozat fájljaiba írna.
DEFAULT_OUT = Path("TRANSLATION.local.md")
DEFAULT_GLOSSARY = Path("glossary.json")

# A script saját repója — csak a `subtr` csomag importjához kell, kimenethez NEM.
REPO_ROOT = Path(__file__).resolve().parents[2]

# A glossary.json kategóriái — a subtr csomagból, hogy egy helyen legyenek.
# Az add-on önállóan is futtatható, ezért van fallback.
try:
    sys.path.insert(0, str(REPO_ROOT))
    from subtr.glossary import CATEGORIES  # noqa: E402
except ImportError:  # pragma: no cover
    CATEGORIES = ["honorifics", "place_names", "character_names",
                  "special_terms", "phrases"]

# A szinopszis végén álló forrás-/adaptációs lábjegyzetek — a fordítási
# kontextushoz nem adnak semmit, viszont zajt visznek a promptba.
SOURCE_NOTE_RE = re.compile(r"^\s*(\(Source:.*?\)|~~.*)\s*$", re.IGNORECASE)


# ── Glossary-magok ──────────────────────────────────────────────────────────
#
# Miért ide: a `glossary.json` a fordítónak KÖTELEZŐ, ezért a legbiztosabb hely
# annak rögzítésére, hogy egy nevet/címet nem szabad lefordítani. Enélkül a
# fordító epizódonként másképp dönt — a The Early Spring (2026)-nál a négy rész
# adaptációs kártyáján négyféle cím szerepelt, kettőben lefordítva.

TITLE_CONTEXT = (
    "a SOROZAT eredeti címe — párbeszédben és képernyőfeliraton NEM fordítjuk. "
    "KIVÉTEL a sorozatcím-kártyája: ott a TRANSLATION.md „Címkártya” szabálya "
    "érvényes (fölül a magyar cím, alatta változatlanul az eredeti)."
)
SOURCE_WORK_CONTEXT = (
    "a FORRÁSMŰ címe, amiből a sorozat készült — NEM fordítjuk. Az adaptációs "
    "kártyán („Adapted from…”) is ez az alak szerepeljen, minden epizódban "
    "azonosan. A sorozat magyar címe ettől FÜGGETLEN."
)

# Az MDL-szinopszis végén álló adaptációs lábjegyzet:
#   ~~ Adapted from the web novel "Zao Chun Qing Lang" (早春晴朗) by Gu Niang Bie Ku
# A minta nem futhat át mondat-/bekezdéshatáron ([^"“”\n.]*): a szinopszis
# törzsében álló »adapted from real events. He said "hello"« különben "hello"-t
# tenne a KÖTELEZŐ szójegyzékbe. Több találatnál az utolsó (a lábjegyzet) nyer.
# A szerzőnév pontot is tartalmazhat (J.K. Rowling) — csak a záró pont vág.
ADAPTED_RE = re.compile(
    r"adapted from(?: the)?[^\"“”\n.]*[\"“”](?P<work>[^\"“”\n]+)[\"“”]"
    r"(?:\s*\((?P<native>[^)]+)\))?"
    r"(?:\s*by\s+(?P<author>[^(\n]+?)\s*(?:\(|\.?\s*$))?",
    re.IGNORECASE | re.MULTILINE,
)


def parse_adapted_from(synopsis: str) -> dict:
    """A szinopszis adaptációs lábjegyzetéből a forrásmű címe és szerzője.

    A `clean_synopsis` ezt a sort eldobja (jogosan: a fordítási döntésekhez nem
    ad semmit), de a CÍME igenis kell — az adaptációs kártyán megjelenik.
    """
    matches = list(ADAPTED_RE.finditer(synopsis or ""))
    if not matches:
        return {}
    m = matches[-1]
    out = {"work": (m.group("work") or "").strip()}
    for key in ("native", "author"):
        val = (m.group(key) or "").strip()
        if val:
            out[key] = val
    return out


# A MyDramaList oldalcíme az évszámot is tartalmazza („My Boss (2024)”), a
# felirat viszont sosem — évszámmal a bejegyzés soha nem illeszkedne.
YEAR_SUFFIX_RE = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")


def strip_year(title: str) -> str:
    """A cím végéről leszedi az MDL évszám-toldalékát."""
    return YEAR_SUFFIX_RE.sub("", (title or "").strip()).strip()


def build_glossary_seed(data: dict, hu_title: str) -> list[dict]:
    """A glossary.json-ba felvehető bejegyzések: sorozatcímek + forrásmű címe.

    Szereplőneveket SZÁNDÉKOSAN nem vesz fel: a MyDramaList írásmódja gyakran
    eltér a feliratétól („Shang Zhi Tao” vs. a feliratbeli „Shang Zhitao”), és
    egy kötelező szójegyzékbe rossz alakot tenni rosszabb, mint nem tenni bele
    semmit. A neveket a `subtr.py glossary` szedi ki magából a feliratból.
    """
    hu_note = ""
    if hu_title and not hu_title.startswith("TODO"):
        hu_note = f" A sorozat magyar címe: „{hu_title}”."

    seen, out = set(), []

    def add(en, context):
        key = (en or "").strip()
        if not key or key == "N/A" or key.lower() in seen:
            return
        seen.add(key.lower())
        out.append({"en": key, "hu": key,
                    "category": "special_terms", "context": context})

    add(strip_year(data.get("title")), TITLE_CONTEXT + hu_note)
    add(strip_year(data.get("native_title")), TITLE_CONTEXT + hu_note)

    src = parse_adapted_from(data.get("synopsis", ""))
    if src.get("work"):
        note = SOURCE_WORK_CONTEXT
        if src.get("author"):
            note += f" Szerző: {src['author']}."
        add(src["work"], note)
        add(src.get("native"), note)
    return out


class GlossaryError(ValueError):
    pass


def write_glossary_seed(entries: list[dict], path: Path, series: str = "") -> list[dict]:
    """A magok beírása a glossary.json-ba. Meglévő „en” kulcsot NEM ír felül.

    Új fájlnál a `meta.series` a sorozat címe. Sérült JSON-nál GlossaryError —
    a hívó ezt HIBA-ként jelenti, nem tracebackkel áll le.
    Visszaadja a ténylegesen hozzáadott bejegyzéseket.
    """
    raw = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    if raw.strip():
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise GlossaryError(f"{path}: hibás JSON — {e}") from e
        if not isinstance(data, dict):
            raise GlossaryError(f"{path}: a gyökér nem objektum")
    else:
        data = {"meta": {"description": "Fordítási szójegyzék — kézzel validált kifejezések",
                         "series": series},
                **{cat: [] for cat in CATEGORIES}}

    existing = set()
    for cat in CATEGORIES:
        bucket = data.get(cat, [])
        if not isinstance(bucket, list):
            raise GlossaryError(f"{path}: a(z) {cat!r} kategória nem lista")
        for e in bucket:
            if not isinstance(e, dict):
                raise GlossaryError(f"{path}: a(z) {cat!r} kategóriában nem-objektum elem")
            existing.add(str(e.get("en") or "").lower())
    added = []
    for entry in entries:
        if entry["en"].lower() in existing:
            continue
        data.setdefault(entry["category"], []).append(
            {"en": entry["en"], "hu": entry["hu"], "context": entry["context"]})
        existing.add(entry["en"].lower())
        added.append(entry)

    if not added:
        return []
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return added


def clean_synopsis(text: str) -> str:
    if not text or text == "N/A":
        return "TODO: szinopszis"
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    paragraphs = [p for p in paragraphs if not SOURCE_NOTE_RE.match(p)]
    # A lábjegyzet nem mindig áll külön sorban (a scrapelt HTML-ben lehet
    # <br> vagy szimpla újsor előtte, ami a get_text-ben összeolvad) — a
    # bekezdésen BELÜLI "~~ ..." farok és "(Source: ...)" jelölés is menjen.
    cleaned = []
    for p in paragraphs:
        p = re.sub(r"\s*~~.*$", "", p, flags=re.S)
        p = re.sub(r"\s*\(Source:[^)]*\)", "", p, flags=re.IGNORECASE).strip()
        if p:
            cleaned.append(p)
    return "\n\n".join(cleaned) if cleaned else "TODO: szinopszis"


def filter_cast(cast, max_cast: int, include_guests: bool):
    """Főszereplők előre, vendégszereplők alapból ki, majd vágás max_cast-ra."""
    if not include_guests:
        cast = [c for c in cast if "guest" not in c[2].lower()]
    main = [c for c in cast if "main" in c[2].lower()]
    rest = [c for c in cast if c not in main]
    return (main + rest)[:max_cast], main


def build_document(data: dict, hu_title: str, url: str, max_cast: int, include_guests: bool) -> str:
    cast, main_cast = filter_cast(data["cast"], max_cast, include_guests)

    lines = [
        f"Title: {data['title']} ({data['native_title']})",
        f"Hungarian title: {hu_title}",
        f"Country: {data['country']}",
        f"Episodes: {data['episodes']}",
        f"Duration: {data['duration']}",
        f"Genres: {data['genres']}",
        f"Tags: {data['tags']}",
        "",
        "Synopsis:",
        clean_synopsis(data["synopsis"]),
        "",
        "Cast:",
        "",
    ]

    if cast:
        for actor, role, role_type in cast:
            parts = [f"- {actor}"]
            if role:
                parts.append(f" as {role}")
            if role_type:
                parts.append(f" ({role_type})")
            lines.append("".join(parts))
    else:
        lines.append("- TODO: szereplők (a scraper nem talált cast-adatot)")

    lines += [
        "",
        "Megszólítási regiszter:   (frissítendő MINDEN epizód előtt)",
    ]

    # Csak vázat adunk: a viszonyokat a felhasználó tölti ki. Kitalált
    # regiszter-sor rosszabb, mint a hiányzó — lásd TRANSLATION.md.
    if len(main_cast) >= 2:
        a = main_cast[0][1] or main_cast[0][0]
        b = main_cast[1][1] or main_cast[1][0]
        lines += [
            f"  - TODO: {a} → {b}: MAGÁZ | TEGEZ  (viszony)",
            f"  - TODO: {b} → {a}: MAGÁZ | TEGEZ  (viszony)",
        ]
    for actor, role, role_type in main_cast[2:]:
        lines.append(f"  - TODO: {role or actor} viszonyai")
    lines += [
        "  - alapértelmezés idegenekkel: MAGÁZ",
        "  - váltás: TODO, ha van (pl. „X ↔ Y TEGEZ a 3. rész 312. felirata után”)",
        "",
        "Special terms:",
        "  - TODO: sorozatspecifikus kifejezések = jóváhagyott magyar megfelelő",
        "",
        "Previous episodes:",
        "",
        f"# Forrás: {url}",
        "# Generálta: addons/mdl-init/init_local.py — a TODO sorokat töltsd ki,",
        "# a maradékot töröld, mielőtt fordításba kezdesz.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="TRANSLATION.local.md generálása MyDramaList-adatlapból.",
    )
    parser.add_argument("url", help="MyDramaList sorozat-URL")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Kimeneti fájl")
    parser.add_argument("--hu-title", default="", help="Magyar cím (különben TODO marad)")
    parser.add_argument("--force", action="store_true", help="Meglévő fájl felülírása (.bak mentéssel)")
    parser.add_argument("--stdout", action="store_true", help="Csak kiírja, nem ír fájlt")
    parser.add_argument("--max-cast", type=int, default=12, help="Legfeljebb ennyi szereplő (alap: 12)")
    parser.add_argument("--include-guests", action="store_true", help="Vendégszereplők is kerüljenek bele")
    parser.add_argument("--glossary", type=Path, default=DEFAULT_GLOSSARY,
                        help=f"Szójegyzék útvonala (alap: {DEFAULT_GLOSSARY.name})")
    parser.add_argument("--no-glossary", action="store_true",
                        help="Ne vegye fel a sorozat- és forrásmű-címeket a szójegyzékbe")
    parser.add_argument("--glossary-only", action="store_true",
                        help="CSAK a szójegyzéket bővítse; a TRANSLATION.local.md-hez "
                             "ne nyúljon (már futó sorozat utólagos kiegészítéséhez)")
    args = parser.parse_args()

    if "mydramalist.com" not in args.url:
        parser.error("érvényes mydramalist.com URL kell")
    if args.glossary_only and args.no_glossary:
        parser.error("--glossary-only és --no-glossary kizárja egymást")
    if args.glossary_only and args.stdout:
        parser.error("--glossary-only és --stdout kizárja egymást (a --stdout nem ír fájlt)")

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not args.stdout and not args.glossary_only and args.out.exists() and not args.force:
        print(f"HIBA: {args.out} már létezik. Felülíráshoz: --force (a régit .bak-ba menti).")
        sys.exit(1)

    print(f"Letöltés: {args.url}")
    try:
        data = scrape(args.url)
    except Exception as e:
        print(f"HIBA a letöltésnél: {e}")
        sys.exit(1)

    doc = build_document(
        data,
        args.hu_title or "TODO: magyar cím",
        args.url,
        args.max_cast,
        args.include_guests,
    )

    seed = build_glossary_seed(data, args.hu_title)

    series_title = strip_year(data.get("title"))

    if args.glossary_only:
        # Már futó sorozat: a TRANSLATION.local.md kézzel hangolt (regiszter,
        # special terms), ahhoz nem nyúlunk — csak a címek kerülnek be.
        try:
            added = write_glossary_seed(seed, args.glossary, series_title)
        except GlossaryError as e:
            print(f"HIBA: {e}")
            sys.exit(1)
        if added:
            print(f"Szójegyzék bővítve ({args.glossary.resolve()}) — {len(added)} cím:")
            for e in added:
                print(f'  "{e["en"]}"')
        else:
            print(f"Szójegyzék: nincs új cím, a fájlhoz nem nyúltam ({args.glossary}).")
        print(f"A {args.out.name} érintetlen.")
        return

    if args.stdout:
        print()
        print(doc)
        if seed:
            print("\n# A szójegyzékbe kerülne (--stdout miatt most nem):")
            for e in seed:
                print(f'#   "{e["en"]}" = "{e["hu"]}"')
        return

    if args.out.exists():
        backup = args.out.with_suffix(args.out.suffix + ".bak")
        shutil.copy2(args.out, backup)
        print(f"Régi fájl mentve: {backup}")

    args.out.write_text(doc, encoding="utf-8")
    print(f"Kész: {args.out.resolve()}")

    if not args.no_glossary:
        try:
            added = write_glossary_seed(seed, args.glossary, series_title)
        except GlossaryError as e:
            print(f"HIBA: {e} — a {args.out.name} elkészült, a szójegyzék nem bővült.")
            sys.exit(1)
        if added:
            print(f"\nSzójegyzék bővítve ({args.glossary.resolve()}) — {len(added)} cím,")
            print("hogy a fordító ne próbálkozzon a lefordításukkal:")
            for e in added:
                print(f'  "{e["en"]}"')
        elif seed:
            print(f"\nSzójegyzék: a címek már benne vannak ({args.glossary.name}).")

    todos = [
        ln for ln in doc.splitlines()
        if "TODO" in ln and not ln.lstrip().startswith("#")
    ]
    if todos:
        print(f"\nMég kitöltendő ({len(todos)} sor):")
        for ln in todos:
            print(f"  {ln.strip()}")


if __name__ == "__main__":
    main()
