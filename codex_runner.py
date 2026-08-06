"""Kis, stdlib-alapú adapter a Codex CLI strukturált futtatásaihoz."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


class CodexRunError(RuntimeError):
    """A Codex CLI nem futott le vagy nem adott érvényes JSON választ."""


def find_codex() -> str | None:
    """A Codex CLI elérési útja, vagy None ha nincs telepítve."""
    return shutil.which("codex")


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
            "--output-schema", str(schema_path),
            "--output-last-message", str(response_path),
        ]
        if model:
            cmd.extend(["--model", model])
        # A Codex CLI stdin-es `-` módja egyes host-környezetekben nem adja
        # vissza megbízhatóan a --output-schema kimenetet. A feliratblokkok
        # promptja jóval a macOS parancshossz-korlátja alatt marad, ezért a
        # promptot közvetlen argumentumként adjuk át.
        cmd.append(prompt)

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", timeout=timeout,
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
