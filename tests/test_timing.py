"""subtr/timing.py — időbélyeg-alapú párosítás. Valós tmp fájlokon."""

from subtr.timing import assign, overlap_map, parse_timed


def _srt(path, cues):
    """cues: [(num, start_s, end_s, text)]"""
    def ts(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    body = "\n\n".join(f"{n}\n{ts(a)} --> {ts(b)}\n{t}" for n, a, b, t in cues)
    path.write_text(body + "\n", encoding="utf-8")
    return str(path)


def test_parse_timed_reads_times_and_lines(tmp_path):
    p = _srt(tmp_path / "a.srt", [(1, 1.5, 3.25, "Egy\nKettő"), (7, 10, 12, "Három")])
    cues = parse_timed(p)
    assert [c["num"] for c in cues] == ["1", "7"]
    assert cues[0]["start"] == 1.5 and cues[0]["end"] == 3.25
    assert cues[0]["lines"] == ["Egy", "Kettő"]


def test_parse_timed_handles_bom_and_dot_millis(tmp_path):
    p = tmp_path / "b.srt"
    p.write_text("﻿1\n00:00:01.500 --> 00:00:02.000\nHi\n", encoding="utf-8")
    cues = parse_timed(str(p))
    assert cues[0]["start"] == 1.5 and cues[0]["lines"] == ["Hi"]


def test_assign_many_to_one_by_overlap(tmp_path):
    target = parse_timed(_srt(tmp_path / "t.srt", [(1, 0, 4, "egybe"), (2, 5, 7, "külön")]))
    source = parse_timed(_srt(tmp_path / "s.srt", [
        (1, 0, 2, "a"), (2, 2.1, 3.9, "b"), (3, 5.2, 6.8, "c")]))
    buckets, dropped = assign(target, source)
    assert buckets == [[0, 1], [2]]
    assert dropped == []


def test_assign_nearest_within_gap_and_drops_far(tmp_path):
    target = parse_timed(_srt(tmp_path / "t.srt", [(1, 10, 12, "x")]))
    source = parse_timed(_srt(tmp_path / "s.srt", [
        (1, 12.5, 13, "közel"), (2, 40, 41, "messze")]))
    buckets, dropped = assign(target, source, max_gap=1.0)
    assert buckets == [[0]]
    assert dropped == [1]


def test_assign_works_after_renumbering(tmp_path):
    # a resegment utáni fájl sorszámai mások — a párosítás nem a sorszámot nézi
    target = parse_timed(_srt(tmp_path / "t.srt", [(1, 0, 2, "x"), (2, 3, 5, "y")]))
    source = parse_timed(_srt(tmp_path / "s.srt", [(40, 0.1, 1.9, "a"), (41, 3.1, 4.9, "b")]))
    buckets, _ = assign(target, source)
    assert buckets == [[0], [1]]


def test_long_credit_cue_does_not_steal_dialogue(tmp_path):
    target = parse_timed(_srt(tmp_path / "t.srt", [(1, 0, 3600, "stáblista"), (2, 5, 7, "a"), (3, 8, 9, "b")]))
    source = parse_timed(_srt(tmp_path / "s.srt", [(1, 5, 7, "A"), (2, 8, 9, "B")]))
    buckets, _ = assign(target, source)
    assert buckets == [[], [0], [1]]


def test_caption_cue_does_not_steal_exact_dialogue(tmp_path):
    target = parse_timed(_srt(tmp_path / "t.srt", [(1, 10, 15, "[tábla]"), (2, 11, 13, "mondat")]))
    source = parse_timed(_srt(tmp_path / "s.srt", [(1, 11, 13, "sentence")]))
    assert assign(target, source)[0] == [[], [0]]


def test_larger_source_coverage_wins_over_shorter_neighbour(tmp_path):
    # a forrás nagyobb része a második cue-ba esik, akkor is, ha az hosszabb
    target = parse_timed(_srt(tmp_path / "t.srt", [(1, 43.81, 44.23, "Rendben."), (2, 44.23, 47.27, "Továbbá…")]))
    source = parse_timed(_srt(tmp_path / "s.srt", [(1, 44.03, 44.67, "Also,")]))
    assert assign(target, source)[0] == [[], [0]]


def test_unsorted_inputs_are_handled(tmp_path):
    src_cues = [(i, 10 + i * 2, 11 + i * 2, f"s{i}") for i in range(1, 41)] + [(41, 1, 2, "late caption")]
    source = parse_timed(_srt(tmp_path / "s.srt", src_cues))
    target = parse_timed(_srt(tmp_path / "t.srt", [(1, 3, 5, "x"), (2, 0, 2, "first, but listed last")]))
    buckets, dropped = assign(target, source)
    assert 40 in buckets[1]                     # a fájl végi 1–2 mp-es tábla megtalálja a párját
    assert 40 not in dropped


def test_overlap_map_lists_all_overlaps(tmp_path):
    target = parse_timed(_srt(tmp_path / "t.srt", [(1, 0, 3, "a"), (2, 3, 6, "b")]))
    source = parse_timed(_srt(tmp_path / "s.srt", [(1, 0, 6, "egész")]))
    assert overlap_map(target, source) == [[(0, 3.0)], [(0, 3.0)]]
