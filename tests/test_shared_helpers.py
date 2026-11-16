"""Egy helyen élő közös logika: az add-onok a subtr-ből veszik, nem másolják.

Korábban a glossary-betöltő 6 scriptben élt, és a másolatok szétcsúsztak
(docs/01-telepites.md). Ezek a tesztek azt őrzik, hogy a fájlminta-kibontás
és a nyelvkód-lista ne jusson ugyanerre a sorsra.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from subtr import config

ROOT = Path(__file__).resolve().parent.parent
ADDONS = ROOT / "addons"

# add-on script → a fájllistát fogadó argumentuma van
FILE_LIST_SCRIPTS = [
    "audio-asr/transcribe.py",
    "mkv-subs/extract_subs.py",
    "mkv-subs/embed_subs.py",
    "hardsub-cover/cover_ass.py",
    "vtt2srt/vtt2srt.py",
]


def from_subtr(fn):
    """A függvény a subtr.config-é, nem helyi másolat vagy az üres tartalék.

    Származást nézünk, nem azonosságot: egy másik teszt újratölti a config
    modult, és onnantól az `is` hamisan bukna.
    """
    return fn.__module__ == "subtr.config" and fn.__name__ == "expand_patterns"


def load(rel):
    path = ADDONS / rel
    name = "shared_" + path.stem
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("rel", ["audio-asr/transcribe.py", "mkv-subs/extract_subs.py",
                                 "mkv-subs/embed_subs.py", "vtt2srt/vtt2srt.py"])
def test_addons_use_the_one_expand_patterns(rel):
    assert from_subtr(load(rel).expand_patterns)


def test_cover_ass_gets_it_through_embed_subs():
    assert from_subtr(load("hardsub-cover/cover_ass.py").embed_subs.expand_patterns)


@pytest.mark.parametrize("rel", ["audio-asr/transcribe.py", "mkv-subs/extract_subs.py"])
def test_addons_use_the_one_alias_table(rel):
    # nem üres tartalék, hanem a subtr táblája (a másolatot a lenti forrás-teszt zárja ki)
    assert load(rel)._ALIASES == config.SOURCE_LANG_ALIASES


@pytest.mark.parametrize("rel", FILE_LIST_SCRIPTS)
def test_file_list_scripts_expand_patterns(rel):
    """Minden fájllistát fogadó add-on ténylegesen hívja a kibontást."""
    assert "expand_patterns(args." in (ADDONS / rel).read_text(encoding="utf-8")


def test_no_private_copies_in_addons():
    """Se saját kibontó, se saját nyelvkód-tábla az add-onokban."""
    for path in ADDONS.glob("*/*.py"):
        src = path.read_text(encoding="utf-8")
        assert "def expand_patterns" not in src, path
        assert "glob.has_magic" not in src, path
        assert not re.search(r'"ko":\s*"kor"', src), path


def test_vtt2srt_expands_literal_pattern(tmp_path, monkeypatch, capsys):
    """Windows-szerű hívás: a minta szó szerint érkezik, a script bontja ki."""
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n"
    for n in ("a.hun.vtt", "b.hun.vtt"):
        (tmp_path / n).write_text(vtt, encoding="utf-8")
    mod = load("vtt2srt/vtt2srt.py")
    monkeypatch.setattr(sys, "argv", ["vtt2srt.py", str(tmp_path / "*.hun.vtt")])
    assert mod.main() in (0, None)
    assert (tmp_path / "a.hun.srt").is_file() and (tmp_path / "b.hun.srt").is_file()
