"""addons/hardsub-cover — SRT-olvasás, ASS-szöveg, átfedés-elrendezés, --mux.

A muxoló magot (embed_subs.embed) a test_embed_subs.py teszteli részletesen."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ADDON_DIR = Path(__file__).resolve().parent.parent / "addons" / "hardsub-cover"
_spec = importlib.util.spec_from_file_location("cover_ass", ADDON_DIR / "cover_ass.py")
cover = importlib.util.module_from_spec(_spec)
sys.modules["cover_ass"] = cover
_spec.loader.exec_module(cover)


@pytest.fixture
def cfg(monkeypatch):
    for env, *_ in cover.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)

    class A:
        pass
    a = A()
    for name in cover.SETTINGS:
        setattr(a, name, None)
    return cover.resolve(a)


def cue(start, end, *lines):
    return {"start": start, "end": end, "lines": list(lines), "line": 0}


# ── időbélyeg ───────────────────────────────────────────────────────────────

def test_parse_ts_comma_and_dot():
    assert cover.parse_ts("00:00:03,500") == 350
    assert cover.parse_ts("00:00:03.500") == 350
    assert cover.parse_ts("1:02:03,040") == (3723 * 100 + 4)


def test_parse_ts_short_fraction_and_rounding():
    assert cover.parse_ts("00:00:01,5") == 150
    assert cover.parse_ts("00:00:01,995") == 200


def test_parse_ts_bad_raises():
    with pytest.raises(ValueError):
        cover.parse_ts("00:00:xx,000")


def test_ass_time():
    assert cover.ass_time(3723 * 100 + 4) == "1:02:03.04"


# ── SRT-olvasás: nem dob el semmit csendben ────────────────────────────────

def test_parse_srt_extra_blank_lines_keep_all():
    srt = "1\n00:00:01,000 --> 00:00:02,000\na\n\n\n\n2\n00:00:03,000 --> 00:00:04,000\nb\n"
    cues, problems = cover.parse_srt(srt)
    assert [c["lines"] for c in cues] == [["a"], ["b"]]
    assert problems == []


def test_parse_srt_missing_index_and_crlf_bom_free():
    srt = "00:00:01,000 --> 00:00:02,000\r\na\r\n\r\n00:00:03,000 --> 00:00:04,000\r\nb\r\n"
    cues, problems = cover.parse_srt(srt)
    assert [c["lines"] for c in cues] == [["a"], ["b"]]
    assert problems == []


def test_parse_srt_glued_cues_without_blank_line():
    srt = "1\n00:00:01,000 --> 00:00:02,000\na\n2\n00:00:03,000 --> 00:00:04,000\nb\n"
    cues, _ = cover.parse_srt(srt)
    assert [c["lines"] for c in cues] == [["a"], ["b"]]


def test_parse_srt_dot_timestamp_ok():
    cues, problems = cover.parse_srt("1\n00:00:03.500 --> 00:00:04.000\npont\n")
    assert cues[0]["start"] == 350 and problems == []


def test_parse_srt_reports_instead_of_crashing():
    srt = ("1\n00:00:01,000 --> 00:00:xx,000\nrossz\n\n"
           "2\n00:00:03,000 --> 00:00:04,000\njó\n\nárva szöveg\n\n"
           "3\n00:00:05,000 --> 00:00:05,000\nnulla hossz\n\n"
           "4\n00:00:06,000 --> 00:00:07,000\n\n")
    cues, problems = cover.parse_srt(srt)
    assert [c["lines"] for c in cues] == [["jó"]]
    joined = " | ".join(problems)
    assert "hibás időbélyeg" in joined
    assert "árva szöveg" in joined
    assert "nem a kezdete után" in joined
    assert "üres felirat" in joined


# ── ASS-szöveg ──────────────────────────────────────────────────────────────

def test_ass_text_keeps_italic_bold_as_override_tags():
    assert cover.ass_text("<i>♫ dal ♫</i>") == r"{\i1}♫ dal ♫{\i0}"
    assert cover.ass_text("<b>X</b>") == r"{\b1}X{\b0}"


def test_ass_text_drops_font_tag_and_neutralizes_braces():
    assert cover.ass_text('<font color="#fff">a {b}</font>') == "a (b)"


def test_ass_text_backslash_cannot_become_control():
    out = cover.ass_text(r"C:\new\Nx\hy\z")
    assert "\\n" not in out and "\\N" not in out and "\\h" not in out
    assert r"\z" in out


def test_ass_text_less_than_not_a_tag():
    assert cover.ass_text("1 < 2 és <3") == "1 < 2 és <3"


# ── elrendezés ──────────────────────────────────────────────────────────────

def test_layout_single_line_at_burned_in_position(cfg):
    [(s, e, y, _)] = cover.layout([cue(0, 100, "a")], cfg)
    assert (s, e, y) == (0, 100, cfg["y"])


def test_layout_two_lines_bottom_line_stays(cfg):
    [(_, _, y, _)] = cover.layout([cue(0, 100, "a", "b")], cfg)
    assert y == cfg["y"] - cfg["line_height"] // 2


def test_layout_sequential_cues_one_event_each(cfg):
    ev = cover.layout([cue(0, 100, "a"), cue(100, 200, "b")], cfg)
    assert [(s, e, y) for s, e, y, _ in ev] == [(0, 100, cfg["y"]), (100, 200, cfg["y"])]


def test_layout_overlap_stacks_then_drops_back(cfg):
    song, talk = cue(0, 300, "dal"), cue(100, 400, "egy", "kettő")
    ev = [(s, e, y, q["lines"][0]) for s, e, y, q in cover.layout([song, talk], cfg)]
    base, lh, pad = cfg["y"], cfg["line_height"], cfg["pad"]
    above = round(base - (lh + 2 * pad) - lh / 2)
    assert ev == [
        (0, 300, base, "dal"),                 # a korábbi marad a helyén
        (100, 300, above, "egy"),              # az átfedő fölé kerül
        (300, 400, base - lh // 2, "egy"),     # a dal után visszacsúszik
    ]


def test_layout_stacked_boxes_do_not_overlap(cfg):
    a, b = cue(0, 100, "a"), cue(0, 100, "b")
    ys = sorted(y for _, _, y, _ in cover.layout([a, b], cfg))
    assert ys[1] - ys[0] >= cfg["line_height"] + 2 * cfg["pad"]


def test_overlaps_count():
    assert cover.overlaps([cue(0, 100, "a"), cue(50, 150, "b"), cue(200, 300, "c")]) == 1


def test_header_box_follows_text(cfg):
    style = next(l for l in cover.header(cfg).splitlines() if l.startswith("Style:"))
    fields = style.split(",")
    assert fields[15] == "3"                  # BorderStyle=3: szöveghez igazodó doboz
    assert fields[16] == str(cfg["pad"])      # a doboz margója
    assert "\\p1" not in cover.build_ass([cue(0, 100, "a")], cfg)  # nincs rajzolt téglalap


def test_srt_to_ass_end_to_end(tmp_path, cfg):
    src = tmp_path / "Sorozat - S01E01.hun.srt"
    src.write_text("\ufeff1\n00:00:01,000 --> 00:00:02,000\n<i>szia</i>\n", encoding="utf-8")
    dst = tmp_path / "x.ass"
    n, ov, problems = cover.srt_to_ass(src, dst, cfg)
    assert (n, ov, problems) == (1, 0, [])
    assert r"Dialogue: 0,0:00:01.00,0:00:02.00,Text,,0,0,0,,{\pos(640,650)}{\i1}szia{\i0}" in dst.read_text()


def test_srt_to_ass_empty_file_fails(tmp_path, cfg):
    src = tmp_path / "a.hun.srt"
    src.write_text("", encoding="utf-8")
    with pytest.raises(cover.Fail):
        cover.srt_to_ass(src, tmp_path / "a.ass", cfg)


# ── beállítások ─────────────────────────────────────────────────────────────

def test_resolve_precedence(monkeypatch, cfg):
    monkeypatch.setenv("HARDSUB_Y", "600")
    monkeypatch.setenv("HARDSUB_PAD", "20")

    class A:
        pass
    a = A()
    for name in cover.SETTINGS:
        setattr(a, name, None)
    a.pad = 5
    c = cover.resolve(a)
    assert (c["y"], c["y_src"]) == (600, ".env")
    assert (c["pad"], c["pad_src"]) == (5, "kapcsoló")
    assert c["size_src"] == "alap"


@pytest.mark.parametrize("env,val", [("HARDSUB_FONT_SIZE", "0"), ("HARDSUB_PAD", "-1"),
                                     ("HARDSUB_BOX_ALPHA", "256"), ("HARDSUB_PLAY_RES", "720p"),
                                     ("HARDSUB_Y", "1.5")])
def test_resolve_rejects_bad_values(monkeypatch, cfg, env, val):
    monkeypatch.setenv(env, val)

    class A:
        pass
    a = A()
    for name in cover.SETTINGS:
        setattr(a, name, None)
    with pytest.raises(SystemExit):
        cover.resolve(a)


# ── főprogram ───────────────────────────────────────────────────────────────

def test_main_batch_continues_after_error(tmp_path, monkeypatch, capsys):
    for env, *_ in cover.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "Rossz.hun.srt"
    bad.write_text("", encoding="utf-8")
    good = tmp_path / "Jó.hun.srt"
    good.write_text("1\n00:00:01,000 --> 00:00:02,000\na\n", encoding="utf-8")
    rc = cover.main([str(bad), str(good)])
    assert rc == 1
    assert (tmp_path / "Jó.hun.dobozos.ass").exists()


def test_cover_mux_uses_shared_core_as_default_ass(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cover.embed_subs, "embed",
                        lambda mkv, sub, track, default: seen.update(track=track, default=default) or [])
    cover.mux(tmp_path / "a.mkv", tmp_path / "a.ass")
    assert seen == {"track": cover.ASS_TRACK, "default": True}
    assert cover.ASS_TRACK.title == "Magyar (dobozos)"


def test_main_mux_without_out_dir_leaves_no_sidecar(tmp_path, monkeypatch):
    for env, *_ in cover.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.chdir(tmp_path)
    srt = tmp_path / "Sorozat - S01E01.hun.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\na\n", encoding="utf-8")
    (tmp_path / "Sorozat - S01E01.mkv").write_bytes(b"x")
    seen = []
    monkeypatch.setattr(cover, "mux", lambda mkv, ass: seen.append(ass.read_text()) or [])
    assert cover.main([str(srt), "--mux"]) == 0
    assert seen and "Dialogue:" in seen[0]
    assert not list(tmp_path.glob("*.ass"))


# ── valódi ffmpeg-gel (ha van) ──────────────────────────────────────────────

def _tool(name):
    for cand in (f"/opt/homebrew/opt/ffmpeg-full/bin/{name}", shutil.which(name)):
        if cand and Path(cand).exists():
            return cand
    return None


@pytest.mark.skipif(not (_tool("ffmpeg") and _tool("ffprobe")), reason="nincs ffmpeg/ffprobe")
def test_cover_mux_real_ffmpeg_idempotent_and_keeps_foreign_hun(tmp_path, monkeypatch):
    ff = _tool("ffmpeg")
    monkeypatch.chdir(tmp_path)
    for env, *_ in cover.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    s = tmp_path / "s.srt"
    s.write_text("1\n00:00:00,500 --> 00:00:01,500\nx\n", encoding="utf-8")
    mkv = tmp_path / "Sorozat - S01E01.mkv"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "color=s=320x240:d=2",
                    "-f", "lavfi", "-i", "sine=d=2", "-i", str(s), "-i", str(s),
                    "-map", "0", "-map", "1", "-map", "2", "-map", "3",
                    "-c:v", "mpeg4", "-c:a", "mp2",
                    "-metadata:s:s:0", "language=eng",
                    "-metadata:s:s:1", "language=hun", "-metadata:s:s:1", "title=Külső",
                    str(mkv)], check=True)
    srt = tmp_path / "Sorozat - S01E01.hun.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:01,500\n<i>szia</i>\n", encoding="utf-8")
    assert cover.main([str(srt), "--mux"]) == 0
    assert cover.main([str(srt), "--mux"]) == 0          # újrafuttatható
    out = json.loads(subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-show_entries",
         "stream=codec_type,codec_name:stream_tags:stream_disposition=default",
         "-of", "json", str(mkv)], capture_output=True, text=True, check=True).stdout)
    subs = [x for x in out["streams"] if x["codec_type"] == "subtitle"]
    titles = [cover.embed_subs.tags(x).get("title") for x in subs]
    assert titles.count("Magyar (dobozos)") == 1 and "Külső" in titles
    assert cover.ASS_TRACK.owns(subs[0]) and subs[0]["disposition"]["default"] == 1
    assert sum(x["codec_type"] == "audio" for x in out["streams"]) == 1
    assert not list(tmp_path.glob(".tmp_*")) and not list(tmp_path.glob("*.ass"))
