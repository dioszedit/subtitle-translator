#!/usr/bin/env python3
"""Kész magyar SRT -> „dobozos” ASS, ami eltakarja a videóba égetett idegen feliratot.

Fehér szöveg átlátszatlan fekete dobozban (ASS BorderStyle=3): a dobozt a
lejátszó rajzolja a szöveg köré, így a mérete MINDIG a szöveghez igazodik
(soronként, HARDSUB_PAD belső margóval). A szöveg függőlegesen a beégetett
felirat helyére kerül; kétsoros feliratnál az alsó sor marad ott, a felső
fölé kerül. Rövid magyar szövegnél a beégetett felirat széle kilóghat a doboz
mellől — ez szándékos kompromisszum.

Időben átfedő feliratok (pl. dal + párbeszéd): a korábban kezdődött marad a
beégetett felirat helyén, a többi fölé kerül; amikor az alsó lejár, a fölötte
lévő visszacsúszik a helyére — így egyik sem takarja a másikat, és a beégetett
felirat végig takarva marad.

    python3 addons/hardsub-cover/cover_ass.py "Season 01/Sorozat - S01E01.hun.srt"
    python3 addons/hardsub-cover/cover_ass.py "Season 01"/*.hun.srt --mux
    python3 addons/hardsub-cover/cover_ass.py x.hun.srt --y 980 --play-res 1920x1080
    python3 addons/hardsub-cover/cover_ass.py x.hun.srt --out-dir /tmp/proba

Beállítások (elsőbbségi sorrend): kapcsoló > HARDSUB_* a .env-ben / környezetben
> beégetett 720p-s alapérték. A .env-et a munkakönyvtárból (vagy fölötte)
keresi, mint a pipeline többi része. Lásd: .env.example, README.md.

Kimenet: `<név>.hun.dobozos.ass` az .srt mellé (vagy az --out-dir mappába).

--mux: a kész ASS-t alapértelmezett feliratsávként (hun, „Magyar”) beteszi az
azonos nevű .mkv-ba, újrakódolás nélkül, és lecseréli az eredeti .mkv-t. Csak
a saját, korábban betett sávját (ass + hun + „Magyar”) cseréli; minden más
sáv — más magyar feliratsáv is — megmarad. Muxnál az ASS nem marad az .mkv
mellett (különben a lejátszó külső feliratként is felvenné), csak ha
--out-dir is meg van adva. Hibás fájl esetén a többit tovább feldolgozza.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TRACK_TITLE = "Magyar"

# name: (env kulcs, alapérték, típus, súgó, legkisebb érték)
SETTINGS = {
    "play_res":    ("HARDSUB_PLAY_RES", "1280x720", str,
                    "koordináta-rendszer SZÉLxMAG; a lejátszó a valós felbontásra skáláz", None),
    "x":           ("HARDSUB_X", 640, int, "a beégetett felirat vízszintes középpontja", 0),
    "y":           ("HARDSUB_Y", 650, int, "a beégetett felirat függőleges középpontja (alsó sor helye)", 0),
    "font":        ("HARDSUB_FONT", "Arial", str, "betűtípus", None),
    "size":        ("HARDSUB_FONT_SIZE", 40, int, "betűméret", 1),
    "line_height": ("HARDSUB_LINE_HEIGHT", 48, int,
                    "egy kirajzolt sor magassága (a sorok/feliratok elhelyezéséhez; ~1,2 × betűméret)", 1),
    "pad":         ("HARDSUB_PAD", 12, int, "a doboz belső margója a szöveg körül", 0),
    "box_alpha":   ("HARDSUB_BOX_ALPHA", 0, int, "doboz átlátszósága 0–255 (0 = teljesen fedő)", 0),
}


class Fail(Exception):
    """Egy fájl feldolgozása nem sikerült; a köteg többi része mehet tovább."""


# ── beállítások ─────────────────────────────────────────────────────────────

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


def resolve(args):
    cfg = {}
    for name, (env, default, typ, _, minimum) in SETTINGS.items():
        val = getattr(args, name, None)
        src = "kapcsoló"
        if val is None and os.environ.get(env, "").strip():
            val, src = os.environ[env].strip(), ".env"
        if val is None:
            val, src = default, "alap"
        try:
            cfg[name] = typ(val)
        except ValueError:
            sys.exit(f"Hibás érték: {env}={val!r} ({typ.__name__} kell)")
        if minimum is not None and cfg[name] < minimum:
            sys.exit(f"Hibás érték: {env}={val!r} (legalább {minimum} kell)")
        cfg[name + "_src"] = src
    m = re.fullmatch(r"(\d+)x(\d+)", cfg["play_res"])
    if not m or not int(m.group(1)) or not int(m.group(2)):
        sys.exit(f"Hibás felbontás: {cfg['play_res']!r} (pl. 1280x720)")
    cfg["play_w"], cfg["play_h"] = int(m.group(1)), int(m.group(2))
    if cfg["box_alpha"] > 255:
        sys.exit("HARDSUB_BOX_ALPHA 0 és 255 között legyen")
    return cfg


# ── SRT beolvasás ───────────────────────────────────────────────────────────

TIMING = re.compile(r"\s*(\S+)\s*-->\s*(\S+)")
TS = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})")


def parse_ts(s):
    """SRT-időbélyeg -> centiszekundum. Vesszőt és pontot is elfogad."""
    m = TS.fullmatch(s.strip())
    if not m:
        raise ValueError(f"hibás időbélyeg: {s!r}")
    h, mi, sec, frac = m.groups()
    ms = ((int(h) * 60 + int(mi)) * 60 + int(sec)) * 1000 + int(frac.ljust(3, "0"))
    return (ms + 5) // 10


def parse_srt(text):
    """-> (cue-k, problémák). Cue = {"start", "end" (cs), "lines", "line" (sorszám)}.

    Soronként olvas, nem üres sorral tagolt blokkokként: így nem esik ki cue
    dupla üres sor, hiányzó sorszám vagy hiányzó elválasztó sor miatt. Amit nem
    tud felhasználni, azt a problémák között jelzi — csendben semmit nem dob el.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues, problems = [], []
    cur = None  # az épp olvasott cue; "closed" = üres sor után

    def finish(c):
        if c is None or c.get("bad"):
            return
        while c["lines"] and not c["lines"][-1].strip():
            c["lines"].pop()
        if not c["lines"]:
            problems.append(f"{c['line']}. sor: üres felirat, kimarad")
        elif c["end"] <= c["start"]:
            problems.append(f"{c['line']}. sor: a vége nem a kezdete után van, kimarad")
        else:
            cues.append({k: c[k] for k in ("start", "end", "lines", "line")})

    for no, line in enumerate(lines, 1):
        m = TIMING.match(line) if "-->" in line else None
        if m:
            # elválasztó üres sor nélkül ragadt cue: az utolsó „szövegsor” a sorszám
            if cur and not cur.get("closed") and cur.get("lines") \
                    and re.fullmatch(r"\d+", cur["lines"][-1].strip()):
                cur["lines"].pop()
            finish(cur)
            try:
                cur = {"start": parse_ts(m.group(1)), "end": parse_ts(m.group(2)),
                       "lines": [], "line": no}
            except ValueError as e:
                problems.append(f"{no}. sor: {e}, a felirat kimarad")
                cur = {"bad": True, "closed": True}
            continue
        if cur is None or cur.get("closed"):
            s = line.strip()
            if s and not re.fullmatch(r"\d+", s) and not (cur or {}).get("bad"):
                problems.append(f"{no}. sor: időbélyeg nélküli szöveg, kimarad: {s[:40]!r}")
            continue
        if not line.strip():
            cur["closed"] = True
            continue
        cur["lines"].append(line)
    finish(cur)
    return cues, problems


# ── ASS ─────────────────────────────────────────────────────────────────────

def header(c):
    box = f"&H{c['box_alpha']:02X}000000"
    # BorderStyle=3: átlátszatlan doboz a szöveg köré, a szöveg méretéhez
    # igazodva; az Outline (= pad) a belső margó, az OutlineColour a doboz színe.
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {c['play_w']}
PlayResY: {c['play_h']}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Text,{c['font']},{c['size']},&H00FFFFFF,&H00FFFFFF,{box},{box},0,0,0,0,100,100,0,0,3,{c['pad']},0,5,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(cs):
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _tag(m):
    close, name = m.group(1), m.group(2).lower()
    if name in ("i", "b", "u", "s"):
        return "{\\%s%d}" % (name, 0 if close else 1)
    return ""  # <font> és minden más: eldobva


def ass_text(line):
    """Egy SRT-szövegsor ASS-re: a dőlt/félkövér megmarad ({\\i1}…{\\i0} — nem
    rajzparancs, az egyszerűsítő lejátszók is értik), a kapcsos zárójel és a
    \\n, \\N, \\h nem válhat ASS-vezérlővé."""
    line = line.replace("{", "(").replace("}", ")")
    line = re.sub(r"\\(?=[nNh])", "\\\\⁠", line)  # szóhatár-jel a \ után
    return re.sub(r"<\s*(/?)\s*([A-Za-z]+)\b[^>]*>", _tag, line)


def layout(cues, c):
    """-> [(start, end, középpont-y, cue)] időrendben.

    Az idővonalat a kezdő/záró időpontoknál szeletekre bontja; minden szeletben
    a látszó cue-k kezdés szerint alulról fölfelé rakódnak: a legkorábbi a
    beégetett felirat helyén (HARDSUB_Y az alsó sora), a többi fölötte, egymást
    nem takarva. Egy cue azonos helyzetű szomszédos szeletei egy eseménnyé
    olvadnak, így átfedés nélkül cue-nként pontosan egy esemény lesz.
    """
    lh, gap = c["line_height"], c["line_height"] + 2 * c["pad"]
    order = sorted(range(len(cues)), key=lambda i: (cues[i]["start"], i))
    bounds = sorted({t for q in cues for t in (q["start"], q["end"])})
    pieces = {i: [] for i in order}
    active = []
    for a, b in zip(bounds, bounds[1:]):
        active = [i for i in order if cues[i]["start"] <= a and cues[i]["end"] >= b]
        bottom = c["y"]
        for i in active:
            n = len(cues[i]["lines"])
            center = round(bottom - (n - 1) * lh / 2)
            p = pieces[i]
            if p and p[-1][1] == a and p[-1][2] == center:
                p[-1][1] = b
            else:
                p.append([a, b, center])
            bottom -= (n - 1) * lh + gap
    out = [(s, e, y, cues[i]) for i in order for s, e, y in pieces[i]]
    return sorted(out, key=lambda t: (t[0], -t[2]))


def build_ass(cues, c):
    events = []
    for start, end, y, q in layout(cues, c):
        text = f"{{\\pos({c['x']},{y})}}" + r"\N".join(ass_text(l) for l in q["lines"])
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Text,,0,0,0,,{text}")
    return header(c) + "\n".join(events) + "\n"


def overlaps(cues):
    s = sorted(cues, key=lambda q: q["start"])
    n, latest = 0, -1
    for q in s:
        if q["start"] < latest:
            n += 1
        latest = max(latest, q["end"])
    return n


def srt_to_ass(src: Path, dst: Path, c):
    """-> (cue-szám, átfedések, problémák). Olvashatatlan fájlnál Fail."""
    try:
        text = src.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(f"nem olvasható ({e})")
    cues, problems = parse_srt(text)
    if not cues:
        raise Fail("nincs benne egyetlen felirat sem")
    dst.write_text(build_ass(cues, c), encoding="utf-8")
    return len(cues), overlaps(cues), problems


# ── MKV ─────────────────────────────────────────────────────────────────────

def find_tool(name):
    # muxhoz (stream copy) a sima ffmpeg is elég; a full-t csak előnyben részesítjük
    for cand in (os.environ.get(name.upper()), f"/opt/homebrew/opt/ffmpeg-full/bin/{name}", shutil.which(name)):
        if cand and Path(cand).exists():
            return cand
    raise Fail(f"nem találom: {name} (PATH vagy {name.upper()} környezeti változó)")


def _tags(s):
    return {k.lower(): v for k, v in (s.get("tags") or {}).items()}


def is_own_track(s):
    t = _tags(s)
    return (s.get("codec_type") == "subtitle" and s.get("codec_name") == "ass"
            and t.get("language") == "hun" and t.get("title") == TRACK_TITLE)


def probe(ffprobe, path):
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                        "stream=index,codec_type,codec_name:stream_tags:stream_disposition=default,attached_pic"
                        ":format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if r.returncode:
        raise Fail(f"ffprobe hiba: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout)


def mux_cmd(ffmpeg, mkv, ass, tmp, streams):
    keep = [s for s in streams if s.get("codec_type") == "subtitle" and not is_own_track(s)]
    cmd = [ffmpeg, "-v", "error", "-y", "-i", str(mkv), "-i", str(ass),
           "-map", "0:v", "-map", "0:a?", "-map", "1"]
    for s in keep:
        cmd += ["-map", f"0:{s['index']}"]
    cmd += ["-map", "0:t?", "-c", "copy",
            "-metadata:s:s:0", "language=hun", "-metadata:s:s:0", f"title={TRACK_TITLE}",
            "-disposition:s", "0", "-disposition:s:0", "default", str(tmp)]
    return cmd, keep


def check_mux(before, after, kept):
    """A muxolt fájl ellenőrzése az eredetihez képest -> problémák listája."""
    def count(info, typ):
        return sum(1 for s in info.get("streams", []) if s.get("codec_type") == typ)

    problems = []
    for typ, label in (("video", "videó"), ("audio", "hang"), ("attachment", "melléklet")):
        if count(after, typ) != count(before, typ):
            problems.append(f"{label}sávok száma {count(before, typ)} -> {count(after, typ)}")
    subs = [s for s in after.get("streams", []) if s.get("codec_type") == "subtitle"]
    if not subs or not is_own_track(subs[0]) or not subs[0].get("disposition", {}).get("default"):
        problems.append("nincs az első helyen alapértelmezett magyar ass sáv")
    if len(subs) != len(kept) + 1:
        problems.append(f"feliratsávok száma {len(subs)}, várt {len(kept) + 1}")
    try:
        d0 = float(before["format"]["duration"])
        d1 = float(after["format"]["duration"])
        if abs(d0 - d1) > 1.0:
            problems.append(f"hossz {d0:.1f} s -> {d1:.1f} s")
    except (KeyError, TypeError, ValueError):
        pass
    return problems


def mux(mkv: Path, ass: Path):
    """-> a megtartott másik magyar sávok címei. Hibánál Fail; az eredeti .mkv
    csak sikeres, ellenőrzött mux után cserélődik, ideiglenes fájl nem marad."""
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    before = probe(ffprobe, mkv)
    tmp = mkv.with_name(f".tmp_{mkv.name}")
    cmd, keep = mux_cmd(ffmpeg, mkv, ass, tmp, before.get("streams", []))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise Fail(f"ffmpeg hiba: {r.stderr.strip()[-300:]}")
        problems = check_mux(before, probe(ffprobe, tmp), keep)
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
    return [_tags(s).get("title") or f"#{s['index']}" for s in keep if _tags(s).get("language") == "hun"]


# ── főprogram ───────────────────────────────────────────────────────────────

def process(srt: Path, c, do_mux, out_dir, workdir):
    base = srt.name.removesuffix(".srt")
    target = out_dir or (workdir if do_mux else srt.parent)
    ass = target / (base + ".dobozos.ass")
    mkv = srt.with_name(re.sub(r"\.hun$", "", base) + ".mkv")
    if do_mux and not mkv.exists():
        raise Fail(f"nincs hozzá videó: {mkv.name}")
    n, ov, problems = srt_to_ass(srt, ass, c)
    print(f"{srt.name}: {n} felirat -> {ass if out_dir or not do_mux else '(ideiglenes ASS)'}")
    if ov:
        print(f"  {ov} átfedő felirat egymás fölé rendezve")
    for p in problems:
        print(f"  ! {p}", file=sys.stderr)
    if do_mux:
        others = mux(mkv, ass)
        print(f"  -> beágyazva (alapértelmezett, hun): {mkv.name}")
        if others:
            print(f"  ! megtartott másik magyar feliratsáv(ok): {', '.join(others)}", file=sys.stderr)
    return not problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", nargs="+", type=Path, help="kész magyar .hun.srt fájl(ok)")
    ap.add_argument("--mux", action="store_true", help="betenni alapértelmezett sávként az azonos nevű .mkv-ba")
    ap.add_argument("--out-dir", type=Path, help="az ASS ide kerüljön (alap: az .srt mellé; --mux-nál nem marad meg)")
    for name, (env, default, typ, hlp, _) in SETTINGS.items():
        ap.add_argument("--" + name.replace("_", "-"), dest=name, type=typ, default=None,
                        help=f"{hlp} [{env}, alap: {default}]")
    args = ap.parse_args(argv)

    load_dotenv()
    c = resolve(args)
    print("Beállítások: " + ", ".join(f"{n}={c[n]} ({c[n + '_src']})" for n in SETTINGS))
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    rc = 0
    with tempfile.TemporaryDirectory(prefix="hardsub-") as tmpdir:
        for srt in args.srt:
            try:
                if not process(srt, c, args.mux, args.out_dir, Path(tmpdir)):
                    rc = 1
            except Fail as e:
                print(f"{srt.name}: ! {e}", file=sys.stderr)
                rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
