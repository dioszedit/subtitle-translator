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


def test_extract_subs_uses_the_one_alias_table():
    assert load("mkv-subs/extract_subs.py")._ALIASES == config.SOURCE_LANG_ALIASES


@pytest.mark.parametrize("name", ["normalize_lang", "require_tools", "probe_streams",
                                  "describe", "stem_without_lang", "find_tool"])
def test_audio_asr_takes_track_helpers_from_mkv_subs(name):
    """A hang- és a feliratsávokat ugyanaz a kód listázza."""
    fn = getattr(load("audio-asr/transcribe.py"), name)
    assert fn.__module__ == "extract_subs" and fn.__name__ == name


@pytest.mark.parametrize("definition", ["def normalize_lang", "def require_tools",
                                        "def probe_streams", "def stem_without_lang",
                                        "def describe(tracks", "def find_tool",
                                        "def ffprobe_json", "class Fail", "shutil.which(",
                                        '"-show_entries"'])
def test_track_helpers_defined_once(definition):
    owners = [p.parent.name + "/" + p.name for p in ADDONS.glob("*/*.py")
              if definition in p.read_text(encoding="utf-8")]
    assert owners == ["mkv-subs/extract_subs.py"]


def test_no_silent_fallback_without_subtr():
    """Ha a subtr nem tölthető be, az add-on megáll — nem működik csendben félig."""
    for rel in ("mkv-subs/extract_subs.py", "vtt2srt/vtt2srt.py"):
        src = (ADDONS / rel).read_text(encoding="utf-8")
        assert "except ImportError as exc:\n    sys.exit(" in src, rel
        assert "expand_patterns = list" not in src and "= {}, set()" not in src, rel


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


def test_embed_subs_and_cover_share_tool_lookup_and_fail():
    """Egy ffmpeg-kereső, egy ffprobe-hívó, egy Fail — a beágyazás és a takarás is ezt kapja."""
    emb = load("mkv-subs/embed_subs.py")
    cover = load("hardsub-cover/cover_ass.py")
    for name in ("find_tool", "ffprobe_json", "Fail"):
        assert getattr(emb, name).__module__ == "extract_subs", name
    assert cover.Fail.__module__ == "extract_subs"


def test_no_bare_ffmpeg_command_in_addons():
    """Senki ne hívja névvel az ffmpeg-et: a find_tool ismeri az FFMPEG változót is."""
    for path in ADDONS.glob("*/*.py"):
        src = path.read_text(encoding="utf-8")
        assert not re.search(r'\[\s*"ff(mpeg|probe)"', src), path
