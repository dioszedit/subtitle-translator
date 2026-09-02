"""Jóváhagyott terminológia (glossary.json) betöltése és prompt-szöveggé alakítása."""

import json
import os
import re

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


# A promptba MINDIG teljes egészében bekerülő kategóriák: ezek azonosítók
# (kit hogy szólítunk, kit hogy hívunk, hol játszódik), ahol egy alakváltozat
# miatti kiszűrés névelírást okozna. A maradék kettő a szójegyzék háromnegyede,
# és ott a szövegbeli előfordulás megbízható szűrőfeltétel.
IDENTITY_CATEGORIES = ("honorifics", "place_names", "character_names")
FILTERABLE_CATEGORIES = ("special_terms", "phrases")

# A glossary tipográfiai jeleket használ (’ “ –), a feliratok gyakran ASCII-t.
_MATCH_SUBSTITUTIONS = (
    ("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'),
    ("\u2013", "-"), ("\u2014", "-"), ("\u2026", "..."),
)


def normalize_for_match(text: str) -> str:
    """Kisbetűs, ASCII-írásjelű, egy-szóközös alak az előfordulás-kereséshez."""
    text = text.lower()
    for fancy, plain in _MATCH_SUBSTITUTIONS:
        text = text.replace(fancy, plain)
    return re.sub(r"\s+", " ", text)


def filter_for_source(glossary: dict, *texts: str) -> dict:
    """A szójegyzék szűkítése azokra a bejegyzésekre, amik a szövegben előfordulnak.

    Az IDENTITY_CATEGORIES érintetlen marad, a FILTERABLE_CATEGORIES-ből az
    marad benn, aminek az `en` VAGY a `hu` alakja szerepel a kapott szövegek
    valamelyikében. A `hu` is számít, mert a review a magyar fordítást nézi,
    a fordítás pedig az idegen nyelvű forrást — ugyanaz a szűrő mindkettőre jó.

    Üres/hiányzó szöveg esetén a teljes szójegyzéket adja vissza: a szűrés
    csak akkor szűkíthet, ha tényleg van mihez mérni.
    """
    haystack = normalize_for_match("\n".join(t for t in texts if t))
    if not haystack.strip():
        return glossary

    filtered = dict(glossary)
    for category in FILTERABLE_CATEGORIES:
        if category not in glossary:
            continue
        kept = []
        for entry in glossary[category]:
            forms = [normalize_for_match(str(entry.get(key) or ""))
                     for key in ("en", "hu")]
            if any(form and form in haystack for form in forms):
                kept.append(entry)
        filtered[category] = kept
    return filtered


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


def as_prompt_text(glossary: dict | None = None, path: str | None = None,
                   source_text: str | None = None) -> str:
    """A glossary prompt-szöveggé alakítása — kategóriánként, `"en" = "hu" (ctx)` sorokkal.

    Ha glossary=None, betölti a path-ról (vagy a default GLOSSARY_PATH-ról).
    Ha source_text meg van adva, a filterezhető kategóriák a szövegben tényleg
    előforduló bejegyzésekre szűkülnek — a teljes szójegyzék minden hívásba
    bemenne, holott a nagy része az adott epizódhoz nem tartozik.
    """
    if glossary is None:
        glossary = load(path)
    if source_text:
        glossary = filter_for_source(glossary, source_text)
    lines = []
    for category in CATEGORIES:
        for entry in glossary.get(category, []):
            en = entry.get("en", "")
            hu = entry.get("hu", "")
            ctx = entry.get("context", "")
            if en and hu:
                lines.append(f'  "{en}" = "{hu}"' + (f" ({ctx})" if ctx else ""))
    return "\n".join(lines) if lines else ""
