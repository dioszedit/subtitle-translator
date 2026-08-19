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
