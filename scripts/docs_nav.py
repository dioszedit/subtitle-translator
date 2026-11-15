#!/usr/bin/env python3
"""A docs/ fejezeteinek navigációja — generálva, hogy kézzel ne csússzon szét.

Amit ír (a CHAPTERS sorrend szerint):
  - minden fejezet első sora:        # N. Cím
  - minden fejezet utolsó sora:      [← előző] · [Tartalomjegyzék] · [következő →]
                                     (az utolsó `---` sor utáni rész)
  - docs/README.md fejezetlistája:   fejezet + a ## és ### alcímek horgony-linkkel
                                     (a „## Hivatkozott dokumentumok” rész marad)
  - README.md „## Dokumentáció” listája

A fejezetek SZÖVEGÉT nem érinti. Új fejezetnél: hozd létre a fájlt a többi
mintájára (első sor `# …`, második blokk a Kezdőlap/Tartalomjegyzék sor, a
végén `---` és egy lapozósor), vedd fel a CHAPTERS listába, és futtasd.

Használat (a repó gyökeréből):
    python3 scripts/docs_nav.py           # navigáció frissítése
    python3 scripts/docs_nav.py --check   # csak ellenőrzés: 1-es kilépési kód, ha elavult

A horgonyok a GitHub szabálya szerint képződnek (kisbetű, írásjelek ki, szóköz →
kötőjel, ékezet marad) — ugyanez a tests/test_docs_links.py-ban, ami minden
linket ellenőriz.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (fájl, cím, egysoros leírás) — a sorrend a fejezetek sorrendje.
CHAPTERS = [
    ("01-telepites.md", "Telepítés és mappaszerkezet",
     "előfeltételek, letöltés, új sorozat indítása, frissítés új verzióra, a mappák szerepe"),
    ("02-elso-epizod.md", "Az első epizód — a teljes folyamat",
     "egy epizód lépésről lépésre, a szabályok átadása a modellnek, workflow-skillek"),
    ("03-szojegyzek.md", "Szójegyzék és megszólítási regiszter",
     "a fordítás előtti lépések: glossary, alap-szótárak, a tegezés/magázás kinyerése"),
    ("04-forditas.md", "Fordítás",
     "forrásnyelv, a fordító providerek és kapcsolóik"),
    ("05-review.md", "Review és javítás",
     "a review providerei, megszakadt review folytatása, a javaslatok alkalmazása"),
    ("06-providerek.md", "Provider, modell és effort",
     "melyik funkció melyik modellel fusson, .env-beállítások"),
    ("07-gemini-kvota.md", "Gemini: modellek, limitek, kvóta",
     "modellválasztás, Free tier és saját limitek, napi kvóta, modellváltás"),
    ("08-utomunka.md", "Utómunka",
     "review-hibák, sorhossz-szegmentálás, Subtitle Edit, kézi lektorálás, MKV"),
    ("09-tippek.md", "Tippek", "gyakorlati tanácsok"),
    ("10-fejlesztes.md", "Fejlesztés és háttér",
     "fejlesztőknek: tesztek, commit előtti szűrő, a dokumentáció karbantartása; "
     "mindenkinek: hogyan készült"),
]

TOC_TAIL = "\n## Hivatkozott dokumentumok"


def github_slug(title: str) -> str:
    t = re.sub(r"`", "", title.strip().lower())
    t = re.sub(r"[^\w\- ]", "", t)
    return t.replace(" ", "-")


def headings(text: str, levels=(2, 3)):
    out, code = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            code = not code
        m = re.match(r"^(#{1,6}) (.*)$", line)
        if m and not code and len(m.group(1)) in levels:
            out.append((len(m.group(1)), m.group(2)))
    return out


def chapter_text(i: int, text: str) -> str:
    fname, title, _ = CHAPTERS[i]
    lines = text.rstrip("\n").split("\n")
    if not lines or not lines[0].startswith("# "):
        raise SystemExit(f"HIBA: {fname}: az első sor nem `# …` cím")
    seps = [j for j, line in enumerate(lines) if line == "---"]
    if not seps:
        raise SystemExit(f"HIBA: {fname}: nincs `---` sor a lapozósor előtt")
    lines[0] = f"# {i + 1}. {title}"
    nav = []
    if i > 0:
        nav.append(f"[← {i}. {CHAPTERS[i - 1][1]}]({CHAPTERS[i - 1][0]})")
    nav.append("[Tartalomjegyzék](README.md)")
    if i + 1 < len(CHAPTERS):
        nav.append(f"[{i + 2}. {CHAPTERS[i + 1][1]} →]({CHAPTERS[i + 1][0]})")
    return "\n".join(lines[:seps[-1]] + ["---", "", " · ".join(nav)]) + "\n"


def toc_text(text: str, chapters: dict) -> str:
    if "\n1. **[" not in text or TOC_TAIL not in text:
        raise SystemExit("HIBA: docs/README.md: nem található a fejezetlista / "
                         "a „Hivatkozott dokumentumok” rész")
    head = text.split("\n1. **[", 1)[0]
    tail = text[text.index(TOC_TAIL):]
    out = []
    for i, (fname, title, desc) in enumerate(CHAPTERS, 1):
        out.append(f"{i}. **[{title}]({fname})** — {desc}")
        for level, h in headings(chapters[fname]):
            indent = "   " if level == 2 else "      "
            out.append(f"{indent}- [{h.replace('`', '')}]({fname}#{github_slug(h)})")
    return head + "\n" + "\n".join(out) + "\n" + tail


def readme_text(text: str) -> str:
    m = re.search(r"(## Dokumentáció\n\n[^\n]*\n\n)((?:\d+\. .*\n)+)", text)
    if not m:
        raise SystemExit("HIBA: README.md: nincs „## Dokumentáció” fejezetlista")
    lst = "".join(f"{i}. [{t}](docs/{f}) — {d}\n" for i, (f, t, d) in enumerate(CHAPTERS, 1))
    return text[:m.start(2)] + lst + text[m.end(2):]


def build(root: Path = ROOT) -> dict:
    """{útvonal: új tartalom} minden érintett fájlra."""
    docs = root / "docs"
    result, chapters = {}, {}
    for i, (fname, _, _) in enumerate(CHAPTERS):
        path = docs / fname
        if not path.exists():
            raise SystemExit(f"HIBA: hiányzó fejezet: docs/{fname}")
        chapters[fname] = chapter_text(i, path.read_text(encoding="utf-8"))
        result[path] = chapters[fname]
    toc = docs / "README.md"
    result[toc] = toc_text(toc.read_text(encoding="utf-8"), chapters)
    readme = root / "README.md"
    result[readme] = readme_text(readme.read_text(encoding="utf-8"))
    return result


def stale(root: Path = ROOT) -> list:
    """Azok a fájlok, amelyeknek a navigációja elavult."""
    return [p for p, text in build(root).items()
            if p.read_text(encoding="utf-8") != text]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="A docs/ navigációjának generálása.")
    ap.add_argument("--check", action="store_true",
                    help="csak ellenőrzés; elavult navigációnál 1-es kilépési kód")
    args = ap.parse_args()
    if args.check:
        old = stale()
        for p in old:
            print(f"elavult navigáció: {p.relative_to(ROOT)}")
        if old:
            print("Frissítés: python3 scripts/docs_nav.py")
        sys.exit(1 if old else 0)
    changed = 0
    for path, text in build().items():
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            changed += 1
            print(f"frissítve: {path.relative_to(ROOT)}")
    print("A navigáció naprakész." if not changed else f"{changed} fájl frissítve.")


if __name__ == "__main__":
    main()
