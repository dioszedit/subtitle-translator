"""Részleges megtagadás felismerése + a futási napló.

Valós hiba (Pull Strings S01E12, 007-es blokk): az agent megtagadta a
dalszövegek fordítását, de a fájlt kiírta — a dalsorok helyére `[DAL]`
placeholder került. A szerkezeti ellenőrzés (szekciószám, sorszám,
időbélyeg) ezt nem fogta meg, így a hiányos blokk `ok`-ként ment a merge-be.

A napló azért kell, mert a megtagadás indoklása addig csak a konzolon és a
`claude -p` session-transcriptjében létezett — utólag nem volt visszanézhető.
"""

import os

from subtr.tasks.translate import (
    find_placeholder_sections,
    log,
    placeholder_detail,
    placeholder_warning,
    rotate_log,
    TRANSLATE_LOG,
)

SRT = (
    "1\n00:00:01,000 --> 00:00:02,000\nSzia!\n\n"
    "2\n00:00:03,000 --> 00:00:04,000\n[DAL]\n\n"
    "3\n00:00:05,000 --> 00:00:06,000\n[NEM FORDÍTHATÓ]\n\n"
    "4\n00:00:07,000 --> 00:00:08,000\n[Az óvatos halhatatlan]\n\n"
    "5\n00:00:09,000 --> 00:00:10,000\n\n"
)


def write_srt_file(tmp_path, text=SRT):
    p = tmp_path / "block_HUN.srt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_placeholder_cue_k_felismerese(tmp_path):
    hits = find_placeholder_sections(write_srt_file(tmp_path))
    # 2: [DAL], 3: [NEM FORDÍTHATÓ], 5: üres szöveg
    assert hits == ["2", "3", "5"]


def test_cimkartya_nem_placeholder(tmp_path):
    """A szögletes zárójel önmagában NEM gyanús — a név-/helyszínkártyák
    ilyenek, és a TRANSLATION.md szerint fordítandók."""
    path = write_srt_file(
        tmp_path, "1\n00:00:01,000 --> 00:00:02,000\n[Az óvatos halhatatlan]\n\n")
    assert find_placeholder_sections(path) == []
    assert placeholder_warning(path) is None


def test_warning_es_detail_tartalma(tmp_path):
    path = write_srt_file(tmp_path)
    assert "3 db" in placeholder_warning(path)
    # a detail az ÖSSZES érintett cue-t felsorolja, a message csak 5-öt
    assert placeholder_detail(path) == "érintett cue-k: 2, 3, 5"


def test_ep_fordítas_nem_ad_warningot(tmp_path):
    path = write_srt_file(
        tmp_path, "1\n00:00:01,000 --> 00:00:02,000\nSzia!\n\n")
    assert placeholder_warning(path) is None
    assert placeholder_detail(path) == ""


def test_log_beir_es_behuzza_a_detailt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    log("[FAIL] block_002 — Üres vagy hiányzó output",
        detail="I can't reproduce this\n\nsubtitle content.")
    content = (tmp_path / TRANSLATE_LOG).read_text(encoding="utf-8")
    assert "[FAIL] block_002" in content
    assert "    | I can't reproduce this" in content
    assert "    | subtitle content." in content
    assert "\n\n" not in content  # az üres sorok kiesnek a detailből


def test_log_nem_dob_kivetelt_ha_nem_irhato(tmp_path, monkeypatch):
    """A naplózás nem buktathatja el a fordítást."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / TRANSLATE_LOG).mkdir()  # könyvtár a fájl helyén → OSError
    log("bármi")  # nem dobhat


def test_rotate_log_meret_folott(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("subtr.tasks.translate.TRANSLATE_LOG_MAX_BYTES", 10)
    (tmp_path / TRANSLATE_LOG).write_text("x" * 100, encoding="utf-8")
    rotate_log()
    assert not (tmp_path / TRANSLATE_LOG).exists()
    assert (tmp_path / (TRANSLATE_LOG + ".1")).read_text(encoding="utf-8") == "x" * 100
