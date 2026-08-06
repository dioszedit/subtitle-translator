#!/usr/bin/env python3
"""SRT stilisztikai review Codex CLI-vel, strukturált JSON riporttal."""

import argparse
import json
import sys
from pathlib import Path

from codex_runner import CodexRunError, find_codex, run_codex_json
from review_with_gemini import (
    attach_source, build_system_instruction, check_source_alignment, chunk_entries,
    find_source_srt, load_claude_md, load_glossary, parse_srt,
    parse_srt_by_index,
)

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_CHUNK_SIZE = 100
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sorszam": {"type": "integer"}, "eredeti": {"type": "string"},
                    "hiba": {"type": "string"}, "javaslat": {"type": "string"},
                },
                "required": ["sorszam", "eredeti", "hiba", "javaslat"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["errors"],
    "additionalProperties": False,
}


def review_chunk(chunk_text: str, chunk_num: int, total: int, instruction: str,
                 timeout: int, retries: int, model: str | None, codex_bin: str):
    prompt = f"{instruction}\n\n=== REVIEW BLOKK ({chunk_num}/{total}) ===\n{chunk_text}"
    error = None
    for attempt in range(1, retries + 1):
        try:
            return run_codex_json(prompt, REVIEW_SCHEMA, timeout=timeout, model=model,
                                  codex_bin=codex_bin), None
        except CodexRunError as exc:
            error = str(exc)
            if attempt < retries:
                print(f"  Codex hiba, újrapróbálás ({attempt}/{retries})...")
    return None, error


def normalized_findings(parsed: dict) -> list[dict]:
    findings = []
    for item in parsed.get("errors", []):
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("sorszam"), int):
            continue
        findings.append({key: str(item.get(key, "")) for key in ("eredeti", "hiba", "javaslat")}
                        | {"sorszam": item["sorszam"]})
    return findings


def format_findings(findings: list[dict], chunk_num: int, total: int) -> str:
    lines = [f"--- Chunk {chunk_num}/{total} ---"]
    for finding in findings:
        lines.append(f'#{finding["sorszam"]}: "{finding["eredeti"]}"')
        lines.append(f"  → HIBA: {finding['hiba']}")
        lines.append(f"  → JAVASLAT: {finding['javaslat']}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Magyar SRT review Codex CLI-vel")
    parser.add_argument("srt_file", help="Az összefűzött hun.srt fájl")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--model", help="Opcionális Codex modellazonosító")
    parser.add_argument("--timeout", type=int, default=900, help="Timeout chunkonként mp-ben")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--start-chunk", type=int, default=1)
    parser.add_argument("--end-chunk", type=int)
    parser.add_argument("--suffix", default="")
    parser.add_argument("--source", "--english", dest="source")
    parser.add_argument("--no-source", "--no-english", dest="no_source", action="store_true")
    args = parser.parse_args()
    if args.chunk_size < 1 or args.max_retries < 1:
        parser.error("--chunk-size és --max-retries legalább 1 legyen")
    if args.source and args.no_source:
        parser.error("--source és --no-source együtt nem használható")
    codex_bin = find_codex()
    if not codex_bin:
        parser.error("A 'codex' parancs nem található a PATH-on.")

    srt_path = Path(args.srt_file)
    if not srt_path.is_file():
        parser.error(f"Fájl nem található: {srt_path}")
    entries = parse_srt(srt_path)
    has_source = False
    if not args.no_source:
        source_path = Path(args.source) if args.source else find_source_srt(srt_path)
        if args.source and not source_path.is_file():
            parser.error(f"Forrás SRT nem található: {source_path}")
        if source_path:
            src_map = parse_srt_by_index(source_path)
            problem = check_source_alignment(entries, src_map)
            if problem and not args.source:
                print(f"Forrás kihagyva, igazítási hiba: {problem}")
            else:
                if problem:
                    print(f"FIGYELEM: explicit forrás, de igazítási hiba: {problem}")
                entries, matched = attach_source(entries, src_map)
                has_source = matched > 0
                print(f"Forrás: {source_path} ({matched}/{len(entries)} szekció)")

    chunks = list(chunk_entries(entries, args.chunk_size))
    total = len(chunks)
    start, end = max(1, args.start_chunk), min(args.end_chunk or total, total)
    if start > end:
        parser.error("--start-chunk nagyobb, mint --end-chunk")

    context, glossary = load_claude_md(), load_glossary()
    instruction = build_system_instruction(context, glossary, has_source)
    print(f"Codex review: {start}–{end}/{total} chunk; modell: {args.model or 'Codex alapértelmezés'}")

    report_path = srt_path.with_name(srt_path.stem + f"_REVIEW_CODEX{args.suffix}.txt")
    json_path = srt_path.with_name(srt_path.stem + f"_REVIEW_CODEX{args.suffix}.json")
    if (start > 1 or end < total) and not args.suffix and report_path.exists():
        parser.error("Rész-tartományhoz adj --suffix értéket, hogy ne írj felül teljes riportot")

    report_blocks, json_findings, errors = [], [], []
    for number in range(start, end + 1):
        print(f"[{number}/{total}] Ellenőrzés...")
        parsed, error = review_chunk("\n\n".join(chunks[number - 1]), number, total, instruction,
                                     args.timeout, args.max_retries, args.model, codex_bin)
        if error:
            errors.append(f"--- Chunk {number}/{total} ---\n{error}\n")
            continue
        findings = normalized_findings(parsed)
        if findings:
            report_blocks.append(format_findings(findings, number, total))
            json_findings.extend({**finding, "chunk": number} for finding in findings)

    content = []
    if report_blocks:
        content.append("\n".join(report_blocks))
    if errors:
        content.append("=== HIBÁS / KIHAGYOTT CHUNKOK ===\n\n" + "\n".join(errors))
    if content:
        report_path.write_text(f"Review riport (Codex): {srt_path.name}\nModell: {args.model or 'alapértelmezett'}\n{'=' * 60}\n\n" + "\n\n".join(content), encoding="utf-8")
        print(f"Riport mentve: {report_path}")
    else:
        print("Nincs hiba egyik chunkban sem.")
    if json_findings:
        json_path.write_text(json.dumps({"source": srt_path.name, "reviewer": "codex",
                                         "model": args.model or "default", "findings": json_findings},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON riport mentve: {json_path}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
