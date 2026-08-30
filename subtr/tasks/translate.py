"""Translate-task — a blokk-fordítás közös váza, provider-executorokkal.

A blokk-felfedezés, a --block kezelés, a checkpoint-logika, a szálkezelés és
az összegzés EGY példányban él; a provider egy blokk-fordító closure:
(block_path) -> {"block", "status", "message"}.

A három provider vezérlési modellje szándékosan különbözik, és ez itt is
látszik:
  - gemini: API-hívás strukturált JSON-nal; a szerkezetet (sorszám, időbélyeg)
    Python garantálja, a modell csak szöveget kap és ad.
  - codex: ugyanez a szöveg-transzformer minta a Codex CLI-n át.
  - claude (DOKUMENTÁLT KIVÉTEL): nem szöveg-transzformer — a Claude Code
    agent maga olvassa az input fájlt és írja a _HUN.srt-t (Read,Write
    tool-okkal). Ezért itt subprocess + fájlrendszer-ellenőrzés a minta,
    sys-prompt-fájllal (tartalom-hash név, prompt-cache barát).

A prompt-szövegek providerenkénti megfogalmazása változatlan (bájtra azonos
a refaktor előttivel) — a három prompt tudatosan más, mert a három modell
másképp kapja a feladatot.
"""

import argparse
import glob
import hashlib
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from subtr import config
from subtr.config import PROVIDERS
from subtr.blocks import get_all_blocks, get_pending_blocks, hun_path, safe_remove
from subtr.context import load_translation_context
from subtr.glossary import as_prompt_text
from subtr.providers import claude_cli
from subtr.providers import codex_cli
from subtr.providers import gemini as gemini_provider
from subtr.srt import count_sections, count_sections_text, parse_sections, read_text, write_srt

TEMPERATURE = 0.3
MAX_RETRIES = 4
MODEL_BUILTIN = {"gemini": "gemini-3.6-flash", "claude": "sonnet", "codex": None}

CLAUDE_SYS_PROMPT_PREFIX = ".translate_sys_prompt_"
CLAUDE_SYS_PROMPT_MAX_AGE_DAYS = 1  # ennél régebbi sys prompt fájlokat takarítjuk

# Futási napló. A konzol-kimenet elszáll a scrollbackkel, a hibák oka viszont
# (megtagadás, timeout, szekció-eltérés) csak utólag derül ki — ezért minden
# blokk-eredmény ide is bekerül, a `detail` mezővel együtt, ami a konzolra
# hosszú lenne. A fájl a projekt gyökerében él (mint a sys prompt fájlok).
TRANSLATE_LOG = ".translate.log"
TRANSLATE_LOG_MAX_BYTES = 2 * 1024 * 1024  # e fölött .1-re forgatjuk
LOG_DETAIL_MAX_CHARS = 4000  # a teljes agent-válasz nyers hossza korlátozva

_log_lock = threading.Lock()


def log_path() -> str:
    return os.path.abspath(TRANSLATE_LOG)


def rotate_log():
    """Túl nagy napló forgatása — best-effort, hiba esetén némán tovább."""
    try:
        path = log_path()
        if os.path.isfile(path) and os.path.getsize(path) > TRANSLATE_LOG_MAX_BYTES:
            os.replace(path, path + ".1")
    except Exception:
        pass


def log(text: str, detail: str = ""):
    """Egy bejegyzés a futási naplóba (időbélyeggel). Sosem dob kivételt:
    a naplózás nem buktathatja el a fordítást."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"{stamp} {text}"]
        if detail:
            snippet = detail.strip()[:LOG_DETAIL_MAX_CHARS]
            lines += [f"    | {l}" for l in snippet.splitlines() if l.strip()]
        with _log_lock:
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    except Exception:
        pass

# Részleges megtagadás nyoma: az agent szerkezetileg ÉP fájlt ír (jó szekciószám,
# jó sorszám/időbélyeg), de egyes cue-k tartalmát placeholderre cseréli. A
# szerkezeti ellenőrzés ezt nem fogja meg, ezért külön nézzük — enélkül a hiányos
# fordítás "ok" státusszal menne tovább a merge-be.
PLACEHOLDER_MARKERS = ("[DAL]", "[SONG]", "[LYRICS]", "[NEM FORDITHATO]",
                       "[NEM FORDÍTHATÓ]", "[NOT TRANSLATED]", "[UNTRANSLATED]",
                       "[TODO]")
# Ezek részstringként túl általánosak (egy legitim felirat is tartalmazhat
# "[...]"-t kihagyás-jelölésként) — csak akkor placeholderek, ha egy sor
# TELJES tartalmát adják.
PLACEHOLDER_LINE_MARKERS = ("[...]", "[…]")


def find_placeholder_sections(output_path: str, input_path: str | None = None) -> list[str]:
    """Placeholder-re cserélt vagy üres szövegű cue-k sorszámai.

    Üres kimeneti cue csak akkor gyanús, ha a forrás ugyanazon cue-ja NEM üres:
    a legitim üres forrás-cue (a srt.py érvényesnek tekinti) különben minden
    futásnál "részleges megtagadás"-nak számítana, és a blokk sosem készülne el.
    Ha nincs input_path, minden üres cue találat (régi viselkedés).
    """
    try:
        sections = parse_sections(output_path)
    except Exception:
        return []
    source_empty: set[str] = set()
    if input_path:
        try:
            source_empty = {s["num"] for s in parse_sections(input_path)
                            if not (s.get("text") or "").strip()}
        except Exception:
            source_empty = set()
    hits = []
    for section in sections:
        text = (section.get("text") or "").strip()
        upper = text.upper()
        if not text:
            if section["num"] not in source_empty:
                hits.append(section["num"])
        elif (any(marker in upper for marker in PLACEHOLDER_MARKERS)
              or any(line.strip() in PLACEHOLDER_LINE_MARKERS
                     for line in text.splitlines())):
            hits.append(section["num"])
    return hits


def placeholder_warning(output_path: str, input_path: str | None = None) -> str | None:
    """Warning-üzenet, ha az output placeholder/üres cue-kat tartalmaz (különben None)."""
    hits = find_placeholder_sections(output_path, input_path)
    if not hits:
        return None
    preview = ", ".join(str(n) for n in hits[:5])
    if len(hits) > 5:
        preview += ", ..."
    return (f"Placeholder/üres cue: {len(hits)} db ({preview}) — részleges "
            f"megtagadás gyanúja, output törölve, újrafutáskor újrafordítjuk")


def placeholder_detail(output_path: str, input_path: str | None = None) -> str:
    """A naplóba: az ÖSSZES érintett cue sorszáma (a message csak 5-öt mutat)."""
    hits = find_placeholder_sections(output_path, input_path)
    if not hits:
        return ""
    return "érintett cue-k: " + ", ".join(str(n) for n in hits)


# Codex strict séma
CODEX_TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"sorszam": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["sorszam", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["translations"],
    "additionalProperties": False,
}

# Pydantic séma a Gemini structured outputhoz — lazy, hogy a --help
# függőségek nélkül is fusson.
try:
    from pydantic import BaseModel

    class TranslationItem(BaseModel):
        sorszam: int
        text: str

    class TranslationOutput(BaseModel):
        translations: list[TranslationItem]
except ImportError:
    TranslationOutput = None


# ────────────────────────────────────────────────────────────────────────────
# Promptok — providerenként, bájtra a refaktor előtti szöveggel
# ────────────────────────────────────────────────────────────────────────────

def formality_rule(src_lang: str, bullet: str = "- ") -> str:
    """A tegezés/magázás szabály szövege — a forrásnyelvtől függ.

    Az angol `you` nem jelöli a formalitást, ezért ott a szabály a döntés
    kikerülésére biztat. A legtöbb más forrásnyelv viszont grammatikailag
    jelöli (Sie/du, 您/你, keigo…) — ott a forrás KÖZVETLEN bizonyíték, és
    kár lenne kikerülni a döntést, amit a felirat már meghozott.

    A `bullet` a felsorolásokba szánt "- " prefix; üres stringgel önálló
    bekezdésként (Codex-ág) formáz, behúzás nélkül.
    """
    marker = config.source_lang_formality(src_lang)
    if not marker:
        lines = [
            "Tegezés/magázás: kövesd a sorozatkontextus Megszólítási regiszterét; ha nincs",
            "rá adat és a forrás jeleiből sem egyértelmű, fogalmazz úgy, hogy ne kelljen",
            "választani. Ne találj ki viszonyt.",
        ]
    else:
        name = config.the_source_lang(src_lang)
        lines = [
            "Tegezés/magázás: a sorozatkontextus Megszólítási regisztere az elsődleges.",
            f"Ahol az nem rendelkezik, {name} forrás MAGA JELÖLI a formalitást",
            f"({marker}) — ezt kövesd, ez közvetlen bizonyíték, nem találgatás.",
            "Csak ott kerüld ki a döntést, ahol sem a regiszter, sem a forrás nem dönt.",
        ]
    indent = " " * len(bullet)
    return "\n".join([bullet + lines[0]] + [indent + ln for ln in lines[1:]])


def build_system_instruction(claude_md: str, glossary: str,
                             src_lang: str = config.DEFAULT_SOURCE_LANG) -> str:
    """Gemini system instruction."""
    src = config.source_lang_name(src_lang)
    parts = [f"""=== SZEREP ===
Profi felirat-fordító vagy. {src.capitalize()} nyelvű SRT feliratokat fordítasz
természetes, beszélt magyar nyelvre. NEM tükörfordítasz.

=== KEMÉNY SZABÁLYOK ===
- HTML tagek (<i>, </i>, <b>, </b>), kötőjeles párbeszéd (-), [szögletes
  zárójeles megjegyzések], ♫ daljelek MEGŐRZENDŐK a magyar szövegben.
- Karakterneveket NE fordítsd le (a szójegyzékben szerepelnek a helyes
  írásmódok).
- Az "episode" magyarul mindig "rész", NEM "epizód".
{formality_rule(src_lang)}
- Minden átadott szekcióhoz pontosan egy fordítás tartozzon — sem több, sem kevesebb.

=== KIMENET ===
JSON séma szerint, minden átadott szekcióhoz:
- sorszam: az eredeti szekciószám pontosan ahogy a kérésben szerepel
- text: a magyar fordítás (HTML/kötőjel/daljelek megőrizve, többsoros lehet)

A `translations` tömb minden szekciót tartalmazzon (a kérésben szereplő
sorszámokat). Ne hagyj ki és ne adj hozzá szekciókat."""]

    if claude_md.strip():
        parts.append("=== SOROZAT KONTEXTUS (CLAUDE.md) ===\n" + claude_md.strip())

    if glossary.strip():
        parts.append(
            "=== SZÓJEGYZÉK — KÖTELEZŐ HASZNÁLNI EZEKET A FORDÍTÁSOKAT ===\n"
            + glossary.strip()
        )

    return "\n\n".join(parts)


def build_block_prompt(sections: list[dict],
                       src_lang: str = config.DEFAULT_SOURCE_LANG) -> str:
    """Gemini per-blokk prompt: a szekciók szövegei #N prefixszel listázva."""
    src = config.source_lang_name(src_lang)
    items = []
    for s in sections:
        items.append(f"#{s['num']}\n{s['text']}")
    return (
        f"Fordítsd le az alábbi SRT szekciók szövegét {src} nyelvről magyarra. "
        "Tartsd meg a sorszámokat (#N prefix), és minden szekcióra adj "
        "fordítást a system promptban leírt JSON séma szerint.\n\n"
        + "\n\n".join(items)
    )


def build_codex_instruction(context: str, glossary: str,
                            src_lang: str = config.DEFAULT_SOURCE_LANG) -> str:
    src = config.source_lang_name(src_lang)
    parts = [f"""Profi felirat-fordító vagy. {src.capitalize()} nyelvű SRT feliratszövegeket fordítasz természetes, beszélt magyarra.

KÖTELEZŐ: minden kapott sorszámhoz pontosan egy fordítást adj. A text csak a magyar feliratszöveg legyen; a HTML tageket, kötőjeles párbeszédet, szögletes megjegyzéseket és ♫ jelet őrizd meg. Ne adj magyarázatot.

{formality_rule(src_lang, bullet="")}"""]
    if context.strip():
        parts.append("=== SOROZAT KONTEXTUS ÉS SZABÁLYOK ===\n" + context.strip())
    if glossary.strip():
        parts.append("=== KÖTELEZŐ SZÓJEGYZÉK ===\n" + glossary)
    return "\n\n".join(parts)


def build_codex_prompt(instruction: str, sections: list[dict]) -> str:
    entries = "\n\n".join(f"#{s['num']}\n{s['text']}" for s in sections)
    return f"{instruction}\n\n=== FELADAT ===\nFordítsd le az alábbi szekciókat.\n\n{entries}"


def build_claude_system_prompt(claude_md: str, glossary: str,
                               src_lang: str = config.DEFAULT_SOURCE_LANG) -> str:
    """Claude Code system prompt — az agent fájlt olvas/ír, nem szöveget ad vissza."""
    src = config.source_lang_name(src_lang)
    parts = []
    parts.append(f"""=== SZEREP ===
Profi felirat-fordító vagy. {src.capitalize()} nyelvű SRT feliratokat fordítasz
természetes, beszélt magyar nyelvre. NEM tükörfordítasz.

=== KEMÉNY SZABÁLYOK ===
- A sorszámokat és időbélyegeket PONTOSAN másold át, NE generáld fejből!
- NE számozd újra a szekciókat 1-től, és NE szúrj be plusz sorszám-sort —
  minden szekció ELSŐ sora az eredeti sorszám maradjon.
- HTML tagek (<i>, </i>), kötőjeles párbeszéd (-), [megjegyzések], ♫ jelölés őrizve.
- Karakterneveket NE fordítsd le.
- Az output PONTOSAN ugyanannyi szekciót tartalmazzon, mint az input.
- Csak a kért output fájlt írd ki — semmi extra magyarázat, semmi visszajelzés.
- A Read tool `sorszám<TAB>tartalom` alakban MUTATJA a fájlt (mint a `cat -n`).
  Ez csak megjelenítés, NEM a fájl tartalma! A kiírt fájlba SOHA ne kerüljön
  sorszám-prefix és tabulátor a sorok elejére — az első sor pontosan az SRT
  szekciószám legyen (`1`), nem `1<TAB>1`.
{formality_rule(src_lang)}

=== FOLYAMAT ===
1. Olvasd be a megadott input SRT fájlt.
2. Fordítsd le a szöveget — sorszám + időbélyeg változatlanul.
3. Mentsd a megadott output fájlba.
4. Kész — ne írj összefoglalót, ne ellenőrizd újra.""")

    if claude_md.strip():
        parts.append("=== SOROZAT KONTEXTUS (CLAUDE.md) ===\n" + claude_md.strip())

    if glossary.strip():
        parts.append(
            "=== SZÓJEGYZÉK — KÖTELEZŐ HASZNÁLNI EZEKET A FORDÍTÁSOKAT ===\n"
            + glossary.strip()
        )

    return "\n\n".join(parts)


def write_claude_sys_prompt_file(content: str) -> tuple[str, bool]:
    """Sys prompt fájl tartalom-hash alapú névvel — (útvonal, újonnan_készült).

    Két párhuzamos Python process azonos tartalommal ugyanazt a fájlt használja
    (atomi rename), eltérő tartalommal külön fájlt kap. A régi fájlokat NEM
    töröljük itt (másik process használhatja) — azt a kor-alapú takarítás végzi.
    """
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    sys_path = os.path.abspath(f"{CLAUDE_SYS_PROMPT_PREFIX}{h}.txt")

    if os.path.isfile(sys_path):
        return sys_path, False

    tmp_path = sys_path + f".tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.replace(tmp_path, sys_path)  # atomi op
        return sys_path, True
    except Exception:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        if os.path.isfile(sys_path):
            return sys_path, False  # másik process megírta — használhatjuk
        raise RuntimeError(f"Nem sikerült létrehozni a sys prompt fájlt: {sys_path}")


def cleanup_stale_sys_prompts(max_age_days: int = CLAUDE_SYS_PROMPT_MAX_AGE_DAYS):
    """Régebbi sys prompt fájlok törlése — biztonsági takarítás."""
    cutoff = time.time() - max_age_days * 86400
    for f in glob.glob(f"{CLAUDE_SYS_PROMPT_PREFIX}*.txt"):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
        except Exception:
            pass


# ────────────────────────────────────────────────────────────────────────────
# Blokk-fordítók providerenként: (block_path) -> result dict
# ────────────────────────────────────────────────────────────────────────────

def _make_gemini_translator(client, model, system_instruction, max_retries,
                            src_lang=config.DEFAULT_SOURCE_LANG):
    def translate_block(block_path: str) -> dict:
        output_path = hun_path(block_path)
        block_name = os.path.basename(block_path)
        result = {"block": block_name, "status": "unknown", "message": ""}

        print(f"[START] {block_name}")
        try:
            sections = parse_sections(block_path)
        except Exception as e:
            result["status"] = "fail"
            result["message"] = f"Parse hiba: {e}"
            return result
        if not sections:
            result["status"] = "fail"
            result["message"] = "Üres blokk vagy parse-hiba"
            return result

        in_count = len(sections)
        parsed, err_msg = gemini_provider.call_json(
            client, model, build_block_prompt(sections, src_lang),
            schema=TranslationOutput, system=system_instruction,
            temperature=TEMPERATURE, max_retries=max_retries)
        if err_msg:
            result["status"] = "fail"
            result["message"] = err_msg
            safe_remove(output_path)
            return result

        # Lookup-tábla a fordításokhoz sorszám alapján
        translations = {item.sorszam: item.text for item in parsed.translations}
        if len(translations) < len(parsed.translations):
            dups = len(parsed.translations) - len(translations)
            print(f"  [!] {block_name}: {dups} duplikált sorszám a válaszban — "
                  f"az utolsó változat marad")

        # Hiányzó / extra sorszámok ellenőrzése
        try:
            expected_nums = {int(s["num"]) for s in sections}
        except ValueError:
            bad = [s["num"] for s in sections if not s["num"].strip().isdigit()]
            result["status"] = "fail"
            result["message"] = f"Nem numerikus sorszám az input blokkban: {bad[:5]}"
            return result
        returned_nums = set(translations.keys())
        missing = expected_nums - returned_nums
        extra = returned_nums - expected_nums

        if missing:
            result["status"] = "fail"
            result["message"] = (
                f"Hiányzó fordítás {len(missing)} szekcióhoz "
                f"(első 5: {sorted(missing)[:5]})"
            )
            safe_remove(output_path)
            return result

        if extra:
            print(f"  [!] {block_name}: {len(extra)} extra sorszám a válaszban, ignorálva")

        # Reassemble: eredeti sorszám + időbélyeg + fordított szöveg
        out_sections = [{"num": s["num"], "timestamp": s["timestamp"],
                         "text": translations[int(s["num"])]} for s in sections]
        try:
            write_srt(output_path, out_sections)
        except Exception as e:
            result["status"] = "fail"
            result["message"] = f"Írás hiba: {e}"
            safe_remove(output_path)
            return result

        out_count = count_sections(output_path)
        if in_count == out_count:
            stub = placeholder_warning(output_path, block_path)
            if stub:
                result["status"] = "warning"
                result["message"] = stub
                result["detail"] = placeholder_detail(output_path, block_path)
                safe_remove(output_path)
                return result
            result["status"] = "ok"
            result["message"] = f"{out_count} szekció"
        else:
            # A hibás outputot töröljük, különben a resume késznek látná
            result["status"] = "warning"
            result["message"] = (f"Szekciószám eltérés! Input: {in_count}, "
                                 f"Output: {out_count} — output törölve, "
                                 f"újrafutáskor újrafordítjuk")
            safe_remove(output_path)
        return result
    return translate_block


def _make_codex_translator(codex_bin, model, instruction, timeout, retries):
    def translate_block(block_path: str) -> dict:
        output_path = hun_path(block_path)
        name = os.path.basename(block_path)
        print(f"[START] {name}")
        try:
            sections = parse_sections(block_path)
            expected = {int(s["num"]) for s in sections}
        except Exception as exc:
            return {"block": name, "status": "fail", "message": f"Parse hiba: {exc}"}
        if not sections:
            return {"block": name, "status": "fail", "message": "Üres blokk vagy parse-hiba"}

        error = None
        parsed = None
        for attempt in range(1, retries + 1):
            try:
                parsed = codex_cli.run_codex_json(
                    build_codex_prompt(instruction, sections),
                    CODEX_TRANSLATION_SCHEMA,
                    timeout=timeout, model=model, codex_bin=codex_bin)
                break
            except codex_cli.CodexRunError as exc:
                error = exc
                if attempt < retries:
                    print(f"  Codex hiba, újrapróbálás ({attempt}/{retries})...")
        if parsed is None:
            safe_remove(output_path)
            return {"block": name, "status": "fail", "message": str(error)}

        translations = {}
        for item in parsed.get("translations", []):
            if (isinstance(item, dict) and isinstance(item.get("sorszam"), int)
                    and isinstance(item.get("text"), str)):
                translations[item["sorszam"]] = item["text"]
        missing = expected - set(translations)
        if missing:
            safe_remove(output_path)
            return {"block": name, "status": "fail",
                    "message": f"Hiányzó fordítások: {sorted(missing)[:5]}"}

        write_srt(output_path, [{**section, "text": translations[int(section["num"])]}
                                for section in sections])
        if count_sections(output_path) != len(sections):
            safe_remove(output_path)
            return {"block": name, "status": "warning",
                    "message": "Szekciószám eltérés — output törölve"}
        stub = placeholder_warning(output_path, block_path)
        if stub:
            detail = placeholder_detail(output_path, block_path)
            safe_remove(output_path)
            return {"block": name, "status": "warning", "message": stub,
                    "detail": detail}
        return {"block": name, "status": "ok", "message": f"{len(sections)} szekció"}
    return translate_block


def _make_claude_translator(claude_bin, sys_prompt_path, model, timeout, max_turns):
    def translate_block(block_path: str) -> dict:
        output_path = hun_path(block_path)
        block_name = os.path.basename(block_path)
        result = {"block": block_name, "status": "unknown", "message": ""}

        print(f"[START] {block_name}")

        prompt = (
            f"Input fájl:  {os.path.abspath(block_path)}\n"
            f"Output fájl: {os.path.abspath(output_path)}\n"
            f"Fordítsd le a system promptban megadott szabályok szerint."
        )
        cmd = [
            claude_bin, "-p", prompt,
            "--append-system-prompt-file", sys_prompt_path,
            "--allowedTools", "Read,Write",
            "--model", model,
            "--max-turns", str(max_turns),
        ]

        stdout = stderr = ""
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8"
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                claude_cli.kill_process_tree(proc)
                result["status"] = "fail"
                result["message"] = f"Timeout ({timeout // 60} perc)"
                safe_remove(output_path)
                return result
            if proc.returncode != 0:
                result["status"] = "fail"
                combined = ((stderr or "") + "\n" + (stdout or "")).strip().splitlines()
                tail = [l for l in combined if l.strip()][-3:]
                result["message"] = f"Claude Code hiba (exit {proc.returncode}): {' | '.join(tail)}"
                result["detail"] = ((stderr or "") + "\n" + (stdout or "")).strip()
                safe_remove(output_path)
                return result
        except FileNotFoundError:
            result["status"] = "fail"
            result["message"] = "A 'claude' parancs nem található! Telepítve van a Claude Code?"
            return result
        except Exception as e:
            result["status"] = "fail"
            result["message"] = str(e)
            safe_remove(output_path)
            return result

        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            in_count = count_sections(block_path)
            out_count = count_sections(output_path)
            # Ismert agent-hiba: a Read tool `sorszám<TAB>tartalom` megjelenítési
            # formája átszivárog a kiírt fájlba, így egyetlen szekciófej sem
            # ismerhető fel (out_count == 0), pedig a fordítás maga jó. A prefix
            # eltávolítható; az alábbi szigorú sorszám/időbélyeg-ellenőrzés
            # dönti el, hogy a helyreállított fájl valóban ép-e.
            if out_count == 0:
                repaired = claude_cli.strip_read_line_numbers(read_text(output_path))
                if repaired is not None and count_sections_text(repaired) == in_count:
                    with open(output_path, "w", encoding="utf-8") as f:
                        f.write(repaired)
                    out_count = in_count
                    result["repaired"] = True
            # A count_sections strukturális (szám + időbélyeg-sor pár), ezért nem
            # veszi észre, ha az agent SAJÁT számozást szúr be az igazi elé (az
            # eredeti sorszám a 2. sorba csúszik, és a scanner azt találja meg).
            # Ezért blokk-parse szinten is összevetjük a sorszámokat és
            # időbélyegeket az inputtal — a gemini/codex ágon ezt a felépítés
            # garantálja, a claude-ágon ellenőrizni kell.
            if in_count == out_count:
                try:
                    in_secs = parse_sections(block_path)
                    out_secs = parse_sections(output_path)
                    structure_ok = (
                        [x["num"] for x in in_secs] == [x["num"] for x in out_secs]
                        and [x["timestamp"] for x in in_secs] == [x["timestamp"] for x in out_secs]
                    )
                except Exception:
                    structure_ok = False
                if not structure_ok:
                    result["status"] = "warning"
                    result["message"] = ("Sorszám/időbélyeg-eltérés az inputhoz képest "
                                         "(pl. újraszámozott output) — output törölve, "
                                         "újrafutáskor újrafordítjuk")
                    safe_remove(output_path)
                    return result
                stub = placeholder_warning(output_path, block_path)
                if stub:
                    result["status"] = "warning"
                    result["message"] = stub
                    result["detail"] = (placeholder_detail(output_path, block_path)
                                        + "\n--- agent válasza ---\n" + (stdout or ""))
                    safe_remove(output_path)
                    return result
                result["status"] = "ok"
                result["message"] = f"{out_count} szekció"
                if result.get("repaired"):
                    result["message"] += " (Read-sorszámprefix eltávolítva)"
            else:
                # A hibás outputot töröljük, különben a resume késznek látná,
                # és a szekció-eltérés csendben végleges állapottá válna.
                result["status"] = "warning"
                result["message"] = (f"Szekciószám eltérés! Input: {in_count}, "
                                     f"Output: {out_count} — output törölve, "
                                     f"újrafutáskor újrafordítjuk")
                safe_remove(output_path)
        else:
            # Az agent 0-s exit kóddal is kiléphet anélkül, hogy fájlt írna
            # (pl. ha megtagadja a feladatot). A stdout ilyenkor az EGYETLEN
            # nyom az okról — enélkül a "hiányzó output" félrevezető.
            result["status"] = "fail"
            reply = [l for l in (stdout or "").strip().splitlines() if l.strip()]
            if reply:
                tail = " | ".join(reply[-3:])
                if len(tail) > 500:
                    tail = tail[:500] + "..."
                result["message"] = f"Üres vagy hiányzó output — az agent válasza: {tail}"
                result["detail"] = stdout or ""
            else:
                result["message"] = "Üres vagy hiányzó output (az agent nem válaszolt)"
            safe_remove(output_path)

        return result
    return translate_block


# ────────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    # Windows cp125x konzolon a ✓/⚠/ő és a box-karakterek elszállnának
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Párhuzamos SRT blokk-fordítás (Gemini API / Claude Code / Codex CLI)")
    parser.add_argument("blocks_dir", help="Blokkok mappája (a split kimenete)")
    parser.add_argument("--provider", choices=PROVIDERS,
                        default=config.default_provider(builtin="claude"),
                        help="Fordító provider (default: claude, "
                             "felülírható: SUBTR_DEFAULT_PROVIDER env)")
    parser.add_argument("--agents", type=int, default=None,
                        help="Párhuzamos futások száma (default: gemini/claude 3, codex 1)")
    parser.add_argument("--block", type=str, default=None,
                        help="Csak egy konkrét blokk fordítása (pl. 003 vagy 3 — auto zero-pad)")
    config.add_source_lang_argument(parser)
    parser.add_argument("--model", type=str, default=None,
                        help="Modell-azonosító. Feloldás: --model > "
                             "SUBTR_<PROVIDER>_MODEL_TRANSLATE > SUBTR_<PROVIDER>_MODEL > "
                             "beégetett (gemini: gemini-3.6-flash, claude: sonnet)")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Timeout blokkonként mp-ben (default: 900; a gemini-ágon "
                             "nem használt — ott a retry-logika véd)")
    parser.add_argument("--max-retries", type=int, default=None,
                        help="Újrapróbálkozások (default: gemini 4, codex 2; a claude-ágon "
                             "nem használt)")
    parser.add_argument("--max-turns", type=int, default=20,
                        help="Maximum agent fordulók blokkonként (csak claude; default: 20)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Ne takarítsa ki a régi sys prompt fájlokat startup-kor (csak claude)")
    args = parser.parse_args(argv)

    provider = args.provider
    builtin = MODEL_BUILTIN[provider]

    # Provider-függő defaultok feloldása
    if args.agents is None:
        args.agents = 1 if provider == "codex" else 3
    if args.timeout is None:
        args.timeout = 900
    if args.max_retries is None:
        args.max_retries = {"gemini": MAX_RETRIES, "codex": 2}.get(provider, 1)

    if args.agents < 1:
        print(f"HIBA: --agents legalább 1 legyen (kaptam: {args.agents})")
        sys.exit(1)
    if args.max_retries < 1:
        print(f"HIBA: --max-retries legalább 1 legyen (kaptam: {args.max_retries})")
        sys.exit(1)
    if provider == "claude" and args.model and args.model not in ("haiku", "sonnet", "opus"):
        print(f"HIBA: a claude providernél a --model haiku|sonnet|opus lehet (kaptam: {args.model})")
        sys.exit(1)
    src_lang = config.resolve_source_lang(args.source_lang, args.blocks_dir)

    if not os.path.isdir(args.blocks_dir):
        print(f"HIBA: Nem találom a mappát: {args.blocks_dir}")
        sys.exit(1)

    model = config.resolve_model(args.model, provider, "translate", builtin=builtin)

    # Provider-előfeltételek
    claude_bin = codex_bin = client = None
    if provider == "gemini":
        if not gemini_provider.DEPS_OK:
            print(f"HIBA: Hiányzó Python függőség: {gemini_provider.DEPS_ERROR}")
            print(f"      Telepítés: pip install google-genai python-dotenv pydantic")
            sys.exit(1)
        # Soft warning magas --agents érték esetén — a Gemini API rate limit
        # (RPM) miatt a 10+ párhuzamos hívás már 429-eket generálhat.
        if args.agents > 10:
            print(f"FIGYELEM: --agents = {args.agents} > 10. A Gemini API rate limitek")
            print(f"  függvényében magas párhuzamosság esetén 429 (rate limit) hibák várhatók,")
            print(f"  amiket a retry logika kezel, de pazarolnak API-időt.")
            print(f"  Free tier: ~10-30 RPM modelltől függően. Részletek:")
            print(f"  https://ai.google.dev/gemini-api/docs/rate-limits")
            print()
        try:
            client = gemini_provider.make_client()
        except RuntimeError as e:
            print(f"HIBA: {e}")
            sys.exit(1)
        # Pre-flight: létezik-e a modell (csak a 404 jelent rossz nevet)
        try:
            client.models.get(model=model)
        except gemini_provider.genai_errors.APIError as e:
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            if status == 404:
                print(f"HIBA: Nem létező Gemini modell: '{model}'")
                print(f"      A használható modellek listája:")
                print(f"      https://ai.google.dev/gemini-api/docs/models")
            else:
                print(f"HIBA: Gemini API hiba a modell-ellenőrzésnél ({status}): {e}")
                print(f"      (Kvóta / átmeneti hiba lehet — próbáld később.)")
            sys.exit(1)
    elif provider == "claude":
        claude_bin = claude_cli.which_claude()
        if not claude_bin:
            print("HIBA: A 'claude' parancs nem található a PATH-on!")
            print("      Telepítés: npm install -g @anthropic-ai/claude-code")
            sys.exit(1)
        if not args.no_cleanup:
            cleanup_stale_sys_prompts()
    else:
        codex_bin = codex_cli.find_codex()
        if not codex_bin:
            print("HIBA: A 'codex' parancs nem található a PATH-on.")
            sys.exit(1)

    # Blokk-felfedezés + --block kezelés (auto zero-pad: 3 → 003)
    all_blocks = get_all_blocks(args.blocks_dir)
    total = len(all_blocks)
    if args.block:
        block_id = args.block.zfill(3) if args.block.isdigit() else args.block
        pending = [b for b in all_blocks if f"_block_{block_id}_" in b]
        if not pending:
            print(f"HIBA: Nem találom a {args.block} (={block_id}) számú blokkot!")
            sys.exit(1)
        for b in pending:
            hun = hun_path(b)
            if os.path.isfile(hun):
                safe_remove(hun)
                print(f"Korábbi fordítás törölve: {os.path.basename(hun)}")
    else:
        pending = get_pending_blocks(args.blocks_dir)

    # Tényleges lemez-állapot — figyelembe veszi az imént törölt --block HUN fájlt
    done = total - len(get_pending_blocks(args.blocks_dir))

    # Kontextus + provider-specifikus prompt/executor
    claude_md = load_translation_context()
    glossary = as_prompt_text()

    extra_status = []
    if provider == "gemini":
        instruction = build_system_instruction(claude_md, glossary, src_lang)
        extra_status.append(("Max retry", args.max_retries))
        extra_status.append(("System instr",
                             f"{len(instruction)} char (CLAUDE.md: {len(claude_md)}, "
                             f"glossary: {len(glossary)})"))
    elif provider == "claude":
        sys_prompt_content = build_claude_system_prompt(claude_md, glossary, src_lang)
        sys_prompt_path, newly_created = write_claude_sys_prompt_file(sys_prompt_content)
        extra_status.append(("Max turns", args.max_turns))
        extra_status.append(("Timeout", f"{args.timeout // 60} perc / blokk"))
        extra_status.append(("System prompt",
                             f"{os.path.getsize(sys_prompt_path)} byte "
                             f"({'új fájl' if newly_created else 'meglévő — másik process is használhatja'})"))
        extra_status.append(("   fájl", os.path.basename(sys_prompt_path)))
    else:
        instruction = build_codex_instruction(claude_md, glossary, src_lang)
        extra_status.append(("Timeout", f"{args.timeout // 60} perc / blokk"))
        extra_status.append(("Max retry", args.max_retries))

    print("=" * 50)
    print(f"  Fordítási állapot ({provider.capitalize()})")
    print("=" * 50)
    print(f"  Összes blokk:   {total}")
    print(f"  Kész:           {done}")
    print(f"  Fordítandó:     {len(pending)}")
    print(f"  Agent-ek:       {args.agents}")
    print(f"  Modell:         {model or 'provider-alapértelmezés'}")
    print(f"  Forrásnyelv:    {config.source_lang_name(src_lang)} ({src_lang})"
          f"  [{config.source_lang_origin(args.source_lang, args.blocks_dir)}]")
    for label, value in extra_status:
        print(f"  {label}:{' ' * max(1, 15 - len(label))}{value}")
    if not claude_md:
        print("  FIGYELEM: TRANSLATION.md nem található a munkakönyvtárban —")
        print("     sorozat-kontextus NÉLKÜL fordítok! (rossz mappából futtatod?)")
    if not glossary:
        print("  FIGYELEM: glossary.json üres vagy hiányzik — szójegyzék nélkül fordítok")
    print("=" * 50)

    if not pending:
        print("\nMinden blokk le van fordítva!")
        return

    if provider == "gemini":
        # Kvóta-előrejelzés: blokkonként legalább 1 kérés megy el (retry esetén
        # több), ezért a pending blokkszám az alsó becslés a napi fogyásra.
        gemini_provider.preflight(model, needed=len(pending))

    print(f"\nFordítandó blokkok:")
    for p in pending:
        print(f"  - {os.path.basename(p)}")
    print()

    rotate_log()
    log(f"=== RUN START — provider={provider} model={model or 'default'} "
        f"src_lang={src_lang} "
        f"agents={args.agents} blocks_dir={os.path.abspath(args.blocks_dir)} "
        f"pending={len(pending)}/{total}")

    if provider == "gemini":
        translator = _make_gemini_translator(client, model, instruction,
                                             args.max_retries, src_lang)
    elif provider == "claude":
        translator = _make_claude_translator(claude_bin, sys_prompt_path, model,
                                             args.timeout, args.max_turns)
    else:
        translator = _make_codex_translator(codex_bin, model, instruction,
                                            args.timeout, args.max_retries)

    results = []
    with ThreadPoolExecutor(max_workers=args.agents) as executor:
        futures = {executor.submit(translator, block): block for block in pending}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                result = {"block": os.path.basename(futures[future]),
                          "status": "fail", "message": f"Thread hiba: {e}"}
            results.append(result)
            status_icon = {"ok": "✓", "warning": "⚠", "fail": "✗"}.get(result["status"], "?")
            print(f"  [{status_icon}] {result['block']} — {result['message']}")
            log(f"[{result['status'].upper()}] {result['block']} — {result['message']}",
                detail=result.get("detail", ""))

    ok_count = sum(1 for r in results if r["status"] == "ok")
    warn_count = sum(1 for r in results if r["status"] == "warning")
    fail_count = sum(1 for r in results if r["status"] == "fail")

    print()
    print("=" * 50)
    print("  Végeredmény")
    print("=" * 50)
    print(f"  Sikeres:    {ok_count}")
    if warn_count:
        print(f"  Figyelem:   {warn_count} (szekció-eltérés — output törölve)")
    if fail_count:
        print(f"  Sikertelen: {fail_count}")
    if warn_count or fail_count:
        print(f"\n  A sikertelen/eltérő blokkok újrafordításához futtasd újra ezt a scriptet.")
        print(f"  Részletes indoklás (agent-válasz is): {TRANSLATE_LOG}")
    print("=" * 50)

    log(f"=== RUN END — ok={ok_count} warning={warn_count} fail={fail_count}")

    # A codex-út kontraktusa: hibás blokk esetén nem-nulla exit kód
    if provider == "codex" and (warn_count or fail_count):
        sys.exit(1)
