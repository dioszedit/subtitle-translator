#!/usr/bin/env python3
"""
WebVTT → SRT konverter — meglévő felirat átvételéhez.

Mit csinál?
  Egy vagy több .vtt fájlt SRT-vé alakít, hogy a subtr pipeline (split,
  glossary, register, verify, review) dolgozni tudjon vele:
    - eldobja a WEBVTT fejlécet és a NOTE / STYLE / REGION blokkokat,
    - a cue-azonosítót (sorszám vagy szöveges id) eldobja, és 1..N-ig
      ÚJRASZÁMOZ (a WebVTT-ben az azonosító opcionális — vegyes fájloknál
      is folytonos sorszámot ad),
    - az időbélyeg ezredmásodperc-elválasztóját `.`-ról `,`-ra cseréli, a
      rövid (MM:SS.mmm) alakot HH:MM:SS,mmm-re egészíti ki,
    - az időbélyeg-sor VÉGÉN álló cue-beállításokat (align:, position:,
      line:, size:) elhagyja — az SRT ezeket nem ismeri,
    - a cue-szöveget VÁLTOZATLANUL viszi tovább: <i>, <b>, ♫, sortörések,
      szögletes zárójeles kártyák mind megmaradnak; csak a WebVTT-specifikus
      <c.osztály>…</c> és <v Név> tageket bontja ki (a szöveg marad),
    - CRLF → LF, UTF-8 BOM nélkül.

  Az időzítést NEM módosítja, cue-t NEM von össze és NEM dob el — a kimenet
  cue-száma megegyezik a bemenetével.

Használat:
  python addons/vtt2srt/vtt2srt.py "Season 01/Sorozat - S01E01.hun.vtt"
  python addons/vtt2srt/vtt2srt.py "Season 01"/*.hun.vtt
  python addons/vtt2srt/vtt2srt.py input/*.eng.vtt --out-dir input
  python addons/vtt2srt/vtt2srt.py x.vtt --force        # meglévő .srt felülírása

Kimenet (alapértelmezés): a .vtt mellé, azonos néven, .srt kiterjesztéssel.
Meglévő .srt-t csak --force-szal ír felül.

A fájlok egymástól függetlenül dolgozódnak fel: egy hibás fájl a többit nem
állítja le, a hibák a végén 1-es kilépési kódot adnak.

Kilépési kód: 0 siker, 1 hiba (hiányzó fájl, létező cél --force nélkül,
értelmezhetetlen időbélyeg).
"""

import argparse
import re
import sys
from pathlib import Path

# Az óra a WebVTT-spec szerint 2+ jegyű is lehet; a cue-beállítások (align:,
# position:…) csak szóköz után jöhetnek — "00:00:02.000xyz" hibás, nem elnyelt.
TIMESTAMP_RE = re.compile(
    r"^\s*(?P<start>(?:\d{1,}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*"
    r"(?P<end>(?:\d{1,}:)?\d{2}:\d{2}[.,]\d{3})(?P<settings>\s.*)?$"
)
SKIP_BLOCK_RE = re.compile(r"^(?:WEBVTT|NOTE|STYLE|REGION)\b")
# WebVTT-specifikus szövegtagek — a bennük lévő szöveg marad, csak a tag megy:
# <c.osztály>, <v Név>, <v.osztály Név>, </v>.
VTT_TAG_RE = re.compile(r"</?c(?:\.[^>]*)?>|<v(?:[.\s][^>]*)?>|</v>")


class VttError(ValueError):
    pass


def normalize_timestamp(ts: str) -> str:
    """'MM:SS.mmm' vagy 'HH:MM:SS.mmm' → 'HH:MM:SS,mmm'."""
    ts = ts.strip().replace(".", ",")
    parts = ts.split(":")
    if len(parts) == 2:
        ts = "00:" + ts
    elif len(parts) == 3:
        h = parts[0].zfill(2)
        ts = ":".join([h, parts[1], parts[2]])
    else:
        raise VttError(f"értelmezhetetlen időbélyeg: {ts!r}")
    return ts


def parse_vtt(content: str) -> list[dict]:
    """A WebVTT szövegből cue-lista: {timestamp, text} — sorszám nélkül,
    azt a kiíró adja. Csak az időbélyeg-sort tartalmazó blokkok számítanak."""
    content = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [l.rstrip() for l in block.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            continue
        ts_indexes = [i for i, l in enumerate(lines) if TIMESTAMP_RE.match(l)]
        if not ts_indexes:
            if any("-->" in l for l in lines) and not SKIP_BLOCK_RE.match(lines[0]):
                bad = next(l for l in lines if "-->" in l)
                raise VttError(f"hibás időbélyeg-sor: {bad!r}")
            continue                         # nem cue (fejléc, NOTE, szemét)
        if SKIP_BLOCK_RE.match(lines[0]):
            # Fejléc/NOTE, amelyet NEM választ el üres sor a következő cue-tól
            # (hibás fájl): a fejlécsort eldobjuk, a cue-t megtartjuk.
            lines = lines[1:]
            ts_indexes = [i - 1 for i in ts_indexes]
        # Üres sorral el nem választott cue-k (hibás fájl): minden időbélyeg-sor
        # új cue-t nyit, hogy egyetlen cue se olvadjon össze a következővel.
        for n, ts_index in enumerate(ts_indexes):
            end = ts_indexes[n + 1] if n + 1 < len(ts_indexes) else len(lines)
            m = TIMESTAMP_RE.match(lines[ts_index])
            timestamp = f"{normalize_timestamp(m.group('start'))} --> {normalize_timestamp(m.group('end'))}"
            body = lines[ts_index + 1:end]
            if n + 1 < len(ts_indexes) and body and body[-1].strip().isdigit():
                body = body[:-1]             # a következő cue sorszáma, nem szöveg
            text_lines = [VTT_TAG_RE.sub("", l) for l in body]
            cues.append({"timestamp": timestamp, "text": "\n".join(text_lines).strip("\n")})
    return cues


def render_srt(cues: list[dict]) -> str:
    out = []
    for i, cue in enumerate(cues, 1):
        out.append(f"{i}\n{cue['timestamp']}\n{cue['text']}")
    return "\n\n".join(out) + "\n"


def convert_text(content: str) -> str:
    return render_srt(parse_vtt(content))


def convert_file(src: Path, dst: Path, force: bool = False) -> int:
    if dst.exists() and not force:
        raise VttError(f"a cél már létezik (--force írja felül): {dst}")
    cues = parse_vtt(src.read_text(encoding="utf-8-sig"))
    if not cues:
        raise VttError(f"egyetlen cue-t sem találtam: {src}")
    dst.write_text(render_srt(cues), encoding="utf-8", newline="\n")
    return len(cues)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="WebVTT → SRT konverzió (időzítés és szöveg változatlan)")
    parser.add_argument("vtt", nargs="+", help="Egy vagy több .vtt fájl")
    parser.add_argument("--out-dir", help="Kimeneti mappa (alapból a .vtt mellé)")
    parser.add_argument("--force", action="store_true", help="Meglévő .srt felülírása")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    # --out-dir + azonos alapnevű bemenetek (a/x.vtt, b/x.vtt) ugyanarra a
    # célra írnának; ezt írás ELŐTT fogjuk meg, ne fele úton derüljön ki.
    targets = {}
    for name in args.vtt:
        src = Path(name)
        dst = (out_dir or src.parent) / (src.stem + ".srt")
        if dst in targets and targets[dst] != src:
            print(f"HIBA: {src} és {targets[dst]} ugyanarra a célra írna: {dst}")
            return 1
        targets[dst] = src

    failed = 0
    for name in args.vtt:
        src = Path(name)
        if not src.is_file():
            print(f"HIBA: nem találom: {src}")
            failed += 1
            continue
        dst = (out_dir or src.parent) / (src.stem + ".srt")
        try:
            n = convert_file(src, dst, force=args.force)
        except (VttError, UnicodeDecodeError, OSError) as e:
            print(f"HIBA: {src.name}: {e}")
            failed += 1
            continue
        print(f"OK  {src.name} → {dst.name}  ({n} cue)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
