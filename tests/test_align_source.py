"""addons/align-source/align_source.py — forrás igazítása összevont magyar cue-khoz."""

import importlib.util
from pathlib import Path

ADDON = Path(__file__).resolve().parent.parent / "addons" / "align-source" / "align_source.py"
_spec = importlib.util.spec_from_file_location("align_source", ADDON)
al = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(al)


def _ts(s):
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _write(path, cues):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(f"{n}\n{_ts(a)} --> {_ts(b)}\n{t}" for n, a, b, t in cues) + "\n",
                    encoding="utf-8")


def _series(tmp_path):
    _write(tmp_path / "output" / "S - S01E01.hun.srt", [
        (1, 0, 4, "Összevont magyar sor."), (2, 5, 6, "[Saját tábla]"), (3, 10, 12, "Vége.")])
    _write(tmp_path / "input" / "S - S01E01.eng.srt", [
        (1, 0, 2, "First."), (2, 2.1, 3.9, "Second."), (3, 10.2, 11.8, "End."), (4, 30, 31, "Missed.")])
    return tmp_path


def test_aligns_to_hungarian_numbers_and_lists_unmatched(tmp_path, capsys):
    s = _series(tmp_path)
    assert al.main([str(s / "output" / "S - S01E01.hun.srt"), "--lang", "eng"]) == 0
    out = (s / "input" / "aligned" / "S - S01E01.eng.srt").read_text(encoding="utf-8")
    blocks = [b.split("\n") for b in out.strip().split("\n\n")]
    assert [b[0] for b in blocks] == ["1", "2", "3"]
    assert blocks[0][2:] == ["First.", "Second."]
    assert blocks[1][2:] == [al.NO_SOURCE]
    assert blocks[2][2:] == ["End."]
    unmatched = (s / "input" / "aligned" / "S - S01E01.eng.unmatched.txt").read_text(encoding="utf-8")
    assert "Missed." in unmatched


def test_explicit_src_and_output(tmp_path):
    s = _series(tmp_path)
    out = tmp_path / "x" / "aligned.srt"
    assert al.main([str(s / "output" / "S - S01E01.hun.srt"),
                    "--src", str(s / "input" / "S - S01E01.eng.srt"), "-o", str(out)]) == 0
    assert out.exists()


def test_missing_source_is_reported(tmp_path, capsys):
    _write(tmp_path / "output" / "S - S01E02.hun.srt", [(1, 0, 1, "x")])
    assert al.main([str(tmp_path / "output" / "S - S01E02.hun.srt"), "--lang", "eng"]) == 1
    assert "nincs hozzá forrás-SRT" in capsys.readouterr().out


def test_src_with_multiple_files_is_rejected(tmp_path, capsys):
    s = _series(tmp_path)
    _write(s / "output" / "S - S01E02.hun.srt", [(1, 0, 1, "x")])
    assert al.main([str(s / "output" / "S - S01E01.hun.srt"), str(s / "output" / "S - S01E02.hun.srt"),
                    "--src", "a.srt"]) == 1


def test_output_with_multiple_sources_is_rejected(tmp_path, capsys):
    s = _series(tmp_path)
    _write(s / "input" / "S - S01E01.chi.srt", [(1, 0, 4, "中文")])
    out = tmp_path / "x.srt"
    assert al.main([str(s / "output" / "S - S01E01.hun.srt"), "-o", str(out)]) == 1
    assert not out.exists()
    assert "csak egy forrással" in capsys.readouterr().out


def test_lang_aliases_are_normalised(tmp_path):
    s = _series(tmp_path)
    assert al.main([str(s / "output" / "S - S01E01.hun.srt"), "--lang", "en"]) == 0
    assert (s / "input" / "aligned" / "S - S01E01.eng.srt").exists()


def test_split_source_line_fills_second_hungarian_cue(tmp_path):
    _write(tmp_path / "output" / "S - S01E01.hun.srt", [(1, 0, 3, "Első fele,"), (2, 3, 6, "második fele.")])
    _write(tmp_path / "input" / "S - S01E01.eng.srt", [(1, 0, 6, "One long sentence.")])
    assert al.main([str(tmp_path / "output" / "S - S01E01.hun.srt"), "--lang", "eng"]) == 0
    out = (tmp_path / "input" / "aligned" / "S - S01E01.eng.srt").read_text(encoding="utf-8")
    assert al.NO_SOURCE not in out
    assert out.count("One long sentence.") == 2


def test_translators_own_sign_card_keeps_no_source_marker(tmp_path):
    _write(tmp_path / "output" / "S - S01E01.hun.srt",
           [(1, 11, 14, "[Malom-fogadó]"), (2, 11, 13, "Védjétek a kapitányt!")])
    _write(tmp_path / "input" / "S - S01E01.eng.srt", [(1, 11, 13, "Protect the captain!")])
    assert al.main([str(tmp_path / "output" / "S - S01E01.hun.srt"), "--lang", "eng"]) == 0
    blocks = (tmp_path / "input" / "aligned" / "S - S01E01.eng.srt").read_text(encoding="utf-8").strip().split("\n\n")
    assert blocks[0].endswith(al.NO_SOURCE)
    assert blocks[1].endswith("Protect the captain!")


def test_file_without_hun_tag_gets_clear_message(tmp_path, capsys):
    _write(tmp_path / "output" / "S - S01E01.hu.srt", [(1, 0, 1, "x")])
    _write(tmp_path / "input" / "S - S01E01.eng.srt", [(1, 0, 1, "x")])
    assert al.main([str(tmp_path / "output" / "S - S01E01.hu.srt"), "--lang", "eng"]) == 1
    assert "nincs „.hun.” jelölés" in capsys.readouterr().out


def test_merge_output_finds_its_source(tmp_path):
    _write(tmp_path / "output" / "S - S01E01.hun.merge.srt", [(1, 0, 2, "Szia.")])
    _write(tmp_path / "input" / "S - S01E01.eng.srt", [(1, 0, 2, "Hi.")])
    assert al.main([str(tmp_path / "output" / "S - S01E01.hun.merge.srt"), "--lang", "eng"]) == 0
    assert (tmp_path / "input" / "aligned" / "S - S01E01.eng.srt").exists()
