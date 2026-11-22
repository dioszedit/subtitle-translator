#!/usr/bin/env python3
"""Forrásnyelvi SRT igazítása egy KÜLSŐ (összevont cue-s) magyar fordításhoz.

    python addons/align-source/align_source.py "output/Sorozat - S01E03.hun.srt"
    python addons/align-source/align_source.py "output/Sorozat - S01E*.hun.srt" --lang eng,chi
    python addons/align-source/align_source.py HUN.srt --src SRC.srt -o OUT.srt

A kimenet sorszáma és időbélyege a magyar fájlé, a szövege a forrásé: minden
forrás-cue ahhoz a magyar cue-hoz kerül, amellyel a legnagyobb az időbeli
átfedése (lásd `subtr/timing.py`). Több forrás-cue soronként egymás alá kerül.
Forrás nélküli magyar cue helyére a NO_SOURCE jelölés kerül. Így a
`subtr.py review --source input/aligned/….eng.srt` sorszám-párosítása helyes lesz.

Alapértelmezett kimenet: `input/aligned/<név>.<nyelv>.srt`. A magyar cue-hoz
nem rendelhető forrássorok (lehetséges kihagyás a fordításból) a kimenet mellé
kerülnek: `<kimenet>.unmatched.txt`.
"""

import argparse
import os
import sys
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from subtr.config import SOURCE_LANGS, expand_patterns, normalize_source_lang, utf8_console
    from subtr.timing import assign, overlap, overlap_map, parse_timed
except ImportError as exc:
    sys.exit(f"HIBA: ez az add-on a program `subtr` mappájával együtt működik, "
             f"de az nem tölthető be ({exc}). A teljes program mappájából futtasd.")

NO_SOURCE = "(nincs forrássor — a fordító saját kiírása)"

# Egy üresen maradt magyar cue megkapja azt a forrás-cue-t is, amely az idejének
# legalább ekkora részét lefedi: a fordító egy hosszú forrásmondatot két cue-ra
# bontott, és a második fele is valódi fordítás, nem saját kiírás.
CONTINUATION_COVER = 0.5


def add_continuations(hun: list, src: list, buckets: list) -> None:
    """Üres magyar cue-hoz a forrásmondat folytatása (helyben, a buckets-ben).

    Csak akkor, ha a forrás-cue tényleg TÚLNYÚLIK a hozzá rendelt magyar cue-n
    (az nem fedi le egészen), és az üres cue időben nem fedi át a hozzá rendelt
    cue-t. Így a fordító saját, a párbeszéddel egy időben látszó táblája nem
    kap idegen forrássort: az marad „saját kiírás”."""
    owner = {si: ti for ti, bucket in enumerate(buckets) for si in bucket}
    hits = overlap_map(hun, src)
    for ti, bucket in enumerate(buckets):
        duration = hun[ti]["end"] - hun[ti]["start"]
        if bucket or duration <= 0:
            continue
        for si, ov in hits[ti]:
            if ov / duration < CONTINUATION_COVER or si not in owner:
                continue
            home = hun[owner[si]]
            s_dur = src[si]["end"] - src[si]["start"]
            covered_by_home = overlap(home, src[si]) / s_dur if s_dur > 0 else 1.0
            if covered_by_home < 0.9 and overlap(home, hun[ti]) <= 0:
                bucket.append(si)


HUN_SUFFIXES = (".hun.merge.srt", ".hun.reflow.srt", ".hun.clean.srt", ".hun.srt")


def hun_stem(hun_path: Path) -> str | None:
    """A rész neve a magyar fájlnévből (`X.hun.srt`, `X.hun.merge.srt` …), vagy None."""
    for suffix in HUN_SUFFIXES:
        if hun_path.name.endswith(suffix):
            return hun_path.name[:-len(suffix)]
    return None


def default_sources(hun_path: Path, langs: list[str]) -> list[Path]:
    """A magyar fájlhoz tartozó forrás-SRT-k nyelvenként — ugyanott keres, mint
    a review: a sorozat `input/` mappája, a magyar fájl mappája, a munkakönyvtár
    `input/`-ja."""
    stem = hun_stem(hun_path)
    if stem is None:
        return []
    found = []
    for code in langs:
        name = f"{stem}.{code}.srt"
        for cand in (hun_path.parent.parent / "input" / name, hun_path.parent / name,
                     Path("input") / name):
            if cand.is_file():
                found.append(cand)
                break
    return found


def default_output(src_path: Path) -> Path:
    return src_path.parent / "aligned" / src_path.name


def align(hun_path: Path, src_path: Path, out_path: Path, max_gap: float) -> str:
    hun, src = parse_timed(str(hun_path)), parse_timed(str(src_path))
    if not hun or not src:
        raise ValueError(f"üres vagy értelmezhetetlen SRT: {hun_path if not hun else src_path}")
    buckets, dropped = assign(hun, src, max_gap)
    add_continuations(hun, src, buckets)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for h, bucket in zip(hun, buckets):
            body = [line for si in bucket for line in src[si]["lines"]] or [NO_SOURCE]
            f.write(f"{h['num']}\n{h['timestamp']}\n" + "\n".join(body) + "\n\n")

    side = out_path.with_name(out_path.name[:-len(".srt")] + ".unmatched.txt") \
        if out_path.name.endswith(".srt") else out_path.with_name(out_path.name + ".unmatched.txt")
    if dropped:
        with open(side, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Forrássorok, amelyekhez nincs időben magyar felirat"
                    " (lehetséges kihagyás a fordításból)\n")
            for si in dropped:
                s = src[si]
                f.write(f"{s['timestamp']}  {' | '.join(s['lines'])}\n")
    elif side.exists():
        side.unlink()

    empty = sum(1 for b in buckets if not b)
    return (f"{out_path}: {len(hun)} magyar cue, {len(src)} forrás-cue, "
            f"forrás nélküli: {empty}, kimaradt forrássor: {len(dropped)}"
            + (f" (lásd {side.name})" if dropped else ""))


def main(argv=None) -> int:
    utf8_console()
    ap = argparse.ArgumentParser(
        description="Forrás-SRT igazítása egy összevont cue-s magyar fordítás sorszámaihoz")
    ap.add_argument("hun", nargs="+", help="magyar SRT (minta is lehet, pl. output/*.hun.srt)")
    ap.add_argument("--src", help="a forrás-SRT (csak egy magyar fájlnál); alapból input/…<nyelv>.srt")
    ap.add_argument("--lang", default=",".join(SOURCE_LANGS),
                    help="forrásnyelvek vesszővel, ha nincs --src (alap: mind, ami megvan)")
    ap.add_argument("-o", "--output",
                    help="kimeneti fájl (csak egy magyar fájl és egy forrás esetén); alap: input/aligned/…")
    ap.add_argument("--max-gap", type=float, default=1.0,
                    help="átfedés nélkül legfeljebb ennyi mp résnél még párosít (alap: 1.0)")
    a = ap.parse_args(argv)

    hun_files = [Path(p) for p in expand_patterns(a.hun)]
    if not hun_files:
        print("HIBA: nincs ilyen magyar SRT.")
        return 1
    if (a.src or a.output) and len(hun_files) != 1:
        print("HIBA: a --src és a -o csak egyetlen magyar fájllal használható.")
        return 1

    langs = []
    for code in (c.strip() for c in a.lang.split(",") if c.strip()):
        norm = normalize_source_lang(code)
        if not norm:
            print(f"HIBA: ismeretlen nyelvkód a --lang-ban: {code}")
            return 1
        langs.append(norm)
    failed = 0
    for hun in hun_files:
        sources = [Path(a.src)] if a.src else default_sources(hun, langs)
        if not sources and hun_stem(hun) is None:
            print(f"{hun}: a fájlnévben nincs „.hun.” jelölés, ezért a forrását nem tudom "
                  f"megkeresni — add meg a --src kapcsolóval")
            failed += 1
            continue
        if not sources:
            print(f"{hun}: nincs hozzá forrás-SRT az input/ mappában (--src-cel megadható)")
            failed += 1
            continue
        if a.output and len(sources) > 1:
            print(f"HIBA: a -o csak egy forrással használható, de {len(sources)} található "
                  f"({', '.join(s.name for s in sources)}); add meg a --src-t vagy a --lang-ot.")
            failed += 1
            continue
        for src in sources:
            out = Path(a.output) if a.output else default_output(src)
            try:
                print(align(hun, src, out, a.max_gap))
            except (OSError, ValueError) as exc:
                print(f"HIBA: {exc}")
                failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
