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
    python translate_with_gemini.py blocks/Sorozat_S01E01_eng --model gemini-3.5-flash-lite

Modell:
    Alapértelmezett: gemini-3.6-flash (erős és stabilan elérhető)
    --model <név>: tetszőleges Gemini modell-azonosító
        Flash:      gemini-3.6-flash, gemini-3.5-flash
        Legújabb:   gemini-3.7-flash — gyakran túlterhelt (503), ezért nem default
        Olcsó/lite: gemini-3.5-flash-lite, gemini-3.1-flash-lite
        Pro:        gemini-3.1-pro-preview
        Alias:      gemini-flash-latest, gemini-flash-lite-latest, gemini-pro-latest
        Modell-lista: https://ai.google.dev/gemini-api/docs/models

    Free tier: a nem-lite modellek napi kérésszáma szűkös (tapasztalat szerint
    ~20/nap modellenként), a -lite modellek jóval bőkezűbbek. Ha elfogy a napi
    kvóta, válts lite modellre: --model gemini-3.5-flash-lite

Párhuzamosság:
    Default: --agents 3. A Gemini API a párhuzamos hívást nem tiltja, csak
    RPM (requests/min) korlátok vonatkoznak rá. Free tier-en ~10-30 RPM
    modelltől függően (a -lite modellek bőkezűbbek). Magas --agents érték (>10)
    esetén várhatóan rate limit (429) hibák; ezeket a script automatikusan
    újrapróbálja exponential backoff-fal, de pazarolja az API-időt.
    Hivatalos rate limit doksi:
        https://ai.google.dev/gemini-api/docs/rate-limits
    Saját tier-szintű limiteket az AI Studio-ban lehet megnézni:
        https://aistudio.google.com/rate-limit

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

from subtr.context import load_translation_context as load_claude_md
from subtr.glossary import as_prompt_text as load_glossary
from subtr.srt import count_sections, parse_sections, write_srt
from subtr.blocks import get_all_blocks, get_pending_blocks, safe_remove
from subtr.providers import gemini as gemini_provider

# Kvótakövetés — gépszintű, API kulcs szerint (a Gemini API nem adja vissza
# a maradék napi kérésszámot). Ha a modul hiányzik, a script fut tovább.
try:
    import gemini_quota as _gq
except Exception:
    _gq = None

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

MODEL_DEFAULT = "gemini-3.6-flash"
TEMPERATURE = 0.3
MAX_RETRIES = 4  # (a backoff maga a subtr.providers.gemini adapterben)


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

# ────────────────────────────────────────────────────────────────────────────
# Blokk-felfedezés / checkpoint
# ────────────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────────────
# Kontextus betöltés (CLAUDE.md + glossary)
# ────────────────────────────────────────────────────────────────────────────


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
- Tegezés/magázás: kövesd a sorozatkontextus Megszólítási regiszterét; ha nincs
  rá adat és a forrás jeleiből sem egyértelmű, fogalmazz úgy, hogy ne kelljen
  választani. Ne találj ki viszonyt.
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
    """Egy Gemini API hívás — a retry/kvóta logika a közös adapterben."""
    return gemini_provider.call_json(client, model, prompt,
                                     schema=TranslationOutput,
                                     system=system_instruction,
                                     temperature=TEMPERATURE,
                                     max_retries=max_retries)


def translate_block(block_path: str, client, model: str,
                    system_instruction: str, max_retries: int) -> dict:
    output_path = block_path[:-len(".srt")] + "_HUN.srt"
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
        # A hibás outputot töröljük, különben a resume késznek látná
        result["status"] = "warning"
        result["message"] = (f"Szekciószám eltérés! Input: {in_count}, "
                             f"Output: {out_count} — output törölve, "
                             f"újrafutáskor újrafordítjuk")
        safe_remove(output_path)

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
                        help="Párhuzamos API hívások száma (default: 3). "
                             "Magas érték (>10) esetén 429 rate limit várható; "
                             "lásd: https://ai.google.dev/gemini-api/docs/rate-limits")
    parser.add_argument("--block", type=str, default=None,
                        help="Csak egy konkrét blokk újrafordítása (pl. 003 vagy 3 — auto zero-pad)")
    parser.add_argument("--model", type=str, default=MODEL_DEFAULT,
                        help=f"Gemini modell-azonosító (default: {MODEL_DEFAULT}). "
                             "Pl. gemini-3.7-flash (gyakran túlterhelt), gemini-3.5-flash-lite, "
                             "gemini-3.1-flash-lite, gemini-3.1-pro-preview")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                        help=f"Max API retry rate-limit / 5xx esetén (default: {MAX_RETRIES})")
    args = parser.parse_args()

    # Függőség-ellenőrzés (a --help-hez nem kellett)
    if not _DEPS_OK:
        print(f"HIBA: Hiányzó Python függőség: {_DEPS_ERROR}")
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

    # Pre-flight: ellenőrizzük, hogy a modell létezik-e.
    # Csak a 404 jelent rossz modellnevet — kvótahiba (429) vagy átmeneti
    # 5xx esetén félrevezető lenne "nem létező modell"-t mondani.
    try:
        client.models.get(model=model)
    except genai_errors.APIError as e:
        status = getattr(e, "code", None) or getattr(e, "status_code", None)
        if status == 404:
            print(f"HIBA: Nem létező Gemini modell: '{model}'")
            print(f"      A használható modellek listája:")
            print(f"      https://ai.google.dev/gemini-api/docs/models")
        else:
            print(f"HIBA: Gemini API hiba a modell-ellenőrzésnél ({status}): {e}")
            print(f"      (Kvóta / átmeneti hiba lehet — próbáld később.)")
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
            hun = b[:-len(".srt")] + "_HUN.srt"
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

    # Kvóta-előrejelzés: blokkonként legalább 1 kérés megy el (retry esetén több),
    # ezért a pending blokkszám az alsó becslés a napi fogyásra.
    if _gq:
        _gq.preflight(model, needed=len(pending))

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
