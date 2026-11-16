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

  # 4) rossz vagy hiányzó nyelvcímkénél (pl. a koreai hang „eng” címkét kapott):
  #    a sorszámot a --list mutatja, a --lang ilyenkor kötelező
  python addons/audio-asr/transcribe.py "Season 01"/*.mkv --track 1 --lang kor

A `*.mkv` mintát a script maga is kibontja (subtr.config.expand_patterns), így
Windowson (cmd, PowerShell) is működik.

Függőség: `ffmpeg` + `ffprobe` a PATH-on, a program `subtr` mappája és a
`mkv-subs` add-on (a programmal együtt jönnek), és a `faster-whisper` csomag
(`pip install faster-whisper`). A large-v3 modell (~3 GB) első futáskor
töltődik le. Kínainál az `opencc` (`pip install opencc-python-reimplemented`)
opcionális: ha megvan, a hagyományos írásjegyeket egyszerűsítettre váltja.

Kilépési kód: 0 siker (a már kész részek kihagyása is az), 1 hiba.
"""

import argparse
import functools
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# A sávlistázás, a nyelvkód-kezelés és a fájlminta-kibontás a mkv-subs add-onból
# (és azon át a subtr csomagból) jön — ugyanaz a kód listázza a felirat- és a
# hangsávokat, másolata nincs.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mkv-subs"))
from extract_subs import (  # noqa: E402
    Fail, describe, expand_patterns, find_tool, normalize_lang, probe_streams, require_tools,
    stem_without_lang, utf8_console)
from subtr.config import ASR_SUFFIX  # noqa: E402  (a `.asr` jelölés egyetlen helye)

# Pipeline-kód → Whisper-nyelvkód (ISO 639-1). Ami nincs itt, azt a Whisper
# nem kapja meg nyelvként — ilyenkor a --lang kötelező (lásd whisper_lang).
WHISPER_LANGS = {
    "eng": "en", "ger": "de", "fre": "fr", "spa": "es", "por": "pt",
    "ita": "it", "rus": "ru", "pol": "pl", "tur": "tr", "chi": "zh",
    "jpn": "ja", "kor": "ko", "vie": "vi", "ind": "id", "may": "ms",
    "tha": "th", "hin": "hi", "ara": "ar",
}

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
        # Egyszerűsített és hagyományos alakban is: az opencc opcionális, nélküle
        # a Whisper hagyományos írásjegyes sorai változatlanul érkeznek ide.
        "请不吝点赞订阅转发打赏支持明镜与点点栏目", "請不吝點贊訂閱轉發打賞支持明鏡與點點欄目",
        "点赞订阅转发打赏支持明镜与点点栏目", "點贊訂閱轉發打賞支持明鏡與點點欄目",
        "谢谢观看", "謝謝觀看", "感谢观看", "感謝觀看",
        "字幕由Amaraorg社区提供", "字幕由Amaraorg社區提供", "字幕by索兰娅", "字幕by索蘭婭",
        "请订阅我的频道", "請訂閱我的頻道",
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

def whisper_lang(lang):
    """A Whisper nyelvkódja, vagy None, ha nem ismerjük."""
    return WHISPER_LANGS.get(normalize_lang(lang))


# ── hangsávok ──────────────────────────────────────────────────────────────

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
            untagged = [t for t in tracks if t["lang"] in ("", "und")]
            if len(tracks) == 1 and untagged:
                return tracks[0], None
            if len(untagged) > 1:
                # Nem az a baj, hogy nincs ilyen nyelvű sáv, hanem hogy a címkékből
                # nem derül ki, melyik az: ezt csak a sorszám dönti el.
                return None, (f"{len(untagged)} hangsáv címke nélküli, nem tudni, melyik a „{lang}” — "
                              "válassz a --track kapcsolóval (a sorszámot a --list mutatja)")
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
    stem = stem_without_lang(video)   # "x.kor.mkv" → ne legyen "x.kor.kor.asr.srt"
    return Path(out_dir) / f"{stem}.{lang}{ASR_SUFFIX}.srt"


# ── szöveg-utófeldolgozás ──────────────────────────────────────────────────

_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


def _norm(text):
    return _PUNCT.sub("", text).lower()


# A lista normalizált alakja, nyelvenként egyszer kiszámolva (nem feliratonként).
_HALLUCINATION_KEYS = {lang: frozenset(_norm(h) for h in items)
                       for lang, items in HALLUCINATIONS.items()}


def is_hallucination(text, lang):
    key = _norm(text)
    return not key or key in _HALLUCINATION_KEYS.get(lang, ())


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


@functools.lru_cache(maxsize=None)
def chinese_converter(lang):
    """Hagyományos → egyszerűsített írásjegy-váltó, ha az opencc telepítve van.
    Nyelvenként egyszer épül fel, nem részenként."""
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
    cmd = [find_tool("ffmpeg"), "-nostdin", "-v", "error", "-i", str(video),
           "-map", f"0:{track_index}", "-ac", "1", "-ar", str(SAMPLE_RATE),
           "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def first_line(exc):
    """A hiba első sora röviden; üres üzenetnél a hiba típusa."""
    return (str(exc).splitlines() or [type(exc).__name__])[0][:120]


# A float16 a gyors mód, de a régebbi NVIDIA-kártyák (GTX 10xx/16xx) nem tudják:
# ott a float32 még mindig a kártyán fut, nem a processzoron.
CUDA_CANDIDATES = [("cuda", "float16"), ("cuda", "float32")]


def device_candidates(device):
    """(device, compute_type) próbálási sorrend."""
    cpu = ("cpu", "int8")
    if device == "cpu":
        return [cpu]
    if device == "cuda":
        return [*CUDA_CANDIDATES, cpu]
    if device == "mps":
        return [("mps", "float16"), cpu]
    # auto
    out = []
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            out.extend(CUDA_CANDIDATES)
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
            print(f"  {dev} ({ctype}) nem elérhető ({first_line(exc)}), próbálom a következőt",
                  flush=True)
    raise Fail(f"a modell nem tölthető be: {first_line(last) if last else 'nincs próbálható eszköz'}")


def transcribe(model, video, track, lang, dest, beam):
    audio = decode_audio(video, track["index"])
    duration = len(audio) / SAMPLE_RATE
    segments, _info = model.transcribe(
        audio, language=whisper_lang(lang), beam_size=beam, vad_filter=True,
        condition_on_previous_text=False)
    convert = chinese_converter(lang)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    began = time.time()
    keep = SegmentFilter(lang)
    n = 0
    triples = ((seg.start, seg.end, seg.text) for seg in segments)
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            for start, end, text in filter_segments(triples, keep, convert):
                n += 1
                fh.write(srt_block(n, start, end, text))
                fh.flush()
                if n % 100 == 0:
                    print(f"  {n} felirat, {end / 60:.1f}/{duration / 60:.1f} perc, "
                          f"{(time.time() - began) / 60:.1f} perc telt el", flush=True)
    except BaseException:
        # Hiba vagy megszakítás (Ctrl+C): a félkész fájlból nem lehet folytatni,
        # a rész a következő futáskor elölről indul — ne maradjon szemét utána.
        tmp.unlink(missing_ok=True)
        raise
    if n == 0:
        # Üres átiratot nem mentünk késznek: a következő futás „KÉSZ, kihagyva”
        # üzenettel átugrana egy valójában el sem készült részt.
        tmp.unlink(missing_ok=True)
        raise Fail("egyetlen felirat sem készült — néma vagy rossz hangsáv? "
                   "(--list mutatja a sávokat, --track választ)")
    os.replace(tmp, dest)
    mins = (time.time() - began) / 60
    print(f"  → {dest}  ({n} felirat, {keep.dropped} eldobva, {mins:.1f} perc)", flush=True)


# ── main ───────────────────────────────────────────────────────────────────

def main():
    utf8_console()

    ap = argparse.ArgumentParser(
        description="A videó hangsávjának gépi átirata (Whisper) eredeti nyelvű SRT-be — "
                    "regiszter-támpontnak, nem fordítási forrásnak.")
    ap.add_argument("videos", nargs="+", help="videófájl(ok), pl. mkv")
    ap.add_argument("--lang", help="a hang nyelve (kor, jpn, chi… vagy ko/ja/zh); "
                                   "több hangsávnál ez választ")
    ap.add_argument("--title", help="több azonos nyelvű hangsávnál a cím szűrője")
    ap.add_argument("--track", type=int,
                    help="a hangsáv stream-sorszáma (a --list mutatja); a nyelvcímkét "
                         "figyelmen kívül hagyja — rossz címkés sávhoz; a --lang kötelező mellé")
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

    if args.track is not None and not args.lang:
        # A --track épp akkor kell, amikor a sáv címkéje rossz vagy hiányzik —
        # a nyelvet ilyenkor nem vehetjük csendben ugyanabból a címkéből.
        sys.exit("HIBA: a --track mellé add meg a hang nyelvét is a --lang kapcsolóval (pl. --lang kor)")
    require_tools()
    lang_arg = normalize_lang(args.lang) if args.lang else None
    if lang_arg and not whisper_lang(lang_arg):
        sys.exit(f"HIBA: ismeretlen nyelvkód: {args.lang} "
                 f"(lehet: {', '.join(sorted(WHISPER_LANGS))})")

    # 1) minden videónál sávválasztás — a modellt csak akkor töltjük be, ha van mit átírni
    jobs, errors = [], 0
    targets = {}   # cél → forrásvideó: két bemenet ne írjon ugyanarra a fájlra
    for video in expand_patterns(args.videos):
        if not Path(video).is_file():
            sys.stderr.write(f"HIBA: nincs ilyen fájl: {video}\n")
            errors += 1
            continue
        tracks = probe_streams(video, "a")
        if tracks is None:
            errors += 1
            continue
        print(f"\n{video}")
        if not tracks:
            sys.stderr.write("  HIBA: nincs hangsáv\n")
            errors += 1
            continue
        if args.list:
            describe(tracks, subtitles=False)
            continue
        track, err = pick_track(tracks, lang_arg, args.title, args.track)
        if err:
            describe(tracks, subtitles=False)
            sys.stderr.write(f"  HIBA: {err}\n")
            errors += 1
            continue
        lang = lang_arg or track["lang"]
        if not whisper_lang(lang):
            describe([track], subtitles=False)
            sys.stderr.write(f"  HIBA: a sáv nyelve ismeretlen („{lang or '?'}”) — "
                             "add meg a --lang kapcsolót\n")
            errors += 1
            continue
        dest = out_path(video, lang, args.out_dir)
        source = Path(video).resolve()
        if dest in targets:
            if targets[dest] == source:
                print("  kétszer megadva, egyszer írom át")
            else:
                # Pl. két évad azonos nevű része: a második felülírná az elsőt,
                # két teljes átirat árán. Írás ELŐTT fogjuk meg.
                sys.stderr.write(f"  HIBA: ugyanarra a célra írna, mint {targets[dest]}: {dest} "
                                 "— futtasd külön, más --out-dir mappával\n")
                errors += 1
            continue
        targets[dest] = source
        if dest.exists() and not args.force:
            print(f"  KÉSZ, kihagyva: {dest} (--force felülírja)")
            continue
        print(f"  stream {track['index']} ({lang}) → {dest}")
        jobs.append((video, track, lang, dest))

    # 2) átirat
    if jobs:
        if any(lang == "chi" for _, _, lang, _ in jobs) and chinese_converter("chi") is None:
            print("\n(opencc nincs telepítve vagy nem indul — a kínai írásjegyek változatlanok)")
        try:
            model, device = load_model(args.model, args.device, args.threads)
        except Fail as exc:
            sys.exit(f"HIBA: {exc}")
        for video, track, lang, dest in jobs:
            print(f"\n{video}", flush=True)
            try:
                try:
                    transcribe(model, video, track, lang, dest, args.beam)
                except RuntimeError as exc:
                    if device == "cpu":
                        raise
                    # A videókártya hibája (hiányzó CUDA-fájl, kevés videomemória)
                    # sokszor csak az átirat közben jön elő, nem a betöltéskor, és a
                    # CTranslate2 RuntimeError-ként adja: a hátralévő részek
                    # processzoron mennek tovább, ez a rész elölről. Más hiba
                    # (fájlírás, lemez, memória) NEM ide tartozik — azt az újrafuttatás
                    # nem javítaná, csak megismételné.
                    sys.stderr.write(f"  {device} hiba futás közben "
                                     f"({first_line(exc)}) — processzorra váltok\n")
                    # Ha a processzoros betöltés is elbukik, az Fail: ez a rész hibás
                    # lesz, de az évad többi része megy tovább.
                    model, device = load_model(args.model, "cpu", args.threads)
                    transcribe(model, video, track, lang, dest, args.beam)
            except subprocess.CalledProcessError as exc:
                sys.stderr.write(f"  ffmpeg hiba: {exc.stderr.decode('utf-8', 'replace').strip()}\n")
                errors += 1
            except KeyboardInterrupt:
                sys.stderr.write("\nMegszakítva — ez a rész a következő futáskor elölről indul; "
                                 "a már kész részek megmaradtak.\n")
                return 1
            except Exception as exc:  # noqa: BLE001 — egy rész hibája ne állítsa le az évadot
                sys.stderr.write(f"  HIBA: {first_line(exc)}\n")
                errors += 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
