"""Pytest konfiguráció: a repo gyökere felkerül a sys.path-ra, hogy a `subtr`
csomag importálható legyen telepítés (pip install -e .) nélkül is."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture(autouse=True)
def _isolated_quota_ledger(tmp_path, monkeypatch):
    """Egy teszt se könyveljen a gépszintű ~/.gemini_quota/usage.json-ba: a hamis
    modellnevek („m”, „x”) különben a `subtr.py quota` mai napjában jelennének meg."""
    monkeypatch.setenv("GEMINI_QUOTA_FILE", str(tmp_path / "gemini_quota_usage.json"))
