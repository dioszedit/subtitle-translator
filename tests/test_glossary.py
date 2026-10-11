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


# --- alap-szótárak (meta.bases) --------------------------------------------

def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _project(tmp_path, bases, **cats):
    _write(tmp_path / "glossary.json", {"meta": {"series": "X", "bases": bases}, **cats})
    return str(tmp_path / "glossary.json")


def _base(tmp_path, base_id, **cats):
    d = tmp_path / "glossaries"
    d.mkdir(exist_ok=True)
    _write(d / f"{base_id}.json", {"meta": {"id": base_id}, **cats})


def _entries(merged, category):
    return {(e["en"], e["hu"], e["_source"]) for e in merged[category]}


def test_bases_nelkul_a_mai_viselkedes(tmp_path):
    path = _project(tmp_path, [], special_terms=[{"en": "A", "hu": "a"}])
    merged = glossary.load_merged(path)
    assert _entries(merged, "special_terms") == {("A", "a", "project")}
    assert glossary.describe_bases(merged) == ""


def test_projekt_felulirja_az_alapot_es_kesobbi_alap_a_korabbit(tmp_path):
    _base(tmp_path, "zh-common", honorifics=[{"en": "Marquis", "hu": "őrgróf"},
                                             {"en": "Eunuch", "hu": "herélt"}])
    _base(tmp_path, "zh-historical", honorifics=[{"en": "Marquis", "hu": "márki"},
                                                 {"en": "Eunuch", "hu": "eunuch"}])
    path = _project(tmp_path, ["zh-common", "zh-historical"],
                    honorifics=[{"en": "eunuch", "hu": "udvari szolga"}])
    merged = glossary.load_merged(path)
    assert _entries(merged, "honorifics") == {
        ("eunuch", "udvari szolga", "project"),
        ("Marquis", "márki", "base:zh-historical"),
    }
    info = merged["meta"]["_merge"]
    assert info["bases"] == ["zh-common", "zh-historical"]
    assert info["base_entries"] == 1 and info["overridden"] == 3
    assert "zh-common, zh-historical" in glossary.describe_bases(merged)


def test_alap_azonositoi_is_csak_elofordulaskor_kerulnek_be(tmp_path):
    _base(tmp_path, "zh-historical", honorifics=[{"en": "Marquis", "hu": "márki"},
                                                 {"en": "Eunuch", "hu": "eunuch"}])
    path = _project(tmp_path, ["zh-historical"],
                    character_names=[{"en": "Lan Xiang", "hu": "Lan Xiang"}])
    text = glossary.as_prompt_text(path=path, source_text="Marquis Yuan arrived.")
    assert '"Marquis" = "márki"' in text
    assert "Eunuch" not in text
    assert "Lan Xiang" in text          # a sorozat saját neve mindig bekerül


def test_hianyzo_vagy_ervenytelen_alap_figyelmeztet_es_kihagyja(tmp_path, capsys):
    path = _project(tmp_path, ["nincs-ilyen", "../titok"],
                    special_terms=[{"en": "A", "hu": "a"}])
    merged = glossary.load_merged(path)
    assert merged["meta"]["_merge"]["bases"] == []
    err = capsys.readouterr().err
    assert "nincs-ilyen" in err and "érvénytelen" in err


def test_bases_egyetlen_stringkent_is(tmp_path):
    _base(tmp_path, "ko-common", honorifics=[{"en": "oppa", "hu": "oppa"}])
    path = _project(tmp_path, "ko-common")
    assert glossary.base_ids(glossary.load(path)) == ["ko-common"]
    assert ("oppa", "oppa", "base:ko-common") in _entries(glossary.load_merged(path), "honorifics")


def test_with_bases_nem_modositja_a_bemenetet(tmp_path):
    _base(tmp_path, "zh-common", phrases=[{"en": "x", "hu": "y"}])
    project = {"meta": {"bases": ["zh-common"]}, "phrases": [{"en": "a", "hu": "b"}]}
    glossary.with_bases(project, str(tmp_path / "glossaries"))
    assert project == {"meta": {"bases": ["zh-common"]}, "phrases": [{"en": "a", "hu": "b"}]}


# --- alap-javaslat (glossaries/index.json) ----------------------------------

REPO_INDEX = glossary.load_index(
    str(__import__("pathlib").Path(__file__).resolve().parent.parent / "glossaries"))


def _ids(*args):
    return [i for i, _ in glossary.suggest_bases(REPO_INDEX, *args)]


def test_index_betoltheto_es_azonositok_ervenyesek():
    assert REPO_INDEX
    assert all(glossary.BASE_ID_RE.match(b["id"]) for b in REPO_INDEX)


@pytest.mark.parametrize("countries,genres,keywords,expected", [
    (["CN"], ["Drama"], ["romance", "historical fiction", "costume drama"], ["zh-common", "zh-historical"]),
    (["CN"], ["Sci-Fi & Fantasy"], ["xianxia", "cultivation"], ["zh-common", "zh-xianxia"]),
    (["CN"], ["Drama"], ["based on novel or book"], ["zh-common"]),
    (["KR"], ["Comedy"], ["romcom", "ceo", "chaebol"], ["ko-common", "ko-modern"]),
    (["KR"], ["Drama"], ["joseon", "palace"], ["ko-common", "ko-sageuk"]),
    (["JP"], ["Drama"], [], ["ja-common"]),
    (["US"], ["Drama"], ["historical"], []),
])
def test_javaslat_orszag_es_kulcsszo_szerint(countries, genres, keywords, expected):
    assert _ids(countries, genres, keywords) == expected


def test_hianyzo_index_ures_lista(tmp_path):
    assert glossary.load_index(str(tmp_path)) == []


# --- szóhatáros előfordulás ------------------------------------------------

@pytest.mark.parametrize("entry,text,expected", [
    ({"en": "Mom", "hu": "anya"}, "Just a moment.", False),
    ({"en": "unni", "hu": "unni"}, "Stop running!", False),
    ({"en": "Mom", "hu": "anya"}, "Mom, wait!", True),
    ({"en": "Marquis", "hu": "márki"}, "The Marquises arrived.", True),      # többes szám
    ({"en": "Elder", "hu": "vén"}, "The Elder's sword.", True),             # birtokos
    ({"en": "Marquis", "hu": "márki"}, "Beszéltem a márkival.", True),       # magyar toldalék
    ({"en": "Marquis", "hu": "márki"}, "Ez a bömárki szó.", False),          # magyar eleje szóhatár
    ({"en": "兰香如故", "hu": "兰香如故"}, "第一集兰香如故第二集", True),      # CJK: nincs szóhatár
    ({"en": "Sect Leader", "hu": "szektavezér"}, "The sect leader came.", True),
])
def test_szohataros_elofordulas(entry, text, expected):
    g = {"special_terms": [entry]}
    assert bool(glossary.filter_for_source(g, text)["special_terms"]) is expected
