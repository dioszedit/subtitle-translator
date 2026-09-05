"""subtr.providers — a két headless CLI-adapter (codex, grok) közös felülete.

A tasks réteg egyetlen ággal kezeli őket; ha valamelyik attribútum hiányzik,
az csak a tényleges (fizetős) CLI-hívásnál derülne ki."""

import pytest

from subtr.providers import CliRunError, get_provider


@pytest.mark.parametrize("name", ["codex", "grok"])
def test_cli_adapter_contract(name):
    adapter = get_provider(name)
    assert isinstance(adapter.LABEL, str) and adapter.LABEL
    assert isinstance(adapter.MISSING_HINT, str) and adapter.MISSING_HINT
    assert callable(adapter.find_cli)
    assert callable(adapter.run_json)
    assert issubclass(adapter.RunError, CliRunError)


def test_cli_adapter_run_json_forwards_bin(monkeypatch):
    """A run_json a cli_bin-t az adapter saját függvényének adja tovább."""
    codex = get_provider("codex")
    seen = {}
    monkeypatch.setattr(codex, "run_codex_json",
                        lambda p, s, *, timeout, model, codex_bin: seen.update(
                            bin=codex_bin, model=model) or {"ok": 1})
    assert codex.run_json("p", {}, timeout=1, model="m", cli_bin="/x/codex") == {"ok": 1}
    assert seen == {"bin": "/x/codex", "model": "m"}


def test_get_provider_unknown():
    with pytest.raises(ValueError):
        get_provider("ollama")
