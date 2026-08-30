"""addons/vtt2srt — WebVTT → SRT konverzió: sorszámozás, időbélyeg, tag-megőrzés."""

import importlib.util
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addons" / "vtt2srt" / "vtt2srt.py"
_spec = importlib.util.spec_from_file_location("vtt2srt", ADDON)
vtt2srt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vtt2srt)


UNNUMBERED = (
    "WEBVTT\r\n\r\n"
    "00:00:05.739 --> 00:00:11.119\r\n"
    "<i>♪ Nincs összehasonlítás,\r\nnincs egyenlőség ♪</i>\r\n\r\n"
    "00:01:00.280 --> 00:01:03.600\r\n"
    "<i>[Koronaherceg, Zhu Yousheng]</i>\r\n"
)

NUMBERED = (
    "﻿WEBVTT\n\n"
    "NOTE ez egy megjegyzés\n\n"
    "STYLE\n::cue { color: white }\n\n"
    "1\n00:00:06.560 --> 00:00:08.460 align:start position:10%\nBűnös vagyok!\n\n"
    "7\n00:00:08.460 --> 00:00:11.293\n<v Song Mo>Song Mo <c.red>ártatlan</c>!\n\n"
    "intro-3\n01:12.900 --> 01:14.000\n- Menjünk.\n- Jó.\n"
)


def test_unnumbered_cues_get_sequential_numbers_and_comma_ms():
    out = vtt2srt.convert_text(UNNUMBERED)
    assert out == (
        "1\n00:00:05,739 --> 00:00:11,119\n"
        "<i>♪ Nincs összehasonlítás,\nnincs egyenlőség ♪</i>\n\n"
        "2\n00:01:00,280 --> 00:01:03,600\n"
        "<i>[Koronaherceg, Zhu Yousheng]</i>\n"
    )
    assert "\r" not in out


def test_numbered_cues_are_renumbered_and_vtt_noise_dropped():
    cues = vtt2srt.parse_vtt(NUMBERED)
    assert [c["text"] for c in cues] == ["Bűnös vagyok!", "Song Mo ártatlan!", "- Menjünk.\n- Jó."]
    assert cues[0]["timestamp"] == "00:00:06,560 --> 00:00:08,460"   # beállítások levágva
    assert cues[2]["timestamp"] == "00:01:12,900 --> 00:01:14,000"   # rövid alak kiegészítve
    out = vtt2srt.render_srt(cues)
    assert out.startswith("1\n") and "\n\n2\n" in out and "\n\n3\n" in out
    assert "NOTE" not in out and "::cue" not in out and "WEBVTT" not in out


def test_cue_count_is_preserved_and_srt_parser_reads_it(tmp_path):
    src = tmp_path / "x.hun.vtt"
    src.write_text(UNNUMBERED, encoding="utf-8")
    dst = tmp_path / "x.hun.srt"
    assert vtt2srt.convert_file(src, dst) == 2
    from subtr.srt import parse_sections
    sections = parse_sections(str(dst))
    assert [s["num"] for s in sections] == ["1", "2"]
    assert sections[1]["text"] == "<i>[Koronaherceg, Zhu Yousheng]</i>"


def test_existing_target_needs_force(tmp_path):
    src = tmp_path / "x.vtt"
    src.write_text(UNNUMBERED, encoding="utf-8")
    dst = tmp_path / "x.srt"
    dst.write_text("régi", encoding="utf-8")
    with pytest.raises(vtt2srt.VttError):
        vtt2srt.convert_file(src, dst)
    assert dst.read_text(encoding="utf-8") == "régi"
    vtt2srt.convert_file(src, dst, force=True)
    assert dst.read_text(encoding="utf-8").startswith("1\n")


def test_bad_timestamp_is_an_error():
    with pytest.raises(vtt2srt.VttError):
        vtt2srt.parse_vtt("WEBVTT\n\n00:00:01 --> 00:00:02\nx\n")


# ── Hibás (de a gyakorlatban előforduló) fájlok: egyetlen cue se vesszen el ──

def test_ures_sor_nelkuli_cue_k_nem_olvadnak_ossze():
    cues = vtt2srt.parse_vtt(
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nA\n"
        "2\n00:00:03.000 --> 00:00:04.000\nB\n")
    assert [c["text"] for c in cues] == ["A", "B"]


def test_fejlec_utan_hianyzo_ures_sor_nem_nyeli_el_a_cue_t():
    cues = vtt2srt.parse_vtt(
        "WEBVTT\n00:00:01.000 --> 00:00:02.000\nA\n\n00:00:03.000 --> 00:00:04.000\nB\n")
    assert [c["text"] for c in cues] == ["A", "B"]


def test_note_torzseben_a_nyil_nem_idobelyeg():
    cues = vtt2srt.parse_vtt(
        "WEBVTT\n\nNOTE this --> that\nmore\n\n00:00:03.000 --> 00:00:04.000\nB\n")
    assert [c["text"] for c in cues] == ["B"]


def test_v_tag_osztallyal_is_kibomlik():
    cues = vtt2srt.parse_vtt("WEBVTT\n\n00:00:03.000 --> 00:00:04.000\n<v.loud Song Mo>Hé!</v>\n")
    assert cues[0]["text"] == "Hé!"


def test_haromjegyu_ora_es_szemet_a_beallitas_helyen():
    assert vtt2srt.parse_vtt("WEBVTT\n\n100:00:01.000 --> 100:00:02.500\nX\n")[0]["timestamp"] \
        == "100:00:01,000 --> 100:00:02,500"
    with pytest.raises(vtt2srt.VttError):
        vtt2srt.parse_vtt("WEBVTT\n\n00:00:01.000 --> 00:00:02.000xyz\nX\n")


def test_out_dir_azonos_alapnev_utkozes_iras_elott(tmp_path, capsys):
    for sub in ("a", "b"):
        d = tmp_path / sub
        d.mkdir()
        (d / "x.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nA\n", encoding="utf-8")
    out = tmp_path / "out"
    rc = vtt2srt.main([str(tmp_path / "a" / "x.vtt"), str(tmp_path / "b" / "x.vtt"),
                       "--out-dir", str(out), "--force"])
    assert rc == 1
    assert "ugyanarra a célra" in capsys.readouterr().out
    assert not (out / "x.srt").exists()
