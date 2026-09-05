"""subtr.providers.codex_cli — a prompt átadási módja.

Rövid prompt argumentumként megy (a stdin-es mód egyes környezetekben nem
adta vissza a --output-schema kimenetet), a parancssor-limitet átlépő prompt
viszont stdin-en, különben Windows-on biztos hiba (32 767 karakter)."""

import json
import subprocess

import pytest

from subtr.providers import codex_cli


def _fake_run(calls):
    def run(cmd, **kw):
        calls.append((cmd, kw))
        # a válaszfájl helyét a --output-last-message után kapjuk
        out = cmd[cmd.index("--output-last-message") + 1]
        with open(out, "w", encoding="utf-8") as f:
            f.write(json.dumps({"translations": []}))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return run


def test_short_prompt_goes_as_argument(monkeypatch):
    calls = []
    monkeypatch.setattr(codex_cli.subprocess, "run", _fake_run(calls))
    codex_cli.run_codex_json("rövid prompt", {"type": "object"}, timeout=5)
    cmd, kw = calls[0]
    assert cmd[-1] == "rövid prompt"
    assert kw.get("input") is None


def test_long_prompt_goes_via_stdin(monkeypatch):
    calls = []
    monkeypatch.setattr(codex_cli.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(codex_cli, "PROMPT_ARGV_LIMIT", 100)
    long_prompt = "x" * 101
    codex_cli.run_codex_json(long_prompt, {"type": "object"}, timeout=5)
    cmd, kw = calls[0]
    assert cmd[-1] == "-"
    assert kw.get("input") == long_prompt


def test_windows_limit_is_below_createprocess_max():
    assert 30000 <= codex_cli.PROMPT_ARGV_LIMIT <= 131072


# ── hibautak ────────────────────────────────────────────────────────────────

def _run_returning(rc, stdout="", stderr=""):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr=stderr)
    return run


def test_nonzero_exit_raises_with_tail(monkeypatch):
    monkeypatch.setattr(codex_cli.subprocess, "run",
                        _run_returning(2, stderr="valami\nbaj történt"))
    with pytest.raises(codex_cli.CodexRunError, match="exit 2.*baj történt"):
        codex_cli.run_codex_json("p", {}, timeout=5)


def test_empty_and_invalid_response(monkeypatch):
    monkeypatch.setattr(codex_cli.subprocess, "run", _run_returning(0, stdout=""))
    with pytest.raises(codex_cli.CodexRunError, match="üres"):
        codex_cli.run_codex_json("p", {}, timeout=5)
    monkeypatch.setattr(codex_cli.subprocess, "run", _run_returning(0, stdout="nem json"))
    with pytest.raises(codex_cli.CodexRunError, match="nem érvényes JSON"):
        codex_cli.run_codex_json("p", {}, timeout=5)


def test_timeout_and_missing_binary(monkeypatch):
    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(codex_cli.subprocess, "run", timeout)
    with pytest.raises(codex_cli.CodexRunError, match="Timeout"):
        codex_cli.run_codex_json("p", {}, timeout=120)

    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(codex_cli.subprocess, "run", missing)
    with pytest.raises(codex_cli.CodexRunError, match="nem található"):
        codex_cli.run_codex_json("p", {}, timeout=5)


def test_stdout_fallback_when_no_response_file(monkeypatch):
    monkeypatch.setattr(codex_cli.subprocess, "run",
                        _run_returning(0, stdout='{"errors": []}'))
    assert codex_cli.run_codex_json("p", {}, timeout=5) == {"errors": []}
