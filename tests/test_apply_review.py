"""subtr.tasks.apply_review (interaktív) + apply_review_auto (döntés-fájlos):
riport-betöltés, összefésülés, és a fájlra írás védelmei (drift, .bak)."""

import json
from pathlib import Path

import pytest

from subtr.srt import parse_sections
from subtr.tasks import apply_review, apply_review_auto

SRT = ("1\n00:00:01,000 --> 00:00:02,000\nElső sor\n\n"
       "2\n00:00:03,000 --> 00:00:04,000\nMásodik\nkét sorban\n\n"
       "3\n00:00:05,000 --> 00:00:06,000\nHarmadik\n")


@pytest.fixture
def hun(tmp_path):
    p = tmp_path / "Sorozat - S01E01.hun.srt"
    p.write_text(SRT, encoding="utf-8")
    return p


# ── riportok ────────────────────────────────────────────────────────────────

def test_load_json_and_txt_report(tmp_path):
    js = tmp_path / "x.hun_REVIEW_GEMINI.json"
    js.write_text(json.dumps({"reviewer": "gemini", "findings": [
        {"sorszam": 2, "eredeti": "Második", "hiba": "h", "javaslat": "Jobb"},
        {"sorszam": "nem szám", "javaslat": "x"}]}), encoding="utf-8")
    assert apply_review.load_json_report(js) == [
        {"sorszam": 2, "eredeti": "Második", "hiba": "h", "javaslat": "Jobb",
         "reviewer": "gemini"}]

    txt = tmp_path / "x.hun_REVIEW_CLAUDE.txt"
    txt.write_text('--- Chunk 1/1 ---\n#3: "Harmadik"\n  → HIBA: h\n  → JAVASLAT: Javított\n',
                   encoding="utf-8")
    assert apply_review.load_txt_report(txt) == [
        {"sorszam": 3, "eredeti": "Harmadik", "hiba": "h", "javaslat": "Javított",
         "reviewer": "claude"}]


def test_find_reports_prefers_json_over_txt(hun):
    stem = hun.stem
    for name in (f"{stem}_REVIEW_GEMINI.json", f"{stem}_REVIEW_GEMINI.txt",
                 f"{stem}_REVIEW_CLAUDE.txt", f"{stem}_REVIEW_GROK_part2.json",
                 f"{stem}_REVIEW_CODEX.bak"):
        (hun.parent / name).write_text("{}", encoding="utf-8")
    found = sorted(p.name for p in apply_review.find_reports(hun))
    assert found == [f"{stem}_REVIEW_CLAUDE.txt", f"{stem}_REVIEW_GEMINI.json",
                     f"{stem}_REVIEW_GROK_part2.json"]


def test_merge_findings_dedupes_same_suggestion():
    findings = [
        {"sorszam": 2, "eredeti": "a", "hiba": "h1", "javaslat": "Jobb  szöveg", "reviewer": "gemini"},
        {"sorszam": 2, "eredeti": "a", "hiba": "h2", "javaslat": "Jobb szöveg", "reviewer": "claude"},
        {"sorszam": 2, "eredeti": "a", "hiba": "h3", "javaslat": "Más", "reviewer": "codex"},
        {"sorszam": 1, "eredeti": "b", "hiba": "h", "javaslat": "x", "reviewer": "gemini"},
    ]
    merged = apply_review.merge_findings(findings)
    assert list(merged) == [1, 2]
    assert [v["reviewers"] for v in merged[2]] == [["gemini", "claude"], ["codex"]]


def test_apply_to_block_keeps_header():
    block = "2\n00:00:03,000 --> 00:00:04,000\nrégi\nszöveg"
    assert apply_review.apply_to_block(block, "új") == "2\n00:00:03,000 --> 00:00:04,000\núj"
    assert apply_review.block_text(block) == "régi\nszöveg"


def test_interactive_apply_with_scripted_answers(hun, monkeypatch, capsys):
    js = hun.with_name(hun.stem + "_REVIEW_GEMINI.json")
    js.write_text(json.dumps({"reviewer": "gemini", "findings": [
        {"sorszam": 1, "eredeti": "Első sor", "hiba": "h", "javaslat": "Első JAVÍTVA"},
        {"sorszam": 2, "eredeti": "Második két sorban", "hiba": "h", "javaslat": "kihagyjuk"},
        {"sorszam": 3, "eredeti": "Harmadik", "hiba": "h", "javaslat": "nem érünk ide"},
    ]}), encoding="utf-8")
    answers = iter(["y", "n", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    apply_review.main([str(hun)])
    secs = parse_sections(str(hun))
    assert [s["text"] for s in secs] == ["Első JAVÍTVA", "Második\nkét sorban", "Harmadik"]
    assert hun.with_suffix(".srt.bak").read_text(encoding="utf-8") == SRT
    assert "Alkalmazva: 1, kihagyva: 1" in capsys.readouterr().out


def test_interactive_dry_run_does_not_write(hun, capsys):
    js = hun.with_name(hun.stem + "_REVIEW_CODEX.json")
    js.write_text(json.dumps({"findings": [{"sorszam": 9, "javaslat": "x"}]}), encoding="utf-8")
    apply_review.main([str(hun), "--dry-run"])
    assert hun.read_text(encoding="utf-8") == SRT
    assert "nincs ilyen szekció" in capsys.readouterr().out


# ── apply-auto ──────────────────────────────────────────────────────────────

def _decisions(tmp_path, items):
    p = tmp_path / "decisions.json"
    p.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return p


def test_auto_applies_and_backs_up(hun, tmp_path, capsys):
    dec = _decisions(tmp_path, [
        {"sorszam": 1, "eredeti": "Első sor", "javaslat": "Első ÚJ"},
        {"sorszam": 2, "eredeti": "Második két sorban", "javaslat": "Egy\nsor"},  # whitespace-független
    ])
    apply_review_auto.main([str(hun), str(dec)])
    secs = parse_sections(str(hun))
    assert [s["text"] for s in secs] == ["Első ÚJ", "Egy\nsor", "Harmadik"]
    assert [s["timestamp"] for s in secs][0] == "00:00:01,000 --> 00:00:02,000"
    assert hun.with_suffix(".srt.bak").read_text(encoding="utf-8") == SRT
    assert "Alkalmazva: 2" in capsys.readouterr().out


def test_auto_skips_drifted_entry_unless_ignore_drift(hun, tmp_path, capsys):
    dec = _decisions(tmp_path, [{"sorszam": 3, "eredeti": "Valami más", "javaslat": "ÚJ"}])
    apply_review_auto.main([str(hun), str(dec)])
    assert parse_sections(str(hun))[2]["text"] == "Harmadik"
    assert "ELTÉRÉS" in capsys.readouterr().out
    apply_review_auto.main([str(hun), str(dec), "--ignore-drift"])
    assert parse_sections(str(hun))[2]["text"] == "ÚJ"


def test_auto_is_idempotent_and_counts(hun, tmp_path, capsys):
    dec = _decisions(tmp_path, [
        {"sorszam": 1, "eredeti": "Első sor", "javaslat": "Első ÚJ"},
        {"sorszam": 42, "javaslat": "nincs ilyen"},
        {"sorszam": 3, "javaslat": ""},
    ])
    apply_review_auto.main([str(hun), str(dec)])
    apply_review_auto.main([str(hun), str(dec)])  # újrafuttatás: már egyezik
    out = capsys.readouterr().out
    assert "Alkalmazva: 0, már egyezett: 1, hiányzó szekció: 1" in out
    assert "üres javaslat" in out


def test_auto_dry_run_leaves_file(hun, tmp_path, capsys):
    dec = _decisions(tmp_path, [{"sorszam": 1, "javaslat": "X"}])
    apply_review_auto.main([str(hun), str(dec), "--dry-run"])
    assert hun.read_text(encoding="utf-8") == SRT
    assert not hun.with_suffix(".srt.bak").exists()
    assert "1 javítás alkalmazható" in capsys.readouterr().out


def test_auto_rejects_non_list_and_bad_entry(hun, tmp_path):
    bad = tmp_path / "d.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        apply_review_auto.main([str(hun), str(bad)])
    with pytest.raises(SystemExit):
        apply_review_auto.main([str(hun), str(_decisions(tmp_path, [{"javaslat": "x"}]))])
