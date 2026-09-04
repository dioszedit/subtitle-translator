"""addons/mkv-subs — sávválasztás és fájlnév-képzés (ffmpeg nélkül)."""

import importlib.util
import json
import sys
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent.parent / "addons" / "mkv-subs"
_spec = importlib.util.spec_from_file_location("mkv_subs", ADDON_DIR / "extract_subs.py")
mkv_subs = importlib.util.module_from_spec(_spec)
sys.modules["mkv_subs"] = mkv_subs
_spec.loader.exec_module(mkv_subs)


def track(index, lang, codec="subrip", title=""):
    return {"index": index, "lang": mkv_subs.normalize_lang(lang), "raw_lang": lang,
            "title": title, "codec": codec, "forced": False, "default": False}


# ── nyelvkód ────────────────────────────────────────────────────────────────

def test_normalize_lang_aliases():
    assert mkv_subs.normalize_lang("ja") == "jpn"
    assert mkv_subs.normalize_lang("KO") == "kor"
    assert mkv_subs.normalize_lang("zho") == "chi"
    assert mkv_subs.normalize_lang("jpn") == "jpn"


def test_normalize_lang_unknown_stays():
    assert mkv_subs.normalize_lang("und") == "und"
    assert mkv_subs.normalize_lang(None) == ""


# ── sávválasztás ────────────────────────────────────────────────────────────

def test_pick_uses_language_not_index():
    """A lényeg: a sáv SORRENDJE fájlonként változik, a nyelvcímke nem."""
    e14 = [track(2, "eng"), track(3, "jpn"), track(4, "kor"), track(5, "chi")]
    e17 = [track(2, "eng"), track(3, "kor"), track(4, "chi"), track(5, "jpn")]
    assert mkv_subs.pick(e14, "jpn", None)[0]["index"] == 3
    assert mkv_subs.pick(e17, "jpn", None)[0]["index"] == 5


def test_pick_missing_language_is_empty():
    assert mkv_subs.pick([track(2, "eng")], "ger", None) == []


def test_pick_multiple_same_language_returns_all():
    tracks = [track(2, "eng", title="English"), track(3, "eng", title="English [Forced]")]
    assert len(mkv_subs.pick(tracks, "eng", None)) == 2


def test_pick_title_filter_narrows():
    tracks = [track(2, "eng", title="English"), track(3, "eng", title="English [Forced]")]
    hits = mkv_subs.pick(tracks, "eng", "forced")
    assert [t["index"] for t in hits] == [3]


# ── kimeneti fájlnév ────────────────────────────────────────────────────────

def test_out_path_follows_naming_convention():
    got = mkv_subs.out_path("Season 01/Sorozat - S01E01.mkv", "jpn", None)
    assert got == Path("Season 01/Sorozat - S01E01.jpn.srt")


def test_out_path_out_dir():
    got = mkv_subs.out_path("Season 01/Sorozat - S01E01.mkv", "eng", "input")
    assert got == Path("input/Sorozat - S01E01.eng.srt")


def test_out_path_replaces_existing_lang_tag():
    """`x.eng.mkv` + jpn → `x.jpn.srt`, nem `x.eng.jpn.srt`."""
    got = mkv_subs.out_path("Sorozat - S01E01.eng.mkv", "jpn", None)
    assert got == Path("Sorozat - S01E01.jpn.srt")


def test_out_path_keeps_non_lang_suffix():
    """A pont utáni tag csak akkor nyelvkód, ha tényleg az."""
    got = mkv_subs.out_path("Sorozat - S01E01.1080p.mkv", "jpn", None)
    assert got == Path("Sorozat - S01E01.1080p.jpn.srt")


# ── ffprobe-válasz feldolgozása ─────────────────────────────────────────────

def test_probe_parses_streams(monkeypatch):
    payload = {"streams": [
        {"index": 5, "codec_name": "subrip",
         "tags": {"language": "ja", "title": "Japanese (CC)"},
         "disposition": {"forced": 0, "default": 0}},
        {"index": 6, "codec_name": "hdmv_pgs_subtitle",
         "tags": {"language": "eng"}, "disposition": {"forced": 1, "default": 1}},
    ]}

    class Done:
        stdout = json.dumps(payload)

    monkeypatch.setattr(mkv_subs.subprocess, "run", lambda *a, **k: Done())
    tracks = mkv_subs.probe_subtitles("x.mkv")
    assert [t["lang"] for t in tracks] == ["jpn", "eng"]
    assert tracks[0]["title"] == "Japanese (CC)"
    assert tracks[1]["forced"] is True
    # a képi sáv nem szöveges — a kicsomagolás kihagyja
    assert tracks[1]["codec"] in mkv_subs.IMAGE_CODECS
    assert tracks[0]["codec"] in mkv_subs.TEXT_CODECS
