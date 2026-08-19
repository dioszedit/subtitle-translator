"""subtr.blocks — blokk-konvenció és checkpoint-logika."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtr import blocks


def _make(tmp_path, name, content="1\n00:00:01,000 --> 00:00:02,000\nSzia\n"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_hun_path():
    assert blocks.hun_path("x/eng_block_001_0001-0150.srt") == \
        "x/eng_block_001_0001-0150_HUN.srt"


def test_get_all_es_pending(tmp_path):
    b1 = _make(tmp_path, "ep_block_001_0001-0150.srt")
    b2 = _make(tmp_path, "ep_block_002_0151-0300.srt")
    _make(tmp_path, "ep_block_001_0001-0150_HUN.srt")   # kész fordítás
    _make(tmp_path, "ep_block_001_0001-0150_HUN_REVIEW_CODEX.txt")  # nem srt
    _make(tmp_path, "egyeb.srt")                          # nem blokk

    all_blocks = blocks.get_all_blocks(str(tmp_path))
    assert all_blocks == sorted([b1, b2])
    # az 1-es kész (van _HUN párja), csak a 2-es pending
    assert blocks.get_pending_blocks(str(tmp_path)) == [b2]


def test_safe_remove(tmp_path):
    p = _make(tmp_path, "torlendo_block_001.srt")
    blocks.safe_remove(p)
    assert not os.path.isfile(p)
    # nem létező fájlra nem dob hibát
    blocks.safe_remove(p)
