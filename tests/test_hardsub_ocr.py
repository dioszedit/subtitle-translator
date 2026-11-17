"""addons/hardsub-ocr — a motorfüggetlen mag: SRT, mintavétel, szűrés,
jelöltválasztás, igazítás, fájlnevek, beállítások. A motort egy hamis motor
helyettesíti, így se Vision, se RapidOCR, se ffmpeg nem kell."""

import importlib.util
import sys
from pathlib import Path

import pytest

from subtr import config

ADDON_DIR = Path(__file__).resolve().parent.parent / "addons" / "hardsub-ocr"
_spec = importlib.util.spec_from_file_location("ocr_subs", ADDON_DIR / "ocr_subs.py")
ocr = importlib.util.module_from_spec(_spec)
sys.modules["ocr_subs"] = ocr
_spec.loader.exec_module(ocr)
engines = ocr.engines

SRT = """1
00:00:01,000 --> 00:00:03,000
Hello.

2
00:00:04,000 --> 00:00:04,500
Short.

3
00:00:10,000 --> 00:00:14,000
<i>Song lyrics</i>
second line
"""


@pytest.fixture
def cfg(monkeypatch):
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    return ocr.resolve(ocr.build_parser().parse_args(["x.mp4"]))


# ── SRT ────────────────────────────────────────────────────────────────────

def test_parse_ts():
    assert ocr.parse_ts("00:01:02,345") == pytest.approx(62.345)
    assert ocr.parse_ts("1:00:00.5") == pytest.approx(3600.5)
    with pytest.raises(ValueError):
        ocr.parse_ts("hello")


def test_read_cues_keeps_numbers_and_timestamps(tmp_path):
    p = tmp_path / "Sorozat - S01E01.eng.srt"
    p.write_text("﻿" + SRT, encoding="utf-8")
    cues = ocr.read_cues(p)
    assert [c["num"] for c in cues] == ["1", "2", "3"]
    assert cues[0]["timestamp"] == "00:00:01,000 --> 00:00:03,000"
    assert cues[2]["start"] == 10 and cues[2]["end"] == 14


def test_read_cues_bad_timestamp_is_fail(tmp_path):
    p = tmp_path / "x.srt"
    p.write_text("1\nnope --> 00:00:01,000\nHi\n", encoding="utf-8")
    with pytest.raises(ocr.Fail):
        ocr.read_cues(p)


def test_read_cues_empty_is_fail(tmp_path):
    p = tmp_path / "x.srt"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ocr.Fail):
        ocr.read_cues(p)


def test_output_uses_dash_for_empty(tmp_path):
    p = tmp_path / "in.srt"
    p.write_text(SRT, encoding="utf-8")
    cues = ocr.read_cues(p)
    out = tmp_path / "out.srt"
    ocr.write_srt(str(out), ocr.output_sections(cues, ["你好", "", "歌词"]))
    text = out.read_text(encoding="utf-8")
    assert text == ("1\n00:00:01,000 --> 00:00:03,000\n你好\n\n"
                    "2\n00:00:04,000 --> 00:00:04,500\n—\n\n"
                    "3\n00:00:10,000 --> 00:00:14,000\n歌词\n")


# ── mintavétel ─────────────────────────────────────────────────────────────

def test_sample_frames_two_points_for_long_cue():
    # 10–14 mp, 4 fps: 35% → 11,4 mp → 46. kocka; 70% → 12,8 mp → 51.
    assert ocr.sample_frames(10, 14, 4) == [46, 51]


def test_sample_frames_middle_for_short_cue():
    assert ocr.sample_frames(4.0, 4.5, 4) == [17]   # 4,25 mp × 4


def test_sample_frames_dedupes():
    # ritka mintavételnél a két pont ugyanarra a kockára esik: egyszer kell
    assert ocr.sample_frames(10, 10.9, 0.5) == [5]


def test_retry_frames_all_when_few():
    assert ocr.retry_frames(1.0, 2.0, 4, 8) == [5, 6, 7, 8]


def test_retry_frames_capped_and_spread():
    frames = ocr.retry_frames(0, 10, 4, 8)   # 40 kocka közül 8
    assert len(frames) == 8
    assert frames == sorted(frames)
    assert frames[0] < 10 and frames[-1] > 30   # nem csak az eleje


def test_retry_frames_zero_disables():
    assert ocr.retry_frames(0, 10, 4, 0) == []


# ── sáv ────────────────────────────────────────────────────────────────────

def test_band_relative_scales_with_resolution():
    assert ocr.band_pixels(0.833, 0.986, 720) == (600, 110)
    y, h = ocr.band_pixels(0.833, 0.986, 1080)
    assert (y, h) == (900, 165)


def test_band_pixels_absolute():
    assert ocr.band_pixels(600, 710, 720) == (600, 110)


def test_band_too_narrow_or_reversed():
    with pytest.raises(ocr.Fail):
        ocr.band_pixels(0.9, 0.5, 720)


def test_parse_edge():
    assert ocr.parse_edge("0.8") == 0.8
    assert ocr.parse_edge("600px") == 600
    with pytest.raises(ValueError):
        ocr.parse_edge("600.5")
    with pytest.raises(ValueError):
        ocr.parse_edge("-1")


# ── szűrés ─────────────────────────────────────────────────────────────────

def test_chinese_filter_drops_ads_latin_and_non_cjk():
    f = ocr.LineFilter("chi")
    lines = [("我已经找到线索了", 1.0),
             ("官方娱乐平台", 1.0),          # reklám-kulcsszó
             ("www.example.com", 0.9),        # URL
             ("扫码领取88元", 1.0),           # szám → reklám
             ("VIP会员", 1.0),                # latin betű → reklám
             ("...", 0.5),                    # nincs benne írásjegy
             ("  你  再等等 ", 0.5)]
    assert f(lines) == [("我已经找到线索了", 1.0), ("你 再等等", 0.5)]


def test_korean_filter_wants_hangul():
    f = ocr.LineFilter("kor")
    lines = [("괜찮아요", 0.9), ("我已经", 1.0), ("ABC123", 1.0), ("지금 3시야", 1.0)]
    # a kínai írásjegy nem koreai; a latin/szám reklám
    assert f(lines) == [("괜찮아요", 0.9)]


def test_latin_language_keeps_latin_and_digits():
    f = ocr.LineFilter("eng")
    lines = [("See you at 3 o'clock.", 0.9), ("Visit www.bet.example", 1.0),
             ("你好", 1.0), ("---", 0.8)]
    assert f(lines) == [("See you at 3 o'clock.", 0.9)]


def test_drop_latin_override():
    assert ocr.LineFilter("chi", drop_latin=False)([("VIP会员", 1.0)]) == [("VIP会员", 1.0)]
    assert ocr.LineFilter("eng", drop_latin=True)([("Hello", 1.0)]) == []


def test_ad_extra_extends_list():
    f = ocr.LineFilter("kor", ad_extra="광고|이벤트")
    assert f([("광고 문의", 1.0), ("괜찮아", 1.0)]) == [("괜찮아", 1.0)]


def test_ad_words_not_chinese_for_other_languages():
    # a kínai kulcsszólista nem érvényes a koreaira
    assert not ocr.ad_pattern("kor").search("平台")
    assert ocr.ad_pattern("chi").search("平台")


def test_every_lang_has_script():
    for lang in ocr.LANG_SCRIPT.values():
        assert lang in ocr.SCRIPTS
    assert set(ocr.LANG_SCRIPT) <= set(config.SOURCE_LANGS)


# ── jelöltválasztás ────────────────────────────────────────────────────────

def test_candidate_joins_lines_min_conf():
    assert ocr.candidate([("你好", 1.0), ("再见", 0.5)]) == ("你好 再见", 0.5)
    assert ocr.candidate([]) is None


def test_best_candidate_conf_then_length():
    cands = [("短", 1.0), ("长一点的句子", 0.5), None, ("长一点", 1.0)]
    assert ocr.best_candidate(cands) == ("长一点", 1.0)


def test_best_candidate_threshold():
    assert ocr.best_candidate([("你好", 0.3)], 0.5) == ("", 0.0)
    assert ocr.best_candidate([None, None]) == ("", 0.0)


# ── igazítás hamis motorral ────────────────────────────────────────────────

class FakeEngine:
    name = "fake"

    def __init__(self, answers):
        self.answers = answers   # fájlnév → sorok
        self.calls = []

    def recognize(self, paths):
        self.calls.append(list(paths))
        return [self.answers.get(Path(p).name, []) for p in paths]


def make_frames(d, ns):
    for n in ns:
        ocr.frame_file(d, n).write_bytes(b"")


def test_align_main_pass_and_retry(tmp_path, cfg):
    cues = [{"num": "1", "timestamp": "", "start": 1.0, "end": 3.0},
            {"num": "2", "timestamp": "", "start": 4.0, "end": 4.5},
            {"num": "3", "timestamp": "", "start": 10.0, "end": 12.0}]
    make_frames(tmp_path, range(0, 60))
    answers = {
        # 1. cue: 35% → 1,7 mp → 7. kocka, 70% → 2,4 mp → 10. kocka
        "000007.png": [("你好", 0.5)],
        "000010.png": [("你好吗", 1.0), ("官方平台", 1.0)],
        # 2. cue: semmi a fő körben, a pótlásban csak a binarizált kocka ad biztos találatot
        "000017.png": [("快", 0.3)],
        "bin_000017.png": [("很快", 1.0)],
        # 3. cue: a pótlásban is csak gyenge találat → üres marad
        "000041.png": [("歌", 0.3)],
    }
    rec = ocr.Recognizer(FakeEngine(answers), ocr.LineFilter("chi"))
    cfg["min_conf"] = 0.4

    def binarizer(paths):
        out = {}
        for p in paths:
            b = tmp_path / f"bin_{p.name}"
            b.write_bytes(b"")
            out[p] = b
        return out

    texts, stats = ocr.align(cues, tmp_path, rec, cfg, binarizer, log=lambda *_: None)
    assert texts == ["你好吗", "很快", ""]
    assert stats == {"cues": 3, "first_empty": 2, "retried": 1, "empty": 1}


def test_recognizer_reads_each_frame_once_and_skips_missing(tmp_path):
    make_frames(tmp_path, [1, 2])
    eng = FakeEngine({"000001.png": [("你好", 1.0)]})
    rec = ocr.Recognizer(eng, ocr.LineFilter("chi"))
    p1, p2, p9 = (ocr.frame_file(tmp_path, n) for n in (1, 2, 9))
    rec.run([p1, p2, p9, p1])
    rec.run([p1, p2])
    assert eng.calls == [[p1, p2]]
    assert rec.get(p1) == ("你好", 1.0) and rec.get(p2) is None and rec.get(p9) is None


def test_align_without_retry(tmp_path, cfg):
    cues = [{"num": "1", "timestamp": "", "start": 1.0, "end": 3.0}]
    make_frames(tmp_path, range(20))
    cfg["retry_frames"] = 0
    eng = FakeEngine({})
    texts, stats = ocr.align(cues, tmp_path, ocr.Recognizer(eng, ocr.LineFilter("chi")),
                             cfg, None, log=lambda *_: None)
    assert texts == [""] and stats["empty"] == 1 and len(eng.calls) == 1


# ── fájlnevek ──────────────────────────────────────────────────────────────

def test_out_path_uses_lang_and_strips_video_lang_tag():
    assert ocr.out_path("Season 01/Sorozat - S01E01.mp4", "chi", "input") == \
        Path("input/Sorozat - S01E01.chi.ocr.srt")
    assert ocr.out_path("Sorozat - S01E01.kor.mkv", "kor", "x") == Path("x/Sorozat - S01E01.kor.ocr.srt")
    assert ocr.out_path("Sorozat - S01E01.mkv", "eng", "input") == Path("input/Sorozat - S01E01.eng.ocr.srt")


def test_out_path_is_machine_marked_and_keeps_lang():
    p = ocr.out_path("Sorozat - S01E01.mp4", "kor", "input")
    assert config.is_ocr_path(p) and config.is_machine_path(p)
    assert config.detect_source_lang(p) == "kor"
    assert p.name.endswith(f".kor{config.OCR_SUFFIX}.srt")


def test_find_ref_prefers_english(tmp_path):
    for code in ("kor", "eng"):
        (tmp_path / f"Sorozat - S01E01.{code}.srt").write_text("x")
    ref, err = ocr.find_ref("Season 01/Sorozat - S01E01.mp4", "chi", tmp_path)
    assert err is None and ref.name == "Sorozat - S01E01.eng.srt"


def test_find_ref_skips_ocr_language(tmp_path):
    (tmp_path / "Sorozat - S01E01.chi.srt").write_text("x")   # az OCR nyelve: nem forrás
    (tmp_path / "Sorozat - S01E01.eng.ocr.srt").write_text("x")   # gépi kinyerés: soha
    (tmp_path / "Sorozat - S01E01.ger.srt").write_text("x")
    ref, err = ocr.find_ref("Sorozat - S01E01.mp4", "chi", tmp_path)
    assert err is None and ref.name == "Sorozat - S01E01.ger.srt"


def test_find_ref_missing_or_ambiguous(tmp_path):
    ref, err = ocr.find_ref("Sorozat - S01E01.mp4", "chi", tmp_path)
    assert ref is None and "--ref" in err
    for code in ("ger", "fre"):
        (tmp_path / f"Sorozat - S01E01.{code}.srt").write_text("x")
    ref, err = ocr.find_ref("Sorozat - S01E01.mp4", "chi", tmp_path)
    assert ref is None and "--ref" in err


# ── beállítások ────────────────────────────────────────────────────────────

def test_defaults(cfg):
    assert cfg["lang"] == "chi" and cfg["engine"] == "auto"
    assert cfg["top"] == pytest.approx(0.833) and cfg["fps"] == 4.0
    assert cfg["retry_min_conf"] == 0.5 and cfg["retry_frames"] == 8
    assert cfg["drop_latin"] is None and cfg["lang_src"] == "alap"


def test_switch_beats_env_beats_default(monkeypatch):
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("HARDSUB_OCR_LANG", "ko")
    monkeypatch.setenv("HARDSUB_OCR_FPS", "2")
    c = ocr.resolve(ocr.build_parser().parse_args(["x.mp4", "--fps", "3"]))
    assert c["lang"] == "kor" and c["lang_src"] == ".env"
    assert c["fps"] == 3.0 and c["fps_src"] == "kapcsoló"


@pytest.mark.parametrize("argv", [["--lang", "xx"], ["--engine", "tesseract"],
                                  ["--min-conf", "2"], ["--bin-threshold", "300"],
                                  ["--ad-extra", "(unclosed"], ["--fps", "abc"],
                                  ["--drop-latin", "maybe"]])
def test_bad_values_exit(monkeypatch, argv):
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    with pytest.raises(SystemExit):
        ocr.resolve(ocr.build_parser().parse_args(["x.mp4", *argv]))


def test_existing_output_is_skipped_without_force(tmp_path, monkeypatch, capsys):
    video = tmp_path / "Sorozat - S01E01.mp4"
    video.write_bytes(b"")
    (tmp_path / "Sorozat - S01E01.eng.srt").write_text(SRT, encoding="utf-8")
    dest = tmp_path / "Sorozat - S01E01.chi.ocr.srt"
    dest.write_text("régi", encoding="utf-8")
    monkeypatch.setattr(ocr, "require_tools", lambda: None)
    monkeypatch.setattr(ocr, "load_dotenv", lambda: None)
    monkeypatch.setattr(ocr.engines, "create", lambda *a: pytest.fail("nem kellett volna motor"))
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    rc = ocr.main([str(video), "--ref-dir", str(tmp_path), "--out-dir", str(tmp_path)])
    assert rc == 0 and dest.read_text(encoding="utf-8") == "régi"
    assert "KÉSZ, kihagyva" in capsys.readouterr().out


def test_output_never_overwrites_ref(tmp_path, monkeypatch):
    video = tmp_path / "Sorozat - S01E01.mp4"
    video.write_bytes(b"")
    ref = tmp_path / "Sorozat - S01E01.eng.ocr.srt"   # (rossz) forrásnak egy korábbi kimenet
    ref.write_text(SRT, encoding="utf-8")
    monkeypatch.setattr(ocr, "require_tools", lambda: None)
    monkeypatch.setattr(ocr, "load_dotenv", lambda: None)
    monkeypatch.setattr(ocr.engines, "create", lambda *a: pytest.fail("nem kellett volna motor"))
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    rc = ocr.main([str(video), "--ref", str(ref), "--lang", "eng", "--out-dir", str(tmp_path),
                   "--force"])
    assert rc == 1 and ref.read_text(encoding="utf-8") == SRT


# ── motorok (csak a motorfüggetlen részük) ─────────────────────────────────

def test_pick_engine():
    assert engines.pick_engine("auto", "darwin") == "vision"
    assert engines.pick_engine("auto", "win32") == "rapidocr"
    assert engines.pick_engine("auto", "linux") == "rapidocr"
    assert engines.pick_engine("rapidocr", "darwin") == "rapidocr"


def test_parse_vision_output():
    out = engines.parse_vision_output('[["你好", 1.0], ["再见", 0.5]]\nnull\n[]\n', 3)
    assert out == [[("你好", 1.0), ("再见", 0.5)], None, []]
    with pytest.raises(engines.EngineError):
        engines.parse_vision_output("[]\n", 2)


def test_binary_name_changes_with_source(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDSUB_OCR_CACHE_DIR", str(tmp_path))
    src = tmp_path / "a.swift"
    src.write_text("print(1)")
    a = engines.binary_path(src, "swift 6")
    src.write_text("print(2)")
    b = engines.binary_path(src, "swift 6")
    assert a != b and a.parent == tmp_path
    assert engines.binary_path(src, "swift 7") != b


def test_engine_lang_maps_cover_filter_langs():
    """Minden nyelvhez, amit a szűrő ismer, legyen legalább az egyik motorban leképezés."""
    for lang in ocr.LANG_SCRIPT:
        assert lang in engines.VISION_LANGS or lang in engines.RAPID_LANGS


def test_rapidocr_missing_package_message(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name.startswith("rapidocr"):
            raise ImportError(name)
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(engines.EngineError, match="pip install"):
        engines.RapidOcrEngine("chi")
