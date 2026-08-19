"""
verify_srt.py — Eredeti és fordított SRT összehasonlítása

Használat:
    python verify_srt.py input/eredeti.srt output/fordított.srt
"""

import re
import sys

from subtr.srt import parse_sections
import argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def extract_numbers(filepath: str) -> list[str]:
    """Sorszámok kinyerése — strukturálisan: csak az a csupa-számjegy sor
    számít, amit időbélyeg-sor követ. Így a csak számot tartalmazó
    felirat-SZÖVEG (pl. "3") nem csúsztatja el az összehasonlítást."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        lines = f.read().split('\n')
    return [line.strip() for i, line in enumerate(lines)
            if re.match(r'^\d+$', line.strip())
            and i + 1 < len(lines)
            and re.match(r'^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->', lines[i + 1].strip())]


def extract_timestamps(filepath: str) -> list[str]:
    """Időbélyegek kinyerése — szigorú SRT/WebVTT formátum (--> arrow kötelező),
    hogy ne akadjon be dialógusban szereplő óra-formátumokba (pl. '14:30:00')."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        return [line.strip() for line in f if re.match(r'^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->', line.strip())]


HUN_SUFFIX_PREFIXES = (
    'val', 'vel', 'ban', 'ben', 'ba', 'be', 'bol', 'ből',
    'ra', 're', 'ról', 'ről', 'hoz', 'hez', 'höz',
    'nak', 'nek', 'tól', 'től', 'ig', 'on', 'en', 'ön',
    'n', 'm', 't', 'tt', 'ot', 'et', 'at',
    'ja', 'je', 'juk', 'jük', 'ja', 'ai', 'ei',
)

# Visszatérő hibák — figyelmeztetésként (nem hiba)
# UNIVERZÁLIS minták: bármilyen ázsiai sorozat fordításához érvényesek.
# Sorozat-specifikus szabályok (karakternevek, cégnevek) a glossary.json-ba valók.
WARN_PATTERNS: list[tuple[str, str]] = [
    # Koreai név-átírás: kötőjel helyett szóköz
    # Pl. 'In-a', 'Ki-jun' → rossz; 'Ah-ra', 'Joo-nak' → magyar rag, OK
    # (Kínai pinyinhez egybeírás a jellemző, ezért ott ritkán ad találatot.)
    (r'\b[A-Z][a-z]+-[a-z]+\b',
     "kötőjeles koreai név (pl. 'In-a' → 'In Ah', 'Ki-jun' → 'Ki Jun')"),

    # Pozíció — vállalati drámákban (팀장 / 组长 / 队长) általában 'csoportvezető'
    (r'\bcsapatvezet[őöá]', "rossz cím 'csapatvezető' — helyes: 'csoportvezető'"),

    # Visszatérő tükörfordítások és magyar nyelvi szabályok
    (r'\bJó munka\b', "tükörfordítás 'Jó munka' — helyes: 'Szép munka'"),
    (r'\bepizód\b', "CLAUDE.md szabály: 'epizód' helyett 'rész'"),
    (r'\bjobban próbál', "tükörfordítás 'jobban próbál' — helyes: 'jobban igyekszik'"),
    (r'\bviszony[a-z]* partner', "tükörfordítás 'viszonypartner' — helyes: 'szerető'"),
    (r'\ba hamarabb csak jobb', "tükörfordítás — helyes: 'minél hamarabb, annál jobb'"),
    (r'\bállami kapcsolatok',
     "tükörfordítás 'állami kapcsolatok' (PR félrefordítása) — helyes: 'PR'"),
    (r'\bkinéz érte[md]?\b|\bkinéz érted\b',
     "tükörfordítás 'kinéz érte/érted' (look out for) — helyes: 'kiáll mellette/melletted'"),
    (r'(?i:\bstalk(?:er|ol))', "angolul maradt 'stalker'/'stalkol' — helyes: 'zaklató'/'zaklat'/'üldöz'/'leselkedik'"),
]


def calc_cps(text: str, timestamp: str) -> float | None:
    """Karakter/másodperc (HTML tagek és daljelek nélkül, szóköz nélkül)."""
    m = re.match(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', timestamp)
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

    # 7. Glossary-tiltások és visszatérő hibák (figyelmeztetés)
    print()
    print("Visszatérő hibák (glossary/lektori):")
    pattern_hits: list[tuple[str, str, str]] = []  # (szekciószám, minta, részlet)
    compiled = [(re.compile(pat), msg) for pat, msg in WARN_PATTERNS]
    # az első minta (koreai név) speciális: szűrni kell a magyar ragokat
    korean_name_msg = WARN_PATTERNS[0][1]
    for s in trans_sections:
        text = s["text"]
        for rx, msg in compiled:
            for m in rx.finditer(text):
                hit = m.group(0)
                # Koreai név-mintánál: ha a kötőjel utáni rész magyar rag, kihagyjuk
                if msg == korean_name_msg:
                    after_hyphen = hit.split('-', 1)[1].lower()
                    if any(after_hyphen.startswith(suf) and
                           (len(after_hyphen) == len(suf) or
                            not after_hyphen[len(suf)].isalpha())
                           for suf in HUN_SUFFIX_PREFIXES):
                        continue
                pattern_hits.append((s["num"], msg, hit))
    if not pattern_hits:
        print("  ✓ Nincs ismert hibaminta")
    else:
        # csoportosítás minta szerint
        from collections import defaultdict
        by_msg: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for num, msg, hit in pattern_hits:
            by_msg[msg].append((num, hit))
        print(f"  ⚠ {len(pattern_hits)} találat {len(by_msg)} mintában:")
        for msg, hits in by_msg.items():
            print(f"    • {msg} ({len(hits)} db)")
            for num, hit in hits[:5]:
                print(f"        #{num}: \"{hit}\"")
            if len(hits) > 5:
                print(f"        ... és még {len(hits) - 5} további")

    # 8. Összefoglaló
    print()
    print("=" * 45)
    if errors == 0:
        print("  ✓ Minden rendben! A fordítás formailag helyes.")
    else:
        print(f"  ✗ {errors} probléma találva.")
        print("    Ellenőrizd a fenti részleteket.")
    if cps_issues:
        print(f"  ⚠ {len(cps_issues)} CPS figyelmeztetés (nem hiba)")
    if pattern_hits:
        print(f"  ⚠ {len(pattern_hits)} visszatérő-hiba figyelmeztetés (nem hiba)")
    print("=" * 45)

    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
