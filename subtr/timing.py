"""Időbélyeg-alapú cue-párosítás két SRT között.

Akkor kell, ha a két fájl sorszámai NEM egyeznek: külső (összevont cue-s)
fordítás, vagy a resegment / merge utáni végleges felirat. A sorszám-alapú
párosítás (`subtr.srt.parse_by_index`) ilyenkor rossz párokat adna.

Az algoritmus: minden forrás-cue ahhoz a cél-cue-hoz kerül, amellyel a
legjobban illeszkedik: elsősorban amelyik a nagyobb részét fedi le, egyenlőség
esetén amelyik időben pontosabban egybeesik vele. Így egy hosszú stáblista- vagy
tábla-cue nem viszi el a vele átfedő párbeszéd forrássorát a pontosan illeszkedő
cue elől. Ha egyikkel sem fedi át egymást, akkor a
legközelebbihez kerül, feltéve, hogy a rés legfeljebb `max_gap` másodperc.
Különben kimarad (pl. reklámsor, a fordításból kihagyott mondat). Egy
cél-cue-hoz így több forrás-cue is tartozhat (n:1).

A bemeneti listák sorrendje tetszőleges (a fájl végére fűzött táblafelirat is
jó); a visszaadott indexek mindig az eredeti listákra mutatnak.

Ezt használja az `addons/align-source` és a `subtr.py consistency`.
"""

import re

from subtr.srt import read_text, split_blocks

TIMESTAMP_RE = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _seconds(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_timed(filepath: str) -> list[dict]:
    """SRT beolvasása időzítéssel: [{num, timestamp, start, end, lines}].

    A `num` string (ahogy a fájlban áll), a `lines` a nem üres szövegsorok
    listája. Ha a blokkból hiányzik a sorszám-sor, a `num` a sorrendből jön, és
    `synthetic_num` True — erre a számra NEM lehet hivatkozni (apply-auto).
    Időbélyeg nélküli blokk kimarad. A sorrend a fájl sorrendje."""
    cues = []
    for block in split_blocks(read_text(filepath)):
        lines = block.split("\n")
        ti = next((i for i, l in enumerate(lines) if TIMESTAMP_RE.search(l)), None)
        if ti is None:
            continue
        g = TIMESTAMP_RE.search(lines[ti]).groups()
        cues.append({
            "num": lines[0].strip() if ti >= 1 else str(len(cues) + 1),
            "synthetic_num": ti < 1,
            "timestamp": lines[ti].strip(),
            "start": _seconds(*g[:4]),
            "end": _seconds(*g[4:]),
            "lines": [l.strip() for l in lines[ti + 1:] if l.strip()],
        })
    return cues


def overlap(a: dict, b: dict) -> float:
    """Két cue időbeli átfedése másodpercben (negatív: a köztük lévő rés)."""
    return min(a["end"], b["end"]) - max(a["start"], b["start"])


def _fit(t: dict, s: dict, ov: float) -> tuple:
    """Illeszkedés, összehasonlítható kulcsként.

    Elsődleges: a forrás-cue mekkora részét fedi le a cél-cue (5%-os lépésben,
    hogy a közel egyforma lefedés döntetlen legyen). Döntetlennél: átfedés / a
    két cue uniója — így a forrással pontosan egybeeső cue nyer egy hosszú
    stáblista- vagy tábla-cue ellen, ami szintén teljesen lefedi."""
    s_dur = s["end"] - s["start"]
    cover = round(20 * ov / s_dur) / 20 if s_dur > 0 else 1.0
    union = max(t["end"], s["end"]) - min(t["start"], s["start"])
    return (cover, ov / union if union > 0 else 0.0)


def overlap_map(target: list[dict], source: list[dict]) -> list[list[tuple[int, float]]]:
    """Minden cél-cue-hoz az ŐT ÁTFEDŐ forrás-cue-k: [(forrás-index, átfedés mp)].

    Rendezett söpréssel számol (nem n×m), a sorrend tetszőleges."""
    t_order = sorted(range(len(target)), key=lambda i: target[i]["start"])
    s_order = sorted(range(len(source)), key=lambda i: source[i]["start"])
    result = [[] for _ in target]
    active = []          # a még „élő” forrás-indexek (a vége még nincs előttünk)
    k = 0
    for ti in t_order:
        t = target[ti]
        while k < len(s_order) and source[s_order[k]]["start"] < t["end"]:
            active.append(s_order[k])
            k += 1
        # ami a mostani cél-cue kezdete előtt véget ér, a későbbiekkel sem fed át
        active = [si for si in active if source[si]["end"] > t["start"]]
        for si in active:
            ov = overlap(t, source[si])
            if ov > 0:
                result[ti].append((si, ov))
    return result


def assign(target: list[dict], source: list[dict], max_gap: float = 1.0):
    """A forrás-cue-k szétosztása a cél-cue-k között.

    Visszaad: (buckets, dropped)
      buckets: a cél-cue-k sorrendjében, mindegyikhez a hozzá rendelt
               forrás-cue-k INDEXEINEK listája, időrendben (lehet üres);
      dropped: azoknak a forrás-cue-knak az indexei, amelyek egyik cél-cue-hoz
               sem kerültek.
    Mindkét lista a parse_timed() kimenetét várja."""
    buckets = [[] for _ in target]
    best = {}            # forrás-index → (illeszkedés, cél-index)
    for ti, hits in enumerate(overlap_map(target, source)):
        for si, ov in hits:
            fit = _fit(target[ti], source[si], ov)
            if si not in best or fit > best[si][0]:
                best[si] = (fit, ti)

    dropped = []
    t_order = sorted(range(len(target)), key=lambda i: target[i]["start"])
    for si, s in enumerate(source):
        if si in best:
            buckets[best[si][1]].append(si)
            continue
        # Átfedés nélkül: a legközelebbi cél-cue, ha a rés ≤ max_gap.
        nearest, nearest_gap = None, None
        for ti in t_order:
            gap = -overlap(target[ti], s)
            if gap <= max_gap and (nearest_gap is None or gap < nearest_gap):
                nearest, nearest_gap = ti, gap
            if target[ti]["start"] > s["end"] + max_gap:
                break
        if nearest is None:
            dropped.append(si)
        else:
            buckets[nearest].append(si)
    for b in buckets:
        b.sort(key=lambda si: source[si]["start"])
    return buckets, dropped
