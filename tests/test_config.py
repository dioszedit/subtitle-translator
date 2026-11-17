"""A subtr.config modell-feloldási és provider-feloldási logikájának tesztjei.

FONTOS: a subtr.config import-időben tölti be a .env fájlt, és a repo
gyökerében VAN egy .env fájl GEMINI_API_KEY-jel — ezek a tesztek ettől
függetlenek: nem nyúlnak a GEMINI_API_KEY-hez, csak a SUBTR_* kulcsokat
állítják/takarítják monkeypatch-csel.
"""

import json
import os

import sys

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


# --- provider / modell / effort feloldás ---------------------------------------

DEFAULTS = {
    "SUBTR_TRANSLATE_PROVIDER": "claude",
    "SUBTR_TRANSLATE_MODEL": "sonnet",
    "SUBTR_TRANSLATE_EFFORT": "",
    "SUBTR_REVIEW_PROVIDER": "antigravity",
    "SUBTR_REVIEW_MODEL": "agy-modell",
    "SUBTR_REVIEW_EFFORT": "high",
    "SUBTR_GLOSSARY_PROVIDER": "claude",
    "SUBTR_GLOSSARY_MODEL": "",
    "SUBTR_GLOSSARY_EFFORT": "",
    "SUBTR_REGISTER_PROVIDER": "gemini",
    "SUBTR_REGISTER_MODEL": "gemini-alap",
    "SUBTR_REGISTER_EFFORT": "",
    "SUBTR_GEMINI_MODEL": "gemini-alap",
    "SUBTR_CLAUDE_MODEL": "sonnet",
    "SUBTR_CODEX_MODEL": "",
    "SUBTR_GROK_MODEL": "grok-alap",
    "SUBTR_ANTIGRAVITY_MODEL": "agy-modell",
    "SUBTR_ANTIGRAVITY_EFFORT": "high",
}


@pytest.fixture
def defaults(monkeypatch):
    """Ismert alapértékek a csomag defaults.env-je helyett."""
    monkeypatch.setattr(config, "_DEFAULTS", dict(DEFAULTS))
    monkeypatch.setattr(config, "antigravity_available_models", lambda: None)
    return monkeypatch


def _resolve(task, **cli):
    s = config.resolve_settings(task, cli.get("provider"), cli.get("model"),
                                cli.get("effort"))
    return s.provider, s.model, s.effort


def test_defaults_only(defaults):
    assert _resolve("translate") == ("claude", "sonnet", None)
    assert _resolve("glossary") == ("claude", None, None)      # üres modell: a CLI sajátja
    assert _resolve("register") == ("gemini", "gemini-alap", None)
    # antigravity: az effort a modellnév utótagja, külön kapcsoló nem megy
    s = config.resolve_settings("review")
    assert (s.provider, s.model, s.effort, s.shown_effort) == (
        "antigravity", "agy-modell-high", None, "high")


def test_env_felulirja_a_defaultot(defaults):
    defaults.setenv("SUBTR_TRANSLATE_MODEL", "opus")
    defaults.setenv("SUBTR_TRANSLATE_EFFORT", "medium")
    assert _resolve("translate") == ("claude", "opus", "medium")
    assert _resolve("glossary") == ("claude", None, None)      # más funkcióra nem szivárog


def test_kapcsolo_mindent_felulir(defaults):
    defaults.setenv("SUBTR_TRANSLATE_MODEL", "opus")
    defaults.setenv("SUBTR_TRANSLATE_EFFORT", "medium")
    assert _resolve("translate", model="haiku", effort="low") == ("claude", "haiku", "low")


def test_env_provider_nem_orokli_a_default_modellt(defaults):
    """A defaults.env funkció-modellje a defaults.env providerehez tartozik."""
    defaults.setenv("SUBTR_TRANSLATE_PROVIDER", "grok")
    assert _resolve("translate") == ("grok", "grok-alap", None)
    defaults.setenv("SUBTR_TRANSLATE_MODEL", "grok-uj")
    assert _resolve("translate") == ("grok", "grok-uj", None)


def test_provider_kapcsolo_a_provider_szintu_sorokra_valt(defaults):
    defaults.setenv("SUBTR_TRANSLATE_MODEL", "opus")
    defaults.setenv("SUBTR_TRANSLATE_EFFORT", "medium")
    assert _resolve("translate", provider="grok") == ("grok", "grok-alap", None)
    assert _resolve("translate", provider="codex") == ("codex", None, None)
    assert _resolve("translate", provider="antigravity") == (
        "antigravity", "agy-modell-high", None)
    # ugyanaz a provider kapcsolóval: a funkció sorai érvényesek maradnak
    assert _resolve("translate", provider="claude") == ("claude", "opus", "medium")
    # a provider-szintű sor a .env-ből is felülírható
    defaults.setenv("SUBTR_GROK_MODEL", "grok-env")
    assert _resolve("review", provider="grok") == ("grok", "grok-env", None)


def test_env_provider_szintu_sora_erosebb_a_defaultnal(defaults):
    """A .env bármely sora erősebb a defaults.env-nél — a provider-szintű is."""
    defaults.setenv("SUBTR_ANTIGRAVITY_MODEL", "masik-modell-low")
    assert _resolve("review") == ("antigravity", "masik-modell-low", None)
    defaults.setenv("SUBTR_CLAUDE_EFFORT", "medium")
    assert _resolve("translate") == ("claude", "sonnet", "medium")
    # de a .env funkció-sora a .env provider-sora fölött áll
    defaults.setenv("SUBTR_TRANSLATE_EFFORT", "low")
    assert _resolve("translate") == ("claude", "sonnet", "low")


def test_ures_env_ertek_is_beallitas(defaults):
    """Üres effort = nincs szint; így kapcsolható ki a defaults.env effortja."""
    defaults.setenv("SUBTR_REVIEW_EFFORT", "")
    assert _resolve("review") == ("antigravity", "agy-modell", None)
    defaults.setenv("SUBTR_TRANSLATE_MODEL", "")
    assert _resolve("translate") == ("claude", None, None)


def test_antigravity_effort_es_utotag(defaults):
    defaults.setenv("SUBTR_REVIEW_EFFORT", "low")
    assert _resolve("review")[1] == "agy-modell-low"
    # a modellnévbe írt utótag nyer, eltérésnél figyelmeztetéssel
    defaults.setenv("SUBTR_REVIEW_MODEL", "agy-modell-medium")
    s = config.resolve_settings("review")
    assert s.model == "agy-modell-medium" and s.shown_effort == "medium"
    assert s.warnings
    # az --effort kapcsoló a .env-ből jövő modell utótagját pontosítja
    assert _resolve("review", effort="high")[1] == "agy-modell-high"
    # ha a modell is kapcsoló, az utótagja marad
    assert _resolve("review", model="x-low", effort="high")[1] == "x-low"
    with pytest.raises(config.SettingsError, match="antigravity"):
        config.resolve_settings("review", cli_model="agy-modell", cli_effort="max")


def test_effort_nem_tamogato_providernel_kimarad(defaults):
    s = config.resolve_settings("register", cli_effort="high")
    assert (s.provider, s.effort, s.shown_effort) == ("gemini", None, None)
    assert any("nem hat" in w for w in s.warnings)
    assert not config.resolve_settings("register").warnings


def test_elgepelt_effort_hiba(defaults):
    """Egy elgépelt .env-érték ne essen vissza némán a drágább alapértelmezésre."""
    defaults.setenv("SUBTR_TRANSLATE_EFFORT", "medum")
    with pytest.raises(config.SettingsError, match="medum"):
        config.resolve_settings("translate")


def test_ismeretlen_vagy_hianyzo_provider_hiba(defaults):
    defaults.setenv("SUBTR_TRANSLATE_PROVIDER", "openai")
    with pytest.raises(config.SettingsError, match="openai"):
        config.resolve_settings("translate")
    defaults.setattr(config, "_DEFAULTS", {})
    defaults.delenv("SUBTR_TRANSLATE_PROVIDER")
    with pytest.raises(config.SettingsError, match="SUBTR_TRANSLATE_PROVIDER"):
        config.resolve_settings("translate")


def test_gemini_modell_nelkul_hiba(defaults):
    defaults.setattr(config, "_DEFAULTS", {"SUBTR_REVIEW_PROVIDER": "gemini"})
    with pytest.raises(config.SettingsError, match="SUBTR_REVIEW_MODEL"):
        config.resolve_settings("review")


def test_ismeretlen_task_hiba(defaults):
    with pytest.raises(ValueError):
        config.resolve_settings("summarize")


@pytest.mark.parametrize("old,new", [
    ("SUBTR_DEFAULT_PROVIDER", "SUBTR_TRANSLATE_PROVIDER"),
    ("SUBTR_CLAUDE_MODEL_TRANSLATE", "SUBTR_TRANSLATE_MODEL"),
    ("SUBTR_CLAUDE_EFFORT_GLOSSARY", "SUBTR_GLOSSARY_EFFORT"),
    ("SUBTR_GEMINI_MODEL_REVIEW", "SUBTR_REVIEW_MODEL"),
])
def test_megszunt_valtozonev_hiba(defaults, old, new):
    """Tiszta váltás: a régi nevet nem olvassuk, hanem megállunk, és megnevezzük az újat."""
    defaults.setenv(old, "claude")
    with pytest.raises(config.SettingsError, match=new):
        config.resolve_settings("translate")


def test_providerek(defaults):
    assert "grok" in config.PROVIDERS and "antigravity" in config.PROVIDERS
    assert set(config.CLI_PROVIDERS) <= set(config.PROVIDERS)
    assert "antigravity" in config.CLI_PROVIDERS


def test_settings_or_exit(defaults, capsys):
    import argparse
    p = argparse.ArgumentParser()
    config.add_provider_argument(p, "review")
    config.add_model_argument(p, "review")
    config.add_effort_argument(p, "review")
    s = config.settings_or_exit("review", p.parse_args(["--provider", "gemini", "--effort", "low"]))
    assert (s.provider, s.model, s.effort) == ("gemini", "gemini-alap", None)
    assert "FIGYELEM" in capsys.readouterr().out
    defaults.setenv("SUBTR_DEFAULT_PROVIDER", "gemini")
    with pytest.raises(SystemExit):
        config.settings_or_exit("review", p.parse_args([]))
    assert "SUBTR_DEFAULT_PROVIDER" in capsys.readouterr().out


# --- a csomag defaults.env-je --------------------------------------------------

def test_defaults_env_teljes():
    """Minden funkciónak megvan a hármasa érvényes providerrel, és feloldható."""
    values = config.read_env_file(config.DEFAULTS_PATH)
    for task in config.TASKS:
        for kind in ("PROVIDER", "MODEL", "EFFORT"):
            assert f"SUBTR_{task.upper()}_{kind}" in values
        assert values[f"SUBTR_{task.upper()}_PROVIDER"] in config.PROVIDERS
    for provider in config.PROVIDERS:
        assert f"SUBTR_{provider.upper()}_MODEL" in values


def test_defaults_env_feloldhato(monkeypatch):
    monkeypatch.setattr(config, "_DEFAULTS", config.read_env_file(config.DEFAULTS_PATH))
    monkeypatch.setattr(config, "antigravity_available_models", lambda: None)
    for task in config.TASKS:
        for provider in (None,) + config.PROVIDERS:
            config.resolve_settings(task, cli_provider=provider)
    review = config.resolve_settings("review")
    assert (review.provider, review.model) == ("antigravity", "gemini-3.8-flash-high")


def test_nincs_beegetett_modellnev_a_taskokban():
    """Alapérték csak a defaults.env-ben élhet."""
    import re
    from pathlib import Path
    tasks_dir = Path(config.__file__).parent / "tasks"
    pattern = re.compile(r"gemini-\d|grok-\d|gpt-\d|MODEL_BUILTIN|MODEL_DEFAULT")
    hits = [f"{p.name}:{i}" for p in sorted(tasks_dir.glob("*.py"))
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if pattern.search(line)]
    assert hits == []


def test_read_env_file(tmp_path):
    f = tmp_path / "x.env"
    f.write_text("# komment\n\nA=1\nB=\nC = 'x y'  # megjegyzés\nrossz sor\n", encoding="utf-8")
    assert config.read_env_file(f) == {"A": "1", "B": "", "C": "x y"}
    assert config.read_env_file(tmp_path / "nincs.env") == {}


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
    ("input/asr/Sorozat - S01E01.kor.asr.srt", "kor"),  # gépi hang-átirat
    ("input/asr/Sorozat - S01E01.KOR.ASR.SRT", "kor"),
    ("input/Sorozat - S01E01.asr.srt", None),        # csak .asr, nyelv nélkül
    ("input/Sorozat - S01E01.kor.ocr.srt", "kor"),   # beégetett felirat OCR-rel
    ("input/Sorozat - S01E01.CHI.OCR.srt", "chi"),
    ("input/Sorozat - S01E01.ocr.srt", None),        # csak .ocr, nyelv nélkül
    ("", None),
    (None, None),
])
def test_detect_source_lang(path, expected):
    assert config.detect_source_lang(path) == expected


@pytest.mark.parametrize("path,expected", [
    ("input/asr/Sorozat - S01E01.kor.asr.srt", True),
    ("input/asr/Sorozat - S01E01.kor.ASR.srt", True),
    ("input/Sorozat - S01E01.kor.srt", False),
    ("input/Sorozat - S01E01.laser.srt", False),     # nem tag, csak szóvég
    ("", False),
    (None, False),
])
def test_is_asr_path(path, expected):
    assert config.is_asr_path(path) is expected


@pytest.mark.parametrize("path,asr,ocr", [
    ("input/asr/Sorozat - S01E01.kor.asr.srt", True, False),
    ("input/Sorozat - S01E01.chi.ocr.srt", False, True),
    ("input/Sorozat - S01E01.kor.OCR.srt", False, True),
    ("blocks/Sorozat - S01E01.chi.ocr", False, True),   # mappanév is
    ("input/Sorozat - S01E01.chi.ocr.clean.srt", False, True),   # srt-preclean után is
    ("blocks/Sorozat - S01E01.kor.asr.clean", True, False),
    ("input/Mr. Ocr - S01E01.eng.srt", False, False),   # a címben nem tag
    ("input/Sorozat - S01E01.chi.srt", False, False),
    ("input/Sorozat - S01E01.doctor.srt", False, False),  # nem tag, csak szóvég
    ("", False, False),
    (None, False, False),
])
def test_is_ocr_and_machine_path(path, asr, ocr):
    assert config.is_asr_path(path) is asr
    assert config.is_ocr_path(path) is ocr
    assert config.is_machine_path(path) is (asr or ocr)


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


def test_dotenv_a_munkakonyvtarbol_toltodik(tmp_path, monkeypatch):
    """A .env-et a CWD-ből felfelé keressük (a pipeline a sorozat mappájából
    fut), nem a csomag mappájából — különben egy editable telepítés a másik
    sorozat-másolat .env-jét töltené be."""
    pytest.importorskip("dotenv")
    import importlib
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUBTR_TEST_DOTENV_MARKER", raising=False)
    (tmp_path / ".env").write_text("SUBTR_TEST_DOTENV_MARKER=cwd\n", encoding="utf-8")
    importlib.reload(config)
    assert os.environ.get("SUBTR_TEST_DOTENV_MARKER") == "cwd"
    monkeypatch.delenv("SUBTR_TEST_DOTENV_MARKER", raising=False)


# --- kivezetett modellek -------------------------------------------------------

def test_add_effort_argument_choices():
    import argparse
    p = argparse.ArgumentParser()
    config.add_effort_argument(p, "translate")
    assert p.parse_args(["--effort", "xhigh"]).effort == "xhigh"
    assert p.parse_args([]).effort is None
    with pytest.raises(SystemExit):
        p.parse_args(["--effort", "turbo"])


def _model(task, provider, model):
    return config.resolve_settings(task, provider, model).model


@pytest.fixture
def deprecations(tmp_path, monkeypatch):
    """A Gemini-kivezetések a generált gemini_models.json-ból jönnek — a teszt
    saját, rögzített adatfájllal fut, nem az éppen generálttal."""
    from subtr import gemini_models
    data = {"models": {}, "deprecations": {
        "gemini-3.7-flash": {"replacement": "gemini-3.8-flash", "shutdown": None,
                             "routes": True, "routes_from": None},
        # lánc: 3.5 → 3.6 (átirányít), 3.6 → 3.8 (leállt)
        "gemini-3.5-flash": {"replacement": "gemini-3.6-flash", "shutdown": None,
                             "routes": True},
        "gemini-3.6-flash": {"replacement": "gemini-3.8-flash", "shutdown": "2026-01-01",
                             "routes": False},
        # bejelentett, de még el nem jött leállás: nem cseréljük, csak szólunk
        "gemini-2.5-flash": {"replacement": "gemini-3.5-flash-lite",
                             "shutdown": "2999-12-01", "routes": False},
        # utód van, leállás nincs: nem cseréljük
        "gemini-3-flash-preview": {"replacement": "gemini-3.6-flash", "shutdown": None,
                                   "routes": False},
    }}
    path = tmp_path / "gemini_models.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(gemini_models, "DATA_PATH", path)
    gemini_models.clear_cache()
    yield
    gemini_models.clear_cache()


def test_kivezetett_gemini_modell_utodra_valt(defaults, deprecations, capsys):
    assert _model("translate", "gemini", "gemini-3.7-flash") == "gemini-3.8-flash"
    assert _model("review", "gemini", "gemini-3.5-flash") == "gemini-3.8-flash"
    assert _model("review", "gemini", "gemini-3.6-flash") == "gemini-3.8-flash"
    err = capsys.readouterr().err
    assert "irányítja át" in err and "leállt" in err
    assert "helyette ezt használjuk: gemini-3.8-flash" in err
    # a lite és a nem érintett modellek változatlanok
    assert _model("review", "gemini", "gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"
    assert _model("review", "gemini", "gemini-3.8-flash") == "gemini-3.8-flash"
    assert _model("review", "gemini", "gemini-3-flash-preview") == "gemini-3-flash-preview"
    # más provider nevét nem bántjuk
    assert _model("review", "antigravity", "claude-opus-5-5-high") == "claude-opus-5-5-high"


def test_bejelentett_leallas_csak_figyelmeztet(defaults, deprecations, capsys):
    assert _model("review", "gemini", "gemini-2.5-flash") == "gemini-2.5-flash"
    assert "2999-12-01" in capsys.readouterr().err


def test_kivezetett_modell_env_bol_is(defaults, deprecations):
    defaults.setenv("SUBTR_GEMINI_MODEL", "gemini-3.7-flash")
    assert _model("translate", "gemini", None) == "gemini-3.8-flash"


def test_setting_env_erosebb_a_defaultsnal(defaults):
    defaults.setenv("SUBTR_GEMINI_ON_QUOTA", "auto")
    assert config.setting("SUBTR_GEMINI_ON_QUOTA") == "auto"
    assert config.setting("SUBTR_NINCS_ILYEN", "x") == "x"


@pytest.mark.parametrize("old,new", [
    ("gemini-3.1-pro-high", "gemini-3.8-flash-high"),
    ("gemini-3.1-pro-low", "gemini-3.8-flash-low"),
    ("gemini-3.6-flash-medium", "gemini-3.8-flash-medium"),
    ("gemini-3.7-flash-high", "gemini-3.8-flash-high"),
    ("gemini-3.8-flash-low", "gemini-3.8-flash-low"),      # érvényes: változatlan
])
def test_kivezetett_antigravity_modell_utodra_valt(old, new, defaults, capsys):
    # nem Enterprise: az `agy models` csak a 3.8 Flasht kínálja
    defaults.setattr(config, "antigravity_available_models",
                     lambda: {"gemini-3.8-flash-high", "gemini-3.8-flash-medium",
                              "gemini-3.8-flash-low"})
    assert _model("review", "antigravity", old) == new
    assert ("Enterprise" in capsys.readouterr().err) is (old != new)


def test_kivezetett_antigravity_modell_ha_nem_listazhato_utodra_valt(defaults):
    assert _model("review", "antigravity", "gemini-3.1-pro-high") == "gemini-3.8-flash-high"
    # utótag nélküli régi név: a beállított effortot kapja, nincs rejtett alapérték
    defaults.setenv("SUBTR_REVIEW_MODEL", "gemini-3.1-pro")
    defaults.setenv("SUBTR_REVIEW_EFFORT", "low")
    assert config.resolve_settings("review").model == "gemini-3.8-flash-low"
    assert config.replace_deprecated("antigravity", "gemini-3.1-pro") == "gemini-3.8-flash"


def test_enterprise_eleresnel_a_modell_marad(defaults, capsys):
    # Enterprise-előfizetés: a 3.1 Pro az `agy models` listájában van → nem cseréljük
    defaults.setattr(config, "antigravity_available_models",
                     lambda: {"gemini-3.1-pro-high", "gemini-3.8-flash-high"})
    assert _model("review", "antigravity", "gemini-3.1-pro-high") == "gemini-3.1-pro-high"
    assert "Enterprise" not in capsys.readouterr().err


def test_agy_models_kimenet_feldolgozasa(monkeypatch):
    import shutil
    import subprocess
    class P:
        returncode = 0
        stdout = ("Fetching available models...\n"
                  "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
                  "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n")
    monkeypatch.setattr(config, "_AGY_MODELS_CACHE", {})
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/agy")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
    assert config.antigravity_available_models() == {"gemini-3.8-flash-high", "gpt-oss-120b-medium"}


# ── fájlminták kibontása (Windowson a parancssor nem teszi meg) ─────────────

def test_expand_patterns(tmp_path):
    for name in ("b - S01E02.mkv", "a - S01E01.mkv", "x.srt"):
        (tmp_path / name).write_text("")
    pat = str(tmp_path / "*.mkv")
    assert config.expand_patterns([pat]) == [str(tmp_path / "a - S01E01.mkv"),
                                             str(tmp_path / "b - S01E02.mkv")]
    # nem minta → változatlan; üres találatú minta → változatlan (a hiba megnevezi)
    assert config.expand_patterns(["plain.mkv"]) == ["plain.mkv"]
    nomatch = str(tmp_path / "*.avi")
    assert config.expand_patterns([nomatch]) == [nomatch]


def test_expand_patterns_accepts_path_objects(tmp_path):
    (tmp_path / "a.hun.srt").write_text("")
    assert config.expand_patterns([tmp_path / "*.hun.srt"]) == [str(tmp_path / "a.hun.srt")]


def test_expand_patterns_existing_bracket_name_is_literal(tmp_path):
    """Az `E0[1].mkv` létező fájl, nem minta — ne az `E01.mkv` kerüljön a helyére."""
    for name in ("E0[1].mkv", "E01.mkv"):
        (tmp_path / name).write_text("")
    literal = str(tmp_path / "E0[1].mkv")
    assert config.expand_patterns([literal]) == [literal]


def test_expand_patterns_in_bracketed_folder(tmp_path):
    """`Sorozat [2026]/Season 01/*.mkv` — a mappanév zárójele nem minta."""
    season = tmp_path / "Sorozat [2026]" / "Season 01"
    season.mkdir(parents=True)
    for name in ("b.mkv", "a.mkv"):
        (season / name).write_text("")
    assert config.expand_patterns([str(season / "*.mkv")]) == [str(season / "a.mkv"),
                                                               str(season / "b.mkv")]


def test_expand_patterns_bracketed_folder_plus_wildcard_folder(tmp_path):
    """`Sorozat [2026]/S*/*.mkv` — a létező zárójeles mappa szó szerinti, az `S*` minta."""
    root = tmp_path / "Sorozat [2026]"
    for season in ("S1", "S2"):
        (root / season).mkdir(parents=True)
        (root / season / "E01.mkv").write_text("")
    assert config.expand_patterns([str(root / "S*" / "*.mkv")]) == [
        str(root / "S1" / "E01.mkv"), str(root / "S2" / "E01.mkv")]


def test_expand_patterns_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "a.eng.vtt").write_text("")
    assert config.expand_patterns(["input/*.eng.vtt"]) == ["input/a.eng.vtt"]
    assert config.expand_patterns(["*.nincs"]) == ["*.nincs"]


# ── a szögletes zárójel soha nem minta (harmadik review) ────────────────────

def test_expand_patterns_bracket_in_file_name_with_wildcard(tmp_path):
    for name in ("[Grp] Show - 01.mkv", "[Grp] Show - 02.mkv", "Show [2026] - S01E01.mkv"):
        (tmp_path / name).write_text("")
    assert config.expand_patterns([str(tmp_path / "[Grp]*.mkv")]) == [
        str(tmp_path / "[Grp] Show - 01.mkv"), str(tmp_path / "[Grp] Show - 02.mkv")]
    assert config.expand_patterns([str(tmp_path / "Show [2026] - S01E*.mkv")]) == [
        str(tmp_path / "Show [2026] - S01E01.mkv")]


def test_expand_patterns_missing_bracket_name_does_not_resolve_elsewhere(tmp_path):
    """Az elgépelt `E0[1].mkv` ne oldódjon fel csendben a létező `E01.mkv`-re."""
    (tmp_path / "E01.mkv").write_text("")
    typo = str(tmp_path / "E0[1].mkv")
    assert config.expand_patterns([typo]) == [typo]


def test_expand_patterns_question_mark(tmp_path):
    for name in ("E01.mkv", "E02.mkv", "E10.mkv"):
        (tmp_path / name).write_text("")
    assert config.expand_patterns([str(tmp_path / "E0?.mkv")]) == [
        str(tmp_path / "E01.mkv"), str(tmp_path / "E02.mkv")]


def test_utf8_console_survives_replaced_streams(monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdout", io.StringIO())   # nincs reconfigure-képes kódolása
    monkeypatch.setattr(sys, "stderr", object())
    config.utf8_console()
