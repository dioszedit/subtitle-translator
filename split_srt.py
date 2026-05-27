"""
split_srt.py — SRT fájl feldarabolása fordítási blokkokra

Használat:
    python split_srt.py input/Sorozat_S01E01_eng.srt
    python split_srt.py input/Sorozat_S01E01_eng.srt --block-size 200
"""

import re
import sys
import os
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def parse_sections(content: str) -> list[str]:
    """SRT tartalom szekciókra bontása."""
    raw = re.split(r'\n\s*\n', content.strip())
    return [s.strip() for s in raw if s.strip()]


def get_section_num(section_text: str) -> int | None:
    """Szekció sorszámának kinyerése."""
    try:
        return int(section_text.strip().split('\n')[0].strip())
    except (ValueError, IndexError):
        return None


def split_srt(input_file: str, block_size: int = 150) -> str:
    basename = os.path.splitext(os.path.basename(input_file))[0]
    outdir = os.path.join("blocks", basename)
    os.makedirs(outdir, exist_ok=True)

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
        first = get_section_num(chunk[0]) or (i + 1)
        last = get_section_num(chunk[-1]) or (i + len(chunk))

        fname = os.path.join(outdir, f"{basename}_block_{block_num:03d}_{first:04d}-{last:04d}.srt")
        with open(fname, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(chunk) + '\n')

        print(f"  Blokk {block_num}: {os.path.basename(fname)} ({len(chunk)} szekció, #{first}-#{last})")

    print(f"\nKész! {block_num} blokk létrehozva: {outdir}")
    return outdir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SRT fájl feldarabolása blokkokra")
    parser.add_argument("input", help="Bemeneti SRT fájl útvonala")
    parser.add_argument("--block-size", type=int, default=150, help="Blokk méret (alapértelmezett: 150)")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"HIBA: Nem találom a fájlt: {args.input}")
        sys.exit(1)

    split_srt(args.input, args.block_size)
