#!/usr/bin/env python3
"""
Fordítás ellenőrző script — Gemini API alapú review.
Az ÖSSZEFŰZÖTT hun.srt fájlt darabokra szedi, és minden darabot
Gemini-vel átnézet, kifejezetten tükörfordítások és ragozási hibák
szempontjából. A talált hibákat egy riportba írja.

Használat:
    python review_with_gemini.py "output/Sorozat - S01E01.hun.srt"
    python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --chunk-size 100
    python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --pro
    python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --model gemini-3.1-flash

    Csak egy konkrét chunk(tartomány) lefuttatása (pl. kvótahiba utáni pótlás):
        python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --start-chunk 9 --suffix _part2
        python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2

Modellek:
    Alapértelmezett: gemini-2.5-flash (gyors, olcsó, stabil GA)
    --pro flag-gel: gemini-2.5-pro (alaposabb, drágább)
    --model <név>: tetszőleges Gemini modell-azonosító (felülírja a --pro flag-et)
        Példák (stabil): gemini-3.1-flash, gemini-3.1-flash-lite,
                          gemini-2.5-flash-lite
        Példák (preview): gemini-3.1-pro-preview
        Modell-lista: https://ai.google.dev/gemini-api/docs/models

Tartomány-paraméterek:
    --start-chunk N    Csak ettől a chunktól kezdje (1-alapú). Default: 1
    --end-chunk N      Eddig a chunkig bezárólag (1-alapú). Default: utolsó
    --suffix _xxx      Riport fájlnév-utótag, hogy ne írja felül a meglévő
                       riportot. Pl. --suffix _part2 →
                       Sorozat - S01E01.hun_REVIEW_GEMINI_part2.txt

API kulcs:
    A .env fájlba tedd: GEMINI_API_KEY=...

Függőségek:
    pip install google-genai python-dotenv pydantic

Kimenet:
    output/Sorozat - S01E01.hun_REVIEW_GEMINI.txt
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from glossary_categories import CATEGORIES

# Külső függőségek — lazy try/except, hogy a --help akkor is fusson, ha még
# nincsenek telepítve. A main() ellenőrzi a _DEPS_OK flag-et a tényleges
# munka előtt; ha hiányzik függőség, friendly üzenettel kilép.
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
    # Stub BaseModel — a class definíciók (ErrorItem, ErrorReport) így import
    # időben nem hasalnak el. Az osztályokat csak a main()-ből hívjuk meg
    # tényleges használatra, ami ellenőrzi a _DEPS_OK-ot.
    class BaseModel:  # type: ignore[no-redef]
        pass


DEFAULT_CHUNK_SIZE = 100
MODEL_FLASH = "gemini-2.5-flash"
MODEL_PRO = "gemini-2.5-pro"
TEMPERATURE = 0.2
MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # másodperc


class ErrorItem(BaseModel):
    sorszam: int
    eredeti: str
    hiba: str
    javaslat: str


class ErrorReport(BaseModel):
    errors: List[ErrorItem]


def parse_srt(filepath):
    """SRT blokkok beolvasása teljes szöveggel együtt."""
    content = Path(filepath).read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            entries.append(block.strip())
    return entries


def chunk_entries(entries, chunk_size):
    """Entries felosztása chunkokra."""
    for i in range(0, len(entries), chunk_size):
        yield entries[i:i + chunk_size]


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
Magyar fordítás lektor vagy. Angolból magyarra fordított SRT feliratokat
nézel át, és STÍLUS / NYELVTANI hibákat keresel.

=== AMIT KERESEL ===
1. Tükörfordítások (pl. "framed me" → "kereteztek be" helyett "tőrbe csaltak")
2. Helytelen igeragozás (pl. ikes igék, "tetszesz" helyett "tetszel")
3. Nemhez kötött kifejezések hibái (pl. "férjhez megy" férfiról; alapból
   semleges forma kell, csak ha BIZTOSAN ismert a beszélő/alany neme)
4. Természetellenes, angolos magyar nyelvezet
5. Rossz szórend, helytelen határozott/határozatlan ragozás

=== AMIT NE JELENTS ===
- Helyesírás apróságok (azokat a helyesírás-ellenőrző elkapja)
- Stilisztikai ízlésváltozatok, ha az adott fordítás is helyes
- HTML tagek, időbélyegek, sorszámok
- A szójegyzékben (lent) szereplő fordításokat NE javasold átírni —
  ezek a sorozat kötelező, jóváhagyott fordításai
- Karakterneveket NE javasold lefordítani (a szójegyzékben szerepelnek)

=== KIMENET ===
JSON séma szerint, minden hibához:
- sorszam: a felirat szekció sorszáma (egész szám)
- eredeti: az eredeti magyar szöveg (ahogy az SRT-ben van)
- hiba: rövid leírás a problémáról
- javaslat: javított magyar változat

Ha nincs hiba, üres errors tömböt adj vissza."""]

    if claude_md.strip():
        parts.append("=== SOROZAT KONTEXTUS (CLAUDE.md) ===\n" + claude_md.strip())

    if glossary.strip():
        parts.append(
            "=== SZÓJEGYZÉK — EZEK A FORDÍTÁSOK HELYESEK, NE JAVASOLJ MÁST! ===\n"
            + glossary.strip()
        )

    return "\n\n".join(parts)


def build_prompt(chunk_text, chunk_num, total_chunks):
    """Per-chunk prompt — minimális, a szabályok a system instruction-ben."""
    return f"""SRT BLOKK ({chunk_num}/{total_chunks}):
{chunk_text}
"""


def review_chunk_gemini(client, model, chunk_text, chunk_num, total_chunks,
                        system_instruction):
    """Egy chunk átnézetése Gemini API-val. Strukturált JSON kimenet."""
    prompt = build_prompt(chunk_text, chunk_num, total_chunks)

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=TEMPERATURE,
        response_mime_type="application/json",
        response_schema=ErrorReport,
    )

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )

            parsed: ErrorReport = response.parsed
            if parsed is None:
                # Safety filter vagy üres válasz
                return None, "[Üres / blokkolt válasz a Gemini-től]"
            return parsed, None

        except genai_errors.APIError as e:
            last_err = e
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            if status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"  API hiba ({status}), újrapróbálás {delay}s múlva... ({attempt}/{MAX_RETRIES})")
                time.sleep(delay)
                continue
            return None, f"[API hiba: {e}]"
        except Exception as e:
            last_err = e
            return None, f"[Váratlan hiba: {e}]"

    return None, f"[{MAX_RETRIES} próbálkozás után sem sikerült: {last_err}]"


def format_findings(parsed: ErrorReport, chunk_num, total):
    """A JSON-ból szöveges riport-blokk."""
    if not parsed.errors:
        return None

    lines = [f"--- Chunk {chunk_num}/{total} ---"]
    for err in parsed.errors:
        lines.append(f'#{err.sorszam}: "{err.eredeti}"')
        lines.append(f"  → HIBA: {err.hiba}")
        lines.append(f"  → JAVASLAT: {err.javaslat}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Magyar fordítás review Gemini-vel")
    parser.add_argument("srt_file", help="Az összefűzött hun.srt fájl")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Feliratok chunkonként (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--pro", action="store_true",
                        help="Gemini 2.5 Pro használata Flash helyett (drágább, alaposabb)")
    parser.add_argument("--model", type=str, default=None,
                        help="Tetszőleges Gemini modell-azonosító (felülírja a --pro flag-et). "
                             "Pl. gemini-3.1-flash, gemini-3.1-flash-lite, gemini-3.1-pro-preview")
    parser.add_argument("--start-chunk", type=int, default=1,
                        help="Csak ettől a chunktól kezdje (1-alapú). Default: 1")
    parser.add_argument("--end-chunk", type=int, default=None,
                        help="Eddig a chunkig (bezárólag, 1-alapú). Default: utolsó")
    parser.add_argument("--suffix", type=str, default="",
                        help="Riport fájl utótag, pl. '_part2' → _REVIEW_GEMINI_part2.txt")
    args = parser.parse_args()

    # Függőség-ellenőrzés (a --help-hez nem kellettek az import-ok)
    if not _DEPS_OK:
        print(f"HIBA: Hiányzó Python függőség: {_DEPS_ERROR}")
        print(f"      Telepítés: pip install google-genai python-dotenv pydantic")
        sys.exit(1)

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("HIBA: GEMINI_API_KEY nincs beállítva. Tedd a .env fájlba vagy a környezeti változók közé.")
        sys.exit(1)

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"HIBA: Fájl nem található: {srt_path}")
        sys.exit(1)

    if args.model:
        model = args.model
    elif args.pro:
        model = MODEL_PRO
    else:
        model = MODEL_FLASH
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

    entries = parse_srt(srt_path)
    print(f"Beolvasva: {len(entries)} felirat szekció")

    chunks = list(chunk_entries(entries, args.chunk_size))
    total_chunks = len(chunks)
    print(f"Chunkok: {total_chunks} db (chunkonként {args.chunk_size} felirat)")
    print(f"Modell: {model}")

    # Kontextus betöltése
    claude_md = load_claude_md()
    glossary = load_glossary()
    system_instruction = build_system_instruction(claude_md, glossary)
    print(f"System instruction: {len(system_instruction)} char "
          f"(CLAUDE.md: {len(claude_md)} char, glossary: {len(glossary)} char)")

    start = max(1, args.start_chunk)
    end = args.end_chunk if args.end_chunk is not None else total_chunks
    end = min(end, total_chunks)
    if start > end:
        print(f"HIBA: --start-chunk ({start}) nagyobb mint --end-chunk ({end}).")
        sys.exit(1)
    if start > 1 or end < total_chunks:
        print(f"Tartomány: {start}–{end}")
    print()

    report_path = srt_path.with_name(srt_path.stem + f"_REVIEW_GEMINI{args.suffix}.txt")

    all_findings = []
    error_chunks = []

    for i in range(start, end + 1):
        chunk = chunks[i - 1]
        chunk_text = "\n\n".join(chunk)
        print(f"[{i}/{total_chunks}] Ellenőrzés folyamatban...")

        parsed, err_msg = review_chunk_gemini(client, model, chunk_text, i, len(chunks),
                                              system_instruction)

        if err_msg:
            error_chunks.append(f"--- Chunk {i}/{len(chunks)} ---\n{err_msg}\n")
            print(f"  {err_msg}")
            continue

        block = format_findings(parsed, i, len(chunks))
        if block:
            all_findings.append(block)

    # Riport mentése
    sections = []
    if all_findings:
        sections.append("\n".join(all_findings))
    if error_chunks:
        sections.append("=== HIBÁS / KIHAGYOTT CHUNKOK ===\n\n" + "\n".join(error_chunks))

    if sections:
        report_content = (
            f"Review riport (Gemini): {srt_path.name}\n"
            f"Modell: {model}\n"
            f"{'=' * 60}\n\n"
            + "\n\n".join(sections)
        )
        report_path.write_text(report_content, encoding="utf-8")
        print(f"\nRiport mentve: {report_path}")
        print(f"Találatok: {len(all_findings)} chunkban, hibás chunkok: {len(error_chunks)}")
    else:
        print("\nNincs hiba egyik chunkban sem!")


if __name__ == "__main__":
    main()
