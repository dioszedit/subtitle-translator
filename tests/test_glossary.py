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


# ── szójegyzék-szűrés a forrásszöveghez ─────────────────────────────────────

def _sample_glossary():
    return {
        "honorifics": [{"en": "Mentor", "hu": "Mester", "context": ""}],
        "place_names": [{"en": "Ascendance Sect", "hu": "Felemelkedés Rendje"}],
        "character_names": [{"en": "Li Changshou", "hu": "Li Csang-sou"}],
        "special_terms": [
            {"en": "Paper Daoist", "hu": "papírtaoista"},
            {"en": "Golden Immortal", "hu": "Aranyhalhatatlan"},
        ],
        "phrases": [{"en": "advance by leaps and bounds", "hu": "óriásit lép előre"}],
    }


def test_filter_keeps_identity_categories_untouched():
    g = _sample_glossary()
    out = glossary.filter_for_source(g, "semmi releváns szöveg")
    for category in glossary.IDENTITY_CATEGORIES:
        assert out[category] == g[category]
    # a filterezhetők viszont kiürülnek
    assert out["special_terms"] == [] and out["phrases"] == []


def test_filter_matches_english_source():
    out = glossary.filter_for_source(_sample_glossary(),
                                     "He sent a Paper Daoist to the gate.")
    assert [e["en"] for e in out["special_terms"]] == ["Paper Daoist"]


def test_filter_matches_hungarian_side_too():
    # a review a magyar szöveget nézi — a `hu` alaknak is találnia kell
    out = glossary.filter_for_source(_sample_glossary(),
                                     "A papírtaoista elindult a kapu felé.")
    assert [e["en"] for e in out["special_terms"]] == ["Paper Daoist"]


def test_filter_normalizes_typographic_punctuation():
    g = {"special_terms": [{"en": "Dragon King’s heir", "hu": "a Sárkánykirály örököse"}]}
    assert glossary.filter_for_source(g, "the dragon king's heir arrived")["special_terms"]


def test_filter_without_source_returns_everything():
    g = _sample_glossary()
    assert glossary.filter_for_source(g, "") == g
    assert glossary.filter_for_source(g, "   \n  ") == g


def test_filter_ignores_missing_categories():
    g = {"honorifics": [{"en": "Mentor", "hu": "Mester"}]}
    assert glossary.filter_for_source(g, "Mentor") == g


def test_as_prompt_text_source_text_shrinks_output():
    g = _sample_glossary()
    full = glossary.as_prompt_text(g)
    filtered = glossary.as_prompt_text(g, source_text="a Paper Daoist appears")
    assert len(filtered) < len(full)
    assert "Paper Daoist" in filtered and "Golden Immortal" not in filtered
    assert "Mentor" in filtered  # az azonosítók bent maradnak
