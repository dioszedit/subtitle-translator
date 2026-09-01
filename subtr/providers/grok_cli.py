"""Kis, stdlib-alapú adapter a Grok CLI strukturált futtatásaihoz.

A Codex-úthoz hasonló: headless `grok --prompt-file --json-schema`, a modell
JSON-t ad, a Python írja az SRT-t / riportot. A prompt fájlba kerül (a Grok
CLI nem olvassa a stdin-t), a séma a `--json-schema` argumentum.

Az agent-es viselkedést szándékosan kikapcsoljuk: nincs tool, nincs plan,
nincs subagent, a `--cwd` egy üres temp mappa — így a projekt AGENTS.md-je
és a pipeline-skillek nem keverednek a fordító-promptba.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class GrokRunError(RuntimeError):
    """A Grok CLI nem futott le vagy nem adott érvényes JSON választ."""


def find_grok() -> str | None:
    """A Grok CLI elérési útja, vagy None ha nincs telepítve."""
    return shutil.which("grok")


SCHEMA_ROOT_KEYS = ("translations", "errors", "suggestions", "relations")

_FENCE_RE = re.compile(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", re.S)

# A scan csak akkor fut, ha a teljes kimenet nem parse-olható — ott viszont
# minden zárójel-pozíció egy-egy raw_decode kísérlet, ami egy nagy, csonka
# JSON-on négyzetes lenne. Ezért a kísérletek és a találatok száma is korlátos.
_MAX_EMBEDDED_ATTEMPTS = 2000
_MAX_EMBEDDED_CANDIDATES = 50


def _looks_like_response(value) -> bool:
    """Envelope vagy séma-gyökér — ezt keressük, ha több JSON is akad."""
    if not isinstance(value, dict):
        return False
    return any(key in value for key in
               ("structuredOutput", "structured_output", "type", "text")
               + SCHEMA_ROOT_KEYS)


def _scan_embedded_json(text: str):
    """Minden '{'/'[' pozíciótól egy `raw_decode` — így a JSON elé ÉS mögé
    kerülő szemét is lepereg (pl. prompt-echo, amiben szintén van zárójel).

    Ha több önálló JSON is van a kimenetben, az envelope-nak/séma-gyökérnek
    látszó nyer; különben az utolsó (a tényleges válasz jellemzően a végén
    áll). Egy sikeres dekódolás után a saját tartományát átugorjuk — a
    beágyazott részobjektumok nem külön jelöltek.
    """
    decoder = json.JSONDecoder()
    found = []
    attempts = 0
    index = 0
    length = len(text)
    while index < length:
        if text[index] not in "{[":
            index += 1
            continue
        attempts += 1
        if attempts > _MAX_EMBEDDED_ATTEMPTS:
            break
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index += 1
            continue
        if _looks_like_response(value):
            return value
        found.append(value)
        if len(found) >= _MAX_EMBEDDED_CANDIDATES:
            break
        index = end
    return found[-1] if found else None


def _loads(text: str, what: str):
    """JSON-kinyerés a nyers kimenetből: teljes szöveg → ```json fence →
    beágyazott JSON-scan. Sem a JSON elé, sem mögé kerülő szemét nem ejti el
    a választ."""
    last_exc = None
    candidates = [text]
    fence = _FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_exc = exc

    embedded = _scan_embedded_json(text)
    if embedded is not None:
        return embedded
    raise GrokRunError(f"{what} nem érvényes JSON: {last_exc}") from last_exc


def _as_object(value, where: str):
    """A sémáink gyökere mindig objektum — a lista/skalár válasz hiba.

    Enélkül a tasks réteg `.get(...)`-je AttributeError-ral szállna el,
    ami kikerülné a szabályos retry/hiba-utat.
    """
    if isinstance(value, dict):
        return value
    raise GrokRunError(
        f"A Grok {where} nem objektum, hanem {type(value).__name__} — "
        "a séma szerinti gyökér objektum lenne.")


def parse_grok_response(raw: str):
    """A headless `--output-format json` válaszából a séma szerinti objektum.

    Először a `structuredOutput` (camelCase; a smoke-teszt ezt adta), aztán
    a snake_case `structured_output`, majd az envelope nélküli gyökér-séma,
    végül a `text` mező JSON-parse-a. Hiba-envelope (`{"type":"error",...}`),
    üres/értelmezhetetlen kimenet és nem objektum válasz GrokRunError.
    """
    if raw is None or not str(raw).strip():
        raise GrokRunError("A Grok üres választ adott.")

    data = _loads(str(raw).strip(), "A Grok válasza")

    if isinstance(data, dict) and data.get("type") == "error":
        raise GrokRunError(data.get("message") or "Grok hiba")

    if isinstance(data, dict):
        structured = data.get("structuredOutput")
        if structured is None:
            structured = data.get("structured_output")
        if structured is not None:
            return _as_object(structured, "structuredOutput mezője")

        # structuredOutput nélkül csak befejezett fordulóban bízunk: a
        # `--max-turns 1` miatt egy toolt kérő modell "cancelled"-del áll le,
        # és a `text` ilyenkor CSONKA (fél translations-tömb) is lehet — azt
        # elfogadni néma cue-vesztés volna. Inkább hiba → retry.
        stop = data.get("stopReason") or data.get("stop_reason")
        if stop and stop != "end_turn":
            raise GrokRunError(
                f"A Grok futása nem fejeződött be (stopReason: {stop}), "
                "és nincs structuredOutput — a részleges válasz eldobva.")

        # Ha a CLI a séma szerinti objektumot adja a gyökérben (nincs envelope).
        if any(key in data for key in SCHEMA_ROOT_KEYS):
            return data

        payload = data.get("text")
        if isinstance(payload, (dict, list)):
            return _as_object(payload, "text mezője")
        if isinstance(payload, str) and payload.strip():
            return _as_object(_loads(payload.strip(), "A Grok text mezője"),
                              "text mezője")

    raise GrokRunError("A Grok válaszában nincs structuredOutput.")


def _fmt_timeout(timeout: int) -> str:
    """Emberi timeout-felirat — a percre kerekítés 60 mp alatt hazudna."""
    if timeout >= 60:
        return f"{timeout} mp / {timeout / 60:g} perc"
    return f"{timeout} mp"


def run_grok_json(prompt: str, schema: dict, *, timeout: int,
                  model: str | None = None, grok_bin: str = "grok"):
    """Headless, tool nélküli Grok futás, JSON-séma szerinti válasszal."""
    with tempfile.TemporaryDirectory(prefix="subtitle-grok-") as tmp_dir:
        tmp = Path(tmp_dir)
        prompt_path = tmp / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        cmd = [
            grok_bin,
            "--prompt-file", str(prompt_path),
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--output-format", "json",
            "--max-turns", "1",
            "--no-subagents",
            "--no-plan",
            "--disable-web-search",
            "--verbatim",
            "--tools", "",
            "--cwd", str(tmp),
        ]
        if model:
            cmd.extend(["-m", model])

        env = os.environ.copy()
        env.setdefault("GROK_MEMORY", "0")
        env.setdefault("GROK_DISABLE_AUTOUPDATER", "1")

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise GrokRunError(f"Timeout ({_fmt_timeout(timeout)})") from exc
        except FileNotFoundError as exc:
            raise GrokRunError("A 'grok' parancs nem található a PATH-on.") from exc

        if proc.returncode != 0:
            details = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
            tail = " | ".join(line for line in details.splitlines() if line.strip())[-1200:]
            raise GrokRunError(f"Grok hiba (exit {proc.returncode}): {tail}")

        return parse_grok_response(proc.stdout)
