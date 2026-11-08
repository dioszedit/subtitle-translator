"""addons/mkv-subs/embed_subs.py — a kész magyar felirat beágyazása (közös mux-mag)."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ADDON_DIR = Path(__file__).resolve().parent.parent / "addons" / "mkv-subs"
_spec = importlib.util.spec_from_file_location("embed_subs", ADDON_DIR / "embed_subs.py")
emb = importlib.util.module_from_spec(_spec)
sys.modules["embed_subs"] = emb
_spec.loader.exec_module(emb)


def sub(index, lang, codec="subrip", title=None, default=0, forced=0):
    tags = {"language": lang}
    if title:
        tags["title"] = title
    return {"index": index, "codec_type": "subtitle", "codec_name": codec,
            "tags": tags, "disposition": {"default": default, "forced": forced}}


VA = [{"index": 0, "codec_type": "video"}, {"index": 1, "codec_type": "audio"}]


def maps(cmd):
    return [cmd[i + 1] for i, x in enumerate(cmd) if x == "-map"]


def opts(cmd, prefix):
    return [(x, cmd[i + 1]) for i, x in enumerate(cmd) if x.startswith(prefix)]


# ── saját sávok felismerése ─────────────────────────────────────────────────

def test_srt_track_owns_only_subrip_magyar():
    assert emb.SRT_TRACK.owns(sub(2, "hun", "subrip", "Magyar"))
    assert not emb.SRT_TRACK.owns(sub(2, "hun", "ass", "Magyar"))
    assert not emb.SRT_TRACK.owns(sub(2, "hun", "subrip", "Külső"))
    assert not emb.SRT_TRACK.owns(sub(2, "eng", "subrip", "Magyar"))


def test_ass_track_owns_new_and_legacy_title():
    assert emb.ASS_TRACK.owns(sub(2, "hun", "ass", "Magyar (dobozos)"))
    assert emb.ASS_TRACK.owns(sub(2, "hun", "ass", "Magyar"))             # a hardsub-cover első változata
    assert not emb.ASS_TRACK.owns(sub(2, "hun", "subrip", "Magyar"))


def test_owns_tag_case_insensitive():
    s = sub(3, "hun", "subrip")
    s["tags"] = {"LANGUAGE": "hun", "TITLE": "Magyar"}
    assert emb.SRT_TRACK.owns(s)


# ── mux-parancs ─────────────────────────────────────────────────────────────

def test_mux_cmd_not_default_appends_and_keeps_dispositions():
    streams = VA + [sub(2, "eng", default=1, forced=1), sub(3, "hun", "subrip", "Magyar"),
                    sub(4, "hun", "ass", "Magyar (dobozos)", default=1)]
    cmd, keep, pos = emb.mux_cmd("ffmpeg", "a.mkv", "a.srt", "t.mkv", streams, emb.SRT_TRACK, False)
    assert maps(cmd) == ["0:v", "0:a?", "0:2", "0:4", "1", "0:t?"]
    assert [s["index"] for s in keep] == [2, 4] and pos == 2
    assert opts(cmd, "-disposition") == [("-disposition:s:2", "0")]   # a többihez nem nyúl
    assert ("-metadata:s:s:2", "title=Magyar") in opts(cmd, "-metadata")


def test_mux_cmd_default_goes_first_and_only_clears_default_flag():
    streams = VA + [sub(2, "eng", default=1, forced=1), sub(3, "hun", "subrip", "Magyar")]
    cmd, keep, pos = emb.mux_cmd("ffmpeg", "a.mkv", "a.srt", "t.mkv", streams, emb.SRT_TRACK, True)
    assert maps(cmd) == ["0:v", "0:a?", "1", "0:2", "0:t?"]
    assert pos == 0
    assert opts(cmd, "-disposition") == [("-disposition:s:0", "default"), ("-disposition:s:1", "-default")]


def test_mux_cmd_ass_replaces_legacy_magyar_ass_keeps_srt():
    streams = VA + [sub(2, "hun", "ass", "Magyar", default=1), sub(3, "hun", "subrip", "Magyar")]
    cmd, keep, _ = emb.mux_cmd("ffmpeg", "a.mkv", "a.ass", "t.mkv", streams, emb.ASS_TRACK, True)
    assert maps(cmd) == ["0:v", "0:a?", "1", "0:3", "0:t?"]
    assert ("-metadata:s:s:0", "title=Magyar (dobozos)") in opts(cmd, "-metadata")
    assert ("-metadata:s:s:0", "SUBTR=ass") in opts(cmd, "-metadata")


# ── ellenőrzés ──────────────────────────────────────────────────────────────

def info(streams, duration="100.0"):
    return {"streams": streams, "format": {"duration": duration}}


def test_check_mux_ok_default_and_not_default():
    before = info(VA + [sub(2, "eng", default=1)])
    keep = [sub(2, "eng", default=1)]
    good_def = info(VA + [sub(2, "hun", "subrip", "Magyar", 1), sub(3, "eng")])
    assert emb.check_mux(before, good_def, keep, 0, emb.SRT_TRACK, True) == []
    good_nodef = info(VA + [sub(2, "eng", default=1), sub(3, "hun", "subrip", "Magyar")])
    assert emb.check_mux(before, good_nodef, keep, 1, emb.SRT_TRACK, False) == []


def test_check_mux_problems():
    before = info(VA + [sub(2, "eng")])
    keep = [sub(2, "eng")]
    no_audio = info(VA[:1] + [sub(1, "hun", "subrip", "Magyar", 1), sub(2, "eng")], "50.0")
    p = emb.check_mux(before, no_audio, keep, 0, emb.SRT_TRACK, True)
    assert any("hang" in x for x in p) and any("hossz" in x for x in p)
    two_defaults = info(VA + [sub(2, "hun", "subrip", "Magyar", 1), sub(3, "eng", default=1)])
    assert emb.check_mux(before, two_defaults, keep, 0, emb.SRT_TRACK, True)
    missing = info(VA + [sub(2, "eng")])
    assert emb.check_mux(before, missing, keep, 0, emb.SRT_TRACK, True)
    wrong_place = info(VA + [sub(2, "eng"), sub(3, "hun", "subrip", "Magyar", 1)])
    assert emb.check_mux(before, wrong_place, keep, 0, emb.SRT_TRACK, True)


# ── hibautak: az eredeti marad, tmp nem marad ───────────────────────────────

@pytest.fixture
def files(tmp_path, monkeypatch):
    mkv, s = tmp_path / "a.mkv", tmp_path / "a.hun.srt"
    mkv.write_bytes(b"ORIGINAL")
    s.write_text("x")
    monkeypatch.setattr(emb, "find_tool", lambda n: n)
    monkeypatch.setattr(emb, "probe", lambda tool, p: info(VA))
    return tmp_path, mkv, s


def test_embed_ffmpeg_failure_keeps_original(files, monkeypatch):
    d, mkv, s = files

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"PARTIAL")
        return subprocess.CompletedProcess(cmd, 1, "", "boom")
    monkeypatch.setattr(emb.subprocess, "run", fake_run)
    with pytest.raises(emb.Fail, match="ffmpeg hiba"):
        emb.embed(mkv, s, emb.SRT_TRACK, False)
    assert mkv.read_bytes() == b"ORIGINAL"
    assert sorted(p.name for p in d.iterdir()) == ["a.hun.srt", "a.mkv"]


def test_embed_bad_result_keeps_original(files, monkeypatch):
    d, mkv, s = files

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"NEW")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(emb.subprocess, "run", fake_run)   # a probe szerint nincs benne felirat
    with pytest.raises(emb.Fail, match="hibás"):
        emb.embed(mkv, s, emb.SRT_TRACK, False)
    assert mkv.read_bytes() == b"ORIGINAL"
    assert sorted(p.name for p in d.iterdir()) == ["a.hun.srt", "a.mkv"]


# ── főprogram ───────────────────────────────────────────────────────────────

def test_split_name_language_from_filename(tmp_path):
    mkv, lang = emb.split_name(tmp_path / "Sorozat - S01E01.hun.srt")
    assert (mkv.name, lang) == ("Sorozat - S01E01.mkv", "hun")
    assert emb.split_name(tmp_path / "Sorozat - S01E01.eng.srt")[1] == "eng"
    assert emb.split_name(tmp_path / "Sorozat - S01E01.ja.srt")[1] == "jpn"      # alias


def test_split_name_lang_option_overrides_and_fills_in(tmp_path):
    mkv, lang = emb.split_name(tmp_path / "Sorozat - S01E01.srt", "ko")
    assert (mkv.name, lang) == ("Sorozat - S01E01.mkv", "kor")
    assert emb.split_name(tmp_path / "Sorozat - S01E01.eng.srt", "hun")[1] == "hun"


def test_split_name_without_language_fails(tmp_path):
    with pytest.raises(emb.Fail, match="--lang"):
        emb.split_name(tmp_path / "Sorozat - S01E01.srt")
    with pytest.raises(emb.Fail, match="--lang"):
        emb.split_name(tmp_path / "Sorozat - S01E01.hun.clean.srt")
    with pytest.raises(emb.Fail, match="nyelvkód"):
        emb.split_name(tmp_path / "x.srt", "magyar")


def test_srt_track_titles():
    assert emb.srt_track("hun").title == "Magyar"
    assert emb.srt_track("eng").title == "English"
    assert emb.srt_track("chi").title == "Chinese"
    assert emb.srt_track("chi", "Chinese (Simplified)").title == "Chinese (Simplified)"
    assert emb.srt_track("xyz").title == "xyz"


# ── jelölő címke: a kiadó azonos című sávja nem keveredik bele ─────────────

def marked(index, lang, kind, codec, title, default=0):
    s = sub(index, lang, codec, title, default)
    s["tags"]["SUBTR"] = kind
    return s


def test_release_english_track_is_not_ours():
    eng = emb.srt_track("eng")
    assert not eng.owns(sub(2, "eng", "subrip", "English"))            # a kiadóé
    assert eng.owns(marked(3, "eng", "srt", "subrip", "English"))
    assert eng.owns(marked(3, "eng", "srt", "subrip", "Régi cím"))     # --title-csere után is
    assert not eng.owns(marked(3, "hun", "srt", "subrip", "English"))  # más nyelv
    assert not eng.owns(marked(3, "eng", "ass", "ass", "English"))     # más fajta


def test_legacy_hungarian_titles_without_marker_still_ours():
    assert emb.SRT_TRACK.owns(sub(2, "hun", "subrip", "Magyar"))
    assert emb.ASS_TRACK.owns(sub(2, "hun", "ass", "Magyar (dobozos)"))
    assert not emb.srt_track("eng").owns(sub(2, "eng", "subrip", "Magyar"))


def test_mux_cmd_sets_marker_and_language():
    streams = VA + [sub(2, "eng", "subrip", "English", default=1), marked(3, "eng", "srt", "subrip", "English")]
    cmd, keep, pos = emb.mux_cmd("ffmpeg", "a.mkv", "a.srt", "t.mkv", streams, emb.srt_track("eng"), False)
    assert maps(cmd) == ["0:v", "0:a?", "0:2", "1", "0:t?"]       # a kiadó angolja marad, a saját cserélődik
    md = opts(cmd, "-metadata")
    assert ("-metadata:s:s:1", "language=eng") in md
    assert ("-metadata:s:s:1", "title=English") in md
    assert ("-metadata:s:s:1", "SUBTR=srt") in md


def test_is_ours():
    assert emb.is_ours(marked(2, "eng", "srt", "subrip", "English"))
    assert emb.is_ours(sub(2, "hun", "ass", "Magyar"))
    assert not emb.is_ours(sub(2, "eng", "subrip", "English"))


@pytest.mark.parametrize("val,expected", [("1", True), ("igen", True), ("true", True),
                                          ("0", False), ("", False), ("nem", False)])
def test_env_flag(monkeypatch, val, expected):
    monkeypatch.setenv("MKV_SUBS_DEFAULT", val)
    assert emb.env_flag("MKV_SUBS_DEFAULT") is expected


def test_main_default_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    srt = tmp_path / "Sorozat - S01E01.hun.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\na\n", encoding="utf-8")
    (tmp_path / "Sorozat - S01E01.mkv").write_bytes(b"x")
    seen = []
    monkeypatch.setattr(emb, "embed", lambda mkv, s, track, default: seen.append(default) or [])
    monkeypatch.setenv("MKV_SUBS_DEFAULT", "1")
    assert emb.main([str(srt)]) == 0
    assert emb.main([str(srt), "--no-default"]) == 0
    monkeypatch.delenv("MKV_SUBS_DEFAULT")
    assert emb.main([str(srt)]) == 0
    assert emb.main([str(srt), "--default"]) == 0
    assert seen == [True, False, False, True]
    assert srt.exists()                                    # a .hun.srt a helyén marad


def test_main_batch_continues_after_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MKV_SUBS_DEFAULT", raising=False)
    bad = tmp_path / "Nincs videó - S01E01.hun.srt"
    bad.write_text("1\n00:00:01,000 --> 00:00:02,000\na\n", encoding="utf-8")
    empty = tmp_path / "Üres - S01E01.hun.srt"
    empty.write_text("", encoding="utf-8")
    (tmp_path / "Üres - S01E01.mkv").write_bytes(b"x")
    good = tmp_path / "Jó - S01E01.hun.srt"
    good.write_text("1\n00:00:01,000 --> 00:00:02,000\na\n", encoding="utf-8")
    (tmp_path / "Jó - S01E01.mkv").write_bytes(b"x")
    seen = []
    monkeypatch.setattr(emb, "embed", lambda mkv, s, track, default: seen.append(mkv.name) or [])
    assert emb.main([str(bad), str(empty), str(good)]) == 1
    assert seen == ["Jó - S01E01.mkv"]


# ── valódi ffmpeg-gel (ha van) ──────────────────────────────────────────────

def _tool(name):
    for cand in (f"/opt/homebrew/opt/ffmpeg-full/bin/{name}", shutil.which(name)):
        if cand and Path(cand).exists():
            return cand
    return None


@pytest.mark.skipif(not (_tool("ffmpeg") and _tool("ffprobe")), reason="nincs ffmpeg/ffprobe")
def test_embed_real_ffmpeg(tmp_path, monkeypatch):
    ff, fp = _tool("ffmpeg"), _tool("ffprobe")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MKV_SUBS_DEFAULT", raising=False)
    s = tmp_path / "s.srt"
    s.write_text("1\n00:00:00,500 --> 00:00:01,500\nx\n", encoding="utf-8")
    mkv = tmp_path / "Sorozat - S01E01.mkv"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "color=s=320x240:d=2",
                    "-f", "lavfi", "-i", "sine=d=2", "-i", str(s),
                    "-map", "0", "-map", "1", "-map", "2", "-c:v", "mpeg4", "-c:a", "mp2", "-c:s", "srt",
                    "-metadata:s:s:0", "language=eng",
                    "-disposition:s:0", "default+forced", str(mkv)], check=True)
    srt = tmp_path / "Sorozat - S01E01.hun.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:01,500\nszia\n", encoding="utf-8")

    def subs():
        out = json.loads(subprocess.run(
            [fp, "-v", "error", "-show_entries",
             "stream=codec_type,codec_name:stream_tags:stream_disposition", "-of", "json", str(mkv)],
            capture_output=True, text=True, check=True).stdout)
        return [(x["codec_name"], emb.tags(x).get("language"), emb.tags(x).get("title"),
                 x["disposition"]["default"], x["disposition"]["forced"])
                for x in out["streams"] if x["codec_type"] == "subtitle"]

    assert emb.main([str(srt)]) == 0
    assert subs() == [("subrip", "eng", None, 1, 1), ("subrip", "hun", "Magyar", 0, 0)]
    assert emb.main([str(srt), "--default"]) == 0          # újrafuttatás: csere, nem duplázás
    assert subs() == [("subrip", "hun", "Magyar", 1, 0), ("subrip", "eng", None, 0, 1)]
    assert srt.exists() and not list(tmp_path.glob(".tmp_*"))

    # angol: a kiadó angolja (cím nélkül) marad; --title-cserénél a saját cserélődik
    eng = tmp_path / "Sorozat - S01E01.eng.srt"
    eng.write_text("1\n00:00:00,500 --> 00:00:01,500\nhello\n", encoding="utf-8")
    assert emb.main([str(eng)]) == 0
    assert emb.main([str(eng), "--title", "English (CC)"]) == 0
    assert subs() == [("subrip", "hun", "Magyar", 1, 0), ("subrip", "eng", None, 0, 1),
                      ("subrip", "eng", "English (CC)", 0, 0)]
