#!/usr/bin/env python3
"""
A kész magyar felirat beágyazása az azonos nevű .mkv-ba (az extract_subs.py párja).

    python3 addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.hun.srt"
    python3 addons/mkv-subs/embed_subs.py "Season 01"/*.hun.srt --default
    python3 addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.hun.srt" --dry-run

Mit csinál:
  - a `<név>.hun.srt`-t szöveges (subrip) feliratsávként beteszi a `<név>.mkv`-ba
    (`hun`, „Magyar”), újrakódolás nélkül (stream copy), és lecseréli az
    eredeti .mkv-t; a .hun.srt a helyén marad (az a javítható forrás);
  - csak a SAJÁT, korábban betett sávját cseréli (subrip + hun + „Magyar”), így
    újrafuttatható; minden más sáv — angol, kínai, a hardsub-cover dobozos
    ASS-sávja, más magyar sáv — megmarad, a jelöléseivel együtt;
  - `--default`: a magyar sáv lesz az alapértelmezett (az első feliratsáv), a
    többiről lekerül a default jelölés (a forced és társai maradnak). Enélkül
    a sáv a meglévők után kerül, nem alapértelmezettként, és a többi sáv
    jelölése nem változik. Állandó beállításként: MKV_SUBS_DEFAULT=1 a .env-ben
    (a --no-default felülírja);
  - csere előtt ellenőrzi az új fájlt (videó-, hang-, mellékletsávok száma,
    hossz, az új sáv helye és jelölése); hibánál az eredeti érintetlen marad,
    ideiglenes fájl nem marad hátra; több fájlnál egy hibás nem állítja le a
    többit.

A muxoló mag (embed) közös: a hardsub-cover add-on is ezt használja a dobozos
ASS-sávhoz („Magyar (dobozos)”).

Függőség: `ffmpeg` és `ffprobe` (PATH, `FFMPEG`/`FFPROBE` környezeti változó,
vagy macOS-en a Homebrew ffmpeg-full). Python oldalról csak stdlib.

Kilépési kód: 0 siker, 1 hiba.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

LANG = "hun"


class Fail(Exception):
    """Egy fájl feldolgozása nem sikerült; a köteg többi része mehet tovább."""


class Track:
    """Egy saját feliratsáv fajtája: kodek + cím (+ régi címek, amiket még a
    sajátjának ismer fel)."""

    def __init__(self, codec, title, legacy_titles=()):
        self.codec, self.title, self.titles = codec, title, {title, *legacy_titles}

    def owns(self, s):
        t = tags(s)
        return (s.get("codec_type") == "subtitle" and s.get("codec_name") == self.codec
                and t.get("language") == LANG and t.get("title") in self.titles)


# A cím a lejátszó sávválasztójában látszik (a fájlnévbe nem kerül).
SRT_TRACK = Track("subrip", "Magyar")
# a hardsub-cover első változata „Magyar” címmel tette be — azt is a sajátjának tekinti
ASS_TRACK = Track("ass", "Magyar (dobozos)", legacy_titles=("Magyar",))
KNOWN_TRACKS = (SRT_TRACK, ASS_TRACK)


# ── .env ────────────────────────────────────────────────────────────────────

def load_dotenv():
    """A .env-et a munkakönyvtárból vagy fölötte keresi; a már beállított
    környezeti változókat nem írja felül. python-dotenv nélkül is működik."""
    try:
        from dotenv import find_dotenv, load_dotenv as _load
    except ImportError:
        _load = None
    if _load is not None:
        path = find_dotenv(usecwd=True)
        if path:
            _load(path)
        return
    for d in (Path.cwd(), *Path.cwd().parents):
        env = d / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                m = re.match(r"\s*(?:export\s+)?([A-Za-z_]\w*)\s*=\s*(.*)", line)
                if not m or line.lstrip().startswith("#"):
                    continue
                val = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("'\"")
                os.environ.setdefault(m.group(1), val)
            return


def env_flag(name):
    val = os.environ.get(name, "").strip().lower()
    if val in ("", "0", "false", "no", "nem", "off"):
        return False
    if val in ("1", "true", "yes", "igen", "on"):
        return True
    sys.exit(f"Hibás érték: {name}={val!r} (1/0, true/false, igen/nem)")


# ── ffmpeg / ffprobe ────────────────────────────────────────────────────────

def find_tool(name):
    for cand in (os.environ.get(name.upper()), f"/opt/homebrew/opt/ffmpeg-full/bin/{name}", shutil.which(name)):
        if cand and Path(cand).exists():
            return cand
    raise Fail(f"nem találom: {name} (PATH vagy {name.upper()} környezeti változó)")


def tags(s):
    return {k.lower(): v for k, v in (s.get("tags") or {}).items()}


def probe(ffprobe, path):
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                        "stream=index,codec_type,codec_name:stream_tags:stream_disposition"
                        ":format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if r.returncode:
        raise Fail(f"ffprobe hiba: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout)


def subtitles(info):
    return [s for s in info.get("streams", []) if s.get("codec_type") == "subtitle"]


# ── mux ─────────────────────────────────────────────────────────────────────

def plan(streams, track, default):
    """-> (megtartott feliratsávok, az új sáv helye a feliratsávok között)."""
    keep = [s for s in streams if s.get("codec_type") == "subtitle" and not track.owns(s)]
    return keep, (0 if default else len(keep))


def mux_cmd(ffmpeg, mkv, sub, tmp, streams, track, default):
    keep, pos = plan(streams, track, default)
    order = [None] * len(keep)
    order.insert(pos, "new")
    it = iter(keep)
    cmd = [ffmpeg, "-v", "error", "-y", "-i", str(mkv), "-i", str(sub),
           "-map", "0:v", "-map", "0:a?"]
    for o in order:
        cmd += ["-map", "1" if o == "new" else f"0:{next(it)['index']}"]
    cmd += ["-map", "0:t?", "-c", "copy",
            f"-metadata:s:s:{pos}", f"language={LANG}", f"-metadata:s:s:{pos}", f"title={track.title}",
            f"-disposition:s:{pos}", "default" if default else "0"]
    if default:  # a többiről csak a default jelölés kerül le, a forced stb. marad
        for i in range(len(keep) + 1):
            if i != pos:
                cmd += [f"-disposition:s:{i}", "-default"]
    return cmd + [str(tmp)], keep, pos


def check_mux(before, after, keep, pos, track, default):
    """A muxolt fájl ellenőrzése az eredetihez képest -> problémák listája."""
    def count(info, typ):
        return sum(1 for s in info.get("streams", []) if s.get("codec_type") == typ)

    problems = []
    for typ, label in (("video", "videó"), ("audio", "hang"), ("attachment", "melléklet")):
        if count(after, typ) != count(before, typ):
            problems.append(f"{label}sávok száma {count(before, typ)} -> {count(after, typ)}")
    subs = subtitles(after)
    if len(subs) != len(keep) + 1:
        problems.append(f"feliratsávok száma {len(subs)}, várt {len(keep) + 1}")
    elif not track.owns(subs[pos]) or tags(subs[pos]).get("title") != track.title:
        problems.append(f"nincs a(z) {pos + 1}. helyen a magyar „{track.title}” sáv")
    else:
        if bool(subs[pos].get("disposition", {}).get("default")) != default:
            problems.append("az új sáv alapértelmezett-jelölése nem a kért")
        if default and any(s.get("disposition", {}).get("default") for i, s in enumerate(subs) if i != pos):
            problems.append("más feliratsáv is alapértelmezett maradt")
    try:
        d0, d1 = float(before["format"]["duration"]), float(after["format"]["duration"])
        if abs(d0 - d1) > 1.0:
            problems.append(f"hossz {d0:.1f} s -> {d1:.1f} s")
    except (KeyError, TypeError, ValueError):
        pass
    return problems


def embed(mkv: Path, sub: Path, track: Track, default: bool):
    """A feliratfájl beágyazása az mkv-ba. -> a megtartott idegen magyar sávok
    leírása (figyelmeztetéshez; a két saját sávfajta nem számít idegennek). Hibánál Fail; az eredeti .mkv csak sikeres,
    ellenőrzött mux után cserélődik, ideiglenes fájl nem marad."""
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    before = probe(ffprobe, mkv)
    tmp = mkv.with_name(f".tmp_{mkv.name}")
    cmd, keep, pos = mux_cmd(ffmpeg, mkv, sub, tmp, before.get("streams", []), track, default)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise Fail(f"ffmpeg hiba: {r.stderr.strip()[-300:]}")
        problems = check_mux(before, probe(ffprobe, tmp), keep, pos, track, default)
        if problems:
            raise Fail("a muxolt fájl hibás, az eredetit nem cseréltem: " + "; ".join(problems))
        try:
            os.replace(tmp, mkv)
        except PermissionError as e:
            raise Fail(f"nem tudom lecserélni ({e}) — nyitva van lejátszóban?")
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return [describe(s) for s in keep
            if tags(s).get("language") == LANG and not any(t.owns(s) for t in KNOWN_TRACKS)]


def describe(s):
    t = tags(s)
    return f"„{t.get('title') or '—'}” ({s.get('codec_name')})"


# ── főprogram ───────────────────────────────────────────────────────────────

def mkv_for(srt: Path) -> Path:
    if not srt.name.endswith(".hun.srt"):
        raise Fail("csak <név>.hun.srt ágyazható be (a .clean/.merge stb. változatot előbb "
                   "nevezd át a végleges .hun.srt-re)")
    return srt.with_name(srt.name.removesuffix(".hun.srt") + ".mkv")


def check_srt(srt: Path):
    try:
        text = srt.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"nem olvasható UTF-8 SRT ({e})")
    if "-->" not in text:
        raise Fail("nincs benne egyetlen felirat sem")


def process(srt: Path, default: bool, dry_run: bool):
    mkv = mkv_for(srt)
    if not mkv.exists():
        raise Fail(f"nincs hozzá videó: {mkv.name}")
    check_srt(srt)
    if dry_run:
        keep, pos = plan(probe(find_tool("ffprobe"), mkv).get("streams", []), SRT_TRACK, default)
        print(f"{srt.name} -> {mkv.name} (próba, nem ír semmit)")
        print(f"  új sáv: {pos + 1}. feliratsáv, „{SRT_TRACK.title}”, "
              f"{'alapértelmezett' if default else 'nem alapértelmezett'}")
        for s in keep:
            print(f"  marad: {describe(s)} [{tags(s).get('language') or '?'}]")
        return
    others = embed(mkv, srt, SRT_TRACK, default)
    print(f"{srt.name} -> beágyazva ({'alapértelmezett' if default else 'nem alapértelmezett'}, "
          f"hun): {mkv.name}")
    if others:
        print(f"  megtartott másik magyar feliratsáv(ok): {', '.join(others)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", nargs="+", type=Path, help="kész magyar <név>.hun.srt fájl(ok)")
    ap.add_argument("--default", action=argparse.BooleanOptionalAction, default=None,
                    help="legyen az alapértelmezett feliratsáv [MKV_SUBS_DEFAULT, alap: nem]")
    ap.add_argument("--dry-run", action="store_true", help="csak kiírja, mi történne")
    args = ap.parse_args(argv)

    load_dotenv()
    default = args.default if args.default is not None else env_flag("MKV_SUBS_DEFAULT")

    rc = 0
    for srt in args.srt:
        try:
            process(srt, default, args.dry_run)
        except Fail as e:
            print(f"{srt.name}: ! {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
