"""subtr.quota — a napi kvótanapló könyvelése (API-hívás nélkül)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtr import quota


def test_record_creates_and_reads_back_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "usage.json"
    monkeypatch.setenv("GEMINI_QUOTA_FILE", str(ledger))

    quota.record("gemini-3.6-flash")
    quota.record("gemini-3.6-flash", n=2)

    assert ledger.is_file()
    with open(ledger, "r", encoding="utf-8") as f:
        data = json.load(f)

    fp = quota.key_fingerprint()
    day = data["keys"][fp]["days"][quota.today_key()]
    assert day["gemini-3.6-flash"]["calls"] == 3

    st = quota.status("gemini-3.6-flash")
    assert st["used"] == 3


def test_preflight_does_not_raise_on_empty_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "usage.json"
    monkeypatch.setenv("GEMINI_QUOTA_FILE", str(ledger))

    # üres napló — a fájl még nem is létezik
    assert quota.preflight("gemini-3.6-flash", needed=1, quiet=True) is True


def test_key_fingerprint_is_deterministic(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ugyanaz-a-kulcs")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    fp1 = quota.key_fingerprint()
    fp2 = quota.key_fingerprint()
    assert fp1 == fp2
    assert fp1 != "nincs-kulcs"


def test_key_fingerprint_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    assert quota.key_fingerprint() == "nincs-kulcs"
