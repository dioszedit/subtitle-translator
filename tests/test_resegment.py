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


# ---- merge --------------------------------------------------------------------
CFG = dict(max_chars=42, max_lines=2, target_cps=17.0, min_dur=1.0,
           max_dur=7.0, min_gap=0.08, max_gap=0.5)


def _cue(t0, t1, text):
    return {"header": "x", "t0": t0, "t1": t1, "text": text}


def test_merge_joins_fast_continuation():
    cues = [_cue(1.0, 1.8, "Ha most elmész a fővárosba,"),
            _cue(1.8, 3.0, "soha nem jössz vissza.")]
    out, n = rs.merge_cues(cues, CFG, HU)
    assert n == 1 and len(out) == 1
    assert out[0]["t0"] == 1.0 and out[0]["t1"] == 3.0
    assert out[0]["text"] == "Ha most elmész a fővárosba,\nsoha nem jössz vissza."


def test_merge_keeps_sentence_end_gap_dialogue_and_italic_apart():
    end = [_cue(1.0, 1.5, "Menj el!"), _cue(1.5, 2.0, "Nem megyek.")]
    gap = [_cue(1.0, 1.5, "Ha most elmész,"), _cue(2.5, 3.0, "nem jössz vissza.")]
    dia = [_cue(1.0, 1.5, "- Ki az?\n- Én vagyok"), _cue(1.5, 2.0, "és te.")]
    ita = [_cue(1.0, 1.5, "<i>Ha most elmész,</i>"), _cue(1.5, 2.0, "nem jössz vissza.")]
    for cues in (end, gap, dia, ita):
        out, n = rs.merge_cues(cues, CFG, HU)
        assert n == 0 and len(out) == 2


def test_merge_skips_slow_and_too_long():
    slow = [_cue(1.0, 4.0, "Ha most elmész,"), _cue(4.0, 7.0, "nem jössz vissza.")]
    long_ = [_cue(1.0, 2.0, "Ha most elmész a fővárosba a lovaddal együtt,"),
             _cue(2.0, 3.0, "soha többé nem jössz vissza ide a hegyekbe, hidd el nekem.")]
    for cues in (slow, long_):
        assert rs.merge_cues(cues, CFG, HU)[1] == 0


def test_merge_keeps_outer_italic_when_both_italic():
    cues = [_cue(1.0, 1.6, "<i>Ha most elmész,</i>"), _cue(1.6, 2.6, "<i>nem jössz vissza.</i>")]
    out, n = rs.merge_cues(cues, CFG, HU)
    assert n == 1 and out[0]["text"] == "<i>Ha most elmész, nem jössz vissza.</i>"


def test_merge_song_lines_drop_inner_marks():
    cues = [_cue(1.0, 1.6, "<i>♫ Mi történik most velem? ♫</i>"),
            _cue(1.6, 2.4, "<i>♫ a szívem hirtelen kihagy egy ütemet. ♫</i>")]
    out, n = rs.merge_cues(cues, CFG, HU)
    assert n == 1
    assert out[0]["text"] == ("<i>♫ Mi történik most velem?</i>\n"
                              "<i>a szívem hirtelen kihagy egy ütemet. ♫</i>")


def test_merge_song_short_lines_stay_one_line():
    cues = [_cue(1.0, 1.4, "♪ Melletted ♪"), _cue(1.4, 1.8, "♪ még az évszak is ♪")]
    out, n = rs.merge_cues(cues, CFG, HU)
    assert n == 1 and out[0]["text"] == "♪ Melletted még az évszak is ♪"


def test_merge_keeps_song_and_dialogue_apart():
    cues = [_cue(1.0, 1.4, "♫ Melletted ♫"), _cue(1.4, 1.8, "ha most elmész,")]
    assert rs.merge_cues(cues, CFG, HU)[1] == 0


def test_merge_ref_allows_sentence_end_within_same_ref_cue():
    cues = [_cue(1.0, 1.5, "Menj el."), _cue(1.5, 2.2, "Most azonnal.")]
    assert rs.merge_cues(cues, CFG, HU)[1] == 0
    ref = [{"t0": 0.9, "t1": 2.3, "text": "走 现在就走"}]
    out, n = rs.merge_cues(cues, CFG, HU, ref)
    assert n == 1 and out[0]["text"] == "Menj el. Most azonnal."


def test_extend_into_gap_without_overlap():
    cues = [_cue(1.0, 1.5, "Ez egy elég hosszú mondat."), _cue(2.0, 4.0, "Igen.")]
    assert rs.extend_cues(cues, CFG) == 1
    assert abs(cues[0]["t1"] - (2.0 - 0.081)) < 1e-9
    assert cues[1]["t1"] == 4.0


def test_main_merge_renumbers_and_reports(tmp_path, capsys):
    src = tmp_path / "in.srt"
    src.write_text("5\n00:00:01,000 --> 00:00:01,800\nHa most elmész a fővárosba,\n\n"
                   "6\n00:00:01,800 --> 00:00:03,000\nsoha nem jössz vissza.\n\n"
                   "7\n00:00:05,000 --> 00:00:06,000\nIgen.\n", encoding="utf-8")
    out = tmp_path / "out.srt"
    rs.main(["merge", str(src), "-o", str(out)])
    cues = rs.parse(out.read_text(encoding="utf-8"))
    assert [c["header"].split("\n")[0] for c in cues] == ["1", "2"]
    assert "3 -> 2 cue (1 összevonás)" in capsys.readouterr().err


def test_merge_does_not_join_new_capitalized_sentence_but_allows_names():
    cues = [_cue(1.0, 1.4, "Úrnőm,"), _cue(1.4, 2.2, "Nekem a Mesterséget kell vezetnem.")]
    assert rs.merge_cues(cues, CFG, HU)[1] == 0
    names = [_cue(1.0, 1.6, "Végül a vagyonukat elkobozták,"),
             _cue(1.6, 2.4, "Cui Shao'ant pedig lefokozták."),
             _cue(9.0, 12.0, "Azt mondják, Cui Shao'ant látták.")]
    out, n = rs.merge_cues(names, CFG, HU)
    assert n == 1 and out[0]["text"].startswith("Végül a vagyonukat elkobozták,")
