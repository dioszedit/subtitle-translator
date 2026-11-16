"""addons/audio-asr — sávválasztás, fájlnév, szűrés (Whisper és ffmpeg nélkül)."""

import importlib.util
import json
import sys
from pathlib import Path

from subtr import config

ADDON_DIR = Path(__file__).resolve().parent.parent / "addons" / "audio-asr"
_spec = importlib.util.spec_from_file_location("audio_asr", ADDON_DIR / "transcribe.py")
asr = importlib.util.module_from_spec(_spec)
sys.modules["audio_asr"] = asr
_spec.loader.exec_module(asr)


def track(index, lang, title="", default=False):
    return {"index": index, "lang": asr.normalize_lang(lang), "title": title,
            "codec": "aac", "channels": 2, "default": default}


# ── nyelv ──────────────────────────────────────────────────────────────────

def test_normalize_and_whisper_lang():
    assert asr.normalize_lang("ko") == "kor"
    assert asr.whisper_lang("kor") == "ko"
    assert asr.whisper_lang("zh") == "zh"
    assert asr.whisper_lang("chi") == "zh"
    assert asr.whisper_lang("und") is None
    assert asr.whisper_lang("") is None


def test_whisper_langs_cover_pipeline_languages():
    """Minden pipeline-forrásnyelvhez legyen Whisper-kód — a két lista ne csússzon szét."""
    assert set(asr.WHISPER_LANGS) == set(config.SOURCE_LANGS)


# ── hangsáv-választás ──────────────────────────────────────────────────────

def test_single_track_uses_its_label():
    t, err = asr.pick_track([track(1, "kor")], None, None)
    assert err is None and t["index"] == 1


def test_picks_by_language_not_order():
    tracks = [track(1, "eng", default=True), track(2, "kor")]
    t, err = asr.pick_track(tracks, "kor", None)
    assert err is None and t["index"] == 2


def test_multiple_tracks_without_lang_is_error():
    t, err = asr.pick_track([track(1, "kor"), track(2, "eng")], None, None)
    assert t is None and "--lang" in err


def test_missing_language_is_error():
    t, err = asr.pick_track([track(1, "eng"), track(2, "chi")], "kor", None)
    assert t is None and "kor" in err


def test_untagged_single_track_accepts_given_lang():
    t, err = asr.pick_track([track(1, "und")], "kor", None)
    assert err is None and t["index"] == 1


def test_same_language_twice_needs_title():
    tracks = [track(1, "kor", "Korean"), track(2, "kor", "Commentary")]
    t, err = asr.pick_track(tracks, "kor", None)
    assert t is None and "--title" in err
    t, err = asr.pick_track(tracks, "kor", "korean")
    assert err is None and t["index"] == 1


def test_parse_probe():
    raw = json.dumps({"streams": [
        {"index": 1, "codec_name": "AAC", "channels": 2,
         "tags": {"language": "ko", "title": "Korean"}, "disposition": {"default": 1}},
        {"index": 2, "codec_name": "opus"},
    ]})
    tracks = asr.parse_probe(raw)
    assert tracks[0] == {"index": 1, "lang": "kor", "title": "Korean", "codec": "aac",
                         "channels": 2, "default": True}
    assert tracks[1]["lang"] == "" and tracks[1]["default"] is False


# ── kimeneti fájlnév ───────────────────────────────────────────────────────

def test_out_path_convention():
    p = asr.out_path("Season 01/Sorozat - S01E01.mkv", "kor", "input/asr")
    assert p == Path("input/asr/Sorozat - S01E01.kor.asr.srt")


def test_out_path_does_not_double_language_tag():
    p = asr.out_path("Sorozat - S01E01.kor.mkv", "kor", "out")
    assert p.name == "Sorozat - S01E01.kor.asr.srt"


def test_out_path_is_recognised_by_pipeline():
    """A pipeline a nyelvet felismeri, és tudja, hogy gépi átirat."""
    p = asr.out_path("Season 01/Sorozat - S01E03.mkv", "kor", "input/asr")
    assert config.detect_source_lang(p) == "kor"
    assert config.is_asr_path(p)


# ── szűrés ─────────────────────────────────────────────────────────────────

def test_drops_known_hallucinations_only_on_full_match():
    segs = [(0, 1, "시청해 주셔서 감사합니다."),     # zene alatti „köszönjük, hogy nézték”
            (1, 2, "감사합니다."),                   # valódi „köszönöm” — marad
            (2, 3, "시청해 주셔서 감사합니다, 선생님 말씀은요")]  # valódi mondat része — marad
    kept, dropped = asr.clean_segments(segs, "kor")
    assert [t for _, _, t in kept] == ["감사합니다.", "시청해 주셔서 감사합니다, 선생님 말씀은요"]
    assert dropped == 1


def test_hallucination_list_is_language_specific():
    kept, _ = asr.clean_segments([(0, 1, "Thanks for watching!")], "kor")
    assert kept
    kept, _ = asr.clean_segments([(0, 1, "Thanks for watching!")], "eng")
    assert not kept


def test_collapses_repetition_loops():
    segs = [(i, i + 1, "어디 가?") for i in range(6)] + [(6, 7, "집에.")]
    kept, dropped = asr.clean_segments(segs, "kor")
    assert [t for _, _, t in kept] == ["어디 가?", "어디 가?", "집에."]
    assert dropped == 4


def test_drops_empty_and_punctuation_only():
    kept, dropped = asr.clean_segments([(0, 1, "  "), (1, 2, "..."), (2, 3, "응")], "kor")
    assert [t for _, _, t in kept] == ["응"] and dropped == 2


def test_whitespace_is_normalised():
    kept, _ = asr.clean_segments([(0, 1, "  밥은\n먹었어요? ")], "kor")
    assert kept[0][2] == "밥은 먹었어요?"


# ── SRT ────────────────────────────────────────────────────────────────────

def test_srt_block():
    assert asr.srt_block(3, 80.62, 3723.5, "네, 알겠습니다.") == \
        "3\n00:01:20,620 --> 01:02:03,500\n네, 알겠습니다.\n\n"


def test_stamp_never_negative():
    assert asr.stamp(-0.01) == "00:00:00,000"


# ── eszközválasztás ────────────────────────────────────────────────────────

def test_device_candidates_always_end_on_cpu():
    for dev in ("auto", "cuda", "mps", "cpu"):
        assert asr.device_candidates(dev)[-1] == ("cpu", "int8")
    assert asr.device_candidates("cpu") == [("cpu", "int8")]


# ── review-javítások (2026-11-16) ──────────────────────────────────────────

def test_track_index_overrides_wrong_label():
    """A koreai hang „eng” címkét kapott: --track választja ki, a --lang nem kell hozzá."""
    tracks = [track(1, "eng"), track(2, "eng", "Commentary")]
    t, err = asr.pick_track(tracks, "kor", None, index=1)
    assert err is None and t["index"] == 1
    t, err = asr.pick_track(tracks, None, None, index=7)
    assert t is None and "7" in err


def test_dropped_hallucination_breaks_repeat_run():
    segs = [(0, 1, "어디 가?"), (1, 2, "어디 가?"),
            (2, 3, "시청해 주셔서 감사합니다."),
            (3, 4, "어디 가?")]
    kept, dropped = asr.clean_segments(segs, "kor")
    assert [t for _, _, t in kept] == ["어디 가?"] * 3
    assert dropped == 1


def test_convert_runs_before_filter():
    """A kínai átalakítás a szűrés előtt fut — a hallucináció-lista egyszerűsített alakú."""
    kept, dropped = asr.clean_segments([(0, 1, "謝謝觀看"), (1, 2, "你好")], "chi",
                                       convert=lambda t: t.replace("謝謝觀看", "谢谢观看"))
    assert [t for _, _, t in kept] == ["你好"] and dropped == 1


def test_chinese_converter_survives_broken_opencc(monkeypatch):
    class Broken:
        def OpenCC(self, name):
            raise RuntimeError(f"no config {name}")
    monkeypatch.setitem(sys.modules, "opencc", Broken())
    assert asr.chinese_converter("chi") is None
    assert asr.chinese_converter("kor") is None


def _fake_run(monkeypatch, tmp_path, fail_on):
    """main() ffmpeg és Whisper nélkül: a transcribe() az adott eszközön hibát dob."""
    video = tmp_path / "S - S01E01.mkv"
    video.write_text("")
    loads, runs = [], []
    monkeypatch.setattr(asr, "require_tools", lambda: None)
    monkeypatch.setattr(asr, "probe_audio", lambda v: [track(1, "kor")])

    def load(name, device, threads):
        dev = "cuda" if device == "auto" else device
        loads.append(dev)
        return dev, dev

    def run(model, video, trk, lang, dest, beam):
        runs.append(model)
        if model in fail_on:
            raise RuntimeError("cublas64_12.dll not found")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("ok")

    monkeypatch.setattr(asr, "load_model", load)
    monkeypatch.setattr(asr, "transcribe", run)
    monkeypatch.setattr(sys, "argv", ["transcribe.py", str(video),
                                      "--out-dir", str(tmp_path / "asr")])
    return loads, runs


def test_gpu_error_during_run_falls_back_to_cpu(monkeypatch, tmp_path):
    loads, runs = _fake_run(monkeypatch, tmp_path, fail_on={"cuda"})
    assert asr.main() == 0
    assert loads == ["cuda", "cpu"] and runs == ["cuda", "cpu"]
    assert (tmp_path / "asr" / "S - S01E01.kor.asr.srt").read_text() == "ok"


def test_cpu_error_is_reported_not_crashing(monkeypatch, tmp_path):
    loads, runs = _fake_run(monkeypatch, tmp_path, fail_on={"cuda", "cpu"})
    assert asr.main() == 1
    assert runs == ["cuda", "cpu"]
