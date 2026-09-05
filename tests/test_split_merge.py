"""subtr.tasks.split + merge — a pipeline determinisztikus gerince.

A split a CWD-relatív blocks/<alapnév>/ mappába ír, a merge onnan fűz;
a kettő oda-vissza útja és a checkpoint-védelmek (újra-split, hiányzó
blokk, kósza _HUN fájl) itt vannak lefedve."""

import os
from pathlib import Path

import pytest

from subtr.blocks import get_all_blocks, hun_path
from subtr.srt import parse_sections
from subtr.tasks import merge, split


def _srt(n, start=1):
    return "\n\n".join(
        f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\nSor {i}"
        for i in range(start, start + n)) + "\n"


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    src = tmp_path / "input" / "Sorozat - S01E01.eng.srt"
    src.write_text(_srt(7), encoding="utf-8")
    return tmp_path, src


def test_split_creates_named_blocks(workdir):
    tmp, src = workdir
    outdir = split.split_srt(str(src), block_size=3)
    assert outdir == os.path.join("blocks", "Sorozat - S01E01.eng")
    names = [os.path.basename(b) for b in get_all_blocks(outdir)]
    assert names == [
        "Sorozat - S01E01.eng_block_001_0001-0003.srt",
        "Sorozat - S01E01.eng_block_002_0004-0006.srt",
        "Sorozat - S01E01.eng_block_003_0007-0007.srt",
    ]
    # a blokkok együtt pont az eredeti szekciók
    nums = [s["num"] for b in get_all_blocks(outdir) for s in parse_sections(b)]
    assert nums == [str(i) for i in range(1, 8)]


def test_resplit_refuses_without_clean(workdir, capsys):
    tmp, src = workdir
    split.split_srt(str(src), block_size=3)
    with pytest.raises(SystemExit):
        split.split_srt(str(src), block_size=2)
    assert "--clean" in capsys.readouterr().out


def test_resplit_with_clean_removes_old_blocks_and_hun(workdir):
    tmp, src = workdir
    outdir = split.split_srt(str(src), block_size=3)
    Path(hun_path(get_all_blocks(outdir)[0])).write_text("x", encoding="utf-8")
    split.split_srt(str(src), block_size=7, clean=True)
    files = sorted(os.listdir(outdir))
    assert files == ["Sorozat - S01E01.eng_block_001_0001-0007.srt"]


def test_split_zero_based_numbering_uses_real_numbers(tmp_path, monkeypatch):
    """Egyes ripperek 0-tól számoznak: a 0 falsy, de a fájlnévbe a valódi
    sorszám kell, nem a pozíció."""
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "x.eng.srt"
    src.write_text(_srt(2, start=0), encoding="utf-8")
    outdir = split.split_srt(str(src), block_size=5)
    assert os.listdir(outdir) == ["x.eng_block_001_0000-0001.srt"]


def _translate_all(outdir):
    for b in get_all_blocks(outdir):
        Path(hun_path(b)).write_text(
            Path(b).read_text(encoding="utf-8").replace("Sor", "HU"), encoding="utf-8")


def test_merge_roundtrip(workdir, capsys):
    tmp, src = workdir
    outdir = split.split_srt(str(src), block_size=3)
    _translate_all(outdir)
    out = tmp / "output" / "Sorozat - S01E01.hun.srt"
    merge.main([outdir, str(out)])
    merged = parse_sections(str(out))
    assert [s["num"] for s in merged] == [str(i) for i in range(1, 8)]
    assert [s["text"] for s in merged] == [f"HU {i}" for i in range(1, 8)]
    assert "folytonosak" in capsys.readouterr().out


def test_merge_refuses_missing_block_without_force(workdir, capsys):
    tmp, src = workdir
    outdir = split.split_srt(str(src), block_size=3)
    _translate_all(outdir)
    os.remove(hun_path(get_all_blocks(outdir)[1]))
    out = tmp / "out.hun.srt"
    with pytest.raises(SystemExit) as exc:
        merge.main([outdir, str(out)])
    assert exc.value.code == 1
    assert not out.exists()
    assert "_block_002_" in capsys.readouterr().out


def test_merge_force_reports_continuity_gap(workdir, capsys):
    tmp, src = workdir
    outdir = split.split_srt(str(src), block_size=3)
    _translate_all(outdir)
    os.remove(hun_path(get_all_blocks(outdir)[1]))
    out = tmp / "out.hun.srt"
    merge.main([outdir, str(out), "--force"])
    text = capsys.readouterr().out
    assert "folytonossági hiba" in text and "#3 után #7" in text
    assert len(parse_sections(str(out))) == 4


def test_merge_ignores_stray_hun_file(workdir, capsys):
    """Egy régi splitből ottmaradt _HUN fájl nem kerülhet az outputba, és
    nem fedheti el a hiányt."""
    tmp, src = workdir
    outdir = split.split_srt(str(src), block_size=3)
    _translate_all(outdir)
    stray = Path(outdir) / "Sorozat - S01E01.eng_block_009_0100-0110_HUN.srt"
    stray.write_text("100\n00:01:40,000 --> 00:01:41,000\nKÓSZA\n", encoding="utf-8")
    out = tmp / "out.hun.srt"
    merge.main([outdir, str(out)])
    assert "KÓSZA" not in out.read_text(encoding="utf-8")
    assert "kósza" in capsys.readouterr().out
