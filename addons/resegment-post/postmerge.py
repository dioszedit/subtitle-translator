#!/usr/bin/env python3
"""Merge utáni utómunka: <stem>.merge.srt helyben javítása.

1. Kártya-visszabontás: ha a `resegment merge` egy szögletes zárójeles
   képernyőfeliratot (címkártya, névtábla) más cue-val vont össze, azt a
   <stem>.reflow.srt eredeti cue-ira és időzítéseire bontja vissza.
2. Egysorosítás: a kétsoros cue-t egy sorba vonja, ha
   - együtt legfeljebb --max-chars (42) karakter,
   - nem dalszöveg (♪),
   - nem két mondat (nincs a cue belsejében . ! ? … utáni folytatás),
   - nem párbeszéd (- A / - B), és nem két külön [kártya] sor.
   (A szabály a felhasználó kézi javításaiból: Her Willing Subject 1–5. rész.)

Használat:  python addons/resegment-post/postmerge.py "output/Sorozat - S01E07.hun"
            (stem: a .reflow.srt és .merge.srt közös eleje)
"""
import argparse
import re
import sys


def ts(s):
    return sum(float(x) * m for x, m in zip(s.replace(',', '.').split(':'), (3600, 60, 1)))


def load(path):
    out = []
    for block in open(path, encoding='utf-8-sig').read().replace('\r', '').strip().split('\n\n'):
        lines = block.split('\n')
        a, z = lines[1].split(' --> ')
        out.append([ts(a), ts(z), lines[1], lines[2:]])
    return out


SENT_INSIDE = re.compile(r'[.!?…]["”»)]?\s+\S')


def can_unbreak(lines, max_chars):
    if len(lines) != 2:
        return False
    joined = f'{lines[0].rstrip()} {lines[1].lstrip()}'
    if len(joined) > max_chars:
        return False
    if '♪' in joined:
        return False
    if any(l.lstrip().startswith('-') for l in lines):
        return False
    if lines[0].strip().startswith('[') and lines[0].strip().endswith(']') \
            and lines[1].strip().startswith('['):
        return False
    if SENT_INSIDE.search(joined):
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stem', help='pl. "output/Sorozat - S01E07.hun"')
    ap.add_argument('--max-chars', type=int, default=42)
    ap.add_argument('--no-unbreak', action='store_true', help='csak a kártya-visszabontás')
    args = ap.parse_args()

    reflow = load(args.stem + '.reflow.srt')
    merged = load(args.stem + '.merge.srt')
    single = {(c[2].split(' --> ')[0], ' '.join(c[3])) for c in reflow}

    res, unmerged = [], 0
    for c in merged:
        is_merged = (c[2].split(' --> ')[0], ' '.join(c[3])) not in single
        if is_merged and any('[' in s for s in c[3]):
            res += [x for x in reflow if x[0] >= c[0] - 0.001 and x[1] <= c[1] + 0.001]
            unmerged += 1
        else:
            res.append(c)
    if any(b[0] < a[1] for a, b in zip(res, res[1:])):
        sys.exit('HIBA: átfedő időzítés a visszabontás után — a fájl nem módosult')

    unbroken = 0
    if not args.no_unbreak:
        for c in res:
            if can_unbreak(c[3], args.max_chars):
                c[3] = [f'{c[3][0].rstrip()} {c[3][1].lstrip()}']
                unbroken += 1

    with open(args.stem + '.merge.srt', 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(f'{i}\n{c[2]}\n' + '\n'.join(c[3]) for i, c in enumerate(res, 1)) + '\n')
    print(f'{args.stem}.merge.srt: {unmerged} kártya-összevonás visszabontva, '
          f'{unbroken} cue egy sorba vonva, {len(res)} cue')


if __name__ == '__main__':
    main()
