#!/usr/bin/env python3
"""
translate_with_gemini.py — Párhuzamos SRT fordítás Gemini API-val.

A translate_parallel.py (Claude Code-os) alternatívája:
- Ugyanazon a blokk-szerkezeten dolgozik (split_srt.py output)
- Ugyanúgy checkpoint-ol (csak a hiányzó _HUN.srt-ket fordítja újra)
- Ugyanúgy validál (szekciószám match Python oldalon)
- De a Gemini API-t hívja közvetlenül, strukturált JSON kimenettel

A SRT struktúra (sorszám, időbélyeg) Python oldalon GARANTÁLT: a script
parse-olja az input blokkot, csak a szövegeket küldi Gemini-nek a sorszámukkal,
és a válaszból csak a fordításokat illeszti vissza az eredeti sorszám+időbélyeg
mellé. A modell nem tud a struktúrán rontani.

Használat:
    python translate_with_gemini.py blocks/Sorozat_S01E01_eng
    python translate_with_gemini.py blocks/Sorozat_S01E01_eng --agents 5
    python translate_with_gemini.py blocks/Sorozat_S01E01_eng --block 3
    python translate_with_gemini.py blocks/Sorozat_S01E01_eng --model gemini-3.1-flash

Modell:
    Alapértelmezett: gemini-3.1-flash-lite
    --model <név>: tetszőleges Gemini modell-azonosító
        Modell-lista: https://ai.google.dev/gemini-api/docs/models

API kulcs:
    A .env fájlba tedd: GEMINI_API_KEY=...

Függőségek:
    pip install google-genai python-dotenv pydantic
"""

import argparse
import glob
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from glossary_categories import CATEGORIES

# Külső függőségek — lazy try/except, hogy a --help akkor is fusson, ha
# nincsenek telepítve.
_DEPS_OK = True
_DEPS_ERROR = None
try:
    from dotenv import load_dotenv
    from pydantic import BaseModel
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors
except ImportError as _e:
    _DEPS_OK = False
    _DEPS_ERROR = str(_e)
    class BaseModel:  # type: ignore[no-redef]
        pass


# ────────────────────────────────────────────────────────────────────────────
# Konstansok
# ────────────────────────────────────────────────────────────────────────────

MODEL_DEFAULT = "gemini-3.1-flash-lite"
TEMPERATURE = 0.3
MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # másodperc — exponential backoff alapja


# ────────────────────────────────────────────────────────────────────────────
# Pydantic schemes — strukturált JSON kimenet
# ────────────────────────────────────────────────────────────────────────────

class TranslationItem(BaseModel):
    sorszam: int
    text: str


class TranslationOutput(BaseModel):
    translations: List[TranslationItem]


# ────────────────────────────────────────────────────────────────────────────
# SRT parsing / írás
# ────────────────────────────────────────────────────────────────────────────

def parse_sections(filepath: str) -> list[dict]:
    """SRT szekciók kinyerése: {num, timestamp, text}."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    sections = []
    raw_blocks = re.split(r'\n\s*\n', content.strip())
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split('\n')
        if len(lines) >= 3:
            sections.append({
                "num": lines[0].strip(),
                "timestamp": lines[1].strip(),
                "text": "\n".join(lines[2:])
            })
        elif len(lines) == 2:
            sections.append({"num": lines[0].strip(), "timestamp": lines[1].strip(), "text": ""})
    return sections


def write_srt(filepath: str, sections: list[dict]):
    """SRT írása — szekciók közt üres sor, fájl végén egy újsor."""
    with open(filepath, 'w', encoding='utf-8') as f:
        out = []
        for s in sections:
            out.append(f"{s['num']}\n{s['timestamp']}\n{s['text']}")
        f.write("\n\n".join(out) + "\n")


def count_sections(filepath: str) -> int:
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        return len([line for line in content.split('\n') if re.match(r'^\d+$', line.strip())])
    except Exception:
        return 0


# ────────────────────────────────────────────────────────────────────────────
# Blokk-felfedezés / checkpoint
# ────────────────────────────────────────────────────────────────────────────

def get_all_blocks(blocks_dir: str) -> list[str]:
    pattern = os.path.join(blocks_dir, "*_block_*.srt")
    all_files = sorted(glob.glob(pattern))
    return [f for f in all_files if not f.endswith("_HUN.srt")]


def get_pending_blocks(blocks_dir: str) -> list[str]:
    pending = []
    for f in get_all_blocks(blocks_dir):
        hun_file = f.replace(".srt", "_HUN.srt")
        if not os.path.isfile(hun_file):
            pending.append(f)
    return pending


def safe_remove(filepath: str):
    """Fájl biztonságos törlése — Windows-on kezeli a fájl-zárolást."""
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
    except PermissionError:
        time.sleep(2)
        try:
            if os.path.isfile(filepath):
                os.remove(filepath)
        except PermissionError:
            print(f"  [!] Nem sikerült törölni (zárolva): {os.path.basename(filepath)}")


# ────────────────────────────────────────────────────────────────────────────
# Kontextus betöltés (CLAUDE.md + glossary)
# ────────────────────────────────────────────────────────────────────────────

def load_claude_md() -> str:
    if os.path.isfile("CLAUDE.md"):
        with open("CLAUDE.md", 'r', encoding='utf-8') as f:
            return f.read()
    return ""


def load_glossary() -> str:
    if not os.path.isfile("glossary.json"):
        return ""
    with open("glossary.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    lines = []
    for category in CATEGORIES:
        for entry in data.get(category, []):
            en = entry.get("en", "")
            hu = entry.get("hu", "")
            ctx = entry.get("context", "")
            if en and hu:
                lines.append(f'  "{en}" = "{hu}"' + (f" ({ctx})" if ctx else ""))
    return "\n".join(lines) if lines else ""


def build_system_instruction(claude_md: str, glossary: str) -> str:
    parts = ["""=== SZEREP ===
Profi felirat-fordító vagy. Angol SRT feliratokat fordítasz természetes,
beszélt magyar nyelvre. NEM tükörfordítasz.

=== KEMÉNY SZABÁLYOK ===
- HTML tagek (<i>, </i>, <b>, </b>), kötőjeles párbeszéd (-), [szögletes
  zárójeles megjegyzések], ♫ daljelek MEGŐRZENDŐK a magyar szövegben.
- Karakterneveket NE fordítsd le (a szójegyzékben szerepelnek a helyes
  írásmódok).
- Az "episode" magyarul mindig "rész", NEM "epizód".
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


# ────────────────────────────────────────────────────────────────────────────
# Per-block fordítás Gemini-vel
# ────────────────────────────────────────────────────────────────────────────

def build_block_prompt(sections: list[dict]) -> str:
    """Az átadandó szekciók szövegei #N prefixszel listázva."""
    items = []
    for s in sections:
        items.append(f"#{s['num']}\n{s['text']}")
    return (
        "Fordítsd le az alábbi SRT szekciók szövegét angolról magyarra. "
        "Tartsd meg a sorszámokat (#N prefix), és minden szekcióra adj "
        "fordítást a system promptban leírt JSON séma szerint.\n\n"
        + "\n\n".join(items)
    )


def call_gemini(client, model: str, prompt: str, system_instruction: str,
                max_retries: int):
    """Egy Gemini API hívás retry-logikával.
    Visszaad: (parsed: TranslationOutput | None, err_msg | None)."""
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=TEMPERATURE,
        response_mime_type="application/json",
        response_schema=TranslationOutput,
    )

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            parsed: TranslationOutput = response.parsed
            if parsed is None:
                return None, "[Üres / blokkolt válasz a Gemini-től]"
            return parsed, None
        except genai_errors.APIError as e:
            last_err = e
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            if status in (429, 500, 502, 503, 504) and attempt < max_retries:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"  API hiba ({status}), újrapróbálás {delay}s múlva... ({attempt}/{max_retries})")
                time.sleep(delay)
                continue
            return None, f"[API hiba: {e}]"
        except Exception as e:
            return None, f"[Váratlan hiba: {e}]"
    return None, f"[{max_retries} próbálkozás után sem sikerült: {last_err}]"


def translate_block(block_path: str, client, model: str,
                    system_instruction: str, max_retries: int) -> dict:
    output_path = block_path.replace(".srt", "_HUN.srt")
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
    prompt = build_block_prompt(sections)

    parsed, err_msg = call_gemini(client, model, prompt, system_instruction, max_retries)
    if err_msg:
        result["status"] = "fail"
        result["message"] = err_msg
        safe_remove(output_path)
        return result

    # Lookup-tábla a fordításokhoz sorszám alapján
    translations = {item.sorszam: item.text for item in parsed.translations}

    # Hiányzó / extra sorszámok ellenőrzése
    expected_nums = {int(s["num"]) for s in sections}
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
        # Az extra sorszámokat ignoráljuk, de jelezzük
        print(f"  [!] {block_name}: {len(extra)} extra sorszám a válaszban, ignorálva")

    # Reassemble: eredeti sorszám + időbélyeg + fordított szöveg
    out_sections = []
    for s in sections:
        out_sections.append({
            "num": s["num"],
            "timestamp": s["timestamp"],
            "text": translations[int(s["num"])],
        })

    try:
        write_srt(output_path, out_sections)
    except Exception as e:
        result["status"] = "fail"
        result["message"] = f"Írás hiba: {e}"
        safe_remove(output_path)
        return result

    out_count = count_sections(output_path)
    if in_count == out_count:
        result["status"] = "ok"
        result["message"] = f"{out_count} szekció"
    else:
        result["status"] = "warning"
        result["message"] = f"Szekciószám eltérés! Input: {in_count}, Output: {out_count}"

    return result


# ────────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Párhuzamos SRT fordítás Gemini API-val (translate_parallel.py alternatívája)"
    )
    parser.add_argument("blocks_dir", help="Blokkok mappája (split_srt.py outputja)")
    parser.add_argument("--agents", type=int, default=3,
                        help="Párhuzamos API hívások száma (default: 3)")
    parser.add_argument("--block", type=str, default=None,
                        help="Csak egy konkrét blokk újrafordítása (pl. 003 vagy 3 — auto zero-pad)")
    parser.add_argument("--model", type=str, default=MODEL_DEFAULT,
                        help=f"Gemini modell-azonosító (default: {MODEL_DEFAULT}). "
                             "Pl. gemini-3.1-flash, gemini-2.5-flash, gemini-3.1-pro-preview")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                        help=f"Max API retry rate-limit / 5xx esetén (default: {MAX_RETRIES})")
    args = parser.parse_args()

    # Függőség-ellenőrzés (a --help-hez nem kellett)
    if not _DEPS_OK:
        print(f"HIBA: Hiányzó Python függőség: {_DEPS_ERROR}")
        print(f"      Telepítés: pip install google-genai python-dotenv pydantic")
        sys.exit(1)

    if not os.path.isdir(args.blocks_dir):
        print(f"HIBA: Nem találom a mappát: {args.blocks_dir}")
        sys.exit(1)

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("HIBA: GEMINI_API_KEY nincs beállítva. Tedd a .env fájlba.")
        sys.exit(1)

    model = args.model
    client = genai.Client(api_key=api_key)

    # Pre-flight: ellenőrizzük, hogy a modell létezik-e
    try:
        client.models.get(model=model)
    except genai_errors.APIError as e:
        print(f"HIBA: Nem létező Gemini modell: '{model}'")
        print(f"      A használható modellek listája:")
        print(f"      https://ai.google.dev/gemini-api/docs/models")
        print(f"      (Eredeti API hiba: {e})")
        sys.exit(1)

    # Blokk-felfedezés
    all_blocks = get_all_blocks(args.blocks_dir)
    total = len(all_blocks)

    if args.block:
        # Auto zero-pad: --block 3 → 003 (a fájlnév pattern _block_NNN_ formátumú).
        block_id = args.block.zfill(3) if args.block.isdigit() else args.block
        pending = [b for b in all_blocks if f"_block_{block_id}_" in b]
        if not pending:
            print(f"HIBA: Nem találom a {args.block} (={block_id}) számú blokkot!")
            sys.exit(1)
        for b in pending:
            hun = b.replace(".srt", "_HUN.srt")
            if os.path.isfile(hun):
                os.remove(hun)
                print(f"Korábbi fordítás törölve: {os.path.basename(hun)}")
    else:
        pending = get_pending_blocks(args.blocks_dir)

    done = total - len(get_pending_blocks(args.blocks_dir))

    # Kontextus betöltése
    claude_md = load_claude_md()
    glossary = load_glossary()
    system_instruction = build_system_instruction(claude_md, glossary)

    print("=" * 50)
    print("  Fordítási állapot (Gemini)")
    print("=" * 50)
    print(f"  Összes blokk:   {total}")
    print(f"  Kész:           {done}")
    print(f"  Fordítandó:     {len(pending)}")
    print(f"  Agent-ek:       {args.agents}")
    print(f"  Modell:         {model}")
    print(f"  Max retry:      {args.max_retries}")
    print(f"  System instr:   {len(system_instruction)} char "
          f"(CLAUDE.md: {len(claude_md)}, glossary: {len(glossary)})")
    print("=" * 50)

    if not pending:
        print("\nMinden blokk le van fordítva!")
        return

    print(f"\nFordítandó blokkok:")
    for p in pending:
        print(f"  - {os.path.basename(p)}")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=args.agents) as executor:
        futures = {
            executor.submit(translate_block, block, client, model,
                            system_instruction, args.max_retries): block
            for block in pending
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                block_path = futures[future]
                result = {
                    "block": os.path.basename(block_path),
                    "status": "fail",
                    "message": f"Thread hiba: {e}",
                }
            results.append(result)
            status_icon = {"ok": "✓", "warning": "⚠", "fail": "✗"}.get(result["status"], "?")
            print(f"  [{status_icon}] {result['block']} — {result['message']}")

    ok_count = sum(1 for r in results if r["status"] == "ok")
    warn_count = sum(1 for r in results if r["status"] == "warning")
    fail_count = sum(1 for r in results if r["status"] == "fail")

    print()
    print("=" * 50)
    print("  Végeredmény")
    print("=" * 50)
    print(f"  Sikeres:    {ok_count}")
    if warn_count:
        print(f"  Figyelem:   {warn_count}")
    if fail_count:
        print(f"  Sikertelen: {fail_count}")
        print(f"\n  A sikertelen blokkok újrafordításához futtasd újra ezt a scriptet.")
    print("=" * 50)


if __name__ == "__main__":
    main()
