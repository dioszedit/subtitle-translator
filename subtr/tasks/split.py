"""
split_srt.py — SRT fájl feldarabolása fordítási blokkokra

Használat:
    python split_srt.py input/Sorozat_S01E01_eng.srt
    python split_srt.py input/Sorozat_S01E01_eng.srt --block-size 200
"""

import glob
import re
import sys

from subtr.srt import split_blocks as parse_sections
import os
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def get_section_num(section_text: str) -> int | None:
    """Szekció sorszámának kinyerése."""
    try:
        return int(section_text.strip().split('\n')[0].strip())
    except (ValueError, IndexError):
        return None


def split_srt(input_file: str, block_size: int = 150, clean: bool = False) -> str:
    basename = os.path.splitext(os.path.basename(input_file))[0]
    outdir = os.path.join("blocks", basename)
    os.makedirs(outdir, exist_ok=True)

    # Újra-split védelem: a régi (más blokkmérettel készült) blokkfájlok
    # nevei eltérnek, így ottmaradnának, és a fordító + merge mindkét
    # generációt feldolgozná (duplikált szekciók, dupla költség).
    existing = sorted(glob.glob(os.path.join(outdir, "*_block_*.srt")))
    if existing:
        hun = [f for f in existing if f.endswith("_HUN.srt")]
        if not clean:
            print(f"HIBA: A cél mappában már vannak blokkfájlok ({len(existing)} db): {outdir}")
            if hun:
                print(f"      Ebből {len(hun)} db lefordított (_HUN) blokk!")
            print("      Újra-splitnél a régi fájlok duplikált szekciókat okoznának a merge-nél.")
            print("      Használd a --clean kapcsolót a régi blokkok törléséhez.")
            sys.exit(1)
        print(f"--clean: {len(existing)} régi blokkfájl törlése ({len(hun)} _HUN fájllal együtt)")
        for f in existing:
            os.remove(f)
        print()

    with open(input_file, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    sections = parse_sections(content)
    total = len(sections)

    print(f"Fájl: {input_file}")
    print(f"Szekciók: {total}")
    print(f"Blokk méret: {block_size}")
    print(f"Várható blokkok: {(total + block_size - 1) // block_size}")
    print(f"Cél mappa: {outdir}")
    print("---")

    block_num = 0
    for i in range(0, total, block_size):
        block_num += 1
        chunk = sections[i:i + block_size]
        # 'is None' kell, nem 'or': a 0-s sorszám (egyes ripperek 0-tól
        # számoznak) falsy, és tévesen a pozíció-alapú értéket kapná
        first = get_section_num(chunk[0])
        first = first if first is not None else (i + 1)
        last = get_section_num(chunk[-1])
        last = last if last is not None else (i + len(chunk))

        fname = os.path.join(outdir, f"{basename}_block_{block_num:03d}_{first:04d}-{last:04d}.srt")
        with open(fname, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(chunk) + '\n')

        print(f"  Blokk {block_num}: {os.path.basename(fname)} ({len(chunk)} szekció, #{first}-#{last})")

    print(f"\nKész! {block_num} blokk létrehozva: {outdir}")
    return outdir


def main(argv=None):
    parser = argparse.ArgumentParser(description="SRT fájl feldarabolása blokkokra")
    parser.add_argument("input", help="Bemeneti SRT fájl útvonala")
    parser.add_argument("--block-size", type=int, default=150, help="Blokk méret (alapértelmezett: 150)")
    parser.add_argument("--clean", action="store_true",
                        help="Meglévő blokkfájlok törlése a cél mappából újra-split előtt")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"HIBA: Nem találom a fájlt: {args.input}")
        sys.exit(1)

    split_srt(args.input, args.block_size, args.clean)
