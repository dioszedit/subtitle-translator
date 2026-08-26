"""A forrásnyelv-váltás végigvezetése a promptokon és a forrásfájl-kereséten.

A pipeline alapesete az angol felirat, de nem minden epizódhoz van használható
angol sáv. Ezek a tesztek azt rögzítik, hogy (1) a promptok tényleg a megadott
nyelvről beszélnek, (2) a review megtalálja a nem angol forrást is, és
(3) ahol a forrásnyelv jelöli a formalitást, ott a prompt ezt ki is mondja.
"""

from pathlib import Path

import pytest

from subtr import config
from subtr.tasks import register_extract, review, translate


@pytest.mark.parametrize("build", [
    lambda lang: translate.build_system_instruction("", "", lang),
    lambda lang: translate.build_codex_instruction("", "", lang),
    lambda lang: translate.build_claude_system_prompt("", "", lang),
])
def test_translate_prompts_name_the_source_language(build):
    assert "Német" in build("ger")
    assert "Angol" in build("eng")


def test_translate_block_prompt_names_the_source_language():
    assert "német nyelvről magyarra" in translate.build_block_prompt(
        [{"num": "1", "text": "Hallo"}], "ger")


def test_formality_rule_switches_on_source_language():
    """Angolnál kikerülésre biztat, jelölő nyelvnél leolvasásra."""
    eng = translate.formality_rule("eng")
    ger = translate.formality_rule("ger")
    assert "ne kelljen" in eng and "MAGA JELÖLI" not in eng
    assert "MAGA JELÖLI" in ger and "Sie/du" in ger


def test_formality_rule_bullet_prefix():
    """A felsorolásba "- " prefixszel megy, önálló bekezdésbe anélkül."""
    assert translate.formality_rule("eng").startswith("- Tegezés")
    assert translate.formality_rule("eng", bullet="").startswith("Tegezés")
    # a folytatósorok behúzása követi a prefix hosszát
    assert "\n  rá adat" in translate.formality_rule("eng")
    assert "\nrá adat" in translate.formality_rule("eng", bullet="")


def test_register_prompt_reads_instead_of_guessing():
    ger = register_extract.build_prompt("", [], "D", "E02", "ger")
    eng = register_extract.build_prompt("", [], "D", "E01", "eng")
    assert "LEOLVASÁS" in ger and "Sie/du" in ger
    assert "kikövetkeztetni" in eng
    # helyes magyar névelő mindkét irányban
    assert "az angol felirat" in eng
    assert "a német forrás" in ger


def test_review_prompt_mentions_the_formality_marker():
    ger = review.build_system_instruction("", "", has_source=True, src_lang="ger")
    eng = review.build_system_instruction("", "", has_source=True, src_lang="eng")
    assert "a német forrásban ez konkrétan: Sie/du" in ger
    # angolnál nincs mit mondani — és nem marad üres sor a felsorolásban
    assert "konkrétan" not in eng
    assert "\n\n   (c)" not in eng


def _touch(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n", encoding="utf-8")


def test_find_source_srt_prefers_the_given_language(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _touch(tmp_path / "input" / "S - S01E02.eng.srt")
    _touch(tmp_path / "input" / "S - S01E02.ger.srt")
    hun = tmp_path / "output" / "S - S01E02.hun.srt"
    assert review.find_source_srt(hun, "ger").name.endswith(".ger.srt")
    assert review.find_source_srt(hun, "eng").name.endswith(".eng.srt")


def test_find_source_srt_falls_back_to_any_known_language(tmp_path, monkeypatch):
    """A .hun.srt neve nem árulja el a forrásnyelvet, ezért ha a kért nyelvvel
    nincs találat, végig kell próbálni a többit — különben a német forrásból
    készült epizód review-ja forrás nélkül futna."""
    monkeypatch.chdir(tmp_path)
    _touch(tmp_path / "input" / "S - S01E02.ger.srt")
    hun = tmp_path / "output" / "S - S01E02.hun.srt"
    assert review.find_source_srt(hun, "eng").name.endswith(".ger.srt")
    assert review.find_source_srt(hun, None).name.endswith(".ger.srt")


def test_find_source_srt_returns_none_without_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hun = tmp_path / "output" / "S - S01E02.hun.srt"
    assert review.find_source_srt(hun, "ger") is None
    # .hun. tag nélküli névből nem próbálkozunk
    assert review.find_source_srt(tmp_path / "valami.srt", "ger") is None


def test_split_dir_name_keeps_the_language_tag():
    """A translate a blokkmappa nevéből oldja fel a nyelvet — a split
    a bemeneti fájl teljes törzsét használja mappanévnek, így a tag megmarad."""
    stem = Path("input/S - S01E02.ger.srt").stem       # "S - S01E02.ger"
    assert config.detect_source_lang(f"blocks/{stem}") == "ger"
