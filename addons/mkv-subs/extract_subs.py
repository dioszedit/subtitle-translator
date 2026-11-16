#!/usr/bin/env python3
"""
Beágyazott feliratsávok kilistázása és kicsomagolása videófájlból.

Mire jó?
  A kiadott mkv-k jellemzően több feliratsávot visznek (angol, eredeti nyelvű
  CC, kínai, koreai). A pipeline-nak kettőre lehet szüksége:
    - a FORDÍTÁS forrására (általában angol), és
    - az EREDETI NYELVŰ sávra a megszólítási regiszterhez — a japán keigo, a
      koreai beszédszintek stb. közvetlen bizonyítékok, az angol `you` nem az.
  A kettő nem ugyanaz a fájl, és nem is kell ugyanannak lennie: fordíthatsz
  angolból úgy, hogy a regisztert a japán sávból olvasod ki.
  Részletek: docs/04-forditas.md → Forrásnyelv.

MIÉRT NYELVCÍMKE SZERINT?
  A sávok SORRENDJE fájlonként változik — ugyanannak a sorozatnak az egyik
  részében a japán a 3., a másikban az 5. stream. Egy beégetett `-map 0:5`
  ezért NÉMÁN rossz nyelvet csomagol ki: a fájl létrejön, csak épp kínai van
  benne. Ez a script mindig a `language` címke alapján választ.

Használat:
  # 1) mi van benne? (semmit nem ír ki, csak listáz)
  python addons/mkv-subs/extract_subs.py "Season 01/Sorozat - S01E01.mkv"

  # 2) egy nyelv kicsomagolása a névkonvenció szerint
  python addons/mkv-subs/extract_subs.py "Season 01/Sorozat - S01E01.mkv" --lang jpn
  #    → "Season 01/Sorozat - S01E01.jpn.srt"

  # 3) egész évad, az input/ mappába
  python addons/mkv-subs/extract_subs.py "Season 01"/*.mkv --lang eng --out-dir input

  # 4) minden szöveges sáv
  python addons/mkv-subs/extract_subs.py video.mkv --all

A kimeneti fájlnév a pipeline konvencióját követi (`Sorozat - S01E01.jpn.srt`),
így a `split`, `translate`, `glossary` és `register` a fájlnévből felismeri a
forrásnyelvet — nem kell `--source-lang`.

Korlát: csak SZÖVEGES sávot tud (subrip, ass/ssa, mov_text, webvtt). A képi
feliratok (PGS/`hdmv_pgs_subtitle`, VobSub/`dvd_subtitle`) OCR-t igényelnek,
azokat a script kihagyja és megnevezi.

Függőség: `ffmpeg` és `ffprobe` (PATH, vagy `FFMPEG`/`FFPROBE` környezeti
változó). Python oldalról csak stdlib.

Kilépési kód: 0 siker, 1 hiba (hiányzó ffmpeg, nincs ilyen nyelvű sáv,
létező cél --force nélkül, képi felirat).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# A pipeline nyelvkódjai és a fájlminta-kibontás a subtr csomagból jönnek —
# másolatuk SEHOL nincs, hogy ne csúszhassanak szét. Az add-on a programmal
# együtt települ; a subtr nélkül nem fut, és ezt meg is mondja, ahelyett hogy
# csendben félig működne.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from subtr.config import SOURCE_LANG_ALIASES as _ALIASES, SOURCE_LANGS, expand_patterns
except ImportError as exc:
    sys.exit(f"HIBA: ez az add-on a program `subtr` mappájával együtt működik, "
             f"de az nem tölthető be ({exc}). A teljes program mappájából futtasd.")
_LANGS = set(SOURCE_LANGS)

# Amit az ffmpeg SRT-vé tud alakítani. A képi feliratok nincsenek köztük.
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
IMAGE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}


def normalize_lang(value):
    """Nyelvkód a pipeline alakjára (`ja` → `jpn`). Ismeretlen kód marad."""
    if not value:
        return ""
    key = str(value).strip().lower()
    return _ALIASES.get(key, key)


class Fail(Exception):
    """Egy fájl feldolgozása nem sikerült; a köteg többi része mehet tovább."""


# ── ffmpeg / ffprobe — a mkv-subs, a hardsub-cover és az audio-asr közös kódja ──

def find_tool(name):
    """Az `ffmpeg` / `ffprobe` útvonala: FFMPEG / FFPROBE környezeti változó,
    a Homebrew ffmpeg-full, végül a PATH. Ha nincs meg: Fail."""
    for cand in (os.environ.get(name.upper()), f"/opt/homebrew/opt/ffmpeg-full/bin/{name}",
                 shutil.which(name)):
        if cand and Path(cand).exists():
            return cand
    raise Fail(f"nem találom: {name} (PATH vagy {name.upper()} környezeti változó)")


def require_tools():
    """Indulás előtti ellenőrzés: ha hiányzik az ffmpeg vagy az ffprobe, megáll."""
    try:
        for name in ("ffprobe", "ffmpeg"):
            find_tool(name)
    except Fail as exc:
        sys.exit(f"HIBA: {exc} (macOS: brew install ffmpeg; Windows: winget install ffmpeg)")


def ffprobe_json(path, entries, select=None, tool=None):
    """Az ffprobe JSON-válasza a kért mezőkkel (`-show_entries`). Hibánál Fail.

    select: sávtípus-szűrő (`-select_streams`), pl. "s" felirat, "a" hang.
    """
    cmd = [tool or find_tool("ffprobe"), "-v", "error"]
    if select:
        cmd += ["-select_streams", select]
    cmd += ["-show_entries", entries, "-of", "json", str(path)]
    # encoding: a sávcímek UTF-8-ban jönnek (koreai, kínai) — Windowson a
    # konzol kódlapjával olvasva elhasalna.
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise Fail(f"ffprobe hiba: {(r.stderr or '').strip()[-300:]}")
    return json.loads(r.stdout or "{}")


def probe_streams(video, kind):
    """A videó sávjai: kind="s" felirat, "a" hang.

    [{index, lang, raw_lang, title, codec, channels, forced, default}] —
    a `channels` csak hangsávnál van kitöltve. ffprobe-hibánál None.
    Az audio-asr add-on is ezt használja a hangsávokhoz.
    """
    try:
        data = ffprobe_json(video, "stream=index,codec_name,channels:stream_tags=language,title"
                                   ":stream_disposition=forced,default", select=kind)
    except Fail as exc:
        sys.stderr.write(f"  {exc}\n")
        return None
    out = []
    for st in data.get("streams", []):
        tags = st.get("tags") or {}
        disp = st.get("disposition") or {}
        out.append({
            "index": st.get("index"),
            "lang": normalize_lang(tags.get("language")),
            "raw_lang": (tags.get("language") or "").lower(),
            "title": tags.get("title") or "",
            "codec": (st.get("codec_name") or "").lower(),
            "channels": st.get("channels"),
            "forced": bool(disp.get("forced")),
            "default": bool(disp.get("default")),
        })
    return out


def probe_subtitles(video):
    """A videó feliratsávjai."""
    return probe_streams(video, "s")


def describe(tracks, subtitles=True):
    """A sávok kiírása. subtitles=False: hangsávok (csatornaszám, kodek-minősítés nélkül)."""
    for t in tracks:
        flags = []
        if t["default"]:
            flags.append("default")
        if t.get("forced"):
            flags.append("forced")
        if subtitles and t["codec"] in IMAGE_CODECS:
            flags.append("KÉPI — nem csomagolható ki")
        elif subtitles and t["codec"] not in TEXT_CODECS:
            flags.append("ismeretlen kodek")
        extra = f"  [{', '.join(flags)}]" if flags else ""
        title = f"  „{t['title']}”" if t["title"] else ""
        lang = t["lang"] or "?"
        codec = t["codec"] if subtitles else f"{t['codec']} {t.get('channels') or '?'}ch"
        print(f"  stream {t['index']:>2}  {lang:<4} {codec:<18}{title}{extra}")


def stem_without_lang(video):
    """A fájlnév töve a záró nyelvjelölés nélkül: `x.eng.mkv` → `x`, `x.mkv` → `x`."""
    stem = Path(video).stem
    base, dot, tag = stem.rpartition(".")
    return base if dot and base and normalize_lang(tag) in _LANGS else stem


def pick(tracks, lang, title_filter):
    """A kért nyelvű sáv. Több találatnál nem tippel — visszaadja mindet."""
    hits = [t for t in tracks if t["lang"] == lang]
    if title_filter:
        needle = title_filter.lower()
        hits = [t for t in hits if needle in t["title"].lower()]
    return hits


def out_path(video, lang, out_dir):
    # Ha a videónév már visel nyelvtaget, ne duplázzuk: "x.eng.mkv" → "x.jpn.srt"
    stem = stem_without_lang(video)
    target_dir = Path(out_dir) if out_dir else Path(video).parent
    return target_dir / f"{stem}.{lang}.srt"


def extract(video, track, dest, force):
    if dest.exists() and not force:
        sys.stderr.write(f"  KIHAGYVA: {dest} már létezik (--force felülírja)\n")
        return False
    if track["codec"] in IMAGE_CODECS:
        sys.stderr.write(f"  KIHAGYVA: a(z) {track['index']}. sáv képi felirat "
                         f"({track['codec']}), OCR kellene hozzá\n")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [find_tool("ffmpeg"), "-v", "error", "-y", "-i", video,
           "-map", f"0:{track['index']}", "-c:s", "srt", str(dest)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"  ffmpeg hiba a(z) {track['index']}. sávnál: "
                         f"{exc.stderr.strip()}\n")
        return False
    print(f"  → {dest}")
    return True


def main():
    ap = argparse.ArgumentParser(
        description="Beágyazott feliratsávok listázása / kicsomagolása "
                    "nyelvcímke szerint.")
    ap.add_argument("videos", nargs="+", help="videófájl(ok), pl. mkv")
    ap.add_argument("--lang", help="nyelvkód (jpn, kor, eng, ger… vagy ja/ko/en)")
    ap.add_argument("--all", action="store_true",
                    help="minden szöveges sáv kicsomagolása")
    ap.add_argument("--title", help="több azonos nyelvű sávnál a cím szűrője "
                                    "(részlet, kis/nagybetű mindegy)")
    ap.add_argument("--out-dir", help="kimeneti mappa (alap: a videó mellé)")
    ap.add_argument("--force", action="store_true",
                    help="létező .srt felülírása")
    args = ap.parse_args()

    require_tools()
    lang = normalize_lang(args.lang) if args.lang else None
    errors = 0

    for video in expand_patterns(args.videos):
        if not Path(video).is_file():
            sys.stderr.write(f"HIBA: nincs ilyen fájl: {video}\n")
            errors += 1
            continue
        print(f"\n{video}")
        tracks = probe_subtitles(video)
        if tracks is None:
            errors += 1
            continue
        if not tracks:
            print("  (nincs feliratsáv)")
            continue

        if not lang and not args.all:
            describe(tracks)
            continue

        wanted = [t for t in tracks if t["codec"] in TEXT_CODECS] if args.all \
            else pick(tracks, lang, args.title)

        if not wanted:
            describe(tracks)
            sys.stderr.write(f"  HIBA: nincs „{args.lang}” nyelvű szöveges sáv\n")
            errors += 1
            continue
        if lang and len(wanted) > 1:
            describe(wanted)
            sys.stderr.write(f"  HIBA: {len(wanted)} db „{lang}” sáv van — "
                             "szűkítsd a --title kapcsolóval\n")
            errors += 1
            continue

        for track in wanted:
            dest = out_path(video, track["lang"] or "und", args.out_dir)
            if not extract(video, track, dest, args.force):
                errors += 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
