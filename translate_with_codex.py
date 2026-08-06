#!/usr/bin/env python3
"""Párhuzamos SRT fordítás Codex CLI-vel, strukturált JSON kimenettel."""

import argparse
import glob
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from codex_runner import CodexRunError, find_codex, run_codex_json
from glossary_categories import CATEGORIES
from translation_context import load_translation_context

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


TRANSLATION_SCHEMA = {
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


def parse_sections(filepath: str) -> list[dict]:
    content = open(filepath, encoding="utf-8-sig").read()
    sections = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            sections.append({"num": lines[0].strip(), "timestamp": lines[1].strip(),
                             "text": "\n".join(lines[2:])})
    return sections


def write_srt(filepath: str, sections: list[dict]):
    output = [f"{s['num']}\n{s['timestamp']}\n{s['text']}" for s in sections]
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(output) + "\n")


def count_sections(filepath: str) -> int:
    try:
        lines = open(filepath, encoding="utf-8-sig").read().split("\n")
        return sum(1 for i, line in enumerate(lines)
                   if re.fullmatch(r"\d+", line.strip()) and i + 1 < len(lines)
                   and "-->" in lines[i + 1])
    except OSError:
        return 0


def get_all_blocks(blocks_dir: str) -> list[str]:
    return [p for p in sorted(glob.glob(os.path.join(blocks_dir, "*_block_*.srt")))
            if not p.endswith("_HUN.srt")]


def get_pending_blocks(blocks_dir: str) -> list[str]:
    return [p for p in get_all_blocks(blocks_dir)
            if not os.path.isfile(p[:-4] + "_HUN.srt")]


def safe_remove(filepath: str):
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
    except PermissionError:
        time.sleep(2)
        if os.path.isfile(filepath):
            os.remove(filepath)


def load_glossary() -> str:
    if not os.path.isfile("glossary.json"):
        return ""
    data = json.loads(open("glossary.json", encoding="utf-8").read())
    lines = []
    for category in CATEGORIES:
        for entry in data.get(category, []):
            if entry.get("en") and entry.get("hu"):
                context = f" ({entry['context']})" if entry.get("context") else ""
                lines.append(f'  "{entry["en"]}" = "{entry["hu"]}"{context}')
    return "\n".join(lines)


def build_instruction(context: str, glossary: str) -> str:
    parts = ["""Profi felirat-fordító vagy. Angol SRT feliratszövegeket fordítasz természetes, beszélt magyarra.

KÖTELEZŐ: minden kapott sorszámhoz pontosan egy fordítást adj. A text csak a magyar feliratszöveg legyen; a HTML tageket, kötőjeles párbeszédet, szögletes megjegyzéseket és ♫ jelet őrizd meg. Ne adj magyarázatot."""]
    if context.strip():
        parts.append("=== SOROZAT KONTEXTUS ÉS SZABÁLYOK ===\n" + context.strip())
    if glossary.strip():
        parts.append("=== KÖTELEZŐ SZÓJEGYZÉK ===\n" + glossary)
    return "\n\n".join(parts)


def build_prompt(instruction: str, sections: list[dict]) -> str:
    entries = "\n\n".join(f"#{s['num']}\n{s['text']}" for s in sections)
    return f"{instruction}\n\n=== FELADAT ===\nFordítsd le az alábbi szekciókat.\n\n{entries}"


def translate_block(block_path: str, instruction: str, timeout: int, retries: int,
                    model: str | None, codex_bin: str) -> dict:
    output_path = block_path[:-4] + "_HUN.srt"
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
            parsed = run_codex_json(build_prompt(instruction, sections), TRANSLATION_SCHEMA,
                                    timeout=timeout, model=model, codex_bin=codex_bin)
            break
        except CodexRunError as exc:
            error = exc
            if attempt < retries:
                print(f"  Codex hiba, újrapróbálás ({attempt}/{retries})...")
    if parsed is None:
        safe_remove(output_path)
        return {"block": name, "status": "fail", "message": str(error)}

    translations = {}
    for item in parsed.get("translations", []):
        if isinstance(item, dict) and isinstance(item.get("sorszam"), int) and isinstance(item.get("text"), str):
            translations[item["sorszam"]] = item["text"]
    missing = expected - set(translations)
    if missing:
        safe_remove(output_path)
        return {"block": name, "status": "fail", "message": f"Hiányzó fordítások: {sorted(missing)[:5]}"}

    write_srt(output_path, [{**section, "text": translations[int(section["num"])]}
                            for section in sections])
    if count_sections(output_path) != len(sections):
        safe_remove(output_path)
        return {"block": name, "status": "warning", "message": "Szekciószám eltérés — output törölve"}
    return {"block": name, "status": "ok", "message": f"{len(sections)} szekció"}


def main():
    parser = argparse.ArgumentParser(description="Párhuzamos SRT fordítás Codex CLI-vel")
    parser.add_argument("blocks_dir", help="A split_srt.py által létrehozott blokkmappa")
    parser.add_argument("--agents", type=int, default=1, help="Párhuzamos Codex futások száma (default: 1)")
    parser.add_argument("--block", help="Csak egy blokk (pl. 3 vagy 003)")
    parser.add_argument("--model", help="Opcionális Codex modellazonosító")
    parser.add_argument("--timeout", type=int, default=900, help="Timeout blokkonként mp-ben")
    parser.add_argument("--max-retries", type=int, default=2, help="Próbálkozások blokkanként")
    args = parser.parse_args()
    if args.agents < 1 or args.max_retries < 1:
        parser.error("--agents és --max-retries legalább 1 legyen")
    if not os.path.isdir(args.blocks_dir):
        parser.error(f"Nem találom a mappát: {args.blocks_dir}")
    codex_bin = find_codex()
    if not codex_bin:
        parser.error("A 'codex' parancs nem található a PATH-on.")

    all_blocks = get_all_blocks(args.blocks_dir)
    if args.block:
        block_id = args.block.zfill(3) if args.block.isdigit() else args.block
        pending = [p for p in all_blocks if f"_block_{block_id}_" in p]
        if not pending:
            parser.error(f"Nem találom a(z) {args.block}. blokkot")
        for block in pending:
            safe_remove(block[:-4] + "_HUN.srt")
    else:
        pending = get_pending_blocks(args.blocks_dir)

    context = load_translation_context()
    instruction = build_instruction(context, load_glossary())
    print(f"Codex fordítás: {len(pending)} / {len(all_blocks)} blokk, {args.agents} agent")
    print(f"Közös kontextus: {len(context)} karakter; modell: {args.model or 'Codex alapértelmezés'}")
    if not pending:
        print("Minden blokk le van fordítva!")
        return

    results = []
    with ThreadPoolExecutor(max_workers=args.agents) as executor:
        futures = [executor.submit(translate_block, block, instruction, args.timeout,
                                   args.max_retries, args.model, codex_bin) for block in pending]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"[{result['status'].upper()}] {result['block']}: {result['message']}")
    failed = [result for result in results if result["status"] != "ok"]
    print(f"\nKész: {len(results) - len(failed)} sikeres, {len(failed)} hibás")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
