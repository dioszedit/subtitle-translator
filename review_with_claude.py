#!/usr/bin/env python3
"""
Fordítás ellenőrző script — Claude Code alapú review.
Az ÖSSZEFŰZÖTT hun.srt fájlt darabokra szedi, és minden darabot
Claude Code-dal átnézet, kifejezetten tükörfordítások és ragozási hibák
szempontjából. A talált hibákat egy riportba írja.

Használat:
    python review_with_claude.py "output/Sorozat - S01E01.hun.srt"
    python review_with_claude.py "output/Sorozat - S01E01.hun.srt" --chunk-size 100
    python review_with_claude.py "output/Sorozat - S01E01.hun.srt" --model haiku
    python review_with_claude.py "output/Sorozat - S01E01.hun.srt" --model opus

    Csak egy konkrét chunk(tartomány) lefuttatása (pl. megszakítás utáni pótlás):
        python review_with_claude.py "output/...hun.srt" --start-chunk 9 --suffix _part2
        python review_with_claude.py "output/...hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2

Modell:
    Alapértelmezett: sonnet
    --model haiku  : olcsóbb, gyorsabb
    --model opus   : alaposabb, drágább

Tartomány-paraméterek:
    --start-chunk N    Csak ettől a chunktól kezdje (1-alapú). Default: 1
    --end-chunk N      Eddig a chunkig (bezárólag, 1-alapú). Default: utolsó
    --suffix _xxx      Riport fájlnév-utótag, hogy ne írja felül a meglévő
                       riportot. Pl. --suffix _part2 →
                       Sorozat - S01E01.hun_REVIEW_CLAUDE_part2.txt

Kimenet:
    output/Sorozat - S01E01.hun_REVIEW_CLAUDE.txt
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from glossary_categories import CATEGORIES

DEFAULT_CHUNK_SIZE = 100  # Ennyi felirat kerül egy chunkba
TIMEOUT_PER_CHUNK = 600   # 10 perc chunkonként
SYS_PROMPT_PREFIX = ".review_claude_sys_prompt_"  # hash kerül utána


def parse_srt(filepath):
    """SRT blokkok beolvasása teljes szöveggel együtt (sorszám, időbélyeg, szöveg)."""
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


def build_review_system_prompt(claude_md: str, glossary: str) -> str:
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
- Karakterneveket NE javasold lefordítani (a szójegyzékben szerepelnek)"""]

    if claude_md.strip():
        parts.append("=== SOROZAT KONTEXTUS (CLAUDE.md) ===\n" + claude_md.strip())

    if glossary.strip():
        parts.append(
            "=== SZÓJEGYZÉK — EZEK A FORDÍTÁSOK HELYESEK, NE JAVASOLJ MÁST! ===\n"
            + glossary.strip()
        )

    return "\n\n".join(parts)


def write_sys_prompt_file(content: str) -> str:
    """Sys prompt mentése tartalom-hash alapú névvel — két párhuzamos futás
    azonos tartalommal ugyanazt a fájlt használja, eltérővel külön fájlt
    (mint a translate_parallel.py)."""
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    path = os.path.abspath(f"{SYS_PROMPT_PREFIX}{h}.txt")
    if os.path.isfile(path):
        return path
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def review_chunk(chunk_text, chunk_num, total_chunks, sys_prompt_path,
                 model="sonnet", timeout=TIMEOUT_PER_CHUNK):
    """Egy chunk átnézetése Claude Code-dal."""
    prompt = f"""Lektoráld az alábbi SRT felirat blokkot a system promptban
megadott szabályok szerint. Listázd a hibákat ebben a formátumban:

#SORSZÁM: "eredeti magyar szöveg"
  → HIBA: rövid leírás
  → JAVASLAT: javított változat

Ha nincs hiba ebben a chunkban, csak írd: "NINCS HIBA"

SRT BLOKK ({chunk_num}/{total_chunks}):
{chunk_text}
"""

    try:
        proc = subprocess.run(
            ["claude", "-p", prompt,
             "--append-system-prompt-file", sys_prompt_path,
             "--allowedTools", "",
             "--model", model],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8"
        )
        if proc.returncode != 0:
            return f"[HIBA a chunkban {chunk_num}]: exit code {proc.returncode}\n{proc.stderr}"
        return proc.stdout.strip()
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT a chunkban {chunk_num} ({timeout // 60} perc)]"
    except FileNotFoundError:
        print("HIBA: A 'claude' parancs nem található!")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Magyar fordítás review Claude-dal")
    parser.add_argument("srt_file", help="Az összefűzött hun.srt fájl")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Feliratok chunkonként (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--model", type=str, default="sonnet",
                        choices=["haiku", "sonnet", "opus"],
                        help="Claude modell (default: sonnet)")
    parser.add_argument("--start-chunk", type=int, default=1,
                        help="Csak ettől a chunktól kezdje (1-alapú). Default: 1")
    parser.add_argument("--end-chunk", type=int, default=None,
                        help="Eddig a chunkig (bezárólag, 1-alapú). Default: utolsó")
    parser.add_argument("--suffix", type=str, default="",
                        help="Riport fájl utótag, pl. '_part2' → _REVIEW_CLAUDE_part2.txt")
    args = parser.parse_args()

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"HIBA: Fájl nem található: {srt_path}")
        sys.exit(1)

    entries = parse_srt(srt_path)
    print(f"Beolvasva: {len(entries)} felirat szekció")

    chunks = list(chunk_entries(entries, args.chunk_size))
    total_chunks = len(chunks)
    print(f"Chunkok: {total_chunks} db (chunkonként {args.chunk_size} felirat)")
    print(f"Modell: {args.model}")

    # Kontextus betöltése + system prompt fájl
    claude_md = load_claude_md()
    glossary = load_glossary()
    sys_prompt_content = build_review_system_prompt(claude_md, glossary)
    sys_prompt_path = write_sys_prompt_file(sys_prompt_content)
    print(f"System prompt: {len(sys_prompt_content)} char "
          f"(CLAUDE.md: {len(claude_md)} char, glossary: {len(glossary)} char)")

    # Chunk-tartomány
    start = max(1, args.start_chunk)
    end = args.end_chunk if args.end_chunk is not None else total_chunks
    end = min(end, total_chunks)
    if start > end:
        print(f"HIBA: --start-chunk ({start}) nagyobb mint --end-chunk ({end}).")
        sys.exit(1)
    if start > 1 or end < total_chunks:
        print(f"Tartomány: {start}–{end}")
    print()

    # Output riport fájl
    report_path = srt_path.with_name(srt_path.stem + f"_REVIEW_CLAUDE{args.suffix}.txt")

    all_findings = []
    error_chunks = []

    for i in range(start, end + 1):
        chunk = chunks[i - 1]
        chunk_text = "\n\n".join(chunk)
        print(f"[{i}/{total_chunks}] Ellenőrzés folyamatban...")

        result = review_chunk(chunk_text, i, total_chunks, sys_prompt_path, args.model)

        if not result:
            continue
        # Hibás chunk: subprocess timeout vagy exit code != 0
        if result.startswith("[HIBA") or result.startswith("[TIMEOUT"):
            error_chunks.append(f"--- Chunk {i}/{total_chunks} ---\n{result}\n")
            print(f"  {result.splitlines()[0]}")
            continue
        if "NINCS HIBA" not in result:
            all_findings.append(f"--- Chunk {i}/{total_chunks} ---\n{result}\n")

    # Riport mentése
    sections = []
    if all_findings:
        sections.append("\n".join(all_findings))
    if error_chunks:
        sections.append("=== HIBÁS / KIHAGYOTT CHUNKOK ===\n\n" + "\n".join(error_chunks))

    if sections:
        report_content = (
            f"Review riport (Claude): {srt_path.name}\n"
            f"Modell: {args.model}\n"
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
