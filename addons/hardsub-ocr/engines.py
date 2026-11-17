"""OCR-motorok a hardsub-ocr add-onhoz.

Egy motor egyetlen dolgot tud: képfájlok listájából soronkénti
(szöveg, megbízhatóság) párokat ad, a bemenet sorrendjében:

    engine.recognize([kép1, kép2, …]) -> [[(szöveg, conf), …] vagy None, …]

A None azt jelzi, hogy az a kép nem volt olvasható. Minden más (melyik képkocka
kell, mi a reklám, melyik jelölt nyer, SRT-írás) az ocr_subs.py motorfüggetlen
magjában van — a tesztek ott egy hamis motort adnak át.

- `vision`: macOS beépített szövegfelismerője (Vision). Nem kell telepíteni
  semmit, csak a Swift-fordítót (Xcode Command Line Tools). A vocr.swift
  forrást első futáskor lefordítja a felhasználói cache-mappába, és csak akkor
  fordítja újra, ha a forrás (vagy a fordító verziója) változott.
- `rapidocr`: bármely rendszeren (Windows, Linux, macOS), a `rapidocr` és az
  `onnxruntime` csomaggal (`pip install -e ".[ocr]"`). Lusta import: csak akkor
  töltődik be, ha ezt a motort választod.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A külső programok futtatása (UTF-8 kimenet) a mkv-subs közös run_tool-ja.
sys.path.insert(0, str(HERE.parent / "mkv-subs"))
from extract_subs import run_tool as _run  # noqa: E402
SWIFT_SOURCE = HERE / "vocr.swift"

ENGINES = ("auto", "vision", "rapidocr")


class EngineError(Exception):
    """A motor nem indítható (hiányzó csomag vagy fordító) — a futás megáll."""


def pick_engine(name, platform=None):
    """`auto` → macOS-en vision, máshol rapidocr; a többi név változatlan."""
    platform = platform or sys.platform
    if name == "auto":
        return "vision" if platform == "darwin" else "rapidocr"
    return name


def create(name, lang, engine_lang=None):
    """A választott motor példánya. Hiányzó feltételnél EngineError.

    lang: pipeline-nyelvkód (chi, kor, eng…); engine_lang: a motor saját
    nyelvkódja, ha a leképezést felül akarod írni (pl. Visionnél
    `zh-Hant,zh-Hans` hagyományos kínaihoz, RapidOCR-nél `chinese_cht`).
    """
    name = pick_engine(name)
    if name == "vision":
        return VisionEngine(lang, engine_lang)
    if name == "rapidocr":
        return RapidOcrEngine(lang, engine_lang)
    raise EngineError(f"ismeretlen OCR-motor: {name} (lehet: {', '.join(ENGINES)})")


# ── macOS Vision ───────────────────────────────────────────────────────────

# Pipeline-kód → Vision-nyelv. A Vision ténylegesen ismert nyelveit a segéd
# `--supported` módja adja meg (macOS-verziónként bővülhet); ami itt nincs,
# vagy a gép Vision-je nem ismeri, arra érthető hibát adunk.
VISION_LANGS = {
    "chi": "zh-Hans", "jpn": "ja-JP", "kor": "ko-KR", "tha": "th-TH", "vie": "vi-VT",
    "eng": "en-US", "ger": "de-DE", "fre": "fr-FR", "spa": "es-ES", "por": "pt-BR",
    "ita": "it-IT", "rus": "ru-RU", "pol": "pl-PL", "tur": "tr-TR", "ind": "id-ID",
    "may": "ms-MY", "ara": "ar-SA", "hin": "hi-IN",
}


def cache_dir():
    """A lefordított segédprogram helye: a felhasználói cache-mappa.

    Nem a repóba kerül: így nem kell .gitignore-bejegyzés, csak olvasható
    programmappánál is működik, és több munkapéldány (klón) is ugyanazt a
    fordítást használja. Felülírható: HARDSUB_OCR_CACHE_DIR.
    """
    override = os.environ.get("HARDSUB_OCR_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "subtitle-translator" / "hardsub-ocr"


def find_swiftc():
    """A Swift-fordító útvonala, vagy EngineError a telepítési tanáccsal.

    Az `xcrun --find`-ot kérdezzük, nem a PATH-t: a /usr/bin/swiftc a Command
    Line Tools nélkül is ott van, csak egy telepítő ablakot dob fel futáskor.
    """
    try:
        r = _run(["xcrun", "--find", "swiftc"])
    except FileNotFoundError:
        r = None
    path = (r.stdout.strip() if r and r.returncode == 0 else "")
    if not path or not Path(path).exists():
        raise EngineError("nincs Swift-fordító (swiftc) — a Vision-motorhoz az Xcode Command "
                          "Line Tools kell: xcode-select --install  (vagy válaszd a "
                          "--engine rapidocr motort)")
    return path


def binary_path(source=SWIFT_SOURCE, compiler_id=""):
    """A lefordított program neve a forrás (és a fordító) ujjlenyomatával:
    ha bármelyik változik, új fájlnév → újrafordítás; a régi magától kimarad."""
    digest = hashlib.sha256(source.read_bytes() + compiler_id.encode()).hexdigest()[:12]
    return cache_dir() / f"vocr-{digest}"


def build_vision_helper():
    """A vocr.swift lefordítása, ha még nincs kész példány. -> a program útvonala."""
    swiftc = find_swiftc()
    version = _run([swiftc, "--version"]).stdout.strip()
    exe = binary_path(SWIFT_SOURCE, version)
    if exe.exists():
        return exe
    exe.parent.mkdir(parents=True, exist_ok=True)
    # Egyedi ideiglenes név: két egyszerre induló első futás ne írjon egymás
    # félkész fájljába; a kész programot os.replace teszi a helyére.
    fd, tmp = tempfile.mkstemp(prefix=exe.name + ".", suffix=".part", dir=exe.parent)
    os.close(fd)
    tmp = Path(tmp)
    print(f"A Vision-segéd fordítása (egyszeri, ~1 perc): {exe}", flush=True)
    # xcrun-on át: az állítja be a macOS SDK-t (a fordító közvetlen hívása nélküle
    # „unable to load standard library” hibával áll le).
    r = _run(["xcrun", "swiftc", "-O", str(SWIFT_SOURCE), "-o", str(tmp)])
    if r.returncode or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise EngineError("a vocr.swift nem fordult le:\n" + (r.stderr or r.stdout).strip()[-800:])
    os.replace(tmp, exe)
    return exe


def parse_vision_output(text, expected):
    """A vocr JSON-sorai -> [[(szöveg, conf)] vagy None]. Darabszám-eltérésnél EngineError."""
    rows = [line for line in text.splitlines() if line.strip()]
    if len(rows) != expected:
        raise EngineError(f"a Vision-segéd {len(rows)} választ adott {expected} képre")
    out = []
    for row in rows:
        data = json.loads(row)
        out.append(None if data is None else [(str(t), float(c)) for t, c in data])
    return out


class VisionEngine:
    name = "vision"

    def __init__(self, lang, engine_lang=None):
        if sys.platform != "darwin":
            raise EngineError("a Vision-motor csak macOS-en fut — válaszd a --engine rapidocr motort")
        codes = [c.strip() for c in (engine_lang or VISION_LANGS.get(lang) or "").split(",")]
        codes = [c for c in codes if c]
        if not codes:
            raise EngineError(f"a Vision-motorhoz nincs nyelvleképezés: {lang} — add meg a "
                              "Vision-kódot (HARDSUB_OCR_ENGINE_LANG / --engine-lang, pl. en-US)")
        self.exe = build_vision_helper()
        supported = self.supported()
        missing = [c for c in codes if c not in supported]
        if missing:
            raise EngineError(f"ezen a gépen a Vision nem ismeri: {', '.join(missing)} "
                              f"(ismert: {', '.join(supported)}) — próbáld a --engine rapidocr motort")
        self.lang = ",".join(codes)

    def supported(self):
        r = _run([str(self.exe), "--supported"])
        try:
            return list(json.loads(r.stdout or "[]"))
        except ValueError:
            return []

    def recognize(self, paths):
        if not paths:
            return []
        r = _run([str(self.exe), self.lang], input="".join(f"{p}\n" for p in paths))
        if r.returncode:
            raise EngineError(f"a Vision-segéd hibával állt le: {(r.stderr or '').strip()[-300:]}")
        return parse_vision_output(r.stdout, len(paths))


# ── RapidOCR ───────────────────────────────────────────────────────────────

RAPID_INSTALL = ('pip install -e ".[ocr]"   (vagy: pip install rapidocr onnxruntime)')


# Pipeline-kód → RapidOCR felismerő-nyelv: (a PP-OCRv6 alapmodell kódja,
# tartalék a régebbi nyelvenkénti modellekhez). A v6 többnyelvű alapmodell
# saját kóddal ismeri a kínait (hagyományosat is: chinese_cht), japánt, angolt
# és a latin betűs nyelvek többségét (de, fr, es, it, pl, pt, tr, vi, id, ms —
# a vietnámi ékezeteket jóval pontosabban, mint a régi közös latin modell);
# a koreai, thai, cirill, arab, hindi modell csak a PP-OCRv5-ben van.
RAPID_LANGS = {
    "chi": ("ch", None), "jpn": ("japan", None), "eng": ("en", None),
    "kor": ("korean", None), "tha": ("th", None), "rus": ("cyrillic", None),
    "ara": ("arabic", None), "hin": ("devanagari", None),
    "ger": ("de", "latin"), "fre": ("fr", "latin"), "spa": ("es", "latin"),
    "por": ("pt", "latin"), "ita": ("it", "latin"), "pol": ("pl", "latin"),
    "tur": ("tr", "latin"), "vie": ("vi", "latin"), "ind": ("id", "latin"),
    "may": ("ms", "latin"),
}

# A próbálkozás sorrendje: (ocr_version, model_type), None = az alapmodell
# (PP-OCRv6 small). A régebbi verziókban csak `mobile` típus van nyelvenként.
RAPID_MODEL_ORDER = ((None, None), ("PP-OCRv5", "mobile"), ("PP-OCRv4", "mobile"))


class RapidOcrEngine:
    """RapidOCR (PaddleOCR-modellek ONNX-en). A modellek első futáskor töltődnek le.

    A mai csomag a `rapidocr` (3.x). A régi `rapidocr_onnxruntime` is megy, de
    az csak a kínai (+angol) modellt ismeri.

    A RapidOCR a modelleket lustán, az első képnél tölti be — a konstruktor
    akkor sem hibázik, ha a nyelvhez nincs modell, vagy a letöltés nem megy.
    Ezért induláskor mindhárom modellt (szövegkeresés, orientáció, felismerés)
    betöltjük: ami itt elbukik, az a következő modellverzióval próbálkozik, a
    végén EngineError — még mielőtt egyetlen képkocka elkészülne.
    """
    name = "rapidocr"
    last_error = None   # az utolsó olvasási hiba (a Recognizer hibaüzenetéhez)

    def __init__(self, lang, engine_lang=None):
        override = (engine_lang or "").strip()
        primary, fallback = (override, None) if override else RAPID_LANGS.get(lang, (None, None))
        if not primary:
            raise EngineError(f"a RapidOCR-motorhoz nincs modell ehhez a nyelvhez: {lang}")
        try:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        except ImportError:
            LangRec = None
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError:
                raise EngineError(f"nincs telepítve a RapidOCR — {RAPID_INSTALL}") from None
        if LangRec is None:
            if primary != "ch":
                raise EngineError("a régi rapidocr_onnxruntime csak kínait tud — "
                                  "telepítsd az új csomagot: pip install rapidocr onnxruntime")
            self._ocr, self._new = RapidOCR(), False
            return

        def lang_value(code):
            # A LangRec csak a régi, nyelvenkénti modellek kódjait sorolja fel;
            # a v6 alapmodell nyelvkódjait (de, vi…) szövegként kéri.
            try:
                return LangRec(code)
            except ValueError:
                return code

        errors = []
        for version, model_type in RAPID_MODEL_ORDER:
            code = primary if version is None else (fallback or primary)
            params = {"Rec.lang_type": lang_value(code), "Global.log_level": "error"}
            label = f"alap/{code}"
            if version is not None:
                params["Rec.ocr_version"] = OCRVersion(version)
                params["Rec.model_type"] = ModelType(model_type)
                label = f"{version} {model_type}/{code}"
            try:
                ocr = RapidOCR(params=params)
                self._warm_up(ocr)
            except ImportError as exc:   # pl. hiányzó onnxruntime
                raise EngineError(f"a RapidOCR nem indul ({exc}) — {RAPID_INSTALL}") from None
            except Exception as exc:  # noqa: BLE001 — nincs ilyen modell, vagy nem töltődött le
                errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:120]}")
                continue
            self._ocr, self._new = ocr, True
            return
        raise EngineError(f"a RapidOCR „{primary}” felismerő modellje nem indult el — vagy nincs "
                          "ilyen modell, vagy az első futáskori letöltés nem sikerült (internet "
                          "kell hozzá). Próbálkozások: " + "; ".join(errors))

    def _warm_up(self, ocr):
        """Mindhárom modell betöltése most.

        A felismerőt egy csak-felismerés hívás tölti be (üres képen a keresés
        semmit sem találna, és a felismerő sosem futna le); a keresőt és az
        orientáció-modellt a RapidOCR saját betöltője (ha van ilyen — régebbi
        3.x-ben egy keresős hívás az üres képen).

        A RapidOCR a hívásnál megadott use_det/use_cls/use_rec kapcsolót
        MEGJEGYZI; ezért az eredeti értékeket elmentjük, és minden képnél
        kifejezetten ezekkel hívjuk (különben a teljes képsávot egyetlen
        sorként olvasná, szövegkeresés nélkül)."""
        import numpy as np
        self._steps = {"use_det": ocr.use_det, "use_cls": ocr.use_cls, "use_rec": ocr.use_rec}
        ocr(np.zeros((48, 320, 3), np.uint8), use_det=False, use_cls=False, use_rec=True)
        loaders = [getattr(ocr, n, None) for n in ("_load_det_model", "_load_cls_model")]
        if all(callable(f) for f in loaders):
            if self._steps["use_det"]:
                loaders[0]()
            if self._steps["use_cls"]:
                loaders[1]()
        else:
            ocr(np.zeros((64, 320, 3), np.uint8), **self._steps)

    def _one(self, path):
        if self._new:
            res = self._ocr(str(path), **self._steps)
            txts, scores = res.txts or (), res.scores or ()
            return [(str(t), float(s)) for t, s in zip(txts, scores)]
        res, _elapse = self._ocr(str(path))
        return [(str(t), float(s)) for _box, t, s in (res or [])]

    def recognize(self, paths):
        out = []
        for p in paths:
            try:
                out.append(self._one(p))
            except Exception as exc:  # noqa: BLE001 — egy olvashatatlan kép ne állítsa le a részt
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
                out.append(None)
        return out
