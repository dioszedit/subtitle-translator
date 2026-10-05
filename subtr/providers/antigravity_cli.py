"""Kis, stdlib-alapú adapter az Antigravity CLI (`agy`) strukturált futtatásaihoz.

A Codex/Grok-úthoz hasonló: headless `agy -p= --json-schema`, a modell JSON-t
ad, a Python írja az SRT-t / riportot. A Gemini-modelleket az előfizetés
adja, API-kulcs és napi API-kvóta nélkül.

A prompt MINDEN platformon a stdin-en megy, stream-json NDJSON-sorként:

    {"event": "user", "message": {"content": "<prompt>"}}

Argumentumként nem adható át: a Windows parancssora 32 767 karakternél
elhasal, a fordító- és review-prompt pedig ennél hosszabb. A sor-formátum
nem dokumentált (az `agy` 1.2.16 hibaüzeneteiből derült ki) — ha egy
frissítés megváltoztatja, a hibaüzenet erre utal (lásd STDIN_FORMAT_HINT).

A kimenet szintén NDJSON; a `"event": "result"` sor `result` objektuma az
envelope: `{"status": "SUCCESS", "structured_output": {...}, ...}`.

Az agent-toolokat az `agy` nem engedi kikapcsolni, ezért a `cwd` egy üres
temp mappa — így a projekt AGENTS.md-je és fájljai nem kerülnek a modell
látókörébe, és nincs mihez hozzányúlnia. Egyes modellek (élesben: a
gemini-3.8-flash) ennek ellenére körülnéznének (`ls -la`); a headless mód ezt
letiltja, és a futás válasz nélkül ér véget. Ezért a prompt elé NO_TOOLS_PREAMBLE
kerül, a mégis megtagadott tool-hívás pedig beszédes hibát ad.
"""

import json
import re
import shutil
import subprocess
import tempfile
import time

from subtr.providers import CliRunError

LABEL = "Antigravity"
MISSING_HINT = ("Az 'agy' parancs (Antigravity CLI) nem található a PATH-on.\n"
                "      Telepítés és bejelentkezés után az `agy models` listázza "
                "az elérhető modelleket.")

# Ha az `agy` a bemenetet nem érti, a hibaüzenete ezekre a szavakra fut ki.
STDIN_FORMAT_HINT = ("Az Antigravity CLI nem fogadta el a stdin-es "
                     "stream-json bemenetet — lehet, hogy egy `agy`-frissítés "
                     "megváltoztatta a nem dokumentált formátumot "
                     "(subtr/providers/antigravity_cli.py, build_stdin_message).")
_STDIN_ERROR_RE = re.compile(r"stream input|failed to decode", re.I)

# A --print-timeout az `agy` saját korlátja; a subprocess-timeout ennél
# valamivel hosszabb, hogy a CLI rendezett hibát adhasson, mielőtt lelőnénk.
_KILL_GRACE_SECONDS = 30

# Szerveroldali, átmeneti hibák (kapacitáshiány, rate limit). Élesben látott:
# "UNAVAILABLE (code 503): No capacity available for model …". Ilyenkor az
# azonnali újrapróbálás ugyanígy elbukik, ezért az adapter VÁR, mielőtt újra
# hívna — a tasks réteg saját (azonnali) retry-ja ezen felül marad.
_TRANSIENT_RE = re.compile(
    r"\b(503|429|UNAVAILABLE|RESOURCE_EXHAUSTED)\b|no capacity|overloaded|rate limit",
    re.I)
TRANSIENT_DELAYS = (20, 60)  # másodperc; a hossza = a várakozásos újrapróbálások száma

NO_TOOLS_PREAMBLE = (
    "FONTOS: Ne használj semmilyen eszközt (tool), ne futtass parancsot, ne olvass "
    "fájlt — a munkamappa üres, minden szükséges adat ebben az üzenetben van. "
    "Válaszolj közvetlenül, a megadott JSON-séma szerint.\n\n")

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


class AntigravityRunError(CliRunError):
    """Az Antigravity CLI nem futott le vagy nem adott érvényes JSON választ."""


def find_agy() -> str | None:
    """Az Antigravity CLI elérési útja, vagy None ha nincs telepítve."""
    return shutil.which("agy")


def build_stdin_message(prompt: str) -> str:
    """A prompt egyetlen stream-json bemeneti sorként (újsorral lezárva)."""
    return json.dumps({"event": "user", "message": {"content": prompt}},
                      ensure_ascii=False) + "\n"


def _result_envelope(raw: str) -> dict:
    """A stream-json kimenetből az utolsó `"event": "result"` sor `result`-ja.

    A nem JSON sorokat (pl. figyelmeztetés a stdout-on) átugorjuk; az
    `init` / `step_update` események nem érdekesek."""
    envelope = None
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "result":
            result = event.get("result")
            if isinstance(result, dict):
                envelope = result
    if envelope is None:
        raise AntigravityRunError("Az Antigravity kimenetében nincs result esemény.")
    return envelope


def _parse_response_text(text: str):
    """Tartalék: a `response` szöveg JSON-ja, ha nincs `structured_output`."""
    candidates = [text]
    fence = _FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def parse_agy_response(raw: str, schema: dict | None = None) -> dict:
    """A headless stream-json kimenetből a séma szerinti objektum.

    Elsődleges a `structured_output`. Ha nincs, a `response` szöveg JSON-ja —
    de abba a modell plusz kulcsokat is tehet (pl. `toolAction`), ezért ott a
    séma gyökérkulcsaira szűrünk. Hiba-státusz, üres kimenet és nem objektum
    válasz AntigravityRunError.
    """
    if raw is None or not str(raw).strip():
        raise AntigravityRunError("Az Antigravity üres választ adott.")

    envelope = _result_envelope(str(raw))
    status = envelope.get("status")
    if status != "SUCCESS":
        message = envelope.get("error") or f"status: {status}"
        if _STDIN_ERROR_RE.search(message):
            message = f"{message} — {STDIN_FORMAT_HINT}"
        raise AntigravityRunError(f"Antigravity hiba: {message}")

    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured
    if structured is not None:
        raise AntigravityRunError(
            f"Az Antigravity structured_output mezője nem objektum, hanem "
            f"{type(structured).__name__}.")

    text = envelope.get("response")
    parsed = _parse_response_text(text.strip()) if isinstance(text, str) and text.strip() else None
    if not isinstance(parsed, dict):
        denied = [a.get("display_name") or a.get("action") for a in envelope.get("denied_actions") or []
                  if isinstance(a, dict)]
        if denied:
            raise AntigravityRunError(
                f"A modell eszközt próbált használni ({', '.join(map(str, denied))}), amit a "
                f"headless mód letiltott — válasz nem született.")
        raise AntigravityRunError("Az Antigravity válaszában nincs structured_output.")
    keys = (schema or {}).get("properties")
    if keys:
        parsed = {k: v for k, v in parsed.items() if k in keys}
        if not parsed:
            raise AntigravityRunError(
                "Az Antigravity válaszában nincs structured_output, és a "
                "szövegválasz nem a séma szerinti objektum.")
    return parsed


def _fmt_timeout(timeout: int) -> str:
    """Emberi timeout-felirat — a percre kerekítés 60 mp alatt hazudna."""
    if timeout >= 60:
        return f"{timeout} mp / {timeout / 60:g} perc"
    return f"{timeout} mp"


def build_command(agy_bin: str, schema: dict, *, timeout: int,
                  model: str | None = None) -> list[str]:
    """A headless `agy` parancssor. A prompt NEM része — az a stdin-en megy.

    A `-p=` alak kell: `-p` után szóközzel a következő kapcsolót venné
    promptnak."""
    cmd = [
        agy_bin,
        "-p=",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--print-timeout", f"{timeout}s",
        "--disable-slash-commands",
    ]
    if model:
        cmd.extend(["--model", model])
    return cmd


def is_transient_error(exc: Exception) -> bool:
    """Átmeneti szerveroldali hiba-e (kapacitás / rate limit) — erre érdemes várni."""
    return bool(_TRANSIENT_RE.search(str(exc)))


def run_agy_json(prompt: str, schema: dict, *, timeout: int,
                 model: str | None = None, agy_bin: str = "agy"):
    """Headless Antigravity futás, átmeneti hibánál várakozásos újrapróbálással."""
    for delay in TRANSIENT_DELAYS:
        try:
            return _run_once(prompt, schema, timeout=timeout, model=model, agy_bin=agy_bin)
        except AntigravityRunError as exc:
            if not is_transient_error(exc):
                raise
            print(f"  Antigravity: átmeneti szerverhiba, {delay} mp múlva újra… "
                  f"({str(exc)[:120]})")
            time.sleep(delay)
    return _run_once(prompt, schema, timeout=timeout, model=model, agy_bin=agy_bin)


def _run_once(prompt: str, schema: dict, *, timeout: int,
              model: str | None, agy_bin: str):
    """Egy headless Antigravity futás üres temp mappában, JSON-séma szerinti válasszal."""
    with tempfile.TemporaryDirectory(prefix="subtitle-agy-") as tmp_dir:
        cmd = build_command(agy_bin, schema, timeout=timeout, model=model)
        try:
            proc = subprocess.run(
                cmd, input=build_stdin_message(NO_TOOLS_PREAMBLE + prompt),
                capture_output=True, text=True, encoding="utf-8",
                timeout=timeout + _KILL_GRACE_SECONDS, cwd=tmp_dir,
            )
        except subprocess.TimeoutExpired as exc:
            raise AntigravityRunError(f"Timeout ({_fmt_timeout(timeout)})") from exc
        except FileNotFoundError as exc:
            raise AntigravityRunError("Az 'agy' parancs nem található a PATH-on.") from exc

        try:
            return parse_agy_response(proc.stdout, schema)
        except AntigravityRunError as exc:
            # A result-envelope hibaüzenete (status: ERROR) már beszédes;
            # csak értelmezhetetlen kimenetnél mond többet a stderr.
            if proc.returncode == 0 or str(exc).startswith("Antigravity hiba:"):
                raise
            details = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
            tail = " | ".join(line for line in details.splitlines() if line.strip())[-1200:]
            if _STDIN_ERROR_RE.search(tail):
                tail = f"{tail} — {STDIN_FORMAT_HINT}"
            raise AntigravityRunError(
                f"Antigravity hiba (exit {proc.returncode}): {tail}") from None


# A közös CLI-adapter felület (lásd subtr.providers docstring).
RunError = AntigravityRunError
find_cli = find_agy


def run_json(prompt: str, schema: dict, *, timeout: int,
             model: str | None = None, cli_bin: str | None = None):
    return run_agy_json(prompt, schema, timeout=timeout, model=model,
                        agy_bin=cli_bin or "agy")
