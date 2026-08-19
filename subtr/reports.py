"""Review-riport kontraktus — fájlnevek, formázás, mentés EGY helyen.

A riport-utótag (`_REVIEW_CLAUDE.json` stb.) kontraktus: az apply_review.py
globbal keresi, a review-triage skill `_REVIEW_*.json`-t vár. Az alakja itt
rögzül, és nem változhat a fogyasztók tudta nélkül.

Egy finding normalizált alakja (minden provider erre hozza):
    {"sorszam": int, "eredeti": str, "hiba": str, "javaslat": str}
a JSON-riportban kiegészülve a "chunk" mezővel.
"""

import json
from pathlib import Path

# reviewer-név → riport-utótag törzs (a .txt/.json és az opcionális
# --suffix a hívónál ragad hozzá)
REVIEW_SUFFIX = {
    "claude": "_REVIEW_CLAUDE",
    "gemini": "_REVIEW_GEMINI",
    "codex": "_REVIEW_CODEX",
}


def report_paths(srt_path: Path, reviewer: str, suffix: str = ""):
    """(txt_path, json_path) a kontraktus szerint."""
    stem = srt_path.stem + REVIEW_SUFFIX[reviewer] + suffix
    return (srt_path.with_name(stem + ".txt"),
            srt_path.with_name(stem + ".json"))


def format_findings(findings: list[dict], chunk_num: int, total: int):
    """Normalizált találatokból szöveges riport-blokk (a bevált formátumban)."""
    if not findings:
        return None
    lines = [f"--- Chunk {chunk_num}/{total} ---"]
    for err in findings:
        lines.append(f'#{err["sorszam"]}: "{err["eredeti"]}"')
        lines.append(f"  → HIBA: {err['hiba']}")
        lines.append(f"  → JAVASLAT: {err['javaslat']}")
        lines.append("")
    return "\n".join(lines)


def write_reports(srt_path: Path, report_path: Path, json_path: Path, *,
                  reviewer: str, model_label: str,
                  finding_blocks: list[str], json_findings: list[dict],
                  error_chunks: list[str]):
    """A .txt és .json riport mentése a bevált szerkezetben.

    A .txt fejlécében a reviewer nagybetűs kezdőbetűvel jelenik meg
    (Claude/Gemini/Codex), a .json-ban kisbetűvel — ez a meglévő kontraktus.
    """
    sections = []
    if finding_blocks:
        sections.append("\n".join(finding_blocks))
    if error_chunks:
        sections.append("=== HIBÁS / KIHAGYOTT CHUNKOK ===\n\n" + "\n".join(error_chunks))

    if sections:
        report_content = (
            f"Review riport ({reviewer.capitalize()}): {srt_path.name}\n"
            f"Modell: {model_label}\n"
            f"{'=' * 60}\n\n"
            + "\n\n".join(sections)
        )
        report_path.write_text(report_content, encoding="utf-8")
        print(f"\nRiport mentve: {report_path}")
        print(f"Találatok: {len(finding_blocks)} chunkban, hibás chunkok: {len(error_chunks)}")
    else:
        print("\nNincs hiba egyik chunkban sem!")

    if json_findings:
        json_path.write_text(json.dumps({
            "source": srt_path.name,
            "reviewer": reviewer,
            "model": model_label,
            "findings": json_findings,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON riport mentve: {json_path}")
