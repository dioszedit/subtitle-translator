#!/usr/bin/env python3
"""Merge utáni utómunka: <stem>.merge.srt helyben javítása.

1. Kártya-visszabontás: ha a `resegment merge` egy szögletes zárójeles
   képernyőfeliratot (címkártya, névtábla) más cue-val vont össze, azt a
   <stem>.reflow.srt eredeti cue-ira és időzítéseire bontja vissza.
2. Egysorosítás: a kétsoros cue-t egy sorba vonja, ha
   - együtt legfeljebb --max-chars (42) karakter,
   - nem dalszöveg (♪ / ♫),
   - nem két mondat (nincs a cue belsejében . ! ? … utáni folytatás),
   - nem párbeszéd (- A / – A, dőlt <i>- A is), és nem két külön [kártya] sor.
   (A szabály a felhasználó kézi javításaiból: Her Willing Subject 1–5. rész.)

Használat:  python addons/resegment-post/postmerge.py "output/Sorozat - S01E07.hun"
            (stem: a .reflow.srt és .merge.srt közös eleje)
"""
import argparse
import re
import sys


def ts(s):
    return sum(float(x) * m for x, m in zip(s.replace(',', '.').split(':'), (3600, 60, 1)))


TIMING = re.compile(r'^\s*(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)')


def load(path):
    """Cue-k [start, end, időzítés-sor, sorok]. Üres blokkot (több üres sor,
    szóközös elválasztó) kihagy; időzítés nélküli blokk [None, None, None,
    sorok] — változatlanul továbbmegy, ahogy a merge is átengedi."""
    out = []
    text = open(path, encoding='utf-8-sig').read().replace('\r', '')
    for block in re.split(r'\n[ \t]*\n', text.strip()):
        lines = [l for l in block.split('\n')]
        if not any(l.strip() for l in lines):
            continue
        i = next((k for k, l in enumerate(lines[:2]) if TIMING.match(l)), None)
        if i is None:
            out.append([None, None, None, lines])
            continue
        m = TIMING.match(lines[i])
        out.append([ts(m[1]), ts(m[2]), lines[i].strip(), lines[i + 1:]])
    return out


def words(lines):
    return ' '.join(' '.join(lines).split())


def is_card(lines):
    """Egész cue egy szögletes zárójeles képernyőfelirat (címkártya, névtábla) —
    nem egy mondatba ékelt hangjelzés ([nevet])."""
    t = words(lines)
    return t.startswith('[') and t.endswith(']')


TAGS = re.compile(r'<[^>]+>|\{[^}]*\}')


SENT_INSIDE = re.compile(r'[.!?…]["”»)]?\s+\S')


def can_unbreak(lines, max_chars):
    if len(lines) != 2:
        return False
    joined = f'{lines[0].rstrip()} {lines[1].lstrip()}'
    if len(joined) > max_chars:
        return False
    if re.search('[♪♫]', joined):
        return False
    if any(TAGS.sub('', l).lstrip().startswith(('-', '–', '—')) for l in lines):
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
    timed = [x for x in reflow if x[0] is not None]
    single = {(round(x[0], 3), words(x[3])) for x in timed}

    res, unmerged, kept = [], 0, []
    for c in merged:
        if c[0] is None or (round(c[0], 3), words(c[3])) in single:
            res.append(c)
            continue
        parts = [x for x in timed if x[0] >= c[0] - 0.001 and x[1] <= c[1] + 0.001]
        if len(parts) < 2 or not any(is_card(x[3]) for x in parts):
            res.append(c)          # nem kártya-összevonás
            continue
        # Csak ha a darabok pontosan kiadják a cue-t: kézi javítás vagy
        # eltérő időzítés után nem írjuk vissza (a javítás elveszne).
        if abs(parts[0][0] - c[0]) > 0.001 or words(sum((x[3] for x in parts), [])) != words(c[3]):
            kept.append(c[2])
            res.append(c)
            continue
        res += [list(x) for x in parts]
        unmerged += 1
    for t in kept:
        print(f'FIGYELEM: {t} — a kártyás cue szövege/időzítése eltér a .reflow.srt-től '
              f'(kézi javítás?), változatlanul hagyom.')
    tl = [c for c in res if c[0] is not None]
    if any(b[0] < a[1] for a, b in zip(tl, tl[1:])):
        sys.exit('HIBA: átfedő időzítés a visszabontás után — a fájl nem módosult')

    unbroken = 0
    if not args.no_unbreak:
        for c in res:
            if c[0] is not None and can_unbreak(c[3], args.max_chars):
                c[3] = [f'{c[3][0].rstrip()} {c[3][1].lstrip()}']
                unbroken += 1

    with open(args.stem + '.merge.srt', 'w', encoding='utf-8') as f:
        blocks, i = [], 0
        for c in res:
            if c[0] is None:
                blocks.append('\n'.join(c[3]))
            else:
                i += 1
                blocks.append(f'{i}\n{c[2]}\n' + '\n'.join(c[3]))
        f.write('\n\n'.join(blocks) + '\n')
    print(f'{args.stem}.merge.srt: {unmerged} kártya-összevonás visszabontva, '
          f'{unbroken} cue egy sorba vonva, {len(res)} cue')


if __name__ == '__main__':
    main()
