"""subtr.srt — a kanonikus parser viselkedési kontraktusa.

A refaktor előtti 5+ parse-változat apró eltéréseit ezek a tesztek rögzítik:
ami itt zöld, az a megengedőbb (verify/gemini) viselkedés.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtr import srt

SAMPLE = """1
00:00:01,000 --> 00:00:02,000
Első sor
Második sor

2
00:00:03,000 --> 00:00:04,000

3
00:00:05,000 --> 00:00:06,000
3
"""


def _write(tmp_path, content, encoding="utf-8"):
    p = tmp_path / "sample.srt"
    p.write_bytes(content.encode(encoding))
    return str(p)


def test_parse_sections_alap(tmp_path):
    path = _write(tmp_path, SAMPLE)
    secs = srt.parse_sections(path)
    assert [s["num"] for s in secs] == ["1", "2", "3"]
    assert secs[0]["text"] == "Első sor\nMásodik sor"
    # 2 soros blokk: érvényes, üres szöveggel (a codex-parser régen eldobta)
    assert secs[1]["text"] == ""
    # a csak számot tartalmazó felirat-szöveg ("3") text marad, nem új szekció
    assert secs[2]["text"] == "3"


def test_parse_sections_bom_es_crlf(tmp_path):
    path = _write(tmp_path, "﻿" + SAMPLE.replace("\n", "\r\n"))
    secs = srt.parse_sections(path)
    assert [s["num"] for s in secs] == ["1", "2", "3"]
    assert secs[0]["num"] == "1"  # a BOM nem ragad a sorszámra


def test_count_sections_visszaszamlalas(tmp_path):
    # az önálló "3" szövegsor nem számít szekciónak (nincs utána -->)
    path = _write(tmp_path, SAMPLE)
    assert srt.count_sections(path) == 3


def test_count_sections_hianyzo_fajl():
    assert srt.count_sections("nincs_ilyen_fajl.srt") == 0


def test_roundtrip(tmp_path):
    path = _write(tmp_path, SAMPLE)
    secs = srt.parse_sections(path)
    out = str(tmp_path / "out.srt")
    srt.write_srt(out, secs)
    # az újraolvasott szerkezet azonos
    assert srt.parse_sections(out) == secs
    assert srt.count_sections(out) == 3
    # fájl vége: pontosan egy újsor
    raw = open(out, encoding="utf-8").read()
    assert raw.endswith("\n") and not raw.endswith("\n\n")


def test_parse_entries_csak_teljes_blokkok(tmp_path):
    path = _write(tmp_path, SAMPLE)
    entries = srt.parse_entries(path)
    # a 2 soros blokk itt kimarad (a review nem tud mit kezdeni üres szöveggel)
    assert len(entries) == 2
    assert entries[0].startswith("1\n")


def test_parse_by_index(tmp_path):
    path = _write(tmp_path, SAMPLE)
    idx = srt.parse_by_index(path)
    assert set(idx) == {1, 3}
    ts, text = idx[1]
    assert "-->" in ts
    assert text == "Első sor | Második sor"


def test_parse_blocks_with_index_nem_szabvanyos(tmp_path):
    # nem szabványos blokk (nincs időbélyeg) megőrződik, de nem indexelt
    content = SAMPLE + "\nEz egy kósza megjegyzés\n"
    path = _write(tmp_path, content)
    blocks, index = srt.parse_blocks_with_index(path)
    assert len(blocks) == 4
    assert set(index) == {1, 2, 3}
    assert blocks[index[2]].startswith("2\n")
