#!/usr/bin/env python3
"""
TRANSLATION.local.md inicializáló — új sorozat indításához futtatandó add-on.

Mit csinál?
  A megadott MyDramaList-adatlapról letölti a sorozat adatait (cím, ország,
  epizódszám, hossz, műfajok, tagek, szinopszis, szereplők), és ebből
  megírja a projekt gyökerében a `TRANSLATION.local.md` fájlt — abban a
  formában, amit a `TRANSLATION.md` "Aktuális sorozat adatai" szakasza vár.

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

Kimenet:
  <repo gyökér>/TRANSLATION.local.md   (gitignore-olt, a --out felülbírálja)

Függőségek: cloudscraper, beautifulsoup4  →  pip install -e ".[addons]"
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mdl_scrape import scrape  # noqa: E402


# A repo gyökere: addons/mdl-init/ két szinttel lejjebb van
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "TRANSLATION.local.md"

# A szinopszis végén álló forrás-/adaptációs lábjegyzetek — a fordítási
# kontextushoz nem adnak semmit, viszont zajt visznek a promptba.
SOURCE_NOTE_RE = re.compile(r"^\s*(\(Source:.*?\)|~~.*)\s*$", re.IGNORECASE)


def clean_synopsis(text: str) -> str:
    if not text or text == "N/A":
        return "TODO: szinopszis"
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    paragraphs = [p for p in paragraphs if not SOURCE_NOTE_RE.match(p)]
    return "\n\n".join(paragraphs) if paragraphs else "TODO: szinopszis"


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
    args = parser.parse_args()

    if "mydramalist.com" not in args.url:
        parser.error("érvényes mydramalist.com URL kell")

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not args.stdout and args.out.exists() and not args.force:
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

    if args.stdout:
        print()
        print(doc)
        return

    if args.out.exists():
        backup = args.out.with_suffix(args.out.suffix + ".bak")
        shutil.copy2(args.out, backup)
        print(f"Régi fájl mentve: {backup}")

    args.out.write_text(doc, encoding="utf-8")
    print(f"Kész: {args.out}")

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
