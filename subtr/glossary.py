"""Jóváhagyott terminológia (glossary.json) betöltése és prompt-szöveggé alakítása."""

import json
import os

from subtr.config import GLOSSARY_PATH

# A `glossary.json` fix kategóriái, fix sorrendben. Új kategória esetén ITT
# add hozzá egy helyen — minden olvasó modul innen importál:
#   - subtr/tasks/translate.py, subtr/tasks/review.py
#   - subtr/tasks/glossary_extract.py, subtr/tasks/register_extract.py
CATEGORIES = [
    "honorifics",
    "place_names",
    "character_names",
    "special_terms",
    "phrases",
]


def load(path: str | None = None) -> dict:
    """A glossary.json beolvasása dict-ként.

    Hiányzó vagy üres fájl esetén üres kategória-dict-et ad vissza (a
    CATEGORIES-ből felépítve), hogy a hívók egységesen `data.get(category, [])`
    formában dolgozhassanak.
    """
    if path is None:
        path = GLOSSARY_PATH
    if not os.path.isfile(path):
        return {cat: [] for cat in CATEGORIES}
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return {cat: [] for cat in CATEGORIES}
    return json.loads(content)


def as_prompt_text(glossary: dict | None = None, path: str | None = None) -> str:
    """A glossary prompt-szöveggé alakítása — kategóriánként, `"en" = "hu" (ctx)` sorokkal.

    Ha glossary=None, betölti a path-ról (vagy a default GLOSSARY_PATH-ról).
    """
    if glossary is None:
        glossary = load(path)
    lines = []
    for category in CATEGORIES:
        for entry in glossary.get(category, []):
            en = entry.get("en", "")
            hu = entry.get("hu", "")
            ctx = entry.get("context", "")
            if en and hu:
                lines.append(f'  "{en}" = "{hu}"' + (f" ({ctx})" if ctx else ""))
    return "\n".join(lines) if lines else ""
