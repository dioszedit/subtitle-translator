#!/usr/bin/env python3
"""
A videó hangsávjának gépi átirata SRT-be (Whisper, helyben futtatva).

Mire jó?
  Koreai, japán, kínai… sorozatoknál a beszédszint (koreai -요/반말, japán
  です/plain) a megszólítási regiszter legerősebb bizonyítéka — az angol
  `you` ezt elfedi. Ha a kiadásban NINCS eredeti nyelvű feliratsáv, a hang az
  egyetlen forrás. Ez a script abból készít eredeti nyelvű „feliratot”.

  Az eredmény TÁMPONT, nem fordítási forrás: félrehallások, szétesett vagy
  összevont mondatok vannak benne, és nem tudja, ki beszél. A regiszterhez és
  a névalakokhoz jó, a fordításhoz nem.

Kimenet:
  `input/asr/Sorozat - S01E01.kor.asr.srt`
  A `.asr` tag jelzi, hogy gépi átirat. A pipeline a nyelvet így is felismeri
  (`kor`), a `register` pedig figyelmezteti a modellt a félrehallásokra.

Használat:
  # 1) milyen hangsávok vannak? (nem ír semmit)
  python addons/audio-asr/transcribe.py "Season 01/Sorozat - S01E01.mkv" --list

  # 2) átirat — egy hangsávnál a nyelv a sáv címkéjéből jön
  python addons/audio-asr/transcribe.py "Season 01"/*.mkv

  # 3) több hangsávnál (pl. eredeti + szinkron) a nyelvet meg kell adni
  python addons/audio-asr/transcribe.py "Season 01"/*.mkv --lang kor

  # 4) rossz nyelvcímkés sávnál (pl. a koreai hang „eng” címkét kapott)
  python addons/audio-asr/transcribe.py "Season 01"/*.mkv --track 1 --lang kor

A `*.mkv` mintát a script maga is kibontja (subtr.config.expand_patterns), így
Windowson (cmd, PowerShell) is működik.

Függőség: `ffmpeg` + `ffprobe` a PATH-on, és a `faster-whisper` csomag
(`pip install faster-whisper`). A large-v3 modell (~3 GB) első futáskor
töltődik le. Kínainál az `opencc` (`pip install opencc-python-reimplemented`)
opcionális: ha megvan, a hagyományos írásjegyeket egyszerűsítettre váltja.

Kilépési kód: 0 siker (a már kész részek kihagyása is az), 1 hiba.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# A pipeline nyelvkód-rövidítései és a fájlminta-kibontás a subtr csomagból
# jönnek — másolatuk SEHOL nincs. Az add-on a programmal együtt települ; ha
# valaki mégis a subtr nélkül futtatja, a tartalék csak annyi, hogy a script ne
# omoljon össze: a rövid kódok (`ko`) helyett a hosszú kell (`kor`), és a
# `*.mkv` minta nem bomlik ki.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from subtr.config import SOURCE_LANG_ALIASES as _ALIASES, expand_patterns
except Exception:  # noqa: BLE001 — subtr nélkül: lásd fent
    _ALIASES, expand_patterns = {}, list

# Pipeline-kód → Whisper-nyelvkód (ISO 639-1). Ami nincs itt, azt a Whisper
# nem kapja meg nyelvként — ilyenkor a --lang kötelező (lásd whisper_lang).
WHISPER_LANGS = {
    "eng": "en", "ger": "de", "fre": "fr", "spa": "es", "por": "pt",
    "ita": "it", "rus": "ru", "pol": "pl", "tur": "tr", "chi": "zh",
    "jpn": "ja", "kor": "ko", "vie": "vi", "ind": "id", "may": "ms",
    "tha": "th", "hin": "hi", "ara": "ar",
}

ASR_TAG = "asr"
DEFAULT_OUT_DIR = os.path.join("input", "asr")
SAMPLE_RATE = 16000

# A Whisper ismert „hallucinációi”: zene vagy csend alatt a tanítóanyag
# (YouTube-feliratok) záró sorait írja ki. Csak TELJES egyezést dobunk el, hogy
# valódi mondat ne vesszen el; az írásjeleket és szóközöket az összevetés előtt
# lehagyjuk (lásd _norm).
HALLUCINATIONS = {
    "kor": [
        "시청해주셔서감사합니다", "시청해주셔서고맙습니다", "구독과좋아요부탁드립니다",
        "구독과좋아요", "구독좋아요알림설정", "다음영상에서만나요",
        "MBC뉴스이덕영입니다",
        # A sima „감사합니다” (köszönöm) NINCS itt: a párbeszédben is gyakori.
    ],
    "jpn": [
        "ご視聴ありがとうございました", "ご視聴ありがとうございます",
        "チャンネル登録お願いします", "チャンネル登録よろしくお願いします",
    ],
    "chi": [
        "请不吝点赞订阅转发打赏支持明镜与点点栏目", "谢谢观看", "感谢观看",
        "字幕由Amaraorg社区提供", "字幕by索兰娅", "请订阅我的频道", "點贊訂閱轉發打賞支持明鏡與點點欄目",
    ],
    "eng": [
        "thanksforwatching", "thankyouforwatching", "pleasesubscribe",
        "subtitlesbytheamaraorgcommunity",
    ],
}
# Ha egy szegmens egymás után ennél többször jön, az beragadás (loop): az első
# MAX_REPEAT darabot megtartjuk, a többit eldobjuk.
MAX_REPEAT = 2


# ── nyelv ──────────────────────────────────────────────────────────────────

def normalize_lang(value):
    """Nyelvkód a pipeline alakjára (`ko` → `kor`). Ismeretlen kód marad."""
    if not value:
        return ""
    key = str(value).strip().lower()
    return _ALIASES.get(key, key)


def whisper_lang(lang):
    """A Whisper nyelvkódja, vagy None, ha nem ismerjük."""
    return WHISPER_LANGS.get(normalize_lang(lang))


# ── hangsávok ──────────────────────────────────────────────────────────────

def require_tools():
    missing = [t for t in ("ffprobe", "ffmpeg") if not shutil.which(t)]
    if missing:
        sys.exit(f"HIBA: nincs a PATH-on: {', '.join(missing)} "
                 "(macOS: brew install ffmpeg; Windows: winget install ffmpeg)")


def probe_audio(video):
    """A videó hangsávjai: [{index, lang, title, codec, channels, default}]."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=index,codec_name,channels:stream_tags=language,title"
           ":stream_disposition=default",
           "-of", "json", str(video)]
    try:
        raw = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             check=True).stdout
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"  ffprobe hiba: {exc.stderr.strip()}\n")
        return None
    return parse_probe(raw)


def parse_probe(raw):
    out = []
    for st in json.loads(raw or "{}").get("streams", []):
        tags = st.get("tags") or {}
        disp = st.get("disposition") or {}
        out.append({
            "index": st.get("index"),
            "lang": normalize_lang(tags.get("language")),
            "title": tags.get("title") or "",
            "codec": (st.get("codec_name") or "").lower(),
            "channels": st.get("channels"),
            "default": bool(disp.get("default")),
        })
    return out


def describe(tracks):
    for t in tracks:
        flags = ["default"] if t["default"] else []
        extra = f"  [{', '.join(flags)}]" if flags else ""
        title = f"  „{t['title']}”" if t["title"] else ""
        lang = t["lang"] or "?"
        ch = f"{t['channels']}ch" if t["channels"] else ""
        print(f"  stream {t['index']:>2}  {lang:<4} {t['codec']:<8} {ch:<4}{title}{extra}")


def pick_track(tracks, lang, title_filter, index=None):
    """A használandó hangsáv. (sáv, None) siker, (None, hibaüzenet) ha nem dönthető el.

    Nem tippel: ha több sáv közül nem egyértelmű, melyik kell, hibát ad, mert
    egy rossz nyelvű sáv átirata csendben használhatatlan.

    index: a stream sorszáma (`--track`) — a nyelvcímkét figyelmen kívül
    hagyja, ezzel választható ki a rosszul címkézett sáv is.
    """
    if index is not None:
        hits = [t for t in tracks if t["index"] == index]
        if not hits:
            return None, f"nincs {index}. sorszámú hangsáv"
        return hits[0], None
    hits = tracks
    if lang:
        hits = [t for t in hits if t["lang"] == lang]
        if not hits:
            # Címke nélküli egyetlen sáv: a felhasználó megmondta a nyelvét.
            if len(tracks) == 1 and tracks[0]["lang"] in ("", "und"):
                return tracks[0], None
            return None, f"nincs „{lang}” címkéjű hangsáv"
    if title_filter:
        needle = title_filter.lower()
        hits = [t for t in hits if needle in t["title"].lower()]
        if not hits:
            return None, f"nincs „{title_filter}” című hangsáv"
    if not hits:
        return None, "nincs hangsáv"
    if len(hits) > 1:
        what = f"„{lang}” " if lang else ""
        hint = "szűkítsd a --title kapcsolóval" if lang else "add meg a --lang kapcsolót"
        return None, f"{len(hits)} db {what}hangsáv van — {hint}"
    return hits[0], None


# ── fájlnév ────────────────────────────────────────────────────────────────

def out_path(video, lang, out_dir):
    """`Season 01/X - S01E01.mkv` → `<out_dir>/X - S01E01.kor.asr.srt`."""
    stem = Path(video).stem
    base, dot, tag = stem.rpartition(".")
    if dot and base and normalize_lang(tag) in WHISPER_LANGS:
        stem = base   # "x.kor.mkv" → ne legyen "x.kor.kor.asr.srt"
    return Path(out_dir) / f"{stem}.{lang}.{ASR_TAG}.srt"


# ── szöveg-utófeldolgozás ──────────────────────────────────────────────────

_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


def _norm(text):
    return _PUNCT.sub("", text).lower()


def is_hallucination(text, lang):
    key = _norm(text)
    if not key:
        return True
    return any(key == _norm(h) for h in HALLUCINATIONS.get(lang, ()))


class SegmentFilter:
    """Szegmensenkénti szűrő: üres, ismert hallucináció, beragadás.

    Állapotot tart (az előző szegmens), mert a Whisper menet közben adja a
    szegmenseket, és a beragadás csak az egymás utániakból látszik.
    """

    def __init__(self, lang):
        self.lang = lang
        self.dropped = 0
        self._last_key = None
        self._run = 0

    def __call__(self, text):
        """A megtartandó (normalizált szóközű) szöveg, vagy None, ha eldobjuk."""
        text = " ".join(text.split())
        if is_hallucination(text, self.lang):
            # Az eldobott sor (zene alatti hallucináció) megszakítja a sorozatot:
            # az előtte és utána álló azonos sor nem egy beragadás.
            self.dropped += 1
            self._last_key, self._run = None, 0
            return None
        key = _norm(text)
        self._run = self._run + 1 if key == self._last_key else 1
        self._last_key = key
        if self._run > MAX_REPEAT:
            self.dropped += 1
            return None
        return text


def filter_segments(segments, keep, convert=None):
    """(start, end, text) hármasok: írásjegy-váltás (ha van), majd szűrés.

    Ez az egyetlen út — a valódi futás és a tesztek is ezen mennek át.
    """
    for start, end, text in segments:
        text = keep(convert(text) if convert else text)
        if text:
            yield start, end, text


def clean_segments(segments, lang, convert=None):
    """A teljes lista szűrése. Visszaad: (megtartottak, eldobottak száma)."""
    keep = SegmentFilter(lang)
    kept = list(filter_segments(segments, keep, convert))
    return kept, keep.dropped


def stamp(t):
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_block(n, start, end, text):
    return f"{n}\n{stamp(start)} --> {stamp(end)}\n{text}\n\n"


def chinese_converter(lang):
    """Hagyományos → egyszerűsített írásjegy-váltó, ha az opencc telepítve van."""
    if lang != "chi":
        return None
    try:
        import opencc
    except ImportError:
        return None
    for config_name in ("t2s", "t2s.json"):   # a két opencc-csomag más nevet vár
        try:
            return opencc.OpenCC(config_name).convert
        except Exception:  # noqa: BLE001 — hibás telepítésnél átalakítás nélkül megyünk tovább
            continue
    return None


# ── Whisper ────────────────────────────────────────────────────────────────

def decode_audio(video, track_index):
    """A hangsáv 16 kHz mono float32-ként, ffmpeggel dekódolva.

    Nem a faster-whisper saját (PyAV-os) betöltőjét használjuk: az egy
    PyAV-verzióeltérésnél azonnal elhasalt, az ffmpeg viszont úgyis kell.
    """
    import numpy as np
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
           "-map", f"0:{track_index}", "-ac", "1", "-ar", str(SAMPLE_RATE),
           "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def device_candidates(device):
    """(device, compute_type) próbálási sorrend."""
    cpu = ("cpu", "int8")
    if device == "cpu":
        return [cpu]
    if device == "cuda":
        return [("cuda", "float16"), cpu]
    if device == "mps":
        return [("mps", "float16"), cpu]
    # auto
    out = []
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            out.append(("cuda", "float16"))
    except Exception:
        pass
    if sys.platform == "darwin":
        out.append(("mps", "float16"))
    out.append(cpu)
    return out


def load_model(name, device, threads):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("HIBA: nincs telepítve a faster-whisper (pip install faster-whisper)")
    last = None
    for dev, ctype in device_candidates(device):
        try:
            kwargs = {"device": dev, "compute_type": ctype}
            if dev == "cpu":
                kwargs["cpu_threads"] = threads
            model = WhisperModel(name, **kwargs)
            print(f"Modell: {name}, eszköz: {dev} ({ctype})", flush=True)
            return model, dev
        except Exception as exc:  # noqa: BLE001 — a következő eszközre váltunk
            last = exc
            print(f"  {dev} nem elérhető ({str(exc).splitlines()[0][:120]}), próbálom a következőt",
                  flush=True)
    sys.exit(f"HIBA: a modell nem tölthető be: {last}")


def transcribe(model, video, track, lang, dest, beam):
    audio = decode_audio(video, track["index"])
    duration = len(audio) / SAMPLE_RATE
    segments, _info = model.transcribe(
        audio, language=whisper_lang(lang), beam_size=beam, vad_filter=True,
        condition_on_previous_text=False)
    convert = chinese_converter(lang)
    if lang == "chi" and convert is None:
        print("  (opencc nincs telepítve vagy nem indul — a kínai írásjegyek változatlanok)",
              flush=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    began = time.time()
    keep = SegmentFilter(lang)
    n = 0
    triples = ((seg.start, seg.end, seg.text) for seg in segments)
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for start, end, text in filter_segments(triples, keep, convert):
            n += 1
            fh.write(srt_block(n, start, end, text))
            fh.flush()
            if n % 100 == 0:
                print(f"  {n} felirat, {end / 60:.1f}/{duration / 60:.1f} perc, "
                      f"{(time.time() - began) / 60:.1f} perc telt el", flush=True)
    os.replace(tmp, dest)
    mins = (time.time() - began) / 60
    print(f"  → {dest}  ({n} felirat, {keep.dropped} eldobva, {mins:.1f} perc)", flush=True)


# ── main ───────────────────────────────────────────────────────────────────

def main():
    for stream in (sys.stdout, sys.stderr):   # Windows-konzolon se haljon el a koreain
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="A videó hangsávjának gépi átirata (Whisper) eredeti nyelvű SRT-be — "
                    "regiszter-támpontnak, nem fordítási forrásnak.")
    ap.add_argument("videos", nargs="+", help="videófájl(ok), pl. mkv")
    ap.add_argument("--lang", help="a hang nyelve (kor, jpn, chi… vagy ko/ja/zh); "
                                   "több hangsávnál ez választ")
    ap.add_argument("--title", help="több azonos nyelvű hangsávnál a cím szűrője")
    ap.add_argument("--track", type=int,
                    help="a hangsáv stream-sorszáma (a --list mutatja); a nyelvcímkét "
                         "figyelmen kívül hagyja — rossz címkés sávhoz, a --lang-gal együtt")
    ap.add_argument("--list", action="store_true",
                    help="csak a hangsávok listázása, átirat nélkül")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                    help=f"kimeneti mappa (alap: {DEFAULT_OUT_DIR})")
    ap.add_argument("--model", default="large-v3", help="Whisper-modell (alap: large-v3)")
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"],
                    help="hol fusson (alap: auto — NVIDIA-kártya, Macen a grafikus "
                         "gyorsító, különben processzor)")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 4,
                    help="processzorszálak CPU-n (alap: mind)")
    ap.add_argument("--beam", type=int, default=5, help="beam size (alap: 5)")
    ap.add_argument("--force", action="store_true", help="kész átirat felülírása")
    args = ap.parse_args()

    require_tools()
    lang_arg = normalize_lang(args.lang) if args.lang else None
    if lang_arg and not whisper_lang(lang_arg):
        sys.exit(f"HIBA: ismeretlen nyelvkód: {args.lang} "
                 f"(lehet: {', '.join(sorted(WHISPER_LANGS))})")

    # 1) minden videónál sávválasztás — a modellt csak akkor töltjük be, ha van mit átírni
    jobs, errors = [], 0
    for video in expand_patterns(args.videos):
        if not Path(video).is_file():
            sys.stderr.write(f"HIBA: nincs ilyen fájl: {video}\n")
            errors += 1
            continue
        tracks = probe_audio(video)
        if tracks is None:
            errors += 1
            continue
        print(f"\n{video}")
        if not tracks:
            sys.stderr.write("  HIBA: nincs hangsáv\n")
            errors += 1
            continue
        if args.list:
            describe(tracks)
            continue
        track, err = pick_track(tracks, lang_arg, args.title, args.track)
        if err:
            describe(tracks)
            sys.stderr.write(f"  HIBA: {err}\n")
            errors += 1
            continue
        lang = lang_arg or track["lang"]
        if not whisper_lang(lang):
            describe([track])
            sys.stderr.write(f"  HIBA: a sáv nyelve ismeretlen („{lang or '?'}”) — "
                             "add meg a --lang kapcsolót\n")
            errors += 1
            continue
        dest = out_path(video, lang, args.out_dir)
        if dest.exists() and not args.force:
            print(f"  KÉSZ, kihagyva: {dest} (--force felülírja)")
            continue
        print(f"  stream {track['index']} ({lang}) → {dest}")
        jobs.append((video, track, lang, dest))

    # 2) átirat
    if jobs:
        model, device = load_model(args.model, args.device, args.threads)
        for video, track, lang, dest in jobs:
            print(f"\n{video}", flush=True)
            try:
                try:
                    transcribe(model, video, track, lang, dest, args.beam)
                except (subprocess.CalledProcessError, KeyboardInterrupt):
                    raise
                except Exception as exc:  # noqa: BLE001
                    if device == "cpu":
                        raise
                    # A videókártya hibája (hiányzó CUDA-fájl, kevés memória) sokszor
                    # csak az átirat közben jön elő, nem a betöltéskor: a hátralévő
                    # részek processzoron mennek tovább, ez a rész elölről.
                    sys.stderr.write(f"  {device} hiba futás közben "
                                     f"({str(exc).splitlines()[0][:120]}) — processzorra váltok\n")
                    model, device = load_model(args.model, "cpu", args.threads)
                    transcribe(model, video, track, lang, dest, args.beam)
            except subprocess.CalledProcessError as exc:
                sys.stderr.write(f"  ffmpeg hiba: {exc.stderr.decode('utf-8', 'replace').strip()}\n")
                errors += 1
            except KeyboardInterrupt:
                sys.stderr.write("\nMegszakítva — a félkész átirat a .part fájlban maradt.\n")
                return 1
            except Exception as exc:  # noqa: BLE001 — egy rész hibája ne állítsa le az évadot
                sys.stderr.write(f"  HIBA: {exc}\n")
                errors += 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
