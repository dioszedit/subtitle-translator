#!/usr/bin/env python3
"""
SRT forrás-előtisztító — fordítás ELŐTT futtatandó add-on.

Mit csinál?
  A nyers (jellemzően angol, SDH) SRT feliratból eltávolítja a tisztán
  hang-/zene-/effekt cue-kat és a WebVTT-artefaktumokat (STYLE, ::cue()),
  eldobja az így teljesen üressé vált feliratokat, ÚJRASZÁMOZ, majd
  opcionálisan N-esével blokkfájlokra bontja a gépi/kézi fordításhoz.

  Az időbélyegeket VÁLTOZATLANUL viszi tovább — csak a szöveget/sorokat
  szűri. A megőrzött feliratok sorszáma 1..N-ig folytonos lesz.

Mikor érdemes használni?
  Csak akkor, ha a forrásfelirat SDH/CC jellegű, azaz tartalmaz
  hangulat-/zene-/effekt-/beszélő-jegyzeteket, pl.:
    [music playing]  [tense music]  [♪]  [door creaks]  [sighs]  [laughs]
    (whispers)  ♪ lyrics ♪  STYLE ... ::cue() ...
  A legtöbb "sima" felirat NEM tartalmaz ilyet — ott erre nincs szükség.

Beszélő-/névcímkék ([Hari], [narrator], Anna:):
  Alapból MEGMARADNAK, mert a fordításnál kontextust adnak (ki beszél ->
  nem, tegezés/magázás). A kész fordításból úgyis kikerülnek.
  Ha eleve el akarod dobni őket: --strip-labels.

Cím-/megtartandó sorok:
  A tisztán cue-nak tűnő, de valójában megtartandó sorokra (pl. kétnyelvű
  sorozatcím-kártya) add meg: --keep "DOCTOR ON THE EDGE" (többször is).
  Az ilyen mintát tartalmazó sor SOHA nem törlődik.

Használat:
  python preclean_srt.py "input.eng.srt"
  python preclean_srt.py "input.eng.srt" --block-size 150
  python preclean_srt.py "input.eng.srt" --keep "DOCTOR ON THE EDGE" --keep "OPENING TITLE"
  python preclean_srt.py "input.eng.srt" --no-blocks          # csak tisztított SRT
  python preclean_srt.py "input.eng.srt" --strip-labels       # beszélőcímkék törlése is
  python preclean_srt.py "input.eng.srt" --outdir out --blocks-dir out/blocks

Kimenet (alapértelmezés):
  <forrás mappája>/<alap>.clean.srt                      (tisztított, újraszámozott)
  <forrás mappája>/blocks/<alap>/<alap>_block_NNN_SSSS-EEEE.srt   (blokkok)

Kilépési kód: 0 siker, 1 hiba (pl. hiányzó fájl).
"""

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# WebVTT-artefaktumok, amelyek néha SRT-be szivárognak.
# Szóhatár nélküli startswith NEM jó: a "NOTED...", "REGIONAL...", "STYLE is..."
# valódi szövegsorokat is törölné. A kulcsszavak csak EGYEDÜL a sorban
# számítanak artefaktumnak (a "NOTE THE DATE" jellegű képernyőszöveg valódi
# tartalom); egyedül a ::cue biztonságos prefixként. A törlés visszafordít-
# hatatlan, ezért kétes esetben inkább bent marad a sor.
ARTIFACT_RE = re.compile(r"^\s*(?:(?:WEBVTT|STYLE|REGION|NOTE)\s*$|::cue)")

# Beszélő-/névcímke a sor elején:  [Név]  (Név)  NÉV:
# A kettőspontos forma CSAK csupa nagybetűvel számít címkének (SDH-konvenció):
# a vegyes írású "Listen:", "Remember this:", "Meet me at 5:30" valódi
# mondat(kezdet), azt tilos levágni. A zárójeles címkénél a kettőspont opcionális.
_CAPS_WORD = r"[A-ZÁÉÍÓÖŐÚÜŰ][A-ZÁÉÍÓÖŐÚÜŰ'’.\-]{1,15}"
LEADING_LABEL_RE = re.compile(
    r"^\s*[-–—]?\s*(?:"
    r"[\[(][^\])]{1,40}[\])]\s*:?"                      # [Anna]  (Anna)  [Anna]:
    rf"|{_CAPS_WORD}(?:\s+{_CAPS_WORD}){{0,2}}\s*:"     # ANNA:  JOO IN AH:
    r")\s*")


def is_pure_cue_line(line: str, keep_res) -> bool:
    """Igaz, ha a sor tisztán hang-/zene-/effekt cue vagy WebVTT-artefaktum,
    tehát törölhető. A keep-mintát tartalmazó sorokat MINDIG megtartja."""
    s = line.strip()
    if not s:
        return False  # üres sort a felirat-szintű szűrés kezeli
    for kr in keep_res:
        if kr.search(line):
            return False
    if ARTIFACT_RE.match(s):
        return True
    # [...] és (...) szegmensek eltávolítása után nézzük, marad-e valódi szöveg
    nobr = re.sub(r"\[[^\]]*\]", "", line)
    nobr = re.sub(r"\([^)]*\)", "", nobr)
    nobr = nobr.strip(" -–—\t♪♫〜~*·").strip()
    return nobr == ""


def strip_leading_label(line: str, keep_res) -> str:
    """Eltávolítja a sor eleji beszélő-/névcímkét, de a keep-mintás sorokat békén hagyja."""
    for kr in keep_res:
        if kr.search(line):
            return line
    return LEADING_LABEL_RE.sub("", line, count=1)


def parse_srt(txt: str):
    """SRT -> [(timestamp, [szövegsorok]), ...]  (a sorszámot eldobjuk, majd újrageneráljuk)"""
    out = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = block.split("\n")
        if len(lines) < 2:
            continue
        # az 1. sor a sorszám, a 2. az időbélyeg (" --> "), a többi a szöveg
        ts_idx = 1 if "-->" in lines[1] else (0 if "-->" in lines[0] else None)
        if ts_idx is None:
            continue
        ts = lines[ts_idx]
        text = lines[ts_idx + 1:]
        out.append((ts, text))
    return out


def preclean(subs, keep_res, strip_labels: bool):
    kept, dropped = [], 0
    for ts, text in subs:
        newlines = [ln for ln in text if not is_pure_cue_line(ln, keep_res)]
        if strip_labels:
            newlines = [strip_leading_label(ln, keep_res) for ln in newlines]
            newlines = [ln for ln in newlines if ln.strip()]
        if not newlines:
            dropped += 1
            continue
        kept.append((ts, newlines))
    return kept, dropped


def render(kept, start_index=1):
    return "\n\n".join(
        "\n".join([str(i), ts] + t) for i, (ts, t) in enumerate(kept, start_index)
    ) + "\n"


def split_blocks(kept, base, blocks_dir: Path, size: int):
    blocks_dir.mkdir(parents=True, exist_ok=True)
    # CSAK a forrás blokkfájlokat regeneráljuk — a lefordított _HUN.srt (vagy
    # más nyelvi végződésű) fájlokat SOHA nem töröljük, hogy egy újrafuttatás
    # ne semmisítse meg a már elkészült fordítást.
    for old in blocks_dir.glob("*.srt"):
        if re.search(r"_[A-Z]{2,3}\.srt$", old.name, re.IGNORECASE):  # pl. _HUN.srt, _hun.srt
            continue
        old.unlink()
    parts = []
    for bi, start in enumerate(range(0, len(kept), size), 1):
        chunk = kept[start:start + size]
        s, e = start + 1, start + len(chunk)
        fn = f"{base}_block_{bi:03d}_{s:04d}-{e:04d}.srt"
        (blocks_dir / fn).write_text(render(chunk, s), encoding="utf-8")
        parts.append((fn, len(chunk)))
    return parts


def main():
    ap = argparse.ArgumentParser(description="SRT forrás-előtisztító (fordítás előtt)")
    ap.add_argument("srt_file", help="Nyers forrás SRT (pl. input.eng.srt)")
    ap.add_argument("--block-size", type=int, default=150, help="Feliratok blokkonként (default: 150)")
    ap.add_argument("--no-blocks", action="store_true", help="Ne bontsa blokkokra, csak tisztított SRT")
    ap.add_argument("--strip-labels", action="store_true", help="A sor eleji beszélő-/névcímkéket is törölje")
    ap.add_argument("--keep", action="append", default=[], metavar="MINTA",
                    help="Soha ne törölje az ezt (regex) tartalmazó sort. Többször megadható.")
    ap.add_argument("--outdir", default=None, help="Kimeneti mappa a .clean.srt-hez (default: a forrás mappája)")
    ap.add_argument("--blocks-dir", default=None, help="Blokkok gyökérmappája (default: <outdir>/blocks)")
    args = ap.parse_args()

    src = Path(args.srt_file)
    if not src.exists():
        print(f"HIBA: nincs ilyen fájl: {src}")
        sys.exit(1)

    keep_res = [re.compile(k) for k in args.keep]
    base = src.stem  # pl. "Doctor on the Edge - S01E05.eng"

    subs = parse_srt(src.read_text(encoding="utf-8-sig"))
    kept, dropped = preclean(subs, keep_res, args.strip_labels)
    print(f"Eredeti: {len(subs)} -> megtartott: {len(kept)} (eldobott csak-cue felirat: {dropped})")

    outdir = Path(args.outdir) if args.outdir else src.parent
    outdir.mkdir(parents=True, exist_ok=True)
    clean_path = outdir / (base + ".clean.srt")
    clean_path.write_text(render(kept), encoding="utf-8")
    print(f"Kiírva: {clean_path}")

    if not args.no_blocks:
        blocks_root = Path(args.blocks_dir) if args.blocks_dir else (outdir / "blocks")
        blocks_dir = blocks_root / base
        parts = split_blocks(kept, base, blocks_dir, args.block_size)
        print(f"\n{len(parts)} blokkfájl: {blocks_dir}")
        for fn, n in parts:
            print(f"  {fn}  ({n} felirat)")

    data = clean_path.read_text(encoding="utf-8")
    left = len(re.findall(r"(?m)^\s*(?:STYLE\s*$|::cue)", data))
    print(f"\nEllenőrzés — STYLE/::cue() maradt: {left} (0 a jó)")


if __name__ == "__main__":
    main()
