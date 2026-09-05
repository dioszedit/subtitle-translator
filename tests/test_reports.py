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
    for reviewer, tag in (("claude", "CLAUDE"), ("codex", "CODEX"), ("grok", "GROK")):
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


def test_write_reports_removes_stale_reports_when_no_findings(tmp_path):
    """Találat nélküli újrafutás: a korábbi .txt/.json nem maradhat, különben a
    `subtr apply` a már javított találatokat ajánlaná fel újra."""
    srt = tmp_path / "x.hun.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nSzia\n", encoding="utf-8")
    txt, js = reports.report_paths(srt, "gemini")
    txt.write_text("régi riport", encoding="utf-8")
    js.write_text('{"findings": [{"sorszam": 1}]}', encoding="utf-8")
    reports.write_reports(srt, txt, js, reviewer="gemini", model_label="m",
                          finding_blocks=[], json_findings=[], error_chunks=[])
    assert not txt.exists() and not js.exists()


def test_write_reports_keeps_txt_but_removes_json_on_error_only(tmp_path):
    """Csak hibás chunk van: a .txt (hibalista) készül, a régi .json megy."""
    srt = tmp_path / "x.hun.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nSzia\n", encoding="utf-8")
    txt, js = reports.report_paths(srt, "codex")
    js.write_text("{}", encoding="utf-8")
    reports.write_reports(srt, txt, js, reviewer="codex", model_label="m",
                          finding_blocks=[], json_findings=[],
                          error_chunks=["--- Chunk 1/1 ---\nTimeout\n"])
    assert txt.exists() and not js.exists()
