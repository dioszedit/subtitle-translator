#!/usr/bin/env python3
"""
Beégetett (hardsub) idegen nyelvű feliratból OCR-rel segédfelirat, a forrás
(pl. angol) SRT cue-ihoz igazítva.

Mire jó?
  Sok kiadásban az eredeti nyelvű felirat nem külön sáv, hanem a képbe van
  égetve (kínai, koreai, thai… vagy akár latin betűs). A megszólítási regiszter
  (kínai 你/您, koreai -요/반말, japán です/plain) és a névalakok ebből olvashatók
  ki — az angol `you` elfedi őket. Ez a script a képkockákból kiolvassa a
  beégetett szöveget, és a FORRÁS SRT cue-ihoz rendeli: ugyanazok a sorszámok
  és időbélyegek, cue-nként a kinyert szöveg, `—` ha nincs.

  Az eredmény TÁMPONT, nem fordítási forrás: OCR-hibák vannak benne, és a
  dalszöveg/képi felirat cue-k üresek maradhatnak. A regiszterhez és a
  névalakokhoz jó, a fordításhoz nem.

Kimenet:
  `input/Sorozat - S01E01.chi.ocr.srt` (a nyelvkód a --lang kapcsolóból)
  Az `.ocr` tag jelzi, hogy gépi kinyerés. A pipeline a nyelvet így is
  felismeri (`chi`), a `split` megáll rajta, a `register` pedig figyelmezteti
  a modellt a félreolvasásokra.

Használat:
  # a forrás SRT a videó nevéből: input/Sorozat - S01E01.eng.srt (vagy más forrásnyelv)
  python addons/hardsub-ocr/ocr_subs.py "Season 01/Sorozat - S01E01.mp4"

  # egész évad; koreai beégetett felirat
  python addons/hardsub-ocr/ocr_subs.py "Season 01"/*.mp4 --lang kor

  # egy rész, megadott forrással, próbamappába
  python addons/hardsub-ocr/ocr_subs.py "Season 01/Sorozat - S01E01.mp4" \\
      --ref "input/Sorozat - S01E01.eng.srt" --out-dir proba

A `*.mp4` mintát a script maga is kibontja (subtr.config.expand_patterns), így
Windowson (cmd, PowerShell) is működik.

Algoritmus:
  1. cue-nként 1–2 mintavétel (a cue 35%-ánál és 70%-ánál, rövid cue-nál a
     felénél; a képkocka-rács --fps, alapból 4/mp); ffmpeg CSAK ezeket a
     képkockákat vágja ki a felirat-sávból (alapból a kép alsó ~15%-a) → OCR;
  2. ha a motor a képek többségét nem tudja beolvasni, a rész hibával megáll
     (nem ír csupa `—` kimenetet);
  3. szűrés: reklám (kulcsszavak, URL-ek; nem latin írású nyelvnél a latin
     betűs sor és a hosszú számsor — telefonszám, kód), és csak a nyelv
     írásrendszerét tartalmazó sorok;
  4. a legjobb jelölt (a legkisebb soronkénti megbízhatóság, aztán a hossz);
  5. pótló kör az üresen maradt cue-kra: a cue több képkockája (max 8; ezeket
     egy második ffmpeg-menet vágja ki), nyersen ÉS binarizálva (fehér felirat világos háttér előtt), csak
     elég biztos (--retry-min-conf) találat számít.

OCR-motor (--engine): `auto` = macOS-en a beépített Vision (nincs mit
telepíteni, csak az Xcode Command Line Tools a fordításhoz), máshol RapidOCR
(`pip install -e ".[ocr]"`). Lásd engines.py.

Beállítások (elsőbbségi sorrend): kapcsoló > HARDSUB_OCR_* a .env-ben /
környezetben > alapérték. A .env-et a munkakönyvtárból (vagy fölötte)
keresi, mint a pipeline többi része. Lásd: .env.example, README.md.

Függőség: `ffmpeg` (7.0 vagy újabb) + `ffprobe` a PATH-on, a program `subtr` mappája és a
`mkv-subs` add-on (a programmal együtt jönnek), és az OCR-motor.

Kilépési kód: 0 siker (a már kész részek kihagyása is az), 1 hiba.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A nyelvkód-kezelés, a fájlminta-kibontás, az ffmpeg megkeresése és a .env
# olvasása a mkv-subs add-onból (és azon át a subtr csomagból) jön.
sys.path.insert(0, str(HERE.parent / "mkv-subs"))
sys.path.insert(0, str(HERE))
from embed_subs import load_dotenv  # noqa: E402
from extract_subs import (  # noqa: E402
    Fail, expand_patterns, ffprobe_json, find_tool, normalize_lang, require_tools,
    run_tool, stem_without_lang, utf8_console)
from subtr.config import OCR_SUFFIX, SOURCE_LANGS  # noqa: E402  (az `.ocr` jelölés egyetlen helye)
from subtr.srt import parse_sections, write_srt  # noqa: E402

import engines  # noqa: E402

EMPTY = "—"   # üres cue jelölése a kimenetben
DEFAULT_OUT_DIR = "input"
DEFAULT_REF_DIR = "input"
DEFAULT_LANG = "chi"
BATCH = 300   # ennyi képet kap a motor egyszerre (a haladás kiírásához)


# ── írásrendszerek és reklámszűrés ────────────────────────────────────────

# Írásrendszerenként az „elvárt” karakterek: egy OCR-sor csak akkor számít
# feliratnak, ha van benne ilyen. `latin` = latin betűs írás: ott a latin
# betű nem gyanús, a latin-szűrés kikapcsol.
SCRIPTS = {
    "han":        r"[㐀-䶿一-鿿豈-﫿]",
    "japanese":   r"[぀-ヿㇰ-ㇿ㐀-䶿一-鿿ｦ-ﾟ]",
    "hangul":     r"[ᄀ-ᇿ㄰-㆏가-힯]",
    "thai":       r"[฀-๿]",
    "arabic":     r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]",
    "devanagari": r"[ऀ-ॿ]",
    "cyrillic":   r"[Ѐ-ӿ]",
    "latin":      r"[A-Za-zÀ-ɏḀ-ỿ]",
}

LANG_SCRIPT = {
    "chi": "han", "jpn": "japanese", "kor": "hangul", "tha": "thai",
    "ara": "arabic", "hin": "devanagari", "rus": "cyrillic",
    "eng": "latin", "ger": "latin", "fre": "latin", "spa": "latin", "por": "latin",
    "ita": "latin", "pol": "latin", "tur": "latin", "vie": "latin", "ind": "latin",
    "may": "latin",
}

# Nem latin írású feliratban a latin betű szinte mindig a képre tett reklám
# (weboldal, kód) — a teljes és félszélességű alak is. A szám önmagában nem
# gyanús („3天后”, „10억”), csak a hosszú számsor (telefonszám, QQ-szám, kód).
LATIN_OR_LONG_NUMBER = r"[A-Za-zＡ-Ｚａ-ｚ]|[0-9０-９]{5,}"

# Minden nyelvre: webcím-minták.
AD_COMMON = [r"\.(?:com|net|cc|tv|vip|top|xyz|io)\b", r"www\.", r"https?://"]

# Nyelvenkénti reklám-kulcsszavak (szerencsejáték-/fogadási hirdetések, ezek
# kerülnek a kalóz-kiadások képére). Bővítés: HARDSUB_OCR_AD_EXTRA / --ad-extra.
AD_WORDS = {
    "chi": ["官方", "扫码", "投注", "娱乐", "提现", "平台", "CSGO", "天下会", "百家乐", "联盟",
            "世界杯", "锦标赛", "足球", "篮球", "彩票", "博彩"],
}


def script_of(lang):
    return LANG_SCRIPT[lang]


def ad_pattern(lang, extra=""):
    """A nyelv reklám-regexe: közös URL-minták + a nyelv kulcsszavai + extra."""
    parts = list(AD_COMMON) + [re.escape(w) for w in AD_WORDS.get(lang, [])]
    if extra.strip():
        parts.append(f"(?:{extra.strip()})")
    return re.compile("|".join(parts), re.IGNORECASE)


class LineFilter:
    """Egy képkocka OCR-sorainak szűrése: [(szöveg, conf)] → a megtartottak."""

    def __init__(self, lang, ad_extra="", drop_latin=None):
        self.script = re.compile(SCRIPTS[script_of(lang)])
        self.ads = ad_pattern(lang, ad_extra)
        if drop_latin is None:   # auto: csak nem latin írású nyelvnél
            drop_latin = script_of(lang) != "latin"
        self.latin = re.compile(LATIN_OR_LONG_NUMBER) if drop_latin else None

    def keep(self, text):
        text = " ".join(text.split())
        if not text or self.ads.search(text):
            return None
        if self.latin is not None and self.latin.search(text):
            return None
        if not self.script.search(text):
            return None
        return text

    def __call__(self, lines):
        out = []
        for text, conf in lines or ():
            kept = self.keep(text)
            if kept:
                out.append((kept, float(conf)))
        return out


def candidate(parts):
    """Egy képkocka megtartott soraiból (szöveg, conf): a sorok szóközzel
    összefűzve, a megbízhatóság a leggyengébb soré. Üresnél None."""
    if not parts:
        return None
    return " ".join(t for t, _ in parts), min(c for _, c in parts)


def best_candidate(cands, min_conf=0.0):
    """A legjobb (szöveg, conf): a legnagyobb (legkisebb soros) conf, döntetlennél
    a hosszabb. A min_conf alatti jelöltek nem számítanak. Ha nincs: ("", 0.0)."""
    cands = [c for c in cands if c and c[1] >= min_conf]
    if not cands:
        return "", 0.0
    return max(cands, key=lambda c: (c[1], len(c[0])))


# ── SRT ────────────────────────────────────────────────────────────────────

TS = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})")


def parse_ts(s):
    """SRT-időbélyeg → másodperc (float). Vesszőt és pontot is elfogad."""
    m = TS.fullmatch(s.strip())
    if not m:
        raise ValueError(f"hibás időbélyeg: {s!r}")
    h, mi, sec, frac = m.groups()
    return (int(h) * 60 + int(mi)) * 60 + int(sec) + int(frac.ljust(3, "0")) / 1000


def read_cues(path):
    """A forrás SRT cue-i: [{num, timestamp, start, end}] (a sorszám és az
    időbélyeg-sor változatlanul megy át a kimenetbe). Hibánál Fail."""
    try:
        sections = parse_sections(str(path))
    except (OSError, UnicodeDecodeError) as exc:
        raise Fail(f"a forrás SRT nem olvasható: {path} ({exc})")
    cues = []
    for s in sections:
        a, sep, b = s["timestamp"].partition("-->")
        try:
            if not sep:
                raise ValueError("nincs benne -->")
            start, end = parse_ts(a), parse_ts(b.split()[0] if b.split() else b)
        except ValueError as exc:
            raise Fail(f"hibás időbélyeg a(z) {s['num']}. cue-ban: {s['timestamp']!r} ({exc})")
        cues.append({"num": s["num"], "timestamp": s["timestamp"], "start": start, "end": end})
    if not cues:
        raise Fail(f"a forrás SRT-ben nincs egyetlen cue sem: {path}")
    return cues


def output_sections(cues, texts):
    """A kimenet szekciói: a forrás sorszáma és időbélyege, a kinyert szöveg vagy `—`."""
    return [{"num": c["num"], "timestamp": c["timestamp"], "text": t or EMPTY}
            for c, t in zip(cues, texts)]


# ── fájlnevek ──────────────────────────────────────────────────────────────

def out_path(video, lang, out_dir):
    """`Season 01/X - S01E01.mp4` → `<out_dir>/X - S01E01.<lang>.ocr.srt`."""
    return Path(out_dir) / f"{stem_without_lang(video)}.{lang}{OCR_SUFFIX}.srt"


def find_ref(video, lang, ref_dir):
    """A videóhoz tartozó forrás SRT a ref_dir mappában: `<tő>.<kód>.srt`, ahol a
    kód egy ismert forrásnyelv, de NEM az OCR nyelve (az a kimenet lenne).
    Az angol az első; több más találatnál nem tippel. -> (útvonal, None) vagy (None, hiba)."""
    stem = stem_without_lang(video)
    hits = [Path(ref_dir) / f"{stem}.{code}.srt" for code in SOURCE_LANGS if code != lang]
    hits = [p for p in hits if p.is_file()]
    if not hits:
        return None, (f"nincs hozzá forrás SRT: {Path(ref_dir) / (stem + '.<nyelv>.srt')} "
                      "— add meg a --ref kapcsolóval")
    eng = [p for p in hits if p.name.endswith(".eng.srt")]
    if eng:
        return eng[0], None
    if len(hits) > 1:
        return None, (f"több forrás SRT is van ({', '.join(p.name for p in hits)}) — "
                      "válassz a --ref kapcsolóval")
    return hits[0], None


# ── képkockák ──────────────────────────────────────────────────────────────

def sample_frames(start, end, fps):
    """A fő kör mintavételi képkockái (sorszám = round(idő × fps)):
    a cue 35%-ánál és 70%-ánál, 0,8 mp-nél rövidebb cue-nál a felénél."""
    d = end - start
    points = (0.35, 0.7) if d > 0.8 else (0.5,)
    return list(dict.fromkeys(int(round((start + d * p) * fps)) for p in points))


def retry_frames(start, end, fps, limit):
    """A pótló kör képkockái: a cue összes képkockája, de legfeljebb `limit`,
    egyenletesen elosztva (ne csak a cue eleje kerüljön sorra)."""
    frames = list(range(int(start * fps) + 1, int(end * fps) + 1))
    if limit <= 0:
        return []
    if len(frames) <= limit:
        return frames
    step = len(frames) / limit
    return [frames[int(i * step + step / 2)] for i in range(limit)]


def parse_edge(value):
    """A sáv széle: 0–1 közti arány (a kép magasságához) vagy pixel (>1, egész)."""
    v = float(str(value).strip().removesuffix("px"))
    if v < 0:
        raise ValueError("negatív")
    if v > 1 and v != int(v):
        raise ValueError("pixelnél egész szám kell")
    return v


def band_pixels(top, bottom, height):
    """(y, magasság) pixelben a videó magasságából. Hibás sávnál Fail."""
    y0 = round(top * height) if top <= 1 else int(top)
    y1 = round(bottom * height) if bottom <= 1 else int(bottom)
    y1 = min(y1, height)
    if y1 - y0 < 8:
        raise Fail(f"a felirat-sáv túl keskeny vagy fordított: {y0}–{y1} px "
                   f"(a kép {height} px magas) — ellenőrizd a --top / --bottom értékét")
    return y0, y1 - y0


def video_size(video):
    data = ffprobe_json(video, "stream=width,height", select="v:0")
    streams = data.get("streams") or []
    if not streams or not streams[0].get("height"):
        raise Fail("nincs képsáv a fájlban")
    return int(streams[0]["width"]), int(streams[0]["height"])


def select_expr(numbers):
    """Az ffmpeg `select` kifejezése a megadott képkocka-sorszámokra; az egymást
    követő sorszámok egy `between`-be olvadnak (a pótló kör kockái ilyenek)."""
    nums = sorted(set(numbers))
    parts, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(f"eq(n\\,{nums[i]})" if i == j else f"between(n\\,{nums[i]}\\,{nums[j]})")
        i = j + 1
    return "+".join(parts)


def extract_frames(video, frames_dir, fps, y, h, numbers):
    """A felirat-sáv megadott sorszámú képkockái PNG-ként: frames_dir/<n>.png,
    ahol az n. kocka az fps-rács n. kockája (0. = a videó eleje). Csak ezeket
    írja ki — egy egész rész összes kockája gigabájtnyi PNG lenne a temp-ben.

    A szűrőlánc fájlból megy (`-/vf`, ffmpeg 7+): sok ezer sorszám a Windows
    parancssor-korlátjába (32K) nem férne bele."""
    nums = sorted(set(n for n in numbers if n >= 0))
    if not nums:
        return
    frames_dir = Path(frames_dir)
    stage = frames_dir / "_stage"
    stage.mkdir(exist_ok=True)
    script = frames_dir / "_select.txt"
    script.write_text(f"fps={fps},select='{select_expr(nums)}',crop=iw:{h}:0:{y}",
                      encoding="ascii")
    duration = (nums[-1] + 1) / fps + 1.0
    cmd = [find_tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(video),
           "-t", f"{duration:.3f}", "-an", "-sn", "-/vf", str(script),
           "-fps_mode", "passthrough", "-start_number", "0", str(stage / "%06d.png")]
    r = run_tool(cmd)
    if r.returncode:
        err = (r.stderr or "").strip()
        if "/vf" in err:
            err += " — ffmpeg 7.0 vagy újabb kell"
        raise Fail(f"ffmpeg hiba a képkockák kivágásánál: {err[-300:]}")
    # A kimenet sorban számozott (a k. kiírt kocka a k. kért sorszám); ha a
    # videó hamarabb véget ér, a végéről hiányoznak kockák — azok kimaradnak.
    for k, n in enumerate(nums):
        src = stage / f"{k:06d}.png"
        if not src.exists():
            break
        os.replace(src, frame_file(frames_dir, n))


def frame_file(frames_dir, n):
    return Path(frames_dir) / f"{n:06d}.png"


def binarize(paths, out_dir, threshold):
    """Fekete-fehér változat a pótló körhöz: a `threshold` fölötti (fehér felirat)
    feketére, minden más fehérre — világos háttér előtt is olvasható lesz.
    Egy ffmpeg-hívás több képet is visz. -> {eredeti: binarizált}."""
    out = {}
    vf = f"format=gray,lut=y='if(gt(val,{threshold}),0,255)'"
    ffmpeg = find_tool("ffmpeg")
    paths = list(paths)
    for k in range(0, len(paths), 40):
        chunk = paths[k:k + 40]
        cmd = [ffmpeg, "-nostdin", "-v", "error", "-y"]
        for p in chunk:
            cmd += ["-i", str(p)]
        targets = []
        for i, p in enumerate(chunk):
            dst = Path(out_dir) / f"bin_{Path(p).name}"
            cmd += ["-map", f"{i}:v", "-vf", vf, "-frames:v", "1", str(dst)]
            targets.append((p, dst))
        r = run_tool(cmd)
        if r.returncode:
            raise Fail(f"ffmpeg hiba a binarizálásnál: {(r.stderr or '').strip()[-300:]}")
        out.update({p: d for p, d in targets if d.exists()})
    return out


# ── igazítás (motorfüggetlen mag) ──────────────────────────────────────────

# Ha a motor a képek ennél nagyobb részét nem tudja beolvasni, az nem „nincs
# felirat”, hanem motorhiba: a rész megáll, nem ír csupa `—` kimenetet.
MAX_UNREADABLE = 0.5


class Recognizer:
    """Az OCR-motor köré: képenként egyszer olvas (a pótló kör újrahasznosítja
    a fő kör eredményeit), a hiányzó képkockát (a videó vége után) kihagyja,
    és számolja, hány képet nem tudott a motor beolvasni (None)."""

    def __init__(self, engine, line_filter, progress=None):
        self.engine = engine
        self.filter = line_filter
        self.progress = progress
        self.reset()

    def reset(self):
        """Új rész előtt: az előző rész képkockái a temp-mappával együtt törlődtek."""
        self.cache = {}
        self.read = 0
        self.unreadable = 0

    def run(self, paths):
        todo = [p for p in dict.fromkeys(paths) if p not in self.cache and Path(p).exists()]
        for k in range(0, len(todo), BATCH):
            chunk = todo[k:k + BATCH]
            for p, lines in zip(chunk, self.engine.recognize(chunk)):
                self.read += 1
                if lines is None:
                    self.unreadable += 1
                self.cache[p] = candidate(self.filter(lines))
            if self.progress:
                self.progress(min(k + BATCH, len(todo)), len(todo))

    def get(self, path):
        return self.cache.get(path)

    def check(self):
        """Fail, ha a képek többsége olvashatatlan volt — a motor romlott el."""
        if self.read and self.unreadable / self.read > MAX_UNREADABLE:
            last = getattr(self.engine, "last_error", None)
            raise Fail(f"az OCR-motor a {self.read} képkockából {self.unreadable}-t nem tudott "
                       f"beolvasni{f' (utolsó hiba: {last})' if last else ''} — kimenet nem "
                       "készült; ellenőrizd a motor telepítését (--engine)")


def align(cues, frames_dir, recognizer, cfg, binarizer=None, extractor=None, log=print):
    """Cue-nként a kinyert szöveg. -> (szövegek, statisztika).

    binarizer(paths) -> {eredeti: binarizált}; None = a pótló kör csak nyers képpel.
    extractor(sorszámok): kivágja ezeket a képkockákat a frames_dir-be; None =
    a képkockák már ott vannak (tesztek).
    A végén Fail, ha a motor a képek többségét nem tudta beolvasni.
    """
    fps = cfg["fps"]
    nums = [sample_frames(c["start"], c["end"], fps) for c in cues]
    done = {n for ns in nums for n in ns}
    if extractor:
        extractor(done)
    plan = [[frame_file(frames_dir, n) for n in ns] for ns in nums]
    log(f"  OCR: {len(done)} képkocka ({len(cues)} cue)")
    recognizer.run([p for ps in plan for p in ps])
    texts = []
    for ps in plan:
        text, _ = best_candidate([recognizer.get(p) for p in ps], cfg["min_conf"])
        texts.append(text)

    empty = [i for i, t in enumerate(texts) if not t]
    stats = {"cues": len(cues), "first_empty": len(empty), "retried": 0}
    if empty and cfg["retry_frames"] > 0:
        rnums = {i: retry_frames(cues[i]["start"], cues[i]["end"], fps, cfg["retry_frames"])
                 for i in empty}
        if extractor:
            extractor({n for ns in rnums.values() for n in ns} - done)
        rplan = {i: [frame_file(frames_dir, n) for n in ns] for i, ns in rnums.items()}
        raw = [p for ps in rplan.values() for p in ps if p.exists()]
        bins = binarizer(raw) if binarizer else {}
        log(f"  pótló kör: {len(empty)} üres cue, {len(raw)} képkocka nyersen"
            f"{f' + {len(bins)} binarizálva' if bins else ''}")
        recognizer.run(raw + list(bins.values()))
        for i, ps in rplan.items():
            cands = [recognizer.get(p) for p in ps] + [recognizer.get(bins[p]) for p in ps if p in bins]
            text, _ = best_candidate(cands, cfg["retry_min_conf"])
            if text:
                texts[i] = text
                stats["retried"] += 1
    recognizer.check()
    stats["empty"] = sum(1 for t in texts if not t)
    return texts, stats


# ── beállítások ────────────────────────────────────────────────────────────

def parse_bool_auto(value):
    v = str(value).strip().lower()
    if v in ("auto", ""):
        return None
    if v in ("1", "true", "yes", "igen", "on"):
        return True
    if v in ("0", "false", "no", "nem", "off"):
        return False
    raise ValueError("auto, 1 vagy 0 kell")


def engine_name(value):
    v = str(value).strip().lower()
    if v not in engines.ENGINES:
        raise ValueError(f"lehet: {', '.join(engines.ENGINES)}")
    return v


# name: (env kulcs, alapérték, típus, súgó, legkisebb érték)
SETTINGS = {
    "lang":           ("HARDSUB_OCR_LANG", DEFAULT_LANG, str,
                       "a beégetett felirat nyelve (chi, kor, jpn, tha, vie, eng…) — a kimenet "
                       "nevében is ez lesz (<név>.<lang>.ocr.srt)", None),
    "engine":         ("HARDSUB_OCR_ENGINE", "auto", engine_name,
                       "OCR-motor: auto (macOS: vision, máshol rapidocr), vision, rapidocr", None),
    "engine_lang":    ("HARDSUB_OCR_ENGINE_LANG", "", str,
                       "a motor saját nyelvkódja, ha a --lang leképezése nem jó "
                       "(Vision: pl. zh-Hant,zh-Hans; RapidOCR: pl. chinese_cht)", None),
    "top":            ("HARDSUB_OCR_TOP", "0.833", parse_edge,
                       "a felirat-sáv teteje: arány a kép magasságához (0–1) vagy pixel", None),
    "bottom":         ("HARDSUB_OCR_BOTTOM", "0.986", parse_edge,
                       "a felirat-sáv alja: arány a kép magasságához (0–1) vagy pixel", None),
    "fps":            ("HARDSUB_OCR_FPS", 4.0, float, "kivágott képkocka másodpercenként", 0.5),
    "min_conf":       ("HARDSUB_OCR_MIN_CONF", 0.0, float,
                       "a fő körben az elfogadás legkisebb megbízhatósága (0–1)", 0.0),
    "retry_min_conf": ("HARDSUB_OCR_RETRY_MIN_CONF", 0.5, float,
                       "a pótló körben az elfogadás legkisebb megbízhatósága (0–1)", 0.0),
    "retry_frames":   ("HARDSUB_OCR_RETRY_FRAMES", 8, int,
                       "a pótló körben cue-nként legfeljebb ennyi képkocka (0 = nincs pótló kör)", 0),
    "bin_threshold":  ("HARDSUB_OCR_BIN_THRESHOLD", 215, int,
                       "binarizálás küszöbe (0–255): e fölött számít a pixel fehér feliratnak", 0),
    "ad_extra":       ("HARDSUB_OCR_AD_EXTRA", "", str,
                       "további reklám-minta (regex, pl. 'abc|xyz'), a nyelv alaplistája mellé", None),
    "drop_latin":     ("HARDSUB_OCR_DROP_LATIN", "auto", parse_bool_auto,
                       "latin betűs / hosszú számsoros sor eldobása reklámként: auto (csak nem "
                       "latin írású nyelvnél), 1, 0", None),
}


def resolve(args, settings=SETTINGS):
    """kapcsoló > .env / környezet > alapérték — mint a hardsub-cover."""
    cfg = {}
    for name, (env, default, typ, _, minimum) in settings.items():
        val = getattr(args, name, None)
        src = "kapcsoló"
        if val is None and os.environ.get(env, "").strip():
            val, src = os.environ[env].strip(), ".env"
        if val is None:
            val, src = default, "alap"
        try:
            cfg[name] = typ(val)
        except ValueError as exc:
            sys.exit(f"Hibás érték: {env}={val!r} ({exc or typ.__name__})")
        if minimum is not None and cfg[name] < minimum:
            sys.exit(f"Hibás érték: {env}={val!r} (legalább {minimum} kell)")
        cfg[name + "_src"] = src
    cfg["lang"] = normalize_lang(cfg["lang"])
    if cfg["lang"] not in LANG_SCRIPT:
        sys.exit(f"HIBA: ismeretlen nyelvkód: {cfg['lang']} (lehet: {', '.join(sorted(LANG_SCRIPT))})")
    for name in ("min_conf", "retry_min_conf"):
        if cfg[name] > 1:
            sys.exit(f"Hibás érték: {settings[name][0]}={cfg[name]} (0 és 1 között legyen)")
    if cfg["bin_threshold"] > 255:
        sys.exit("HARDSUB_OCR_BIN_THRESHOLD 0 és 255 között legyen")
    if cfg["ad_extra"].strip():
        try:
            re.compile(cfg["ad_extra"])
        except re.error as exc:
            sys.exit(f"Hibás reklám-minta: HARDSUB_OCR_AD_EXTRA={cfg['ad_extra']!r} ({exc})")
    return cfg


# ── egy rész ───────────────────────────────────────────────────────────────

def process(video, ref, dest, recognizer, cfg):
    began = time.time()
    cues = read_cues(ref)
    width, height = video_size(video)
    y, h = band_pixels(cfg["top"], cfg["bottom"], height)
    print(f"  forrás: {ref} ({len(cues)} cue); sáv: {width}x{h} px, y={y}", flush=True)
    with tempfile.TemporaryDirectory(prefix="hardsub-ocr-") as tmp:
        frames = Path(tmp) / "frames"
        frames.mkdir()
        recognizer.reset()
        try:
            texts, stats = align(
                cues, frames, recognizer, cfg,
                binarizer=lambda ps: binarize(ps, tmp, cfg["bin_threshold"]),
                extractor=lambda ns: extract_frames(video, frames, cfg["fps"], y, h, ns))
        finally:
            recognizer.reset()   # a képkockák a mappával együtt törlődnek
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        write_srt(str(part), output_sections(cues, texts))
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    mins = (time.time() - began) / 60
    print(f"  → {dest}  ({stats['cues']} cue, üres: {stats['empty']} "
          f"[a fő kör után {stats['first_empty']}, pótolva {stats['retried']}], {mins:.1f} perc)",
          flush=True)
    return stats


# ── main ───────────────────────────────────────────────────────────────────

def build_parser():
    ap = argparse.ArgumentParser(
        description="Beégetett idegen nyelvű feliratból OCR-rel segédfelirat a forrás SRT "
                    "cue-ihoz igazítva — regiszter-támpontnak, nem fordítási forrásnak.")
    ap.add_argument("videos", nargs="+", help="videófájl(ok), pl. mp4 / mkv")
    ap.add_argument("--ref", help="a forrás SRT (csak egy videónál; alap: "
                                  "<ref-dir>/<videó neve>.<forrásnyelv>.srt, az angol az első)")
    ap.add_argument("--ref-dir", default=DEFAULT_REF_DIR,
                    help=f"itt keresi a forrás SRT-t (alap: {DEFAULT_REF_DIR})")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                    help=f"kimeneti mappa (alap: {DEFAULT_OUT_DIR})")
    ap.add_argument("--force", action="store_true", help="kész kimenet felülírása")
    for name, (env, default, _typ, hlp, _) in SETTINGS.items():
        # A típusellenőrzés a resolve()-ban van, hogy a .env értéke is átessen rajta.
        ap.add_argument("--" + name.replace("_", "-"), dest=name, default=None,
                        help=f"{hlp} [{env}, alap: {default}]")
    return ap


def main(argv=None):
    utf8_console()
    args = build_parser().parse_args(argv)
    load_dotenv()
    cfg = resolve(args)
    lang = cfg["lang"]
    print("Beállítások: " + ", ".join(f"{n}={cfg[n] if cfg[n] is not None else 'auto'} "
                                      f"({cfg[n + '_src']})" for n in SETTINGS), flush=True)
    videos = expand_patterns(args.videos)
    if args.ref and len(videos) > 1:
        sys.exit("HIBA: a --ref csak egy videóval együtt adható meg (több résznél a --ref-dir "
                 "mappából keresi a videók nevéhez illő forrást)")
    require_tools()

    # 1) minden videónál forrás és cél — a motort csak akkor indítjuk, ha van munka
    jobs, errors, targets = [], 0, {}
    for video in videos:
        if not Path(video).is_file():
            sys.stderr.write(f"HIBA: nincs ilyen fájl: {video}\n")
            errors += 1
            continue
        if args.ref:
            ref, err = Path(args.ref), None if Path(args.ref).is_file() else f"nincs ilyen fájl: {args.ref}"
        else:
            ref, err = find_ref(video, lang, args.ref_dir)
        if err:
            sys.stderr.write(f"\n{video}\n  HIBA: {err}\n")
            errors += 1
            continue
        dest = out_path(video, lang, args.out_dir)
        if dest.resolve() == ref.resolve():
            sys.stderr.write(f"\n{video}\n  HIBA: a kimenet a forrás SRT-re írna ({dest}) — más --lang "
                             "vagy --out-dir kell\n")
            errors += 1
            continue
        if dest in targets:
            sys.stderr.write(f"\n{video}\n  HIBA: ugyanarra a célra írna, mint {targets[dest]}: {dest} "
                             "— futtasd külön, más --out-dir mappával\n")
            errors += 1
            continue
        targets[dest] = video
        if dest.exists() and not args.force:
            print(f"\n{video}\n  KÉSZ, kihagyva: {dest} (--force felülírja)")
            continue
        jobs.append((video, ref, dest))

    # 2) OCR
    if jobs:
        try:
            engine = engines.create(cfg["engine"], lang, cfg["engine_lang"].strip() or None)
        except engines.EngineError as exc:
            sys.exit(f"HIBA: {exc}")
        print(f"\nOCR-motor: {engine.name} ({lang})", flush=True)

        def progress(done, total):
            if total > BATCH:
                print(f"    {done}/{total} kép", flush=True)

        recognizer = Recognizer(engine, LineFilter(lang, cfg["ad_extra"], cfg["drop_latin"]), progress)
        for video, ref, dest in jobs:
            print(f"\n{video}", flush=True)
            try:
                process(video, ref, dest, recognizer, cfg)
            except KeyboardInterrupt:
                sys.stderr.write("\nMegszakítva — a már kész részek megmaradtak.\n")
                return 1
            except (Fail, engines.EngineError) as exc:
                sys.stderr.write(f"  HIBA: {exc}\n")
                errors += 1
            except Exception as exc:  # noqa: BLE001 — egy rész hibája ne állítsa le az évadot
                sys.stderr.write(f"  HIBA: {(str(exc).splitlines() or [type(exc).__name__])[0][:200]}\n")
                errors += 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
