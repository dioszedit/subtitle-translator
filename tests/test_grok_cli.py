"""subtr.providers.grok_cli — a headless JSON-válasz kinyerése."""

import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtr.providers import grok_cli
from subtr.providers.grok_cli import (GrokRunError, find_grok,
                                      parse_grok_response)


def test_parse_structured_output_camel_case():
    raw = '{"structuredOutput": {"name": "Alice", "age": 3}, "text": "{\\"name\\": \\"Alice\\"}"}'
    assert parse_grok_response(raw) == {"name": "Alice", "age": 3}


def test_parse_structured_output_snake_case():
    raw = '{"structured_output": {"errors": []}}'
    assert parse_grok_response(raw) == {"errors": []}


def test_parse_falls_back_to_text_json():
    raw = '{"text": "{\\"translations\\": [{\\"sorszam\\": 1, \\"text\\": \\"Szia\\"}]}"}'
    assert parse_grok_response(raw)["translations"][0]["sorszam"] == 1


def test_parse_error_envelope():
    with pytest.raises(GrokRunError, match="Couldn't start"):
        parse_grok_response('{"type": "error", "message": "Couldn\'t start session"}')


def test_parse_empty_raises():
    with pytest.raises(GrokRunError, match="üres"):
        parse_grok_response("")
    with pytest.raises(GrokRunError, match="üres"):
        parse_grok_response(None)


def test_parse_root_schema_object_without_envelope():
    raw = '{"translations": [{"sorszam": 1, "text": "Szia"}]}'
    assert parse_grok_response(raw)["translations"][0]["text"] == "Szia"


def test_parse_prefix_before_json():
    raw = 'warning: something\n{"structuredOutput": {"ok": true}}'
    assert parse_grok_response(raw) == {"ok": True}


def test_parse_invalid_json_raises():
    with pytest.raises(GrokRunError, match="nem érvényes JSON"):
        parse_grok_response("ez nem json")


def test_find_grok_returns_str_or_none():
    result = find_grok()
    assert result is None or (isinstance(result, str) and result != "")


def test_parse_suffix_after_json():
    raw = '{"structuredOutput": {"ok": true}}\nDone.'
    assert parse_grok_response(raw) == {"ok": True}


def test_parse_prefix_containing_brace():
    # A glossary-prompt szó szerint tartalmaz `{"suggestions":[...]}` mintát,
    # így egy prompt-echo garantáltan hoz '{'-t a valódi JSON elé.
    raw = ('echo: a válasz `suggestions` tömbbel: {"suggestions":[...]}.\n'
           '{"structuredOutput": {"suggestions": []}}')
    assert parse_grok_response(raw) == {"suggestions": []}


def test_parse_broken_brace_prefix_and_trailing_text():
    # A csonka '{' miatt az "első { … utolsó }" heurisztika elhasalna, a
    # válaszban lévő üres tömb pedig hamis jelöltet adna — a scan-nek a
    # tényleges envelope-ot kell megtalálnia.
    raw = 'log {részleges\n{"structuredOutput": {"errors": []}}\nDone.'
    assert parse_grok_response(raw) == {"errors": []}


def test_parse_root_schema_wins_over_text_summary():
    raw = '{"translations": [{"sorszam": 1, "text": "Szia"}], "text": "Kész."}'
    assert parse_grok_response(raw)["translations"][0]["text"] == "Szia"


def test_parse_list_structured_output_raises():
    raw = '{"structuredOutput": [{"sorszam": 1}]}'
    with pytest.raises(GrokRunError, match="nem objektum"):
        parse_grok_response(raw)


def test_parse_list_text_payload_raises():
    with pytest.raises(GrokRunError, match="nem objektum"):
        parse_grok_response('{"text": "[{\\"sorszam\\": 1}]"}')


def test_parse_bare_list_root_raises():
    with pytest.raises(GrokRunError, match="nincs structuredOutput"):
        parse_grok_response('[{"sorszam": 1}]')


def test_parse_string_structured_output_raises():
    with pytest.raises(GrokRunError, match="nem objektum"):
        parse_grok_response('{"structuredOutput": "kesz"}')


def test_parse_cancelled_run_without_structured_output_raises():
    # Éles megfigyelés: --max-turns 1 mellett a toolt kérő modell
    # "cancelled"-del áll le, structuredOutput: null, a text pedig csonka
    # lehet — ezt elfogadni néma cue-vesztés volna.
    raw = ('{"structuredOutput": null, "stopReason": "cancelled", '
           '"text": "{\\"translations\\": [{\\"sorszam\\": 1, \\"text\\": \\"Szia\\"}]}"}')
    with pytest.raises(GrokRunError, match="nem fejeződött be"):
        parse_grok_response(raw)


def test_parse_end_turn_text_fallback_still_works():
    raw = ('{"structuredOutput": null, "stopReason": "end_turn", '
           '"text": "{\\"translations\\": []}"}')
    assert parse_grok_response(raw) == {"translations": []}


# ── run_grok_json ───────────────────────────────────────────────────────────

class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_run_grok_json_builds_headless_command(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"], captured["kwargs"] = cmd, kwargs
        return _Proc(stdout='{"structuredOutput": {"errors": []}}')

    monkeypatch.setattr(grok_cli.subprocess, "run", fake_run)
    result = grok_cli.run_grok_json("prompt", {"type": "object"},
                                    timeout=900, model="grok-4.5")
    assert result == {"errors": []}

    cmd = captured["cmd"]
    assert cmd[0] == "grok"
    assert "--prompt-file" in cmd and "--json-schema" in cmd
    for flag in ("--no-subagents", "--no-plan", "--disable-web-search",
                 "--verbatim", "--max-turns"):
        assert flag in cmd
    assert cmd[cmd.index("-m") + 1] == "grok-4.5"
    # a promptot fájlba írjuk, és a --cwd ugyanaz az üres temp mappa
    prompt_path = pathlib.Path(cmd[cmd.index("--prompt-file") + 1])
    assert prompt_path.parent == pathlib.Path(cmd[cmd.index("--cwd") + 1])
    assert captured["kwargs"]["timeout"] == 900
    env = captured["kwargs"]["env"]
    assert env["GROK_MEMORY"] == "0" and env["GROK_DISABLE_AUTOUPDATER"] == "1"


def test_run_grok_json_without_model_omits_flag(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Proc(stdout='{"structuredOutput": {"errors": []}}')

    monkeypatch.setattr(grok_cli.subprocess, "run", fake_run)
    grok_cli.run_grok_json("prompt", {}, timeout=60)
    assert "-m" not in captured["cmd"]


def test_run_grok_json_respects_existing_env(monkeypatch):
    captured = {}
    monkeypatch.setenv("GROK_MEMORY", "1")

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return _Proc(stdout='{"structuredOutput": {}}')

    monkeypatch.setattr(grok_cli.subprocess, "run", fake_run)
    grok_cli.run_grok_json("prompt", {}, timeout=60)
    assert captured["env"]["GROK_MEMORY"] == "1"


def test_run_grok_json_nonzero_exit_includes_tail(monkeypatch):
    def fake_run(cmd, **kwargs):
        return _Proc(returncode=2, stderr="rate limit\n\nreached", stdout="ctx")

    monkeypatch.setattr(grok_cli.subprocess, "run", fake_run)
    with pytest.raises(GrokRunError) as exc:
        grok_cli.run_grok_json("prompt", {}, timeout=60)
    message = str(exc.value)
    assert "exit 2" in message and "rate limit" in message and "ctx" in message


def test_run_grok_json_timeout_message(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 900)

    monkeypatch.setattr(grok_cli.subprocess, "run", fake_run)
    with pytest.raises(GrokRunError, match=r"Timeout \(900 mp / 15 perc\)"):
        grok_cli.run_grok_json("prompt", {}, timeout=900)


def test_run_grok_json_short_timeout_message_is_seconds(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(grok_cli.subprocess, "run", fake_run)
    with pytest.raises(GrokRunError, match=r"Timeout \(30 mp\)"):
        grok_cli.run_grok_json("prompt", {}, timeout=30)


def test_run_grok_json_missing_binary(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(grok_cli.subprocess, "run", fake_run)
    with pytest.raises(GrokRunError, match="nem található"):
        grok_cli.run_grok_json("prompt", {}, timeout=60, grok_bin="grok")
