"""
TMDB sorozat-adatok lekérése a hivatalos API-ról.

Önállóan nyers kiíratásra használható, de az add-on fő belépési pontja az
`init_local.py`, ami az itt lekért adatokból TRANSLATION.local.md-t épít.

    python tmdb_fetch.py <tmdb_url_vagy_id>          # nyers dump a képernyőre

Kulcs: TMDB_API_KEY a .env-ben (https://www.themoviedb.org/settings/api).
Függőség nincs — csak a standard lib (urllib + json).

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.themoviedb.org/3"
KEY_URL = "https://www.themoviedb.org/settings/api"
ATTRIBUTION = "This product uses the TMDB API but is not endorsed or certified by TMDB."

# Ennyi szereplő kaphat "Main Role" címkét (a TMDB `order` sorrendjében) — a
# TMDB nem különböztet fő-/mellékszereplőt, ezt az epizódszámból és a
# sorrendből számoljuk (lásd classify_role). --main-cast kapcsolóval állítható.
DEFAULT_MAIN_LIMIT = 4

# origin_country ISO-kódok → a TRANSLATION.local.md-ben olvasható név.
# Ismeretlen kód változatlanul marad.
COUNTRY_NAMES = {
    "CN": "China", "KR": "South Korea", "JP": "Japan", "TW": "Taiwan",
    "HK": "Hong Kong", "TH": "Thailand", "PH": "Philippines", "VN": "Vietnam",
    "SG": "Singapore", "MY": "Malaysia", "ID": "Indonesia", "IN": "India",
    "TR": "Türkiye", "US": "United States", "GB": "United Kingdom",
    "DE": "Germany", "FR": "France", "ES": "Spain", "IT": "Italy",
    "HU": "Hungary",
}


class TmdbError(Exception):
    """Érthető, magyar hibaüzenet a hívónak — a traceback helyett."""


# ── URL → id ────────────────────────────────────────────────────────────────

_TV_URL_RE = re.compile(r"(?:^|/)tv/(\d+)(?:[-/?#]|$)")
_MOVIE_URL_RE = re.compile(r"(?:^|/)movie/(\d+)")


def parse_tmdb_url(text: str) -> int:
    """A TMDB sorozat-id a linkből.

    Elfogadja: https://www.themoviedb.org/tv/236033-the-double, ugyanez slug
    nélkül, query/fragment farokkal, vagy a puszta számot. Film-linket (/movie/)
    kifejezetten elutasít: az add-on sorozatot kezel, a film-végpont mezői mások.
    """
    s = (text or "").strip()
    if s.isdigit():
        return int(s)
    m = _TV_URL_RE.search(s)
    if m:
        return int(m.group(1))
    if _MOVIE_URL_RE.search(s):
        raise ValueError("film-link (/movie/) — az add-on csak sorozatot kezel: /tv/<id> alak kell")
    raise ValueError("nem TMDB sorozat-link — https://www.themoviedb.org/tv/<id>-<slug> alak vagy puszta id kell")


# ── API-kulcs és HTTP ───────────────────────────────────────────────────────

def _load_dotenv() -> None:
    """Ugyanaz a konvenció, mint a subtr/config.py: a .env-et a MUNKAKÖNYVTÁRBÓL
    (vagy fölötte) keressük, mert a pipeline a sorozat mappájából fut."""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(find_dotenv(usecwd=True) or None)


def api_key() -> str:
    _load_dotenv()
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        raise TmdbError(
            "nincs TMDB_API_KEY a .env-ben vagy a környezetben — "
            f"ingyenes kulcs: {KEY_URL}")
    return key


def _http_error_text(err: urllib.error.HTTPError, path: str) -> str:
    try:
        body = json.loads(err.read().decode("utf-8"))
    except Exception:
        body = {}
    if err.code == 401:
        return f"érvénytelen TMDB_API_KEY (HTTP 401) — kulcs: {KEY_URL}"
    if err.code == 404:
        return f"nincs ilyen sorozat a TMDB-n (HTTP 404): {path}"
    detail = body.get("status_message") or err.reason
    return f"TMDB HTTP {err.code}: {detail}"


def _ssl_context() -> ssl.SSLContext:
    """A python.org-os macOS Python nem látja a rendszer tanúsítványait, és
    CERTIFICATE_VERIFY_FAILED-del áll le. A `certifi` a Gemini-provider
    függőségeivel (httpx) úgyis telepítve van — ha megvan, azt használjuk."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover
        return ssl.create_default_context()


def fetch_json(path: str, params: dict | None = None) -> dict:
    """Egy GET a TMDB v3 API-ra. A tesztek ezt mockolják."""
    query = dict(params or {})
    query["api_key"] = api_key()
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/json",
                      "User-Agent": "subtitle-translator/tmdb-init"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise TmdbError(_http_error_text(e, path)) from e
    except urllib.error.URLError as e:
        hint = ""
        if "CERTIFICATE_VERIFY_FAILED" in str(e.reason):
            hint = " — tanúsítványhiba: pip install certifi (macOS python.org-os Pythonnál az Install Certificates.command is segít)"
        raise TmdbError(f"hálózati hiba: {e.reason}{hint}") from e


def fetch_series(tmdb_id: int) -> dict:
    """Minden, ami a TRANSLATION.local.md-hez kell, EGY hívással."""
    return fetch_json(f"/tv/{tmdb_id}", {
        "language": "en-US",
        "append_to_response": "aggregate_credits,keywords,translations",
    })


# ── JSON → az init_local által várt dict ───────────────────────────────────

def classify_role(order: int, total_ep: int, n_episodes: int,
                  main_limit: int = DEFAULT_MAIN_LIMIT) -> str:
    """Main / Support / Guest Role — ugyanazok a címkék, amiket a korábbi
    forrás adott, így a dokumentum-építő logika változatlan.

    Vendég: legfeljebb 2 epizód, vagy az epizódszám 10 %-a (ami nagyobb).
    Fő: az első `main_limit` a TMDB sorrendjében, ÉS legalább az epizódok
    háromnegyedében szerepel — egy 2-részes cameo a lista elején sem lesz fő.
    """
    n = n_episodes or 0
    total = total_ep or 0
    if total <= max(2, n // 10):
        return "Guest Role"
    if order < main_limit and (not n or total >= 0.75 * n):
        return "Main Role"
    return "Support Role"


def map_series(payload: dict, main_limit: int = DEFAULT_MAIN_LIMIT) -> dict:
    name = (payload.get("name") or "").strip() or "N/A"
    year = (payload.get("first_air_date") or "")[:4]
    title = f"{name} ({year})" if year else name

    codes = payload.get("origin_country") or []
    country = ", ".join(COUNTRY_NAMES.get(c, c) for c in codes) or "N/A"

    n_ep = payload.get("number_of_episodes") or 0

    run_times = payload.get("episode_run_time") or []
    runtime = run_times[0] if run_times else None
    if not runtime:
        runtime = (payload.get("last_episode_to_air") or {}).get("runtime")
    duration = f"{runtime} min." if runtime else "N/A"

    genres = ", ".join(g.get("name", "") for g in payload.get("genres") or [] if g.get("name"))
    keywords = (payload.get("keywords") or {}).get("results") or []
    tags = ", ".join(k.get("name", "") for k in keywords if k.get("name"))

    cast = []
    raw_cast = (payload.get("aggregate_credits") or {}).get("cast") or []
    for c in sorted(raw_cast, key=lambda c: c.get("order", 0)):
        roles = c.get("roles") or []
        character = ((roles[0].get("character") if roles else "") or "").strip()
        total = c.get("total_episode_count") or 0
        role_type = classify_role(c.get("order", 0), total, n_ep, main_limit)
        cast.append(((c.get("name") or "").strip(), character, role_type))

    hu_title = ""
    for t in (payload.get("translations") or {}).get("translations") or []:
        if t.get("iso_639_1") == "hu":
            hu_title = ((t.get("data") or {}).get("name") or "").strip()
            break

    return {
        "title": title,
        "native_title": (payload.get("original_name") or "").strip() or "N/A",
        "country": country,
        "episodes": str(n_ep) if n_ep else "N/A",
        "duration": duration,
        "genres": genres or "N/A",
        "tags": tags or "N/A",
        "synopsis": (payload.get("overview") or "").strip() or "N/A",
        "cast": cast,
        "hu_title": hu_title,
        "tmdb_id": payload.get("id"),
    }


def fetch(url_or_id: str, main_limit: int = DEFAULT_MAIN_LIMIT) -> dict:
    """URL/id → kész adat-dict. ValueError rossz linknél, TmdbError API-hibánál."""
    return map_series(fetch_series(parse_tmdb_url(url_or_id)), main_limit)


# ── Nyers dump ──────────────────────────────────────────────────────────────

def format_output(data: dict) -> str:
    lines = [
        f"Title: {data['title']} ({data['native_title']})",
        f"Hungarian title (TMDB): {data.get('hu_title') or '-'}",
        f"Country: {data['country']}",
        f"Episodes: {data['episodes']}",
        f"Duration: {data['duration']}",
        f"Genres: {data['genres']}",
        f"Tags: {data['tags']}",
        "",
        "Synopsis:",
        data["synopsis"],
        "",
        "Cast:",
    ]
    for actor, role, role_type in data["cast"]:
        parts = [f"  - {actor}"]
        if role:
            parts.append(f" as {role}")
        if role_type:
            parts.append(f" ({role_type})")
        lines.append("".join(parts))
    if not data["cast"]:
        lines.append("  (no cast data found)")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Használat: python tmdb_fetch.py <tmdb_url_vagy_id>")
        print("Példa:     python tmdb_fetch.py https://www.themoviedb.org/tv/12345-sorozat-cime")
        print()
        print("TRANSLATION.local.md készítéséhez: python init_local.py <url>")
        sys.exit(1)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        data = fetch(sys.argv[1])
    except (ValueError, TmdbError) as e:
        print(f"Hiba: {e}")
        sys.exit(1)
    print(format_output(data))


if __name__ == "__main__":
    main()
