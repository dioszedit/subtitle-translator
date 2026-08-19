"""A subtr.glossary betöltésének és prompt-szöveggé alakításának tesztjei."""

import json

import pytest

from subtr import glossary


# --- load() -------------------------------------------------------------


def test_load_missing_file_returns_empty_categories(tmp_path):
    path = tmp_path / "nincs_ilyen.json"
    data = glossary.load(str(path))
    assert data == {
        "honorifics": [],
        "place_names": [],
        "character_names": [],
        "special_terms": [],
        "phrases": [],
    }


def test_load_empty_file_returns_empty_categories(tmp_path):
    path = tmp_path / "ures.json"
    path.write_text("", encoding="utf-8")
    data = glossary.load(str(path))
    assert data == {
        "honorifics": [],
        "place_names": [],
        "character_names": [],
        "special_terms": [],
        "phrases": [],
    }


def test_load_existing_file(tmp_path):
    path = tmp_path / "glossary.json"
    payload = {"honorifics": [{"en": "Sir", "hu": "Uram"}]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    data = glossary.load(str(path))
    assert data == payload


# --- as_prompt_text() ----------------------------------------------------


def test_as_prompt_text_category_order_and_context():
    data = {
        "phrases": [{"en": "no way", "hu": "kizárt", "context": "csodálkozva"}],
        "honorifics": [{"en": "Sir", "hu": "Uram"}],
        "place_names": [],
        "character_names": [{"en": "John", "hu": "János"}],
        "special_terms": [],
    }
    text = glossary.as_prompt_text(data)
    # a kategória-sorrend a CATEGORIES konstansét követi, NEM a dict kulcssorrendjét
    assert text == (
        '  "Sir" = "Uram"\n'
        '  "John" = "János"\n'
        '  "no way" = "kizárt" (csodálkozva)'
    )


def test_as_prompt_text_skips_incomplete_entries():
    data = {"honorifics": [{"en": "", "hu": "Uram"}, {"en": "Sir", "hu": ""}]}
    assert glossary.as_prompt_text(data) == ""


def test_as_prompt_text_empty_glossary_returns_empty_string():
    data = {cat: [] for cat in ("honorifics", "place_names", "character_names",
                                 "special_terms", "phrases")}
    assert glossary.as_prompt_text(data) == ""


def test_as_prompt_text_loads_from_path_when_glossary_none(tmp_path):
    path = tmp_path / "glossary.json"
    path.write_text(
        json.dumps({"honorifics": [{"en": "Sir", "hu": "Uram"}]}),
        encoding="utf-8",
    )
    assert glossary.as_prompt_text(path=str(path)) == '  "Sir" = "Uram"'
