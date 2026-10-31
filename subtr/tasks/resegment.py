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
  merge    Egy beszélő folytatólagos mondatát (nincs mondatvégi írásjel, kis rés)
           egy cue-ba vonja, ha a túl gyors cue így lassul; utána a még mindig
           gyors cue-k végét a következő előtti résbe nyújtja. Újraszámoz.
           --ref : eredeti nyelvű sáv — az ugyanabba a ref-cue-ba eső cue-k is
                   összevonhatók. Párbeszédet (- A / - B) nem képez.

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

# ---- merge (opcionális, cue-kat von össze és nyújt) ---------------------------
SENTENCE_END = re.compile(r'[.!?…]["”»\')\]]*$')

def _cps(chars, t0, t1):
    return chars / (t1 - t0) if t1 > t0 else float('inf')

def _ref_id(cue, ref):
    """A referencia-felirat (pl. eredeti nyelvű sáv) azon cue-jának indexe,
    amellyel `cue` időben a legjobban átfed — vagy None."""
    best = None
    for k, r in enumerate(ref):
        ov = min(cue['t1'], r['t1']) - max(cue['t0'], r['t0'])
        if ov > 0 and (best is None or ov > best[0]):
            best = (ov, k)
    return best[1] if best else None

def _join_texts(a, b, max_chars, max_lines, lang):
    """Két cue szövegének egybetördelése, vagy None, ha nem vonható össze
    (párbeszéd, eltérő dőlt jelölés, belső tag, nem fér el)."""
    la, lb = a.split('\n'), b.split('\n')
    if is_dialogue(la) or is_dialogue(lb):
        return None
    flat_a, flat_b = ' '.join(x.strip() for x in la), ' '.join(x.strip() for x in lb)
    pa, ia, sa = _strip_outer_tag(flat_a)
    pb, ib, sb = _strip_outer_tag(flat_b)
    if (pa, sa) != (pb, sb):
        return None                      # pl. dőlt (belső hang/telefon) + normál
    if '<' in ia or '<' in ib:
        return None                      # belső tag: nem bontjuk szét
    wrapped = _wrap_body(ia + ' ' + ib, max_chars, max_lines, lang)
    if wrapped is None:
        return None
    return '\n'.join(pa + l + sa for l in wrapped)

def _proper_nouns(cues):
    """Mondat közben is nagybetűvel álló szavak (tulajdonnevek) a fájlban."""
    names = set()
    for c in cues:
        if 'raw' in c:
            continue
        words = visible(c['text']).replace('\n', ' ').split()
        for prev, w in zip(words, words[1:]):
            if w[:1].isupper() and not SENTENCE_END.search(prev) and not prev.startswith('-'):
                names.add(re.sub(r'\W+$', '', w))
    return names

def _starts_new_sentence(text, names):
    """A cue nagybetűs, nem-tulajdonnév szóval kezdődik (pl. új mondat egy
    vessző után — akár másik beszélőé)."""
    first = re.sub(r'^[^\w]+', '', visible(text)).split(' ', 1)[0]
    first = re.sub(r'\W+$', '', first)
    return bool(first) and first[:1].isupper() and first not in names

def merge_cues(cues, cfg, lang, ref=None):
    """Egymást követő cue-k összevonása, ha ugyanannak a beszélőnek a folytatólagos
    mondata: az első nem mondatvégi írásjellel zárul (vagy — `ref` megadásakor —
    mindkettő ugyanabba a referencia-cue-ba esik), a rés <= max_gap, az együttes
    időtartam <= max_dur, a szöveg kifér max_lines × max_chars-ba, és legalább az
    egyik túl gyors (> target_cps), az összevont pedig lassabb nála.
    Párbeszédet, eltérő dőlt jelölést és nem szabványos blokkot nem érint."""
    out, n_merged = [], 0
    names = _proper_nouns(cues)
    for c in cues:
        if 'raw' in c or not out or 'raw' in out[-1]:
            out.append(dict(c)); continue
        a = out[-1]
        gap = c['t0'] - a['t1']
        if gap < -0.005 or gap > cfg['max_gap'] or c['t1'] - a['t0'] > cfg['max_dur']:
            out.append(dict(c)); continue
        cont = (not SENTENCE_END.search(visible(a['text']).strip())
                and not _starts_new_sentence(c['text'], names))
        if not cont and ref:
            ra, rb = _ref_id(a, ref), _ref_id(c, ref)
            cont = ra is not None and ra == rb
        if not cont:
            out.append(dict(c)); continue
        ca, cb = vlen(a['text'].replace('\n', '')), vlen(c['text'].replace('\n', ''))
        fast = max(_cps(ca, a['t0'], a['t1']), _cps(cb, c['t0'], c['t1']))
        if fast <= cfg['target_cps']:
            out.append(dict(c)); continue
        joined = _join_texts(a['text'], c['text'], cfg['max_chars'], cfg['max_lines'], lang)
        if joined is None or _cps(vlen(joined.replace('\n', '')), a['t0'], c['t1']) >= fast:
            out.append(dict(c)); continue
        out[-1] = {'t0': a['t0'], 't1': c['t1'], 'text': joined}
        n_merged += 1
    return out, n_merged

def extend_cues(cues, cfg):
    """A még mindig túl gyors cue végét kitolja a következő előtti résbe
    (legfeljebb target_cps-ig és max_dur-ig, min_gap-et hagyva). Átfedést sosem ír."""
    n = 0
    real = [i for i, c in enumerate(cues) if 'raw' not in c]
    for pos, i in enumerate(real):
        c = cues[i]
        chars = vlen(c['text'].replace('\n', ''))
        if _cps(chars, c['t0'], c['t1']) <= cfg['target_cps']:
            continue
        # +1 ms tartalék: a ms-ra kerekített kimenetben se essen a rés min_gap alá
        limit = (cues[real[pos + 1]]['t0'] - cfg['min_gap'] - 0.001
                 if pos + 1 < len(real) else c['t1'] + 2.0)
        want = c['t0'] + min(chars / cfg['target_cps'], cfg['max_dur'])
        new_t1 = min(want, limit)
        if new_t1 > c['t1'] + 0.01:
            cues[i] = dict(c, t1=new_t1); n += 1
    return n

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
def main(argv=None):
    ap = argparse.ArgumentParser(description="Felirat-újraszegmentáló és QA eszköz.")
    ap.add_argument('mode', choices=['report', 'reflow', 'merge'])
    ap.add_argument('input')
    ap.add_argument('-o', '--output', help="kimeneti fájl (reflow/merge)")
    ap.add_argument('--in-place', action='store_true', help="bemenet felülírása (reflow/merge)")
    ap.add_argument('--ref', help="merge: referencia-felirat (pl. az eredeti nyelvű sáv) — "
                                  "az ugyanabba a ref-cue-ba eső cue-k mondatvég után is összevonhatók")
    ap.add_argument('--max-gap', type=float, default=0.5,
                    help="merge: legfeljebb ekkora rés (mp) mellett von össze (alap: 0.5)")
    ap.add_argument('--no-extend', action='store_true',
                    help="merge: ne nyújtsa a még mindig gyors cue-kat a következő előtti résbe")
    ap.add_argument('--split', action='store_true',
                    help="reflow: túl hosszú cue-k idő-arányos bontása (cue-számot változtat)")
    ap.add_argument('--max-chars', type=int, default=42)
    ap.add_argument('--max-lines', type=int, default=2)
    ap.add_argument('--target-cps', type=float, default=17.0)
    ap.add_argument('--min-dur', type=float, default=1.0)
    ap.add_argument('--max-dur', type=float, default=7.0)
    ap.add_argument('--min-gap', type=float, default=0.08)
    ap.add_argument('--lang', default='hu')
    a = ap.parse_args(argv)
    lang = LANG.get(a.lang, LANG['generic'])
    cfg = dict(max_chars=a.max_chars, max_lines=a.max_lines, target_cps=a.target_cps,
               min_dur=a.min_dur, max_dur=a.max_dur, min_gap=a.min_gap, max_gap=a.max_gap)
    # utf-8-sig: a Windows-os szerkesztők BOM-ja különben az első cue
    # fejlécébe kerülne, és a reflow visszaírná a fájl közepére.
    cues = parse(open(a.input, encoding='utf-8-sig').read())

    if a.mode == 'report':
        report(cues, cfg)
        return

    if a.mode == 'merge':
        ref = None
        if a.ref:
            ref = [c for c in parse(open(a.ref, encoding='utf-8-sig').read()) if 'raw' not in c]
        before = len([c for c in cues if 'raw' not in c])
        new_cues, n_merged = merge_cues(cues, cfg, lang, ref)
        n_ext = 0 if a.no_extend else extend_cues(new_cues, cfg)
        out_text = write_renumber(new_cues)
        if a.in_place:
            dest = a.input
        elif a.output:
            dest = a.output
        else:
            sys.stdout.write(out_text); dest = None
        if dest:
            open(dest, 'w', encoding='utf-8').write(out_text)
        after = len([c for c in new_cues if 'raw' not in c])
        print(f"merge: {before} -> {after} cue ({n_merged} összevonás), "
              f"{n_ext} cue nyújtva -> {dest or '(stdout)'}", file=sys.stderr)
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
