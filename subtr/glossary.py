"""Jóváhagyott terminológia (glossary.json) betöltése és prompt-szöveggé alakítása.

Alap-szótárak: a `glossaries/<id>.json` fájlok (műfaj × kultúra, pl. zh-historical)
ugyanazzal a sémával, mint a glossary.json. A sorozat a `meta.bases` listában
választ közülük, és futáskor összefésüljük őket (`with_bases`):
  - elsőbbség: a sorozat saját bejegyzése > később felsorolt alap > korábbi alap,
    az `en` alak (normalizált) szerint;
  - az alap-bejegyzések MINDEN kategóriában csak akkor kerülnek a promptba, ha a
    szövegben előfordulnak (`filter_for_source`) — a sorozat saját azonosítói
    (nevek, megszólítások, helyek) továbbra is mindig.
Az összefésült dict bejegyzései belső `_source` mezőt kapnak („project” /
„base:<id>”); a sorozat fájljába soha nem írunk vissza alap-bejegyzést.
"""

import json
import os
import re
import sys

from subtr.config import GLOSSARIES_DIR, GLOSSARY_PATH

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

    A sorozat saját IDENTITY_CATEGORIES-bejegyzései érintetlenek maradnak; a
    FILTERABLE_CATEGORIES-ből és az alap-szótárak (`_source` = base:…) MINDEN
    kategóriájából az marad benn, aminek az `en` VAGY a `hu` alakja szerepel a kapott szövegek
    valamelyikében. A `hu` is számít, mert a review a magyar fordítást nézi,
    a fordítás pedig az idegen nyelvű forrást — ugyanaz a szűrő mindkettőre jó.

    Üres/hiányzó szöveg esetén a teljes szójegyzéket adja vissza: a szűrés
    csak akkor szűkíthet, ha tényleg van mihez mérni.
    """
    haystack = normalize_for_match("\n".join(t for t in texts if t))
    if not haystack.strip():
        return glossary

    filtered = dict(glossary)
    for category in CATEGORIES:
        if category not in glossary:
            continue
        kept = []
        for entry in glossary[category]:
            if category not in FILTERABLE_CATEGORIES and not _is_base(entry):
                kept.append(entry)       # a sorozat saját azonosítója: mindig
                continue
            forms = [normalize_for_match(str(entry.get(key) or ""))
                     for key in ("en", "hu")]
            if any(form and form in haystack for form in forms):
                kept.append(entry)
        filtered[category] = kept
    return filtered


# ── Alap-szótárak ─────────────────────────────────────────────────────────

# Az azonosító fájlnév is: csak kisbetű, szám, kötőjel (nincs ../ útvonal-trükk).
BASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        print(f"FIGYELEM: {message}", file=sys.stderr)


def _is_base(entry: dict) -> bool:
    return str(entry.get("_source", "")).startswith("base:")


def base_ids(glossary: dict) -> list[str]:
    """A `meta.bases` lista (egyetlen string is elfogadott)."""
    ids = (glossary.get("meta") or {}).get("bases") or []
    if isinstance(ids, str):
        ids = [ids]
    return [i for i in ids if isinstance(i, str) and i.strip()]


def load_base(base_id: str, directory: str | None = None) -> dict | None:
    """Egy alap-szótár beolvasása; hiányzó / hibás fájlnál figyelmeztet és None."""
    base_id = base_id.strip()
    if not BASE_ID_RE.match(base_id):
        _warn_once(f"érvénytelen alap-szótár azonosító: {base_id!r} — kihagyva")
        return None
    path = os.path.join(directory if directory is not None else GLOSSARIES_DIR,
                        base_id + ".json")
    if not os.path.isfile(path):
        _warn_once(f"a(z) {base_id} alap-szótár nem található ({path}) — kihagyva")
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _warn_once(f"a(z) {path} nem olvasható ({e}) — kihagyva")
        return None
    return data if isinstance(data, dict) else None


def with_bases(project: dict, directory: str | None = None) -> dict:
    """A sorozat-glossary és a `meta.bases` alapjainak összefésülése.

    Új dict-et ad vissza (a bemenetet nem módosítja); a bejegyzések másolatok
    `_source` jelöléssel. A `meta._merge` összegzést hordoz a státuszsorhoz:
    bases (betöltött azonosítók), base_entries (bekerült alap-bejegyzés),
    overridden (a sorozat vagy egy későbbi alap által felülírt).
    """
    merged = {cat: [] for cat in CATEGORIES}
    merged["meta"] = dict(project.get("meta") or {})
    seen = set()
    for category in CATEGORIES:
        for entry in project.get(category, []) or []:
            merged[category].append({**entry, "_source": "project"})
            seen.add(normalize_for_match(str(entry.get("en") or "")))

    loaded, added, overridden = [], 0, 0
    bases = [(bid, load_base(bid, directory)) for bid in base_ids(project)]
    # Hátulról előre: a később felsorolt alap erősebb, ezért az kerül be előbb.
    for bid, data in reversed(bases):
        if data is None:
            continue
        loaded.insert(0, bid)
        for category in CATEGORIES:
            for entry in data.get(category, []) or []:
                key = normalize_for_match(str(entry.get("en") or ""))
                if not key:
                    continue
                if key in seen:
                    overridden += 1
                    continue
                seen.add(key)
                merged[category].append({**entry, "_source": f"base:{bid}"})
                added += 1
    merged["meta"]["_merge"] = {"bases": loaded, "base_entries": added,
                                "overridden": overridden}
    return merged


def describe_bases(merged: dict) -> str:
    """Státuszsor az alapokról — üres, ha a sorozat nem használ alapot."""
    info = (merged.get("meta") or {}).get("_merge") or {}
    if not info.get("bases"):
        return ""
    text = f"alap: {', '.join(info['bases'])} ({info['base_entries']} bejegyzés"
    if info.get("overridden"):
        text += f", {info['overridden']} felülírva"
    return text + ")"


def load_index(directory: str | None = None) -> list[dict]:
    """A `glossaries/index.json` alap-listája (hiányzó/hibás fájlnál üres lista)."""
    path = os.path.join(directory if directory is not None else GLOSSARIES_DIR, "index.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    bases = data.get("bases") if isinstance(data, dict) else None
    return [b for b in bases or [] if isinstance(b, dict) and b.get("id")]


def suggest_bases(index: list[dict], countries, genres, keywords) -> list[tuple[str, str]]:
    """Alap-javaslat a sorozat országa, műfajai és kulcsszavai alapján.

    Az index sorrendjét tartja (a közös réteg előbb, a műfaji utána — a később
    felsorolt az erősebb). Szabályok bejegyzésenként (mind opcionális):
      countries      — ISO-kódok, ezek egyikének egyeznie kell
      any_keywords   — a TMDB-kulcsszavak / műfajok közül legalább egy (részszó)
      none_keywords  — ezek egyike sem fordulhat elő
    Visszaad: [(id, indoklás), …].
    """
    countries = {c.upper() for c in countries or []}
    terms = [t.strip().lower() for t in list(genres or []) + list(keywords or []) if t and t.strip()]

    def hits(words):
        return [w for w in words if any(w.lower() in t for t in terms)]

    out = []
    for base in index:
        want = {c.upper() for c in base.get("countries") or []}
        if want and not countries & want:
            continue
        if hits(base.get("none_keywords") or []):
            continue
        anyk = base.get("any_keywords") or []
        found = hits(anyk)
        if anyk and not found:
            continue
        reason = ", ".join(sorted(countries & want)) if want else ""
        if found:
            reason += (" + " if reason else "") + ", ".join(found)
        out.append((base["id"], reason or "mindig"))
    return out


def load_merged(path: str | None = None) -> dict:
    """A glossary.json és a mellette lévő `glossaries/` alapjai, összefésülve."""
    if path is None:
        path = GLOSSARY_PATH
    directory = os.path.join(os.path.dirname(path), GLOSSARIES_DIR)
    return with_bases(load(path), directory)


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

    Ha glossary=None, betölti a path-ról (vagy a default GLOSSARY_PATH-ról),
    a `meta.bases` alap-szótáraival együtt.
    Ha source_text meg van adva, a filterezhető kategóriák a szövegben tényleg
    előforduló bejegyzésekre szűkülnek — a teljes szójegyzék minden hívásba
    bemenne, holott a nagy része az adott epizódhoz nem tartozik.
    """
    if glossary is None:
        glossary = load_merged(path)
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
