"""subtr.providers.antigravity_cli — stdin-es bemenet és a stream-json válasz kinyerése."""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtr.providers import antigravity_cli
from subtr.providers.antigravity_cli import (AntigravityRunError, build_command,
                                             build_stdin_message, find_agy,
                                             parse_agy_response)

SCHEMA = {"type": "object",
          "properties": {"translations": {"type": "array"}},
          "required": ["translations"]}


def _stream(result: dict, *, extra_events=True) -> str:
    """Az `agy --output-format stream-json` kimenetének mintája."""
    lines = []
    if extra_events:
        lines.append(json.dumps({"event": "init", "init": {"tools": ["run_command"]}}))
        lines.append(json.dumps({"event": "step_update", "step": {}}))
    lines.append(json.dumps({"event": "result", "result": result}, ensure_ascii=False))
    return "\n".join(lines) + "\n"


# --- bemenet --------------------------------------------------------------

def test_stdin_message_is_single_ndjson_line():
    msg = build_stdin_message("első sor\nmásodik ♪ sor")
    assert msg.endswith("\n") and msg.count("\n") == 1
    assert json.loads(msg) == {"event": "user",
                               "message": {"content": "első sor\nmásodik ♪ sor"}}


def test_command_never_contains_prompt_and_uses_attached_p():
    cmd = build_command("/x/agy", SCHEMA, timeout=900, model="gemini-3.6-flash-high")
    assert cmd[0] == "/x/agy"
    assert "-p=" in cmd and "-p" not in cmd
    assert cmd[cmd.index("--input-format") + 1] == "stream-json"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert cmd[cmd.index("--print-timeout") + 1] == "900s"
    assert cmd[cmd.index("--model") + 1] == "gemini-3.6-flash-high"


def test_command_without_model_omits_flag():
    assert "--model" not in build_command("agy", SCHEMA, timeout=60)


# --- válasz-parse ---------------------------------------------------------

def test_parse_structured_output():
    raw = _stream({"status": "SUCCESS", "response": "...",
                   "structured_output": {"translations": [{"sorszam": 1, "text": "Szia"}]}})
    assert parse_agy_response(raw, SCHEMA) == {"translations": [{"sorszam": 1, "text": "Szia"}]}


def test_parse_ignores_non_json_lines():
    raw = "figyelmeztetés: valami\n" + _stream(
        {"status": "SUCCESS", "structured_output": {"translations": []}})
    assert parse_agy_response(raw, SCHEMA) == {"translations": []}


def test_parse_falls_back_to_response_and_filters_extra_keys():
    """A `response` szövegbe a modell plusz kulcsokat tesz (élesben látott eset)."""
    text = json.dumps({"toolAction": "Translating", "toolSummary": "x",
                       "translations": [{"sorszam": 2, "text": "Nem"}]})
    raw = _stream({"status": "SUCCESS", "response": text})
    assert parse_agy_response(raw, SCHEMA) == {"translations": [{"sorszam": 2, "text": "Nem"}]}


def test_parse_response_in_fence():
    raw = _stream({"status": "SUCCESS",
                   "response": 'Íme:\n```json\n{"translations": []}\n```'})
    assert parse_agy_response(raw, SCHEMA) == {"translations": []}


def test_parse_response_without_schema_keys_raises():
    raw = _stream({"status": "SUCCESS", "response": '{"toolAction": "x"}'})
    with pytest.raises(AntigravityRunError):
        parse_agy_response(raw, SCHEMA)


def test_parse_error_status():
    raw = _stream({"status": "ERROR", "error": "quota exceeded"})
    with pytest.raises(AntigravityRunError, match="quota exceeded"):
        parse_agy_response(raw, SCHEMA)


def test_parse_stdin_format_error_gets_hint():
    raw = _stream({"status": "ERROR",
                   "error": 'stream input message is missing the "event" field'})
    with pytest.raises(AntigravityRunError, match="stream-json"):
        parse_agy_response(raw, SCHEMA)


def test_parse_no_result_event():
    with pytest.raises(AntigravityRunError, match="result"):
        parse_agy_response(json.dumps({"event": "init"}), SCHEMA)


def test_parse_empty_raises():
    with pytest.raises(AntigravityRunError):
        parse_agy_response("", SCHEMA)
    with pytest.raises(AntigravityRunError):
        parse_agy_response(None, SCHEMA)


def test_parse_non_object_structured_output():
    raw = _stream({"status": "SUCCESS", "structured_output": [1, 2]})
    with pytest.raises(AntigravityRunError, match="nem objektum"):
        parse_agy_response(raw, SCHEMA)


def test_parse_uses_last_result_event():
    raw = (_stream({"status": "ERROR", "error": "régi"}, extra_events=False)
           + _stream({"status": "SUCCESS", "structured_output": {"translations": []}},
                     extra_events=False))
    assert parse_agy_response(raw, SCHEMA) == {"translations": []}


# --- futtatás -------------------------------------------------------------

def _fake_run(stdout, returncode=0, stderr="", seen=None):
    def run(cmd, **kwargs):
        if seen is not None:
            seen.update(cmd=cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)
    return run


def test_run_sends_prompt_on_stdin_in_empty_tmp_dir(monkeypatch):
    seen = {}
    monkeypatch.setattr(antigravity_cli.subprocess, "run", _fake_run(
        _stream({"status": "SUCCESS", "structured_output": {"translations": []}}), seen=seen))
    long_prompt = "x" * 200_000  # a Windows-argumentumlimit fölött
    result = antigravity_cli.run_json(long_prompt, SCHEMA, timeout=900,
                                      model="m", cli_bin="/x/agy")
    assert result == {"translations": []}
    assert json.loads(seen["input"])["message"]["content"] == \
        antigravity_cli.NO_TOOLS_PREAMBLE + long_prompt
    assert all(long_prompt not in part for part in seen["cmd"])
    assert seen["encoding"] == "utf-8"
    assert os.path.basename(seen["cwd"]).startswith("subtitle-agy-")
    assert seen["timeout"] > 900


def test_run_nonzero_exit_without_result_uses_stderr(monkeypatch):
    monkeypatch.setattr(antigravity_cli.subprocess, "run", _fake_run(
        "", returncode=2, stderr="Error: not authenticated"))
    with pytest.raises(AntigravityRunError, match="exit 2.*not authenticated"):
        antigravity_cli.run_json("p", SCHEMA, timeout=60)


def test_run_nonzero_exit_with_error_envelope_keeps_its_message(monkeypatch):
    monkeypatch.setattr(antigravity_cli.subprocess, "run", _fake_run(
        _stream({"status": "ERROR", "error": "model not found"}), returncode=1))
    with pytest.raises(AntigravityRunError, match="model not found"):
        antigravity_cli.run_json("p", SCHEMA, timeout=60)


def test_run_timeout(monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
    monkeypatch.setattr(antigravity_cli.subprocess, "run", run)
    with pytest.raises(AntigravityRunError, match="Timeout"):
        antigravity_cli.run_json("p", SCHEMA, timeout=120)


def test_run_missing_binary(monkeypatch):
    def run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(antigravity_cli.subprocess, "run", run)
    with pytest.raises(AntigravityRunError, match="nem található"):
        antigravity_cli.run_json("p", SCHEMA, timeout=60)


def test_find_agy_returns_str_or_none():
    result = find_agy()
    assert result is None or isinstance(result, str)


# --- átmeneti hibák -------------------------------------------------------

def test_transient_error_detection():
    assert antigravity_cli.is_transient_error(AntigravityRunError(
        "Antigravity hiba: API error (attempt 1): UNAVAILABLE (code 503): "
        "No capacity available for model gemini-3.6-flash-high on the server"))
    assert antigravity_cli.is_transient_error(AntigravityRunError("RESOURCE_EXHAUSTED"))
    assert not antigravity_cli.is_transient_error(AntigravityRunError("model not found"))
    # sorszám a hibaszövegben nem téveszthető 503-nak
    assert not antigravity_cli.is_transient_error(AntigravityRunError("Hiányzó: [5030]"))


def test_run_waits_and_retries_transient_errors(monkeypatch):
    outputs = iter([
        _stream({"status": "ERROR", "error": "UNAVAILABLE (code 503): No capacity"}),
        _stream({"status": "ERROR", "error": "UNAVAILABLE (code 503): No capacity"}),
        _stream({"status": "SUCCESS", "structured_output": {"translations": []}}),
    ])
    monkeypatch.setattr(antigravity_cli.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, next(outputs), ""))
    slept = []
    monkeypatch.setattr(antigravity_cli.time, "sleep", slept.append)
    assert antigravity_cli.run_json("p", SCHEMA, timeout=60) == {"translations": []}
    assert slept == list(antigravity_cli.TRANSIENT_DELAYS)


def test_run_gives_up_after_transient_delays(monkeypatch):
    calls = []
    def run(cmd, **kw):
        calls.append(1)
        return subprocess.CompletedProcess(
            cmd, 1, _stream({"status": "ERROR", "error": "code 429 rate limit"}), "")
    monkeypatch.setattr(antigravity_cli.subprocess, "run", run)
    monkeypatch.setattr(antigravity_cli.time, "sleep", lambda s: None)
    with pytest.raises(AntigravityRunError, match="429"):
        antigravity_cli.run_json("p", SCHEMA, timeout=60)
    assert len(calls) == len(antigravity_cli.TRANSIENT_DELAYS) + 1


def test_run_does_not_wait_on_permanent_error(monkeypatch):
    monkeypatch.setattr(antigravity_cli.subprocess, "run", _fake_run(
        _stream({"status": "ERROR", "error": "model not found"}), returncode=1))
    monkeypatch.setattr(antigravity_cli.time, "sleep",
                        lambda s: pytest.fail("állandó hibára nem szabad várni"))
    with pytest.raises(AntigravityRunError):
        antigravity_cli.run_json("p", SCHEMA, timeout=60)


def test_parse_denied_tool_gives_clear_error():
    raw = _stream({"status": "SUCCESS", "response": None,
                   "denied_actions": [{"action": "command", "display_name": "RunCommand"}]})
    with pytest.raises(AntigravityRunError, match="eszközt próbált használni.*RunCommand"):
        parse_agy_response(raw, SCHEMA)
