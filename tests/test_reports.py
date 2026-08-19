"""subtr.reports — a _REVIEW_* riport-kontraktus tesztjei."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtr import reports


def test_report_paths_kontraktus():
    p = Path("output/Sorozat - S01E01.hun.srt")
    txt, js = reports.report_paths(p, "gemini", "_part2")
    assert txt.name == "Sorozat - S01E01.hun_REVIEW_GEMINI_part2.txt"
    assert js.name == "Sorozat - S01E01.hun_REVIEW_GEMINI_part2.json"
    for reviewer, tag in (("claude", "CLAUDE"), ("codex", "CODEX")):
        txt, _ = reports.report_paths(p, reviewer)
        assert txt.name.endswith(f"_REVIEW_{tag}.txt")


def test_format_findings():
    findings = [{"sorszam": 12, "eredeti": "Rossz szöveg",
                 "hiba": "tükörfordítás", "javaslat": "Jó szöveg"}]
    block = reports.format_findings(findings, 2, 5)
    assert block.startswith("--- Chunk 2/5 ---")
    assert '#12: "Rossz szöveg"' in block
    assert "→ HIBA: tükörfordítás" in block
    assert "→ JAVASLAT: Jó szöveg" in block
    assert reports.format_findings([], 1, 1) is None


def test_write_reports_json_alak(tmp_path):
    srt = tmp_path / "x.hun.srt"
    txt, js = reports.report_paths(srt, "codex")
    findings = [{"sorszam": 3, "eredeti": "a", "hiba": "b", "javaslat": "c", "chunk": 1}]
    reports.write_reports(srt, txt, js, reviewer="codex", model_label="default",
                          finding_blocks=["--- Chunk 1/1 ---\nvalami"],
                          json_findings=findings, error_chunks=[])
    data = json.loads(js.read_text(encoding="utf-8"))
    # az apply_review.py ezt az alakot olvassa
    assert data["reviewer"] == "codex"
    assert data["source"] == "x.hun.srt"
    assert data["findings"][0]["sorszam"] == 3
    assert txt.read_text(encoding="utf-8").startswith("Review riport (Codex):")


def test_write_reports_ures(tmp_path, capsys):
    srt = tmp_path / "y.hun.srt"
    txt, js = reports.report_paths(srt, "gemini")
    reports.write_reports(srt, txt, js, reviewer="gemini", model_label="m",
                          finding_blocks=[], json_findings=[], error_chunks=[])
    assert not txt.exists() and not js.exists()
    assert "Nincs hiba" in capsys.readouterr().out
