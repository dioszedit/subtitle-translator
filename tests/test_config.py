"""A subtr.config modell-feloldási és provider-feloldási logikájának tesztjei.

FONTOS: a subtr.config import-időben tölti be a .env fájlt, és a repo
gyökerében VAN egy .env fájl GEMINI_API_KEY-jel — ezek a tesztek ettől
függetlenek: nem nyúlnak a GEMINI_API_KEY-hez, csak a SUBTR_* kulcsokat
állítják/takarítják monkeypatch-csel.
"""

import pytest

from subtr import config


def _clear_subtr_env(monkeypatch):
    """Minden SUBTR_ prefixű env-változót eltávolít a jelenlegi környezetből."""
    for key in list(__import__("os").environ):
        if key.startswith("SUBTR_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    _clear_subtr_env(monkeypatch)
    yield


# --- resolve_model precedencia -------------------------------------------------


def test_resolve_model_cli_wins(monkeypatch):
    monkeypatch.setenv("SUBTR_GEMINI_MODEL_TRANSLATE", "task-specifikus")
    monkeypatch.setenv("SUBTR_GEMINI_MODEL", "generikus")
    result = config.resolve_model("cli-modell", "gemini", "translate", builtin="builtin-modell")
    assert result == "cli-modell"


def test_resolve_model_task_specific_wins_over_generic(monkeypatch):
    monkeypatch.setenv("SUBTR_GEMINI_MODEL_TRANSLATE", "task-specifikus")
    monkeypatch.setenv("SUBTR_GEMINI_MODEL", "generikus")
    result = config.resolve_model(None, "gemini", "translate", builtin="builtin-modell")
    assert result == "task-specifikus"


def test_resolve_model_generic_wins_over_builtin(monkeypatch):
    monkeypatch.setenv("SUBTR_GEMINI_MODEL", "generikus")
    result = config.resolve_model(None, "gemini", "translate", builtin="builtin-modell")
    assert result == "generikus"


def test_resolve_model_falls_back_to_builtin(monkeypatch):
    result = config.resolve_model(None, "gemini", "translate", builtin="builtin-modell")
    assert result == "builtin-modell"


def test_resolve_model_empty_env_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("SUBTR_GEMINI_MODEL_TRANSLATE", "")
    monkeypatch.setenv("SUBTR_GEMINI_MODEL", "")
    result = config.resolve_model(None, "gemini", "translate", builtin="builtin-modell")
    assert result == "builtin-modell"


def test_resolve_model_different_task_does_not_leak(monkeypatch):
    monkeypatch.setenv("SUBTR_GEMINI_MODEL_TRANSLATE", "task-specifikus")
    result = config.resolve_model(None, "gemini", "review", builtin="builtin-modell")
    assert result == "builtin-modell"


# --- default_provider ------------------------------------------------------


def test_default_provider_valid_env(monkeypatch):
    monkeypatch.setenv("SUBTR_DEFAULT_PROVIDER", "codex")
    assert config.default_provider(builtin="claude") == "codex"


def test_default_provider_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("SUBTR_DEFAULT_PROVIDER", "nem-letezo-provider")
    assert config.default_provider(builtin="claude") == "claude"


def test_default_provider_no_env(monkeypatch):
    assert config.default_provider(builtin="gemini") == "gemini"


# --- érvénytelen provider/task ---------------------------------------------


def test_resolve_model_invalid_provider_raises():
    with pytest.raises(ValueError):
        config.resolve_model(None, "openai", "translate", builtin="x")


def test_resolve_model_invalid_task_raises():
    with pytest.raises(ValueError):
        config.resolve_model(None, "gemini", "summarize", builtin="x")


def test_model_help_invalid_provider_raises():
    with pytest.raises(ValueError):
        config.model_help("openai", "translate", "x")


def test_model_help_invalid_task_raises():
    with pytest.raises(ValueError):
        config.model_help("gemini", "summarize", "x")


def test_model_help_text():
    text = config.model_help("gemini", "translate", "gemini-3.6-flash")
    assert text == (
        "default: SUBTR_GEMINI_MODEL_TRANSLATE / SUBTR_GEMINI_MODEL / gemini-3.6-flash"
    )


# ────────────────────────────────────────────────────────────────────────────
# Forrásnyelv-feloldás
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("ger", "ger"),
    ("de", "ger"),          # ISO 639-1 alias
    ("DE", "ger"),          # kis-/nagybetű
    ("  eng  ", "eng"),     # whitespace
    ("zh", "chi"),
    ("klingon", None),      # ismeretlen
    ("", None),
    (None, None),
])
def test_normalize_source_lang(value, expected):
    assert config.normalize_source_lang(value) == expected


@pytest.mark.parametrize("path,expected", [
    ("input/Sorozat - S01E02.ger.srt", "ger"),
    ("input/Sorozat - S01E01.eng.srt", "eng"),
    ("blocks/Sorozat - S01E02.ger", "ger"),          # a split mappaneve
    ("blocks/Sorozat - S01E02.ger/", "ger"),         # záró perjellel
    ("/abs/path/Sorozat.chi.srt", "chi"),
    ("input/Sorozat - S01E01.srt", None),            # nincs nyelvkód
    ("input/Sorozat - S01E01.clean.srt", None),      # nem nyelvkód a tag
    ("", None),
    (None, None),
])
def test_detect_source_lang(path, expected):
    assert config.detect_source_lang(path) == expected


def test_resolve_source_lang_precedence(monkeypatch):
    _clear_subtr_env(monkeypatch)
    path = "input/Sorozat - S01E02.ger.srt"

    # 4. alapértelmezés — nincs se kapcsoló, se env, se felismerhető fájlnév
    assert config.resolve_source_lang(None, None) == config.DEFAULT_SOURCE_LANG
    # 3. fájlnév
    assert config.resolve_source_lang(None, path) == "ger"
    # 2. env üti a fájlnevet
    monkeypatch.setenv("SUBTR_SOURCE_LANG", "fre")
    assert config.resolve_source_lang(None, path) == "fre"
    # 1. a kapcsoló mindent üt
    assert config.resolve_source_lang("chi", path) == "chi"
    # érvénytelen kapcsoló/env NEM nyer — visszaesik a fájlnévre
    monkeypatch.delenv("SUBTR_SOURCE_LANG", raising=False)
    assert config.resolve_source_lang("klingon", path) == "ger"


def test_source_lang_name_and_formality():
    assert config.source_lang_name("ger") == "német"
    assert config.source_lang_formality("eng") is None      # `you` mindenre
    assert "Sie/du" in config.source_lang_formality("ger")
    # ismeretlen kód nem robban, az alapértelmezettre esik vissza
    assert config.source_lang_name("klingon") == config.source_lang_name(
        config.DEFAULT_SOURCE_LANG)


@pytest.mark.parametrize("code,expected", [
    ("eng", "az angol"),
    ("ger", "a német"),
    ("ita", "az olasz"),
    ("rus", "az orosz"),
    ("ara", "az arab"),
    ("ind", "az indonéz"),
    ("kor", "a koreai"),
])
def test_the_source_lang_article(code, expected):
    assert config.the_source_lang(code) == expected


def test_every_source_lang_has_name_and_valid_formality():
    """A tábla épsége: minden bejegyzés (név, jel|None) alakú, a név nem üres."""
    for code, entry in config.SOURCE_LANGS.items():
        name, marker = entry
        assert name and isinstance(name, str), code
        assert marker is None or (isinstance(marker, str) and marker), code
    # minden alias létező kódra mutat
    for alias, code in config.SOURCE_LANG_ALIASES.items():
        assert code in config.SOURCE_LANGS, alias


def test_resolve_source_lang_invalid_value_warns(monkeypatch, capsys):
    _clear_subtr_env(monkeypatch)
    assert config.resolve_source_lang("german", "input/X.ger.srt") == "ger"
    err = capsys.readouterr().err
    assert "FIGYELEM" in err and "'german'" in err and "--source-lang" in err
    monkeypatch.setenv("SUBTR_SOURCE_LANG", "deutsch")
    config.resolve_source_lang(None, None)
    assert "SUBTR_SOURCE_LANG" in capsys.readouterr().err


def test_source_lang_origin(monkeypatch):
    _clear_subtr_env(monkeypatch)
    assert config.source_lang_origin("chi", "x.ger.srt") == "--source-lang"
    monkeypatch.setenv("SUBTR_SOURCE_LANG", "fre")
    assert config.source_lang_origin(None, "x.ger.srt") == "SUBTR_SOURCE_LANG"
    monkeypatch.delenv("SUBTR_SOURCE_LANG")
    assert config.source_lang_origin(None, "blocks/x.ger") == "a fájl-/mappanévből"
    assert config.source_lang_origin(None, "blocks/x") == "alapértelmezés"
