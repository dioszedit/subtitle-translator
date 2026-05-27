"""
verify_srt.py — Eredeti és fordított SRT összehasonlítása

Használat:
    python verify_srt.py input/eredeti.srt output/fordított.srt
"""

import re
import sys
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def extract_numbers(filepath: str) -> list[str]:
    """Sorszámok kinyerése."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        return [line.strip() for line in f if re.match(r'^\d+$', line.strip())]


def extract_timestamps(filepath: str) -> list[str]:
    """Időbélyegek kinyerése."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        return [line.strip() for line in f if re.match(r'^\d{2}:\d{2}:\d{2}', line.strip())]


def parse_sections(filepath: str) -> list[dict]:
    """SRT szekciók kinyerése: num, timestamp, text."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    sections = []
    raw_blocks = re.split(r'\n\s*\n', content.strip())
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split('\n')
        if len(lines) >= 3:
            sections.append({
                "num": lines[0].strip(),
                "timestamp": lines[1].strip(),
                "text": "\n".join(lines[2:])
            })
        elif len(lines) == 2:
            sections.append({"num": lines[0].strip(), "timestamp": lines[1].strip(), "text": ""})
    return sections


def calc_cps(text: str, timestamp: str) -> float | None:
    """Karakter/másodperc (HTML tagek és daljelek nélkül, szóköz nélkül)."""
    m = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})', timestamp)
    if not m:
        return None
    start = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000
    end = int(m.group(5))*3600 + int(m.group(6))*60 + int(m.group(7)) + int(m.group(8))/1000
    duration = end - start
    if duration <= 0:
        return None
    clean = re.sub(r'<[^>]+>', '', text)
    clean = clean.replace('♫', '').replace('♪', '')
    chars = sum(len(line.replace(' ', '')) for line in clean.split('\n'))
    return chars / duration


def main():
    parser = argparse.ArgumentParser(description="SRT fordítás ellenőrzése")
    parser.add_argument("original", help="Eredeti (angol) SRT fájl")
    parser.add_argument("translated", help="Fordított (magyar) SRT fájl")
    args = parser.parse_args()

    print("=" * 45)
    print("  SRT Ellenőrzés")
    print("=" * 45)
    print(f"  Eredeti:   {args.original}")
    print(f"  Fordított: {args.translated}")
    print()

    errors = 0

    # 1. Szekciószám
    orig_nums = extract_numbers(args.original)
    trans_nums = extract_numbers(args.translated)

    print(f"Szekciók — Eredeti: {len(orig_nums)}, Fordított: {len(trans_nums)}")
    if len(orig_nums) == len(trans_nums):
        print("  ✓ Szekciószám egyezik")
    else:
        diff = len(trans_nums) - len(orig_nums)
        print(f"  ✗ ELTÉRÉS! Különbség: {diff:+d}")
        errors += 1

    # 2. Sorszámok egyezése
    print()
    print("Sorszámok:")
    num_mismatches = []
    for i, (o, t) in enumerate(zip(orig_nums, trans_nums)):
        if o != t:
            num_mismatches.append((i + 1, o, t))

    if not num_mismatches:
        print("  ✓ Minden sorszám egyezik")
    else:
        print(f"  ✗ {len(num_mismatches)} sorszám eltérés!")
        for pos, orig, trans in num_mismatches[:5]:
            print(f"    {pos}. pozíció: eredeti={orig}, fordított={trans}")
        if len(num_mismatches) > 5:
            print(f"    ... és még {len(num_mismatches) - 5} további")
        errors += 1

    # 3. Időbélyegek
    print()
    print("Időbélyegek:")
    orig_ts = extract_timestamps(args.original)
    trans_ts = extract_timestamps(args.translated)

    ts_mismatches = []
    for i, (o, t) in enumerate(zip(orig_ts, trans_ts)):
        if o != t:
            ts_mismatches.append((i + 1, o, t))

    if not ts_mismatches:
        print("  ✓ Minden időbélyeg egyezik")
    else:
        print(f"  ✗ {len(ts_mismatches)} időbélyeg eltérés!")
        for pos, orig, trans in ts_mismatches[:5]:
            print(f"    {pos}. pozíció:")
            print(f"      eredeti:   {orig}")
            print(f"      fordított: {trans}")
        if len(ts_mismatches) > 5:
            print(f"    ... és még {len(ts_mismatches) - 5} további")
        errors += 1

    # 4. Üres szekciók
    print()
    print("Üres szekciók:")
    trans_sections = parse_sections(args.translated)
    empty_sections = [s for s in trans_sections if not s["text"].strip()]
    if not empty_sections:
        print("  ✓ Nincs üres szekció")
    else:
        print(f"  ✗ {len(empty_sections)} üres szekció!")
        for s in empty_sections[:10]:
            print(f"    #{s['num']} ({s['timestamp']})")
        if len(empty_sections) > 10:
            print(f"    ... és még {len(empty_sections) - 10} további")
        errors += 1

    # 5. HTML tag párosítás
    print()
    print("HTML tagek:")
    tag_issues = []
    for s in trans_sections:
        text = s["text"]
        for tag in ["i", "b"]:
            opens = len(re.findall(f'<{tag}>', text))
            closes = len(re.findall(f'</{tag}>', text))
            if opens != closes:
                tag_issues.append(f"#{s['num']}: <{tag}> = {opens}, </{tag}> = {closes}")
    if not tag_issues:
        print("  ✓ HTML tagek rendben")
    else:
        print(f"  ✗ {len(tag_issues)} párosítatlan HTML tag!")
        for issue in tag_issues[:10]:
            print(f"    {issue}")
        if len(tag_issues) > 10:
            print(f"    ... és még {len(tag_issues) - 10} további")
        errors += 1

    # 6. Olvasási sebesség (CPS > 20) — csak figyelmeztetés
    print()
    print("Olvasási sebesség (CPS):")
    cps_issues = []
    for s in trans_sections:
        cps = calc_cps(s["text"], s["timestamp"])
        if cps is not None and cps > 20:
            cps_issues.append((s["num"], cps))
    if not cps_issues:
        print("  ✓ Minden szekció 20 CPS alatt")
    else:
        print(f"  ⚠ {len(cps_issues)} szekció meghaladja a 20 CPS-t")
        for num, cps in cps_issues[:10]:
            print(f"    #{num}: {cps:.1f} CPS")
        if len(cps_issues) > 10:
            print(f"    ... és még {len(cps_issues) - 10} további")

    # 7. Összefoglaló
    print()
    print("=" * 45)
    if errors == 0:
        print("  ✓ Minden rendben! A fordítás formailag helyes.")
    else:
        print(f"  ✗ {errors} probléma találva.")
        print("    Ellenőrizd a fenti részleteket.")
    if cps_issues:
        print(f"  ⚠ {len(cps_issues)} CPS figyelmeztetés (nem hiba)")
    print("=" * 45)

    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
