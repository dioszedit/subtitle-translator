"""
merge_srt.py — Lefordított blokkok összefűzése egy SRT fájlba

Használat:
    python merge_srt.py blocks/Sorozat_S01E01_eng output/Sorozat_S01E01_hun.srt
"""

import os
import sys

from subtr.blocks import HUN_SUFFIX, get_all_blocks, hun_path
import glob
import re
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description="Lefordított SRT blokkok összefűzése")
    parser.add_argument("blocks_dir", help="Blokkok mappája")
    parser.add_argument("output", help="Kimeneti fájl útvonala")
    parser.add_argument("--force", action="store_true", help="Összefűzés hiányzó blokkok esetén is")
    args = parser.parse_args()

    if not os.path.isdir(args.blocks_dir):
        print(f"HIBA: Nem találom a mappát: {args.blocks_dir}")
        sys.exit(1)

    # Összes eredeti blokk; a fordítottakat az eredetiekből származtatjuk,
    # így egy kósza *_HUN.srt (pl. régi splitből) nem tudja elfedni a hiányt,
    # és nem is kerülhet bele az outputba.
    original = get_all_blocks(args.blocks_dir)
    expected = [(f, hun_path(f)) for f in original]
    translated = [hun for _, hun in expected if os.path.isfile(hun)]
    missing = [os.path.basename(orig) for orig, hun in expected
               if not os.path.isfile(hun)]

    total = len(original)
    done = len(translated)

    # Kósza _HUN fájlok, amik egyik eredetihez sem tartoznak (pl. régi split)
    stray = sorted(set(glob.glob(os.path.join(args.blocks_dir, "*" + HUN_SUFFIX)))
                   - set(hun for _, hun in expected))
    if stray:
        print(f"FIGYELEM: {len(stray)} kósza _HUN fájl a mappában (nem kerül az outputba):")
        for s in stray:
            print(f"  - {os.path.basename(s)}")
        print()

    # Hiányzó blokkok ellenőrzése
    if missing:
        print(f"FIGYELEM: Nem minden blokk van lefordítva! ({done}/{total})")
        print("Hiányzó blokkok:")
        for m in missing:
            print(f"  - {m}")

        if not args.force:
            print("\nHasználd a --force kapcsolót ha mégis össze akarod fűzni.")
            sys.exit(1)
        print("\n--force: folytatás a meglévő blokkokkal\n")

    # Összefűzés
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    with open(args.output, 'w', encoding='utf-8') as out:
        for f in translated:
            with open(f, 'r', encoding='utf-8-sig') as block:
                content = block.read().strip()
                out.write(content + '\n\n')

    # Eredmény — strukturális számlálás: csak az a szám-sor szekció,
    # amit időbélyeg követ (a csak számot tartalmazó felirat-szöveg nem az)
    sections = 0
    with open(args.output, 'r', encoding='utf-8') as f:
        out_lines = f.read().split('\n')
    for i, line in enumerate(out_lines):
        if re.match(r'^\d+$', line.strip()) and i + 1 < len(out_lines) \
                and re.match(r'^\d{2}:\d{2}:\d{2}', out_lines[i + 1].strip()):
            sections += 1

    size = os.path.getsize(args.output)
    size_kb = size / 1024

    # Szekciószám folytonosság ellenőrzése
    continuity_errors = []
    prev_num = None
    with open(args.output, 'r', encoding='utf-8') as f:
        lines_list = f.readlines()
    for i, line in enumerate(lines_list):
        stripped = line.strip()
        # Szekciószám: csak szám, és utána időbélyeg sor jön
        if re.match(r'^\d+$', stripped):
            if i + 1 < len(lines_list) and re.match(r'^\d{2}:\d{2}:\d{2}', lines_list[i + 1].strip()):
                num = int(stripped)
                if prev_num is not None and num != prev_num + 1:
                    continuity_errors.append((prev_num, num))
                prev_num = num

    print(f"Összefűzve: {args.output}")
    print(f"Szekciók:   {sections}")
    print(f"Méret:      {size_kb:.1f} KB")

    if continuity_errors:
        print(f"\n⚠ {len(continuity_errors)} folytonossági hiba!")
        for prev, curr in continuity_errors[:10]:
            print(f"  #{prev} után #{curr} következik (várt: #{prev + 1})")
        if len(continuity_errors) > 10:
            print(f"  ... és még {len(continuity_errors) - 10} további")
    else:
        print("✓ Szekciószámok folytonosak")


if __name__ == "__main__":
    main()
