"""Kis, stdlib-alapú adapter a Codex CLI strukturált futtatásaihoz."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from subtr.providers import CliRunError

LABEL = "Codex"
MISSING_HINT = "A 'codex' parancs nem található a PATH-on."


class CodexRunError(CliRunError):
    """A Codex CLI nem futott le vagy nem adott érvényes JSON választ."""


def find_codex() -> str | None:
    """A Codex CLI elérési útja, vagy None ha nincs telepítve."""
    return shutil.which("codex")


# A prompt alapból ARGUMENTUMKÉNT megy (a stdin-es `-` mód egyes
# host-környezetekben nem adta vissza megbízhatóan a --output-schema
# kimenetet). A parancssornak viszont van hossza: Windows-on a CreateProcess
# 32 767 karakternél elhasal ("The filename or extension is too long"),
# Linuxon egy argumentum legfeljebb 128 KB. A review-prompt (szabályzat +
# szójegyzék + 100 cue + [FORRÁS] sorok) a Windows-limitet könnyen átlépi —
# ott a biztos hiba helyett a stdin-es utat választjuk. A limit alatt marad
# egy kis tartalék a `codex exec` saját kapcsolóinak és az útvonalaknak.
PROMPT_ARGV_LIMIT = 30000 if os.name == "nt" else 100000


def prompt_via_stdin(prompt: str) -> bool:
    """Igaz, ha a prompt túl hosszú ahhoz, hogy argumentumként átadjuk."""
    return len(prompt) > PROMPT_ARGV_LIMIT


def run_codex_json(prompt: str, schema: dict, *, timeout: int,
                   model: str | None = None, codex_bin: str = "codex"):
    """Read-only, ephemerális Codex futás, JSON-séma szerinti válasszal."""
    with tempfile.TemporaryDirectory(prefix="subtitle-codex-") as tmp_dir:
        tmp = Path(tmp_dir)
        schema_path = tmp / "schema.json"
        response_path = tmp / "response.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")

        cmd = [
            codex_bin, "exec", "--ephemeral", "--sandbox", "read-only",
            "--skip-git-repo-check",
            "--output-schema", str(schema_path),
            "--output-last-message", str(response_path),
        ]
        if model:
            cmd.extend(["--model", model])
        use_stdin = prompt_via_stdin(prompt)
        cmd.append("-" if use_stdin else prompt)  # lásd PROMPT_ARGV_LIMIT

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", timeout=timeout,
                input=prompt if use_stdin else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexRunError(f"Timeout ({timeout // 60} perc)") from exc
        except FileNotFoundError as exc:
            raise CodexRunError("A 'codex' parancs nem található a PATH-on.") from exc

        if proc.returncode != 0:
            details = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
            tail = " | ".join(line for line in details.splitlines() if line.strip())[-1200:]
            raise CodexRunError(f"Codex hiba (exit {proc.returncode}): {tail}")

        raw = (response_path.read_text(encoding="utf-8").strip()
               if response_path.is_file() else proc.stdout.strip())
        if not raw:
            raise CodexRunError("A Codex üres választ adott.")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CodexRunError(f"A Codex válasza nem érvényes JSON: {exc}") from exc


# A közös CLI-adapter felület (lásd subtr.providers docstring).
RunError = CodexRunError
find_cli = find_codex


def run_json(prompt: str, schema: dict, *, timeout: int,
             model: str | None = None, cli_bin: str | None = None):
    return run_codex_json(prompt, schema, timeout=timeout, model=model,
                          codex_bin=cli_bin or "codex")
