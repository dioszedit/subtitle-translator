#!/usr/bin/env python3
"""
apply_review_auto.py — Review-javítások NEM interaktív alkalmazása.

Az apply_review.py testvére: ugyanazt a fájlformátumot írja/olvassa, de a
döntéseket nem a konzolon kérdezi, hanem egy előre elkészített döntés-fájlból
veszi. Így egy agent (vagy batch script) is át tudja vezetni a jóváhagyott
javításokat.

Döntés-fájl (JSON):
    [
      {"sorszam": 12, "javaslat": "Az új magyar szöveg"},
      {"sorszam": 40, "javaslat": "Első sor\nMásodik sor"}
    ]

Használat:
    python apply_review_auto.py "output/Sorozat - S01E01.hun.srt" decisions.json
    python apply_review_auto.py "output/....hun.srt" decisions.json --dry-run

Az első íráskor .bak mentés készül az eredetiről (ha még nincs).
A sorszám + időbélyeg SOHA nem módosul, csak a szövegrész.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def parse_srt_blocks(filepath):
    content = Path(filepath).read_text(encoding="utf-8-sig")
    blocks = [b.strip() for b in re.split(r"\n\s*\n", content.strip()) if b.strip()]
    index = {}
    for i, block in enumerate(blocks):
        lines = block.split("\n")
        if len(lines) >= 2 and "-->" in lines[1]:
            try:
                index[int(lines[0].strip())] = i
            except ValueError:
                continue
    return blocks, index


def block_text(block):
    lines = block.split("\n")
    return "\n".join(lines[2:]) if len(lines) >= 3 else ""


def apply_to_block(block, new_text):
    lines = block.split("\n")
    return "\n".join(lines[:2] + new_text.split("\n"))


def main():
    parser = argparse.ArgumentParser(
        description="Review-javítások nem interaktív alkalmazása a magyar SRT-re")
    parser.add_argument("srt_file", help="A magyar (hun.srt) fájl")
    parser.add_argument("decisions", help="Döntés-fájl (JSON lista)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Csak listázás, nem módosít semmit")
    args = parser.parse_args()

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"HIBA: Fájl nem található: {srt_path}")
        sys.exit(1)

    decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8"))
    if not isinstance(decisions, list):
        print("HIBA: A döntés-fájl gyökere nem lista.")
        sys.exit(1)

    blocks, index = parse_srt_blocks(srt_path)

    applied = missing = unchanged = 0
    for d in decisions:
        try:
            num = int(d["sorszam"])
        except (KeyError, ValueError, TypeError):
            print(f"HIBA: érvénytelen bejegyzés (sorszam hiányzik): {d}")
            sys.exit(1)
        new_text = d.get("javaslat", "")
        if not new_text:
            print(f"#{num}: üres javaslat — kihagyva")
            continue
        if num not in index:
            print(f"#{num}: NINCS ilyen szekció a fájlban — kihagyva")
            missing += 1
            continue
        bi = index[num]
        current = block_text(blocks[bi])
        if current == new_text:
            unchanged += 1
            continue
        print(f"#{num}:")
        print(f"  - {current}")
        print(f"  + {new_text}")
        if not args.dry_run:
            blocks[bi] = apply_to_block(blocks[bi], new_text)
        applied += 1

    if args.dry_run:
        print(f"\n--dry-run: {applied} javítás alkalmazható "
              f"({unchanged} már egyezik, {missing} hiányzó szekció)")
        return

    if applied:
        bak = srt_path.with_suffix(srt_path.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(srt_path, bak)
        srt_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        print(f"\nMentve: {srt_path} (backup: {bak.name})")
    print(f"Alkalmazva: {applied}, már egyezett: {unchanged}, hiányzó szekció: {missing}")


if __name__ == "__main__":
    main()
