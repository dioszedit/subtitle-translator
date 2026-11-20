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
import os
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


TAGS = re.compile(r'<[^>]+>|\{[^}]*\}')


def is_card(lines):
    """Egész cue (vagy sor) egy szögletes zárójeles képernyőfelirat (címkártya,
    névtábla) — nem egy mondatba ékelt hangjelzés ([nevet]). A formázó tag
    ({\\an8}, <i>) nem számít."""
    t = words([TAGS.sub('', l) for l in lines])
    return t.startswith('[') and t.endswith(']')


def fmt_ts(sec):
    ms = round(sec * 1000)
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'


def rejoin(pieces, max_chars):
    """Szomszédos nem-kártya darabok újra egy cue-ba (a merge döntése marad):
    egy sor, ha belefér, különben két sor a középhez legközelebbi szóköznél."""
    text = words(sum((x[3] for x in pieces), []))
    lines = [text]
    if len(text) > max_chars and ' ' in text:
        cut = min((k for k, ch in enumerate(text) if ch == ' '), key=lambda k: abs(k - len(text) / 2))
        lines = [text[:cut], text[cut + 1:]]
    a, z = pieces[0][0], pieces[-1][1]
    return [a, z, f'{fmt_ts(a)} --> {fmt_ts(z)}', lines]


def overlaps(cues):
    tl = [c for c in cues if c[0] is not None]
    return {(round(a[0], 3), round(b[0], 3)) for a, b in zip(tl, tl[1:]) if b[0] < a[1]}


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
    if is_card(lines[:1]) or is_card(lines[1:]):   # kártya sor + bármi: két sor marad
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

    stem = re.sub(r'\.(merge|reflow)\.srt$|\.srt$', '', args.stem)
    for ext in ('.reflow.srt', '.merge.srt'):
        if not os.path.isfile(stem + ext):
            sys.exit(f'HIBA: nincs {stem}{ext} — a stem a .reflow.srt és a .merge.srt közös eleje')
    reflow = load(stem + '.reflow.srt')
    merged = load(stem + '.merge.srt')
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
        # A kártyák külön cue-k; a köztük lévő mondatdarabok összevonása marad.
        run = []
        for x in parts + [None]:
            if x is not None and not is_card(x[3]):
                run.append(x)
                continue
            if run:
                res.append(list(run[0]) if len(run) == 1 else rejoin(run, args.max_chars))
                run = []
            if x is not None:
                res.append(list(x))
        unmerged += 1
    for t in kept:
        print(f'FIGYELEM: {t} — a kártyás cue szövege/időzítése eltér a .reflow.srt-től '
              f'(kézi javítás?), változatlanul hagyom.')
    # Csak az új átfedés hiba: a forrásból örökölt (merge-ben, reflow-ban is
    # meglévő) átfedő cue-pár változatlanul marad.
    new = overlaps(res) - overlaps(merged) - overlaps(reflow)
    if new:
        sys.exit(f'HIBA: {len(new)} új átfedő időzítés a visszabontás után — a fájl nem módosult')

    unbroken = 0
    if not args.no_unbreak:
        for c in res:
            if c[0] is not None and can_unbreak(c[3], args.max_chars):
                c[3] = [f'{c[3][0].rstrip()} {c[3][1].lstrip()}']
                unbroken += 1

    with open(stem + '.merge.srt', 'w', encoding='utf-8') as f:
        blocks, i = [], 0
        for c in res:
            if c[0] is None:
                blocks.append('\n'.join(c[3]))
            else:
                i += 1
                blocks.append(f'{i}\n{c[2]}\n' + '\n'.join(c[3]))
        f.write('\n\n'.join(blocks) + '\n')
    print(f'{stem}.merge.srt: {unmerged} kártya-összevonás visszabontva, '
          f'{unbroken} cue egy sorba vonva, {len(res)} cue')


if __name__ == '__main__':
    main()
