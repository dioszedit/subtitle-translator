#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resegment_srt — determinisztikus felirat-újraszegmentáló és QA eszköz.

Módok:
  report   Csak olvasás. Cue-nkénti CPS/sorhossz metrika + flag-ek + összegzés.
  reflow   Minden cue szövegét kiegyensúlyozott <=max-lines sorra tördeli,
           soronként <=max-chars, nyelvi (mondat/kötőszó) határon törve.
           Az időzítést NEM változtatja; a szám+időbélyeg sorok bitre változatlanok.
           --split : ha egy (nem párbeszéd) cue tördelés után is túl hosszú,
                     arányos időfelosztással több egymást követő cue-ra bontja.

Csak Python stdlib. Nyelvfüggetlen (--lang), a plafonok CLI-ből állíthatók.
Nem módosít fordítást/szót — kizárólag tördel és (opcionálisan) időt oszt.
"""
import re, sys, argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

TS = re.compile(
    r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})')

# ---- nyelvi modul (bővíthető) -------------------------------------------------
LANG = {
    "hu": {
        # kötőszavak: törés ELŐTTÜK jó (a kötőszó a 2. sor élére kerül)
        "conj": {"és", "s", "de", "vagy", "hogy", "mert", "mint", "ha", "aki",
                 "akik", "ami", "amely", "amelyek", "ahol", "ahogy", "amikor",
                 "míg", "hiszen", "tehát", "pedig", "illetve", "azonban",
                 "viszont", "ezért", "így", "vagyis", "noha", "bár"},
        # névelők: NE maradjanak sorvégen
        "articles": {"a", "az", "egy"},
    },
    # más nyelvekhez: adj hozzá egy kulcsot ugyanezzel a szerkezettel.
    "generic": {"conj": set(), "articles": set()},
}

# ---- SRT parse / write --------------------------------------------------------
def _sec(h, m, s, ms): return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000

def _fmt(sec):
    if sec < 0: sec = 0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def parse(text):
    """Blokkokra bontja az SRT-t. Megőrzi a fejlécet (szám+időbélyeg sorok)
    szó szerint, hogy a reflow bitre azonos időzítést adhasson vissza."""
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip('\n')
    cues = []
    for b in re.split(r'\n[ \t]*\n', text):
        if not b.strip():
            continue
        lines = b.split('\n')
        ts_i = next((i for i, l in enumerate(lines) if TS.match(l.strip())), None)
        if ts_i is None:
            cues.append({'raw': b})               # nem szabványos blokk: érintetlen
            continue
        m = TS.match(lines[ts_i].strip())
        cues.append({
            'header': '\n'.join(lines[:ts_i + 1]),  # szám + időbélyeg, szó szerint
            't0': _sec(*m.group(1, 2, 3, 4)),
            't1': _sec(*m.group(5, 6, 7, 8)),
            'text': '\n'.join(lines[ts_i + 1:]).strip('\n'),
        })
    return cues

def write_preserve(cues):
    """reflow kimenet: eredeti fejléc szó szerint + (esetleg) új szöveg."""
    out = []
    for c in cues:
        if 'raw' in c:
            out.append(c['raw'])
        else:
            out.append(c['header'] + '\n' + c['text'])
    return '\n\n'.join(out) + '\n'

def write_renumber(cues):
    """split kimenet: 1..N újraszámozás + időbélyeg-újraformázás."""
    out, n = [], 0
    for c in cues:
        if 'raw' in c:
            out.append(c['raw']); continue
        n += 1
        out.append(f"{n}\n{_fmt(c['t0'])} --> {_fmt(c['t1'])}\n{c['text']}")
    return '\n\n'.join(out) + '\n'

# ---- szöveg-segédek -----------------------------------------------------------
def visible(s): return re.sub(r'<[^>]+>', '', s)
def vlen(s): return len(visible(s))

def is_dialogue(lines):
    return any(re.match(r'^-\s', l) for l in lines)

def _strip_outer_tag(text):
    """Ha az egész (akár többsoros) szöveg egyetlen tagpárba van csomagolva
    (<i>...</i>), visszaadja (prefix, belső, suffix)-et, különben ('', text, '')."""
    m = re.match(r'^(<[a-zA-Z]+>)(.*)(</[a-zA-Z]+>)$', text, re.S)
    # A belső részt a NYERS szövegben vizsgáljuk — a visible() kiszedné a
    # tageket, így belső tag sosem tűnne fel, és pl. két külön <i>...</i>
    # sort egyetlen tagpárnak nézne (párosítatlan tagek a kimenetben).
    if m and visible(m.group(1)) == '' and '<' not in m.group(2):
        return m.group(1), m.group(2), m.group(3)
    return '', text, ''

# ---- sortördelés --------------------------------------------------------------
def _break_penalty(left, right, lang):
    """Kisebb = jobb töréspont a `left` sorvég és `right` sorkezdet között."""
    p = 0.0
    le = left.rstrip()
    last = le[-1:] if le else ''
    first_word = re.sub(r'^[^\wÀ-ÿ]+', '', right).split(' ', 1)[0].strip('.,!?;:').lower()
    if last in '.!?…':      p += 0
    elif last in ';:':      p += 0.5
    elif last == ',':       p += 1.0
    elif first_word in lang["conj"]: p += 2.0
    else:                   p += 3.0
    # kerülendő: névelő a sorvégen
    if le.split(' ')[-1].strip('.,!?;:').lower() in lang["articles"]: p += 5.0
    # kerülendő: szám és a rá következő szó szétvágása
    if last.isdigit():      p += 2.0
    # kerülendő: túl rövid csonka sor
    if vlen(left) <= 2 or vlen(right) <= 2: p += 5.0
    # kiegyensúlyozottság
    p += abs(vlen(left) - vlen(right)) * 0.08
    return p

def _wrap_body(body, max_chars, max_lines, lang):
    """Nyers (tag nélküli) szöveg tördelése <= max_lines sorra, rekurzívan.
    Visszatér: sorok listája, vagy None, ha nem fér el."""
    if vlen(body) <= max_chars:
        return [body]
    if max_lines <= 1:
        return None
    spaces = [i for i, ch in enumerate(body) if ch == ' ']
    best, best_p = None, None
    for i in spaces:
        left, right = body[:i].rstrip(), body[i:].lstrip()
        if not left or not right or vlen(left) > max_chars:
            continue
        rest = _wrap_body(right, max_chars, max_lines - 1, lang)
        if rest is None:
            continue
        # kevesebb sor előny; a törésminőség a _break_penalty-ből jön
        p = _break_penalty(left, right, lang) + 0.5 * (len(rest) - 1)
        if best_p is None or p < best_p:
            best_p, best = p, [left] + rest
    return best

def wrap_lines(text, max_chars, max_lines, lang):
    """Egy logikai sort <= max_lines sorra tördel, soronként <= max_chars.
    Visszatér: sorok listája, vagy None, ha nem fér el."""
    if vlen(text) <= max_chars:
        return [text]
    pre, inner, suf = _strip_outer_tag(text)
    body = inner if pre else text
    wrapped = _wrap_body(body, max_chars, max_lines, lang)
    if wrapped is None:
        return None
    if pre:
        return [pre + l + suf for l in wrapped]
    return wrapped

def wrap2(text, max_chars, lang):
    """Kompatibilitási wrapper: <=2 soros tördelés."""
    return wrap_lines(text, max_chars, 2, lang)

def reflow_cue(text, max_chars, max_lines, lang, allow_split):
    """Visszatér: (új_szöveg_vagy_None, flag_lista, szükséges_e_split).
    None új_szöveg => nem kellett változtatni."""
    lines = text.split('\n')
    ok = len(lines) <= max_lines and all(vlen(l) <= max_chars for l in lines)
    if ok:
        return None, [], False                      # már megfelelő -> érintetlen (idempotens)
    if is_dialogue(lines):
        # párbeszéd: szereplőnként külön sor, nem vonjuk össze
        if len(lines) > max_lines or any(vlen(l) > max_chars for l in lines):
            return None, ["dialog-too-long"], False
        return None, [], False
    logical = ' '.join(l.strip() for l in lines if l.strip())
    wrapped = wrap_lines(logical, max_chars, max_lines, lang)
    if wrapped is None:
        return None, [f"too-long-for-{max_lines}-lines"], True
    return '\n'.join(wrapped), [], False

# ---- split (opcionális, időt oszt) --------------------------------------------
def split_cue(cue, max_chars, max_lines, min_dur, min_gap, lang):
    """Túl hosszú (nem párbeszéd) cue-t több egymást követő cue-ra bont,
    az időt a karakterszámmal arányosan osztva."""
    pre, inner, suf = _strip_outer_tag(cue['text'].replace('\n', ' '))
    body = inner if pre else cue['text'].replace('\n', ' ')
    cap = max_chars * max_lines
    words = body.split(' ')
    pieces, cur = [], ''
    for w in words:
        cand = (cur + ' ' + w).strip()
        if vlen(cand) > cap and cur:
            pieces.append(cur); cur = w
        else:
            cur = cand
    if cur:
        pieces.append(cur)
    if len(pieces) < 2:
        return [cue]                                 # nem sikerült bontani
    total = sum(vlen(p) for p in pieces)
    t0, t1 = cue['t0'], cue['t1']
    n_p = len(pieces)
    span = t1 - t0 - min_gap * (n_p - 1)
    if span < 0.1 * n_p:
        return [cue]                                 # nincs elég idő a bontáshoz
    # A min_dur padló csak akkor kényszeríthető, ha összesen belefér a cue
    # idejébe — a feltétel nélküli max(min_dur, ...) korábban átfedő és
    # negatív időtartamú cue-kat adott sűrű (sok szöveg / kevés idő) cue-nál.
    enforce_min = span >= min_dur * n_p
    floor = min_dur if enforce_min else 0.1
    out, cursor = [], t0
    for k, p in enumerate(pieces):
        if k == n_p - 1:
            s0, s1 = cursor, t1
        else:
            d = span * vlen(p) / total
            if enforce_min:
                d = max(min_dur, d)
            # hagyjunk helyet a hátralévő daraboknak
            reserved = (n_p - 1 - k) * (floor + min_gap)
            d = min(d, t1 - cursor - reserved)
            s0, s1 = cursor, cursor + max(d, floor)
            cursor = s1 + min_gap
        if s1 <= s0 or s1 > t1 + 1e-6:
            return [cue]                             # nem osztható értelmesen
        wl = wrap_lines(p, max_chars, max_lines, lang) or [p]
        txt = '\n'.join((pre + x + suf) if pre else x for x in wl)
        out.append({'t0': s0, 't1': s1, 'text': txt})
    return out

# ---- metrikák / report --------------------------------------------------------
def cue_metrics(cues, i):
    c = cues[i]
    lines = [l for l in c['text'].split('\n') if l.strip()]
    chars = sum(vlen(l) for l in lines)
    dur = c['t1'] - c['t0']
    nxt = None
    for j in range(i + 1, len(cues)):
        if 'raw' not in cues[j]:
            nxt = cues[j]; break
    gap = (nxt['t0'] - c['t1']) if nxt else None
    return {
        'chars': chars, 'dur': dur,
        'cps': (chars / dur) if dur > 0 else 0.0,
        'nlines': len(lines),
        'maxline': max((vlen(l) for l in lines), default=0),
        'gap': gap,
    }

def report(cues, cfg):
    rows, flags_total = [], {}
    cps_list = []
    real = [i for i, c in enumerate(cues) if 'raw' not in c]
    for i in real:
        m = cue_metrics(cues, i)
        cps_list.append(m['cps'])
        fl = []
        if m['cps'] > cfg['target_cps']:      fl.append('CPS')
        if m['maxline'] > cfg['max_chars']:   fl.append('LINE')
        if m['nlines'] > cfg['max_lines']:    fl.append('LINES')
        if m['dur'] < cfg['min_dur']:         fl.append('SHORT')
        if m['dur'] > cfg['max_dur']:         fl.append('LONG')
        # csak valódi rés-hiba: átfedés, vagy 0-nál nagyobb de a min-gap alatti
        # rés (villódzás). A ~0 (láncolt, érintkező) cue-kat NEM jelezzük.
        if m['gap'] is not None and (m['gap'] < -0.005 or
                                     0.005 < m['gap'] < cfg['min_gap']):
            fl.append('GAP')
        for f in fl:
            flags_total[f] = flags_total.get(f, 0) + 1
        if fl:
            rows.append((i, m, fl))
    n = len(real)
    if n == 0:
        print("Nincs értelmezhető cue a fájlban (rossz útvonal / nem SRT formátum?)")
        return []
    cps_sorted = sorted(cps_list)
    med = cps_sorted[n // 2]
    over = sum(1 for c in cps_list if c > cfg['target_cps'])
    lines_all = []
    for i in real:
        lines_all += [vlen(l) for l in cues[i]['text'].split('\n') if l.strip()]
    overline = sum(1 for l in lines_all if l > cfg['max_chars'])
    print(f"cue-k: {n} | medián CPS: {med:.1f} | >{cfg['target_cps']} CPS: "
          f"{over} ({100*over/n:.1f}%) | sorok >{cfg['max_chars']} kar.: "
          f"{overline} ({100*overline/max(len(lines_all), 1):.1f}%)")
    if flags_total:
        print("flag-ek:", ", ".join(f"{k}={v}" for k, v in sorted(flags_total.items())))
    for i, m, fl in rows:
        num = cues[i]['header'].split('\n')[0].lstrip('﻿')
        g = f"{m['gap']:.2f}" if m['gap'] is not None else "-"
        print(f"  #{num:<5} cps={m['cps']:4.1f} maxline={m['maxline']:>2} "
              f"lines={m['nlines']} dur={m['dur']:.2f} gap={g}  [{','.join(fl)}]  "
              f"{cues[i]['text'].replace(chr(10),' / ')[:60]!r}")
    return rows

# ---- fő -----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Felirat-újraszegmentáló és QA eszköz.")
    ap.add_argument('mode', choices=['report', 'reflow'])
    ap.add_argument('input')
    ap.add_argument('-o', '--output', help="kimeneti fájl (reflow)")
    ap.add_argument('--in-place', action='store_true', help="bemenet felülírása (reflow)")
    ap.add_argument('--split', action='store_true',
                    help="reflow: túl hosszú cue-k idő-arányos bontása (cue-számot változtat)")
    ap.add_argument('--max-chars', type=int, default=42)
    ap.add_argument('--max-lines', type=int, default=2)
    ap.add_argument('--target-cps', type=float, default=17.0)
    ap.add_argument('--min-dur', type=float, default=1.0)
    ap.add_argument('--max-dur', type=float, default=7.0)
    ap.add_argument('--min-gap', type=float, default=0.08)
    ap.add_argument('--lang', default='hu')
    a = ap.parse_args()
    lang = LANG.get(a.lang, LANG['generic'])
    cfg = dict(max_chars=a.max_chars, max_lines=a.max_lines, target_cps=a.target_cps,
               min_dur=a.min_dur, max_dur=a.max_dur, min_gap=a.min_gap)
    cues = parse(open(a.input, encoding='utf-8').read())

    if a.mode == 'report':
        report(cues, cfg)
        return

    # reflow
    changed = flagged = split_n = 0
    new_cues = []
    for c in cues:
        if 'raw' in c:
            new_cues.append(c); continue
        newtext, fl, need_split = reflow_cue(
            c['text'], a.max_chars, a.max_lines, lang, a.split)
        if need_split and a.split:
            parts = split_cue(c, a.max_chars, a.max_lines, a.min_dur, a.min_gap, lang)
            if len(parts) > 1:
                split_n += 1
                new_cues.extend(parts); continue
        if newtext is not None:
            c = dict(c); c['text'] = newtext; changed += 1
        if fl:
            flagged += 1
        new_cues.append(c)

    out_text = write_renumber(new_cues) if a.split else write_preserve(new_cues)
    if a.in_place:
        open(a.input, 'w', encoding='utf-8').write(out_text)
        dest = a.input
    elif a.output:
        open(a.output, 'w', encoding='utf-8').write(out_text)
        dest = a.output
    else:
        sys.stdout.write(out_text); dest = '(stdout)'
    msg = f"reflow: {changed} cue újratördelve, {flagged} flag-elve"
    if a.split:
        msg += f", {split_n} cue bontva"
    print(f"{msg} -> {dest}", file=sys.stderr)

if __name__ == '__main__':
    main()
