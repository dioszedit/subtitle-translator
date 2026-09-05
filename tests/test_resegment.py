"""subtr.tasks.resegment — tördelés, idő-arányos bontás, riport."""

from subtr.tasks import resegment as rs

HU = rs.LANG["hu"]


def test_parse_preserves_header_and_roundtrip():
    text = "1\n00:00:01,000 --> 00:00:02,500\nSzia\n\n2\n00:00:03,000 --> 00:00:04,000\nHello\nvilág\n"
    cues = rs.parse(text)
    assert cues[0]["t0"] == 1.0 and cues[0]["t1"] == 2.5
    assert cues[1]["text"] == "Hello\nvilág"
    assert rs.write_preserve(cues) == text


def test_parse_keeps_nonstandard_block_raw():
    cues = rs.parse("WEBVTT\n\n1\n00:00:01,000 --> 00:00:02,000\nX\n")
    assert cues[0] == {"raw": "WEBVTT"} and "header" in cues[1]


def test_wrap_lines_breaks_before_conjunction_within_limit():
    text = "Ez egy hosszú mondat, amit két sorba kell tördelni, mert nem fér el egyben"
    lines = rs.wrap_lines(text, 42, 2, HU)
    assert len(lines) == 2 and all(rs.vlen(l) <= 42 for l in lines)
    assert " ".join(lines) == text
    assert not lines[0].rstrip().endswith((" a", " az", " egy"))


def test_wrap_lines_keeps_outer_italic_tag_per_line():
    text = "<i>" + "szó " * 15 + "vége</i>"
    lines = rs.wrap_lines(text, 42, 2, HU)
    assert all(l.startswith("<i>") and l.endswith("</i>") for l in lines)


def test_wrap_lines_returns_none_when_it_does_not_fit():
    assert rs.wrap_lines("x" * 100, 42, 2, HU) is None


def test_reflow_cue_is_idempotent_and_skips_dialogue():
    assert rs.reflow_cue("Rövid\nkét sor", 42, 2, HU, False) == (None, [], False)
    assert rs.reflow_cue("- Nagyon " + "hosszú " * 8 + "\n- Válasz", 42, 2, HU, False) == \
        (None, ["dialog-too-long"], False)
    new, flags, need_split = rs.reflow_cue("egy " * 30, 42, 2, HU, False)
    assert new is None and flags == ["too-long-for-2-lines"] and need_split


def test_split_cue_divides_time_proportionally_without_overlap():
    cue = {"t0": 10.0, "t1": 16.0, "text": "alma " * 40}
    parts = rs.split_cue(cue, 42, 2, min_dur=1.0, min_gap=0.08, lang=HU)
    assert len(parts) >= 2
    assert parts[0]["t0"] == 10.0 and parts[-1]["t1"] == 16.0
    for a, b in zip(parts, parts[1:]):
        assert a["t1"] < b["t0"]
    assert " ".join(p["text"].replace("\n", " ") for p in parts).split() == cue["text"].split()


def test_split_cue_gives_up_without_time():
    cue = {"t0": 0.0, "t1": 0.2, "text": "alma " * 40}
    assert rs.split_cue(cue, 42, 2, 1.0, 0.08, HU) == [cue]


def test_report_flags(capsys):
    cues = rs.parse(
        "1\n00:00:00,000 --> 00:00:00,500\n" + "x" * 50 + "\n\n"     # CPS + LINE + SHORT
        "2\n00:00:00,520 --> 00:00:09,000\nok\n")                    # LONG, GAP (0.02 < 0.08)
    cfg = dict(max_chars=42, max_lines=2, target_cps=17.0, min_dur=1.0, max_dur=7.0, min_gap=0.08)
    rows = rs.report(cues, cfg)
    flags = {i: fl for i, _, fl in rows}
    assert set(flags[0]) == {"CPS", "LINE", "SHORT", "GAP"}
    assert flags[1] == ["LONG"]


def test_main_reflow_writes_output_and_strips_bom(tmp_path, capsys):
    src = tmp_path / "in.srt"
    src.write_text("﻿1\n00:00:01,000 --> 00:00:05,000\n" + "szó " * 12 + "\n", encoding="utf-8")
    out = tmp_path / "out.srt"
    rs.main(["reflow", str(src), "-o", str(out)])
    text = out.read_text(encoding="utf-8")
    assert not text.startswith("﻿")
    assert text.startswith("1\n00:00:01,000 --> 00:00:05,000\n")
    assert len(rs.parse(text)[0]["text"].split("\n")) == 2
    assert "1 cue újratördelve" in capsys.readouterr().err


def test_main_reflow_split_renumbers(tmp_path):
    src = tmp_path / "in.srt"
    src.write_text("7\n00:00:01,000 --> 00:00:09,000\n" + "alma " * 40 + "\n", encoding="utf-8")
    out = tmp_path / "out.srt"
    rs.main(["reflow", str(src), "-o", str(out), "--split"])
    cues = rs.parse(out.read_text(encoding="utf-8"))
    assert len(cues) >= 2
    assert [c["header"].split("\n")[0] for c in cues] == [str(i) for i in range(1, len(cues) + 1)]
