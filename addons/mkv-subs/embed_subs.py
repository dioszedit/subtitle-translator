#!/usr/bin/env python3
"""
Kész felirat beágyazása az azonos nevű .mkv-ba (az extract_subs.py párja).
Bármilyen nyelvű lehet; a nyelvet a fájlnév nyelvjelöléséből veszi.

    python3 addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.hun.srt"
    python3 addons/mkv-subs/embed_subs.py "Season 01"/*.hun.srt --default
    python3 addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.eng.srt"
    python3 addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.chi.srt" --title "Chinese (Simplified)"
    python3 addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.hun.srt" --dry-run

Mit csinál:
  - a `<név>.<nyelv>.srt`-t szöveges (subrip) feliratsávként beteszi a
    `<név>.mkv`-ba, újrakódolás nélkül (stream copy), és lecseréli az eredeti
    .mkv-t; az .srt a helyén marad (az a javítható forrás);
  - nyelv: a fájlnév nyelvjelöléséből (`.hun`, `.eng`, `.chi`, `.ja` → jpn …),
    vagy `--lang`; cím: a nyelv angol neve („English”, „Chinese”), a magyaré
    „Magyar” — vagy `--title`;
  - csak a SAJÁT, korábban betett sávját cseréli: ezt egy rejtett jelölő
    címke (SUBTR=srt) azonosítja, nem a cím — így a kiadó saját, szintén
    „English” című angol sávja megmarad, és egy `--title`-cserénél sem marad
    bent a régi sáv. Minden más sáv — a kiadó sávjai, a hardsub-cover dobozos
    ASS-sávja — megmarad, a jelöléseivel együtt;
  - `--default`: az új sáv lesz az alapértelmezett (az első feliratsáv), a
    többiről lekerül a default jelölés (a forced és társai maradnak). Enélkül
    a sáv a meglévők után kerül, nem alapértelmezettként, és a többi sáv
    jelölése nem változik. Állandó beállításként: MKV_SUBS_DEFAULT=1 a .env-ben
    (a --no-default felülírja);
  - csere előtt ellenőrzi az új fájlt (videó-, hang-, mellékletsávok száma,
    hossz, az új sáv helye és jelölése); hibánál az eredeti érintetlen marad,
    ideiglenes fájl nem marad hátra; több fájlnál egy hibás nem állítja le a
    többit.

A muxoló mag (embed) közös: a hardsub-cover add-on is ezt használja a dobozos
ASS-sávhoz („Magyar (dobozos)”, jelölő: SUBTR=ass).

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_subs import normalize_lang  # noqa: E402  (a pipeline nyelvkód-kezelése)

MARKER = "SUBTR"  # rejtett sávcímke: ezzel ismeri fel a saját, korábban betett sávját

# A sáv címe alapból a nyelv angol neve (ahogy a kiadások sávjai is), a magyaré „Magyar”.
LANG_NAMES = {
    "hun": "Magyar", "eng": "English", "chi": "Chinese", "jpn": "Japanese", "kor": "Korean",
    "ger": "German", "fre": "French", "spa": "Spanish", "por": "Portuguese", "ita": "Italian",
    "rus": "Russian", "pol": "Polish", "tur": "Turkish", "vie": "Vietnamese", "ind": "Indonesian",
    "may": "Malay", "tha": "Thai", "hin": "Hindi", "ara": "Arabic", "fil": "Filipino",
    "tgl": "Tagalog", "ukr": "Ukrainian", "dut": "Dutch", "swe": "Swedish", "cze": "Czech",
    "slo": "Slovak", "rum": "Romanian", "gre": "Greek", "heb": "Hebrew", "fin": "Finnish",
    "dan": "Danish", "nor": "Norwegian",
}


class Fail(Exception):
    """Egy fájl feldolgozása nem sikerült; a köteg többi része mehet tovább."""


class Track:
    """Egy saját feliratsáv: fajta (srt/ass) + kodek + nyelv + cím.

    Sajátnak az a sáv számít, amelyen a jelölő címke (SUBTR=<fajta>) és a nyelv
    egyezik — a cím nem számít, így a kiadó azonos című sávja nem keveredik
    bele. A jelölő előtti (2026-11 eleji) magyar sávokat a legacy_titles alapján
    ismeri fel: ugyanaz a kodek, `hun`, és az egyik régi cím."""

    def __init__(self, kind, codec, lang, title, legacy_titles=()):
        self.kind, self.codec, self.lang, self.title = kind, codec, lang, title
        self.legacy_titles = set(legacy_titles)

    def owns(self, s):
        if s.get("codec_type") != "subtitle":
            return False
        t = tags(s)
        if t.get("language") != self.lang:
            return False
        if t.get(MARKER.lower()) == self.kind:
            return True
        return (MARKER.lower() not in t and s.get("codec_name") == self.codec
                and t.get("title") in self.legacy_titles)


def srt_track(lang, title=None):
    """Sima szöveges sáv az adott nyelvhez (cím: --title, vagy a nyelv neve)."""
    legacy = ("Magyar",) if lang == "hun" else ()
    return Track("srt", "subrip", lang, title or LANG_NAMES.get(lang, lang), legacy)


SRT_TRACK = srt_track("hun")
# a hardsub-cover dobozos sávja; a jelölő előtti címekkel betetteket is felismeri
ASS_TRACK = Track("ass", "ass", "hun", "Magyar (dobozos)", legacy_titles=("Magyar", "Magyar (dobozos)"))


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
            f"-metadata:s:s:{pos}", f"language={track.lang}", f"-metadata:s:s:{pos}", f"title={track.title}",
            f"-metadata:s:s:{pos}", f"{MARKER}={track.kind}",
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
        problems.append(f"nincs a(z) {pos + 1}. helyen a(z) {track.lang} „{track.title}” sáv")
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
    """A feliratfájl beágyazása az mkv-ba. -> a megtartott, azonos nyelvű, nem
    általunk betett sávok leírása (tájékoztatáshoz). Hibánál Fail; az eredeti
    .mkv csak sikeres, ellenőrzött mux után cserélődik, ideiglenes fájl nem marad."""
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
    return [describe(s) for s in keep if tags(s).get("language") == track.lang and not is_ours(s)]


def is_ours(s):
    """Bármelyik saját sávfajta (a jelölő, vagy a régi magyar címek alapján)."""
    t = tags(s)
    return MARKER.lower() in t or SRT_TRACK.owns(s) or ASS_TRACK.owns(s)


def describe(s):
    t = tags(s)
    return f"„{t.get('title') or '—'}” ({s.get('codec_name')})"


# ── főprogram ───────────────────────────────────────────────────────────────

def split_name(srt: Path, lang=None):
    """<név>.<nyelv>.srt -> (mkv útvonal, nyelvkód). A --lang felülírja a
    fájlnév nyelvjelölését; jelölés nélküli névnél kötelező."""
    if srt.suffix.lower() != ".srt":
        raise Fail("csak .srt ágyazható be")
    stem = srt.name[: -len(srt.suffix)]
    base, dot, tag = stem.rpartition(".")
    tag_lang = normalize_lang(tag) if dot and base else ""
    if tag_lang not in LANG_NAMES:
        tag_lang = ""
    if tag_lang:
        stem = base
    if lang:
        code = normalize_lang(lang)
        if not re.fullmatch(r"[a-z]{3}", code):
            raise Fail(f"ismeretlen nyelvkód: {lang!r} (3 betűs kód kell, pl. hun, eng, chi)")
    elif tag_lang:
        code = tag_lang
    else:
        raise Fail("a fájlnévből nem derül ki a nyelv (<név>.<nyelv>.srt, pl. .hun.srt) — add meg "
                   "a --lang kapcsolóval; a .clean/.merge stb. köztes változatot előbb nevezd át "
                   "a végleges névre")
    return srt.with_name(stem + ".mkv"), code


def check_srt(srt: Path):
    try:
        text = srt.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"nem olvasható UTF-8 SRT ({e})")
    if "-->" not in text:
        raise Fail("nincs benne egyetlen felirat sem")


def process(srt: Path, default: bool, dry_run: bool, lang=None, title=None):
    mkv, code = split_name(srt, lang)
    track = srt_track(code, title)
    if not mkv.exists():
        raise Fail(f"nincs hozzá videó: {mkv.name}")
    check_srt(srt)
    mode = "alapértelmezett" if default else "nem alapértelmezett"
    if dry_run:
        streams = probe(find_tool("ffprobe"), mkv).get("streams", [])
        keep, pos = plan(streams, track, default)
        print(f"{srt.name} -> {mkv.name} (próba, nem ír semmit)")
        print(f"  új sáv: {pos + 1}. feliratsáv, {code}, „{track.title}”, {mode}")
        for s in streams:
            if s.get("codec_type") == "subtitle" and track.owns(s):
                print(f"  cserélődik: {describe(s)} [{code}]")
        for s in keep:
            print(f"  marad: {describe(s)} [{tags(s).get('language') or '?'}]")
        return
    others = embed(mkv, srt, track, default)
    print(f"{srt.name} -> beágyazva ({mode}, {code}, „{track.title}”): {mkv.name}")
    if others:
        print(f"  megmaradt a kiadó azonos nyelvű sávja is: {', '.join(others)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", nargs="+", type=Path, help="kész felirat(ok): <név>.<nyelv>.srt")
    ap.add_argument("--lang", help="nyelvkód (hun, eng, chi… vagy en/ja/ko); alap: a fájlnévből")
    ap.add_argument("--title", help="a sáv címe; alap: a nyelv angol neve, magyarnál „Magyar”")
    ap.add_argument("--default", action=argparse.BooleanOptionalAction, default=None,
                    help="legyen az alapértelmezett feliratsáv [MKV_SUBS_DEFAULT, alap: nem]")
    ap.add_argument("--dry-run", action="store_true", help="csak kiírja, mi történne")
    args = ap.parse_args(argv)

    load_dotenv()
    default = args.default if args.default is not None else env_flag("MKV_SUBS_DEFAULT")

    rc = 0
    for srt in args.srt:
        try:
            process(srt, default, args.dry_run, args.lang, args.title)
        except Fail as e:
            print(f"{srt.name}: ! {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
