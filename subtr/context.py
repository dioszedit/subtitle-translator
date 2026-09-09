"""Közös sorozat- és fordítási szabályzat betöltése minden providerhez."""

import re
from pathlib import Path


BASE_CONTEXT_FILES = ("TRANSLATION.md", "CLAUDE.md")
LOCAL_CONTEXT_FILE = "TRANSLATION.local.md"


def load_translation_context() -> str:
    """A verziózott alapot és az opcionális, gitignore-os helyi kontextust tölti be."""
    base = ""
    for name in BASE_CONTEXT_FILES:
        path = Path(name)
        if path.is_file():
            base = path.read_text(encoding="utf-8")
            break

    local_path = Path(LOCAL_CONTEXT_FILE)
    if local_path.is_file():
        local = local_path.read_text(encoding="utf-8").strip()
        if local:
            return f"{base.rstrip()}\n\n=== HELYI SOROZATKONTEXTUS ===\n{local}\n"
    return base


# A `Country:` mezőt az addons/tmdb-init generálja a TMDB adataiból; a
# sablon kitöltetlenül `[Ország]`-ot tartalmaz (lásd TRANSLATION.md).
_COUNTRY_RE = re.compile(r"^\s*Country\s*:\s*(.+?)\s*$",
                         re.IGNORECASE | re.MULTILINE)


def series_country() -> str | None:
    """A sorozat országa a TRANSLATION.local.md `Country:` sorából.

    None, ha a fájl, a mező vagy az érték hiányzik — a kitöltetlen `[Ország]`
    sablon-helykitöltő is None. Olvasási hibára nem dob: a hívóknak ez csak
    kiegészítő információ, nem futásfeltétel.
    """
    path = Path(LOCAL_CONTEXT_FILE)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = _COUNTRY_RE.search(text)
    if not match:
        return None
    country = match.group(1).strip()
    # A kitöltetlen sablon (`[Ország]`, `[Country]`) nem érték.
    if not country or (country.startswith("[") and country.endswith("]")):
        return None
    return country


def is_korean_series() -> bool:
    """Igaz, ha a `Country` mező koreai sorozatot jelöl.

    A tmdb-init „South Korea" alakot ír, de a mezőt kézzel is írhatják
    („Korea", „South-Korea"), ezért részsztringre illesztünk. Ismeretlen
    ország hamis — a hívó dönti el, mit kezd vele.
    """
    country = series_country()
    return bool(country) and "korea" in country.lower()
