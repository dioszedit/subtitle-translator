"""
subtr.py consistency — sorozatszintű konzisztencia-riport a kész fordításokból

Használat:
    python subtr.py consistency                       # a munkakönyvtár sorozata
    python subtr.py consistency "..\\Sorozat (2026)"   # egy másik sorozat-mappa
    python subtr.py consistency --decisions           # + javaslatfájl részenként

LLM nélkül, csak riportál. Két dolgot keres a sorozat összes kész magyar
feliratában:

1. **Azonos forrássor, eltérő fordítás.** Ugyanaz a (normalizált) forrássor
   különböző helyeken másképp lett lefordítva:
     - képernyőszöveg (`[…]` a forrásban: tábla, névkártya, helyszín),
     - dalszöveg (`♪` / `♫`),
     - hosszabb párbeszédsor (`--min-chars`, alap 25 karakter; a rövid
       mondatok, pl. „Igen.”, jogosan térnek el).
   A magyar feliratot a forrással IDŐZÍTÉS alapján párosítja
   (`subtr/timing.py`), így a resegment utáni, átszámozott fájlon és a külső,
   összevont feliratú fordításon is működik.

2. **Írásmód-változatok.** Ugyanannak a névnek több alakja él a magyar
   szövegben (Taolu / Taolú, Nagy Zen / Nagy Zhen, Hongshan / Hongsan): a
   nagybetűs, nem mondatkezdő szóalakokat ékezet, kötőjel és a pinyin
   sh/zh/ch → s/z/c különbség nélkül veti össze.

Melyik fájl számít késznek: a `Season NN/…hun.srt`, ha van; különben az
`output/…hun.merge.srt` (a resegment utáni végleges változat), ha az sincs, az
`output/…hun.srt`. A forrás az `input/…<nyelv>.srt` — ugyanaz a keresés és
nyelvválasztás (`--source-lang`, `SUBTR_SOURCE_LANG`), mint a review-é.

Egy előfordulás csak akkor számít, ha a magyar felirat és a forrássor időben
lényegében egybeesik: a kettévágott dalsor, vagy a dal mellé került
párbeszédsor kimarad, mert ott az összevetés (és a javaslat) téves lenne.

A `--decisions` kapcsolóval a képernyőszöveg- és dal-eltérésekhez, ahol van
egyértelmű többségi változat, részenként egy `decisions.json`-formátumú fájl
készül az `output/` mappába (`<név>.hun_consistency.json`); az elavult
javaslatfájlt törli. Ezt a meglévő `apply-auto` vezeti át, előbb `--dry-run`-nal. Párbeszédhez és írásmódhoz nem
készül automatikus javaslat: ott a döntés a felhasználóé.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from subtr import config
from subtr.glossary import normalize_for_match
from subtr.timing import assign, overlap_map, parse_timed

SEASON_DIR_RE = re.compile(r"^Season \d+$")

# Párosítási tűrések (másodperc-arányok). Egy előfordulás csak akkor számít,
# ha a magyar cue és a forrás-cue tényleg ugyanazt a szakaszt fedi: különben
# egy félbevágott dalsor vagy egy szomszédos párbeszédsor hamis eltérést, a
# --decisions pedig sorvesztést vagy duplázást okozna.
MIN_SOURCE_COVER = 0.75     # a forrás-cue legalább ekkora részét fedje ez a magyar cue
MAX_SPILL = 0.25            # … és legfeljebb ekkora része essen más magyar cue-ra
FOREIGN_SPEECH = 0.3        # ennél (mp) több átfedés más forrás-beszéddel → kimarad

BRACKET_RE = re.compile(r"\[[^\[\]]+\]")   # a tábla több sorra is törhet
TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")
SONG_RE = re.compile(r"[♪♫]")
LEADING_DASH_RE = re.compile(r"^\s*[-–—]\s*", re.M)
NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)

# Nagybetűs szóalak (a magyar ékezetes nagybetűkkel); a kötőjel és az
# aposztróf a szó része (Malom-fogadó, Mei'er).
NAME_TOKEN_RE = re.compile(r"(?<![\w'’-])[A-ZÁÉÍÓÖŐÚÜŰ][\w'’-]*", re.UNICODE)
# Ami után a következő szó mondatkezdő (nem bizonyít tulajdonnevet).
SENTENCE_BREAK = set(".!?…:;\"„”»«([–—-")

MAX_EXAMPLES = 4


# ── Fájlok ────────────────────────────────────────────────────────────────

def final_subtitles(project_dir: str, only_dir: str | None = None) -> list[dict]:
    """A kész magyar feliratok, részenként egy: [{path, stem, folder}].

    Elsőbbség: `Season NN/…hun.srt`; ha a rész ott nincs, az `output/`-ból a
    `…hun.merge.srt` (a resegment utáni végleges változat), ha az sincs, a
    `…hun.srt`. A `.reflow.srt` köztes fájl, kimarad."""
    if only_dir:
        dirs = [only_dir]
    else:
        seasons = sorted(d for d in os.listdir(project_dir)
                         if SEASON_DIR_RE.match(d) and os.path.isdir(os.path.join(project_dir, d))) \
            if os.path.isdir(project_dir) else []
        dirs = seasons + ["output"]
    chosen = {}
    for sub in dirs:
        folder = os.path.join(project_dir, sub)
        if not os.path.isdir(folder):
            continue
        names = set(os.listdir(folder))
        for name in sorted(names):
            if name.endswith(".hun.merge.srt"):
                stem = name[:-len(".hun.merge.srt")]
            elif name.endswith(".hun.srt"):
                stem = name[:-len(".hun.srt")]
                if f"{stem}.hun.merge.srt" in names:
                    continue
            else:
                continue
            chosen.setdefault(stem, {"path": os.path.join(folder, name), "stem": stem,
                                     "folder": folder})
    return [chosen[s] for s in sorted(chosen)]


def find_source(entry: dict, lang: str | None) -> str | None:
    """A forrás-SRT — ugyanaz a keresés, mint a review-é, a rész nevéből."""
    from subtr.tasks.review import find_source_srt
    found = find_source_srt(Path(entry["folder"]) / f"{entry['stem']}.hun.srt", lang)
    return str(found) if found else None


def episode_label(stem: str) -> str:
    m = re.search(r"S\d+E\d+", stem, re.I)
    return m.group(0).upper() if m else stem


# ── Normalizálás ──────────────────────────────────────────────────────────

def strip_markup(text: str) -> str:
    """HTML/ASS tag, daljel és párbeszéd-gondolatjel nélküli szöveg."""
    text = TAG_RE.sub("", text)
    text = SONG_RE.sub("", text)
    return LEADING_DASH_RE.sub("", text)


def norm_key(text: str) -> str:
    """Összevetési kulcs: jelölés, írásjel, kis/nagybetű és tördelés nélkül."""
    text = normalize_for_match(strip_markup(text))
    text = NON_WORD_RE.sub(" ", text)
    return " ".join(text.split())


def is_caption_cue(lines: list[str]) -> bool:
    """A cue teljes szövege egy vagy több [szögletes zárójeles] darab
    (egy darab több sorra is törhet)."""
    text = TAG_RE.sub("", "\n".join(lines))
    return bool(BRACKET_RE.search(text)) and not BRACKET_RE.sub("", text).strip()


def is_song_cue(lines: list[str]) -> bool:
    return any(SONG_RE.search(l) for l in lines)


def without_captions(text: str) -> str:
    """A magyar szöveg a képernyőszöveg-darabok nélkül (sorok megtartva)."""
    lines = [l.strip() for l in BRACKET_RE.sub("", text).split("\n")]
    return "\n".join(l for l in lines if l)


# ── 1. Azonos forrás, eltérő fordítás ─────────────────────────────────────

DIALOGUE_LINE_RE = re.compile(r"^\s*(?:<[^>]+>|\{\\[^}]*\})*\s*[-–—]")   # „- Gyere!”, „-Gyere!”, {\an8} után is


def _whole_match(ti: int, si: int, src: list, by_source: dict, ov: float,
                 same_kind: list[bool]) -> bool:
    """A forrás-cue (si) lényegében ebben a magyar cue-ban (ti) van, nem kettévágva.

    „Kilógásnak” csak az azonos fajtájú magyar cue-kkal (tábla a táblát hordozó,
    beszéd a szöveget hordozó cue-kkal) közös idő számít: egy vele egy időben
    futó, külön tábla-cue nem teszi a párbeszédet kettévágottá, és fordítva."""
    duration = src[si]["end"] - src[si]["start"]
    if duration <= 0:
        return True
    spill = sum(o for tj, o in by_source.get(si, ()) if tj != ti and same_kind[tj])
    return ov / duration >= MIN_SOURCE_COVER and spill / duration <= MAX_SPILL


def collect_occurrences(hun_path: str, src_path: str, min_chars: int,
                        captions: bool = True) -> list[dict]:
    """Egy rész párosított előfordulásai: [{kind, key, source, raw, norm, num, text, num_ok}]."""
    hun, src = parse_timed(hun_path), parse_timed(src_path)
    if not hun or not src:
        return []
    buckets, _ = assign(hun, src)
    hits = overlap_map(hun, src)
    by_source = defaultdict(list)            # forrás-index → [(magyar-index, átfedés)]
    for ti, row in enumerate(hits):
        for si, ov in row:
            by_source[si].append((ti, ov))
    num_counts = Counter(c["num"] for c in hun)
    hun_texts = ["\n".join(c["lines"]) for c in hun]
    has_caption = [bool(BRACKET_RE.search(x)) for x in hun_texts]
    has_body = [bool(without_captions(x)) for x in hun_texts]

    out = []
    for ti, (cue, bucket) in enumerate(zip(hun, buckets)):
        if not bucket:
            continue
        text = "\n".join(cue["lines"])
        ov_of = dict(hits[ti])
        num_ok = (cue["num"].isdigit() and num_counts[cue["num"]] == 1
                  and not cue.get("synthetic_num"))
        caption_idx = [si for si in bucket if is_caption_cue(src[si]["lines"])]
        spoken_idx = [si for si in bucket if si not in caption_idx]

        # Képernyőszöveg: csak ha a forrásban és a magyarban is pontosan EGY
        # tábla-darab van (több táblánál a fordító sorrendje eltérhet), és a
        # forrás-tábla ebbe a cue-ba esik, nem kettévágva.
        if captions and len(caption_idx) == 1:
            si = caption_idx[0]
            src_caps = BRACKET_RE.findall("\n".join(src[si]["lines"]))
            hun_caps = BRACKET_RE.findall(text)
            if (len(src_caps) == 1 and len(hun_caps) == 1
                    and _whole_match(ti, si, src, by_source, ov_of.get(si, 0.0), has_caption)):
                out.append(_occ("caption", src_caps[0], hun_caps[0], cue, text, num_ok))

        if not spoken_idx:
            continue
        body = without_captions(text)
        if not body:
            continue
        # Minden forrás-beszéd egészében itt van, és nincs a cue-ban más,
        # máshova rendelt forrás-beszéd (pl. egy párbeszédsor a dal mellett).
        if not all(_whole_match(ti, si, src, by_source, ov_of.get(si, 0.0), has_body)
                   for si in spoken_idx):
            continue
        # A forrásban tábla is van, de a magyarban nincs zárójeles tábla: a
        # fordító zárójel nélkül (pl. dőlten) írta, az a szövegtörzsben maradt.
        if caption_idx and not BRACKET_RE.search(text):
            continue
        foreign = [si for si, ov in hits[ti] if si not in bucket
                   and not is_caption_cue(src[si]["lines"]) and ov > FOREIGN_SPEECH]
        if foreign:
            continue
        spoken = [src[si]["lines"] for si in spoken_idx]
        source_text = "\n".join("\n".join(lines) for lines in spoken)
        if all(is_song_cue(lines) for lines in spoken):
            # párbeszédjeles sor, vagy daljeles és daljel nélküli sor vegyesen:
            # nem tiszta dal-cue, a javaslat a nem-dal sort is lecserélné
            body_lines = body.split("\n")
            if any(DIALOGUE_LINE_RE.match(l) for l in body_lines):
                continue
            marked = [bool(SONG_RE.search(l)) for l in body_lines]
            if any(marked) and not all(marked) and not _song_wrapped(body_lines):
                continue
            out.append(_occ("song", source_text, body, cue, text, num_ok))
        elif len(spoken) == 1 and len(norm_key(source_text)) >= min_chars:
            out.append(_occ("dialogue", source_text, body, cue, text, num_ok))
    return out


def _song_wrapped(lines: list[str]) -> bool:
    """A daljel csak a cue elejét és végét fogja közre (♫ első sor / utolsó sor ♫)."""
    first, last = TAG_RE.sub("", lines[0]).strip(), TAG_RE.sub("", lines[-1]).strip()
    return SONG_RE.search(first[:2]) is not None and SONG_RE.search(last[-2:]) is not None


def caption_norm(text: str) -> str:
    """Táblánál szigorúbb összevetés: a kis/nagybetű és a kötőjel is számít
    ([Malom-fogadó] ≠ [Malom Fogadó]), csak a jelölés és a tördelés nem."""
    return " ".join(strip_markup(text).split())


def _occ(kind, source, raw, cue, text, num_ok=True):
    norm = caption_norm(raw) if kind == "caption" else norm_key(raw)
    return {"kind": kind, "key": norm_key(source), "source": " / ".join(source.split("\n")),
            "raw": raw, "norm": norm, "num": cue["num"], "text": text, "num_ok": num_ok}


def find_conflicts(occurrences: list[dict]) -> list[dict]:
    """Az azonos forrású, de eltérő magyarságú csoportok, többségi javaslattal."""
    groups = defaultdict(list)
    for occ in occurrences:
        if occ["key"] and occ["norm"]:
            groups[(occ["kind"], occ["key"])].append(occ)
    conflicts = []
    for (kind, _), occs in groups.items():
        counts = Counter(o["norm"] for o in occs)
        if len(counts) < 2:
            continue
        ranked = counts.most_common()
        majority = ranked[0][0] if ranked[0][1] > ranked[1][1] else None
        suggested = None
        if majority:
            suggested = Counter(o["raw"] for o in occs if o["norm"] == majority).most_common(1)[0][0]
        variants = []
        for norm, n in ranked:
            members = [o for o in occs if o["norm"] == norm]
            variants.append({"norm": norm, "count": n, "raw": members[0]["raw"],
                             "where": [f"{o['episode']}#{o['num']}" for o in members]})
        conflicts.append({"kind": kind, "source": occs[0]["source"], "variants": variants,
                          "majority": majority, "suggested": suggested, "occurrences": occs})
    order = {"caption": 0, "song": 1, "dialogue": 2}
    conflicts.sort(key=lambda c: (order[c["kind"]], -len(c["occurrences"]), c["source"]))
    return conflicts


# ── 2. Írásmód-változatok ─────────────────────────────────────────────────

def skeleton(token: str) -> str:
    """Ékezet, kötőjel, aposztróf és pinyin sh/zh/ch nélküli kisbetűs alak."""
    t = unicodedata.normalize("NFD", token.lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    # kötőjel, aposztróf ÉS szóköz nélkül: a „Malom-Fogadó” és a „Malom Fogadó”
    # ugyanaz a név, csak másképp írva
    t = re.sub(r"['’\- ]", "", t)
    # Pinyin sh/zh/ch ↔ s/z/c csak hosszabb alaknál: a rövid, önálló „Si” és „Shi”
    # (pl. egy kétszavas név második tagja mondat elején) két különböző név lehet.
    if len(t) >= 5:
        t = re.sub(r"([szc])h", r"\1", t)
    return t


_NAME_WORD = r"[A-ZÁÉÍÓÖŐÚÜŰ][\w'’-]*"
NAME_RUN_RE = re.compile(r"(?<![\w'’-])" + _NAME_WORD + r"(?: " + _NAME_WORD + r")*", re.UNICODE)


def name_tokens(text: str):
    """Nagybetűs szóalakok, a szomszédos nagybetűs szavak EGYBEN (Wu Si, Nagy Zhen):
    így egy rövid névtag nem keveredik egy másik név tagjával. A mondat első szava nem
    számít (a mondatkezdő nagybetű nem bizonyít nevet)."""
    for line in text.split("\n"):
        line = LEADING_DASH_RE.sub("", strip_markup(line))
        for m in NAME_RUN_RE.finditer(line):
            run = m.group(0).rstrip("-'’")
            before = line[:m.start()].rstrip()
            starts_sentence = not before or before[-1] in SENTENCE_BREAK or before.endswith("[")
            if starts_sentence:
                # A mondat első szava nagybetűs akkor is, ha nem név („A Taolu”,
                # „Látta Fangot”): elhagyjuk, a maradék név még számít.
                if " " not in run:
                    continue
                run = run.split(" ", 1)[1]
            if len(run) >= 2:
                yield run


def find_spelling_variants(texts: list[tuple[str, str, str]]) -> list[dict]:
    """texts: [(episode, num, text)] → az azonos vázú, eltérő alakú szócsoportok."""
    by_skeleton = defaultdict(lambda: defaultdict(list))
    for episode, num, text in texts:
        for token in name_tokens(text):
            by_skeleton[skeleton(token)][token].append(f"{episode}#{num}")
    groups = []
    for skel, forms in by_skeleton.items():
        if len(forms) < 2:
            continue
        ranked = sorted(forms.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        bare = {re.sub(r"['’-]", "", f) for f in forms}
        # Csak a kötőjeles/kötőjel nélküli ragozás tér el (Fang-ot / Fangot)?
        hyphen_only = len(bare) == 1
        if not hyphen_only and not _suspicious_difference(bare):
            continue
        groups.append({"skeleton": skel, "hyphen_only": hyphen_only,
                       "forms": [{"form": f, "count": len(w), "where": w} for f, w in ranked]})
    groups.sort(key=lambda g: -sum(f["count"] for f in g["forms"]))
    return groups


# Magyar kettős betű: a pinyin átírásban nem fordul elő, a magyar szóban gyakori.
# Ha az ékezet nélküli alak ilyet tartalmaz (Hegyet / Hegyét, Kincset / Kincsét),
# az eltérés valószínűleg ragozás, nem névírás.
HUNGARIAN_WORD_RE = re.compile(r"gy|ny|ty|ly|sz|cs|zs|dzs")


def _suspicious_difference(forms: set[str]) -> bool:
    """Szavanként nézi, hol tér el a csoport: az eltérés csak akkor gyanús, ha
    az eltérő szavak valamelyike ékezet nélküli (pinyin név: Taolu / Taolú).
    Ha az összes eltérő szó ékezetes, az magyar ragozás is lehet (Szívet /
    Szívét), nem írásmód-hiba; ugyanígy, ha az ékezet nélküli alak magyar szónak
    látszik (Hegyet / Hegyét). A név többi szava (Jáde) nem számít."""
    split = [f.split(" ") for f in forms]
    if len({len(s) for s in split}) != 1:
        return True
    for words in zip(*split):
        if len(set(words)) > 1 and any(w.isascii() and not HUNGARIAN_WORD_RE.search(w.lower())
                                       for w in words):
            return True
    return False


# ── Javaslatfájl ──────────────────────────────────────────────────────────

def build_decisions(conflicts: list[dict]) -> dict:
    """{hun_path: [ {sorszam, eredeti, javaslat} ]} — csak tábla és dal, csak többséggel."""
    per_file = defaultdict(dict)
    for c in conflicts:
        if c["kind"] not in ("caption", "song") or not c["suggested"]:
            continue
        for o in c["occurrences"]:
            if o["norm"] == c["majority"] or not o.get("num_ok", True):
                continue        # nem szám vagy ismétlődő sorszám: apply-auto nem tudná célozni
            current = per_file[o["path"]].get(o["num"], {}).get("javaslat", o["text"])
            if current.count(o["raw"]) != 1:
                continue        # nem egyértelmű, hol cseréljünk — kézre bízzuk
            new = c["suggested"] if c["kind"] == "caption" else rewrap(o["raw"], c["suggested"])
            per_file[o["path"]][o["num"]] = {
                "sorszam": int(o["num"]), "eredeti": o["text"],
                "javaslat": current.replace(o["raw"], new),
            }
    return {path: sorted(d.values(), key=lambda x: x["sorszam"]) for path, d in per_file.items()}


_PREFIX_RE = re.compile(r"^(?:\s*(?:<i>|<b>|\{\\[^}]*\}|[♪♫]|[-–—](?=\s)))*\s*")
_SUFFIX_RE = re.compile(r"\s*(?:(?:</i>|</b>|[♪♫])\s*)*$")


def plain_lines(raw: str) -> list[str]:
    """A szöveg sorai jelölés (tag, daljel) nélkül."""
    return [l.strip() for l in strip_markup(raw).split("\n") if l.strip()]


def rewrap(target_raw: str, suggested_raw: str) -> str:
    """A javasolt szöveg a CÉL-felirat saját jelölésével (♫ … ♫, <i> … </i>,
    sor eleji gondolatjel): a dal szövege egységesül, a részenkénti formázás
    nem keveredik.

    Ha a cél soronként jelöl (minden sor ♫ … ♫), a javaslat sorai is így kapják;
    ha a jelölés a cue egészét fogja közre (<i> az első sor elején, </i> az
    utolsó végén), akkor a javaslat egészét."""
    t_lines = target_raw.split("\n")
    body = plain_lines(suggested_raw)
    if not body:
        return target_raw
    # A csak jelölésből álló sorok (pl. külön sorban álló ♫) a helyükön maradnak.
    lead, trail = [], []
    while t_lines and not strip_markup(t_lines[0]).strip():
        lead.append(t_lines.pop(0))
    while t_lines and not strip_markup(t_lines[-1]).strip():
        trail.insert(0, t_lines.pop())
    if not t_lines:
        return "\n".join(lead + body + trail)
    return "\n".join(lead + [_rewrap_text(t_lines, body)] + trail)


def _rewrap_text(t_lines: list[str], body: list[str]) -> str:
    prefixes = [_PREFIX_RE.match(l).group(0) for l in t_lines]
    suffixes = [_SUFFIX_RE.search(l).group(0) for l in t_lines]
    # Soronkénti jelölés csak akkor, ha minden sor UGYANAZT kapja (♫ … ♫ minden
    # sorban); eltérő elő-/utótagnál (<i>♪ első / utolsó ♪</i>) a cue egészét
    # fogja közre, különben a záró ♫ középre kerülne vagy elveszne.
    per_line = (len(t_lines) > 1 and prefixes[0].strip() and suffixes[0].strip()
                and len(set(prefixes)) == 1 and len(set(suffixes)) == 1)
    if per_line:
        return "\n".join(f"{prefixes[0]}{line}{suffixes[0]}" for line in body)
    return prefixes[0] + "\n".join(body) + suffixes[-1]


def decisions_path(project_dir: str, stem: str) -> str:
    return os.path.join(project_dir, "output", f"{stem}.hun_consistency.json")


# ── Riport ────────────────────────────────────────────────────────────────

KIND_TITLES = {
    "caption": "Képernyőszöveg ([…])",
    "song": "Dalszöveg (♪)",
    "dialogue": "Párbeszéd",
}


def _where(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_EXAMPLES])
    return shown + (f" … (+{len(items) - MAX_EXAMPLES})" if len(items) > MAX_EXAMPLES else "")


def print_report(conflicts, spelling, limit):
    for kind in ("caption", "song", "dialogue"):
        items = [c for c in conflicts if c["kind"] == kind]
        print(f"\n== {KIND_TITLES[kind]} — azonos forrás, eltérő fordítás: {len(items)}")
        for c in items[:limit]:
            print(f"\n  forrás: {c['source']}")
            for v in c["variants"]:
                raw = " / ".join(v["raw"].split("\n"))
                print(f"    {v['count']:>3}× {raw}   ({_where(v['where'])})")
            if c["suggested"]:
                print(f"    → többségi: {' / '.join(c['suggested'].split(chr(10)))}")
            else:
                print("    → nincs egyértelmű többség")
        if len(items) > limit:
            print(f"\n  … és még {len(items) - limit} (--limit)")

    real = [g for g in spelling if not g["hyphen_only"]]
    hyphen = [g for g in spelling if g["hyphen_only"]]
    print(f"\n== Írásmód-változatok (nevek): {len(real)}")
    for g in real[:limit]:
        forms = "  ↔  ".join(f"{f['form']} ({f['count']}×: {_where(f['where'])})" for f in g["forms"])
        print(f"  {forms}")
    if len(real) > limit:
        print(f"  … és még {len(real) - limit} (--limit)")
    print(f"\n== Ragozás kötőjellel / anélkül (Fang-ot ↔ Fangot): {len(hyphen)}")
    if hyphen:
        print("  " + ";  ".join(" / ".join(f"{f['form']} {f['count']}×" for f in g["forms"])
                               for g in hyphen[:limit]))
        if len(hyphen) > limit:
            print(f"  … és még {len(hyphen) - limit} (--limit)")


# ── CLI ───────────────────────────────────────────────────────────────────

def run(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Sorozatszintű konzisztencia-riport a kész magyar feliratokból (LLM nélkül)")
    parser.add_argument("project_dir", nargs="?", default=".",
                        help="a sorozat mappája (alap: a munkakönyvtár)")
    parser.add_argument("--dir",
                        help="csak ebből az almappából olvasson, pl. \"Season 01\" vagy output "
                             "(alap: a Season NN mappák, ami ott nincs, az output/)")
    parser.add_argument("--min-chars", type=int, default=25,
                        help="párbeszédnél a forrássor minimális hossza (alap: 25)")
    parser.add_argument("--no-dialogue", action="store_true", help="a párbeszéd-ág kihagyása")
    parser.add_argument("--sdh", action="store_true",
                        help="SDH-forrás: a […] beszélőcímke/hangjegyzet, nem képernyőszöveg")
    parser.add_argument("--limit", type=int, default=50,
                        help="csoportok száma szakaszonként a riportban (alap: 50)")
    parser.add_argument("--decisions", action="store_true",
                        help="javaslatfájl részenként az output/ mappába (tábla és dal, többséggel)")
    config.add_source_lang_argument(parser)
    args = parser.parse_args(argv)

    project_dir = args.project_dir
    files = final_subtitles(project_dir, args.dir)
    if not files:
        print(f"HIBA: nincs kész magyar felirat (…hun.srt) itt: "
              f"{os.path.join(project_dir, 'Season NN')} / {os.path.join(project_dir, 'output')}")
        return 1

    # Ugyanaz a nyelvválasztás, mint a review-é: --source-lang, SUBTR_SOURCE_LANG,
    # alapértelmezés; az elgépelt kódra figyelmeztet.
    lang = config.resolve_source_lang(args.source_lang)
    occurrences, texts, missing, unreadable = [], [], [], []
    for entry in files:
        path, episode = entry["path"], episode_label(entry["stem"])
        try:
            sections = parse_timed(path)
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(f"{os.path.basename(path)} ({exc.__class__.__name__})")
            continue
        for section in sections:
            texts.append((episode, section["num"], "\n".join(section["lines"])))
        src = find_source(entry, lang)
        if not src:
            missing.append(os.path.basename(path))
            continue
        try:
            occs = collect_occurrences(path, src, args.min_chars, captions=not args.sdh)
        except (OSError, UnicodeDecodeError) as exc:
            # a FORRÁS hibás: a magyar szöveg az írásmód-ellenőrzésben marad
            unreadable.append(f"{os.path.basename(src)} — forrás ({exc.__class__.__name__})")
            continue
        for occ in occs:
            if args.no_dialogue and occ["kind"] == "dialogue":
                continue
            occ["episode"], occ["path"], occ["stem"] = episode, path, entry["stem"]
            occurrences.append(occ)

    folders = sorted({os.path.basename(e["folder"]) for e in files})
    print(f"Kész feliratok: {len(files)} ({', '.join(folders)})")
    if missing:
        print(f"Forrás nélkül (csak az írásmód-ellenőrzésben): {', '.join(missing)}")
    if unreadable:
        print(f"FIGYELEM: nem olvasható, kihagyva: {', '.join(unreadable)}")

    conflicts = find_conflicts(occurrences)
    spelling = find_spelling_variants(texts)
    print_report(conflicts, spelling, args.limit)

    if args.decisions:
        per_file = build_decisions(conflicts)
        print(f"\n== Javaslatfájlok (apply-auto): {len(per_file)}")
        for entry in files:
            out = decisions_path(project_dir, entry["stem"])
            decisions = per_file.get(entry["path"])
            if not decisions:
                # egy korábbi futás javaslata elavult: ne lehessen véletlenül átvezetni
                if os.path.exists(out):
                    os.remove(out)
                    print(f"  elavult javaslatfájl törölve: {out}")
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(decisions, f, ensure_ascii=False, indent=1)
            print(f"  {len(decisions):>3} javítás → {out}")
            print(f"      py subtr.py apply-auto \"{entry['path']}\" \"{out}\" --dry-run")
    return 0


def main(argv=None):
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
