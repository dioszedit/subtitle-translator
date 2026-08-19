"""Pytest konfiguráció: a repo gyökere felkerül a sys.path-ra, hogy a `subtr`
csomag importálható legyen telepítés (pip install -e .) nélkül is."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
