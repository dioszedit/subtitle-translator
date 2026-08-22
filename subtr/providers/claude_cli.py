"""Kis, stdlib-alapú adapter a Claude Code CLI hívásaihoz.

A repóban négy hely kereste meg és hívta meg saját maga a `claude` parancsot
(glossary_extract.py, register_extract.py, translate_parallel.py,
review_with_claude.py) — ez a modul a közös részt fogja össze: a CLI
elérési útjának feloldását, a `claude -p -` subprocess-hívást és a válaszból
a JSON kinyerését.
"""

import json
import os
import re
import shutil
import subprocess


def find_claude() -> str:
    """A Claude CLI elérési útjának feloldása.

    Sorrend: PATH (shutil.which), majd a Windows-os tipikus telepítési
    helyek (~/.local/bin/claude.exe, ill. az npm globális claude.cmd),
    végül fallback a puszta "claude" string — ha egyik se található,
    hadd kapja el a hívó a FileNotFoundError-t a subprocess.run-ból.
    """
    found = shutil.which("claude")
    if found:
        return found
    local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    if os.path.isfile(local_bin):
        return local_bin
    npm_global = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
    if os.path.isfile(npm_global):
        return npm_global
    return "claude"  # fallback, hadd kapja el a FileNotFoundError


def which_claude() -> str | None:
    """Mint find_claude(), csak None-t ad vissza, ha sehol nem található
    (nincs erőltetett "claude" fallback). Olyan hívóknak, akik a hiányt
    maguk akarják jelezni, mielőtt subprocess-et indítanának."""
    found = shutil.which("claude")
    if found:
        return found
    local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    if os.path.isfile(local_bin):
        return local_bin
    npm_global = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
    if os.path.isfile(npm_global):
        return npm_global
    return None


def run_prompt(prompt: str, timeout: int, claude_bin: str | None = None) -> tuple[str | None, str | None]:
    """A `claude -p -` közös subprocess-váza: a promptot stdin-en küldi,
    és a nyers stdoutot adja vissza.

    Visszatérés: (stdout, None) sikernél, (None, hibaüzenet) hiba esetén
    (nem 0 exit kód, timeout, vagy hiányzó CLI).
    """
    claude_cmd = claude_bin or find_claude()
    try:
        proc = subprocess.run(
            [claude_cmd, "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        return None, f"Timeout ({timeout} mp)"
    except FileNotFoundError:
        return None, f"A 'claude' parancs nem található (keresett: {claude_cmd})"

    if proc.returncode != 0:
        msg = f"Claude Code hiba (exit code: {proc.returncode})"
        if proc.stderr:
            msg += f"\n  stderr: {proc.stderr[:400]}"
        return None, msg

    return proc.stdout, None


def extract_json(raw: str):
    """Robusztus JSON-kinyerés a Claude CLI válaszából.

    Stratégia: (1) ```json ... ``` fence belseje, (2) az első '{' vagy '['
    és az utolsó '}' vagy ']' közötti rész, (3) a nyers szöveg egészben.
    Mindegyiket megpróbálja json.loads-szal; None, ha egyik se parse-olható.
    Objektumot és tömböt egyaránt kinyer.
    """
    if raw is None:
        return None
    raw = raw.strip()

    candidates = []

    fence_match = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", raw, re.S)
    if fence_match:
        candidates.append(fence_match.group(1))

    first_obj, last_obj = raw.find("{"), raw.rfind("}")
    first_arr, last_arr = raw.find("["), raw.rfind("]")
    # Amelyik zárójelpár előbb kezdődik a szövegben, azt próbáljuk előbb —
    # így a válasz tényleges szerkezetéhez (objektum vagy tömb) igazodunk.
    spans = []
    if first_obj != -1 and last_obj > first_obj:
        spans.append((first_obj, raw[first_obj:last_obj + 1]))
    if first_arr != -1 and last_arr > first_arr:
        spans.append((first_arr, raw[first_arr:last_arr + 1]))
    for _, span in sorted(spans, key=lambda s: s[0]):
        candidates.append(span)

    candidates.append(raw)

    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


READ_PREFIX_RE = re.compile(r"^(\d+)\t(.*)$")


def strip_read_line_numbers(content: str) -> str | None:
    """A Read tool sorszám-prefixeinek eltávolítása az agent által ÍRT fájlból.

    A Claude Code Read toolja `sorszám<TAB>tartalom` alakban mutatja a fájlt
    (mint a `cat -n`). Az agent időnként ezt a megjelenítési formát másolja
    tovább a Write-ba, így a kimeneti SRT minden sora sorszámozott lesz:

        1\t1
        2\t00:00:12,530 --> 00:00:20,580
        3\t♪Az őskáoszból a csillagos égig♪
        4                     <- az üres sor csak a sorszámot kapja
        5\t2

    A fordítás ilyenkor jó, csak a szerializálás romlott el — ez a függvény
    visszaállítja az eredeti szöveget. Többsoros felirat folytatássora nem kap
    sorszámot, azt változatlanul átvesszük.

    Visszatérés: a megtisztított szöveg, vagy None, ha a tartalom nem ilyen
    alakú (nincs egyetlen `szám<TAB>` prefixű sor sem) — a hívó ilyenkor a
    szokásos hibaágon megy tovább.
    """
    lines = content.split("\n")
    trailing_newline = bool(lines) and lines[-1] == ""
    if trailing_newline:
        lines = lines[:-1]

    out = []
    expected = 1
    seen_prefix = False
    for line in lines:
        m = READ_PREFIX_RE.match(line)
        if m and int(m.group(1)) == expected:
            out.append(m.group(2))
            expected += 1
            seen_prefix = True
        elif seen_prefix and line.isdigit() and int(line) == expected:
            # csak a sorszámot tartalmazó sor = eredetileg üres sor. Ezt CSAK
            # akkor értelmezzük így, ha már láttunk valódi prefixet — különben
            # egy ép SRT első sorát ("1") is kitörölnénk.
            out.append("")
            expected += 1
        else:
            out.append(line)

    if not seen_prefix:
        return None
    return "\n".join(out) + ("\n" if trailing_newline else "")


def write_sys_prompt_file(content: str, prefix: str) -> str:
    """Sys prompt mentése tartalom-hash alapú névvel — két párhuzamos futás
    azonos tartalommal ugyanazt a fájlt használja, eltérővel külön fájlt.
    A régi (más hash-ű) fájlokat kitakarítja, hogy ne halmozódjanak a repo
    gyökerében."""
    import glob
    import hashlib

    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    path = os.path.abspath(f"{prefix}{h}.txt")
    for stale in glob.glob(f"{prefix}*.txt"):
        if os.path.abspath(stale) != path:
            try:
                os.remove(stale)
            except OSError:
                pass
    if os.path.isfile(path):
        return path
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def kill_process_tree(proc):
    """Timeout után a TELJES folyamatfát leöljük. Windows-on a claude.cmd
    shim alatt futó node process árvaként túlélné a sima kill-t, és utólag
    (a törlés UTÁN) még kiírhatná a kimeneti fájlt — amit a resume aztán
    késznek látna."""
    import subprocess

    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass
