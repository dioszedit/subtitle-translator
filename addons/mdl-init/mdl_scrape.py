"""
MyDramaList sorozat-adatlap scraper.

Önállóan nyers kiíratásra használható, de az add-on fő belépési pontja az
`init_local.py`, ami az itt kinyert adatokból TRANSLATION.local.md-t épít.

    python mdl_scrape.py <mydramalist_url>          # nyers dump a képernyőre

Függőségek: cloudscraper, beautifulsoup4
    pip install -e ".[addons]"
"""

import sys
import re
from bs4 import BeautifulSoup


_scraper = None


def _get_scraper():
    """A cloudscraper session lusta példányosítása (import ne menjen hálózatra)."""
    global _scraper
    if _scraper is None:
        import cloudscraper

        _scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
    return _scraper


def fetch_page(url: str) -> BeautifulSoup:
    resp = _get_scraper().get(url, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def extract_title(soup: BeautifulSoup) -> tuple[str, str]:
    title_tag = soup.select_one("h1.film-title a")
    if not title_tag:
        title_tag = soup.select_one("h1.film-title")
    english = title_tag.get_text(strip=True) if title_tag else "N/A"

    native = "N/A"
    # Native Title is in: <li><b class="inline">Native Title:</b> <a ...>title</a></li>
    b_tag = soup.find("b", string=re.compile(r"Native Title"))
    if b_tag:
        parent_li = b_tag.find_parent("li")
        if parent_li:
            a_tag = parent_li.find("a")
            if a_tag:
                native = a_tag.get_text(strip=True)
            else:
                # fallback: text after the <b> tag
                text = parent_li.get_text(strip=True)
                native = re.sub(r"^Native Title\s*:?\s*", "", text).strip()

    return english, native


def extract_detail(soup: BeautifulSoup, label: str) -> str:
    b_tag = soup.find("b", string=re.compile(rf"^{label}\s*:?$", re.IGNORECASE))
    if not b_tag:
        return "N/A"
    parent = b_tag.find_parent("li")
    if parent:
        text = parent.get_text(separator=" ", strip=True)
        text = re.sub(rf"^{label}\s*:?\s*", "", text, flags=re.IGNORECASE)
        return text.strip()
    return "N/A"


def extract_genres(soup: BeautifulSoup) -> str:
    li = soup.select_one("li.show-genres")
    if li:
        links = li.select("a.text-primary")
        return ", ".join(a.get_text(strip=True) for a in links)
    return extract_detail(soup, "Genres")


def extract_tags(soup: BeautifulSoup) -> str:
    li = soup.select_one("li.show-tags")
    if li:
        links = li.select("a.text-primary")
        return ", ".join(a.get_text(strip=True) for a in links)
    return extract_detail(soup, "Tags")


def extract_synopsis(soup: BeautifulSoup) -> str:
    synopsis_div = soup.select_one(".show-synopsis")
    if not synopsis_div:
        return "N/A"

    # Remove the language list and edit link
    for el in synopsis_div.select("ul.mdl-synopsis-languages, a"):
        el.decompose()

    # Get text from the first/outermost span (it contains the full synopsis)
    span = synopsis_div.select_one("span")
    if span:
        text = span.get_text(strip=True)
    else:
        text = synopsis_div.get_text(strip=True)

    text = re.sub(r"Edit\s*Translation\s*", "", text).strip()
    return text


def extract_cast(soup: BeautifulSoup) -> list[tuple[str, str, str]]:
    cast = []
    for item in soup.select("li.list-item.col-sm-4"):
        # Actor name: <a class="text-primary text-ellipsis"><b>Name</b></a>
        actor_tag = item.select_one("a.text-primary.text-ellipsis b")
        if not actor_tag:
            continue
        actor_name = actor_tag.get_text(strip=True)

        # Role name: <div class="text-ellipsis"><small title="Role">Role</small></div>
        role_small = item.select_one("div.text-ellipsis small")
        role_name = role_small.get_text(strip=True) if role_small else ""

        # Role type: <small class="text-muted">Main Role</small>
        role_type_tag = item.select_one("small.text-muted")
        role_type = role_type_tag.get_text(strip=True) if role_type_tag else ""

        cast.append((actor_name, role_name, role_type))

    return cast


def scrape(url: str) -> dict:
    soup = fetch_page(url)

    english_title, native_title = extract_title(soup)

    return {
        "title": english_title,
        "native_title": native_title,
        "country": extract_detail(soup, "Country"),
        "type": extract_detail(soup, "Type"),
        "episodes": extract_detail(soup, "Episodes"),
        "aired": extract_detail(soup, "Aired"),
        "duration": extract_detail(soup, "Duration"),
        "network": extract_detail(soup, "Original Network"),
        "content_rating": extract_detail(soup, "Content Rating"),
        "score": extract_detail(soup, "Score"),
        "genres": extract_genres(soup),
        "tags": extract_tags(soup),
        "synopsis": extract_synopsis(soup),
        "cast": extract_cast(soup),
    }


def format_output(data: dict) -> str:
    lines = []
    lines.append(f"Title: {data['title']} ({data['native_title']})")
    lines.append(f"Country: {data['country']}")
    lines.append(f"Episodes: {data['episodes']}")
    lines.append(f"Duration: {data['duration']}")
    lines.append(f"Genres: {data['genres']}")
    lines.append(f"Tags: {data['tags']}")
    lines.append("")
    lines.append("Synopsis:")
    lines.append(data["synopsis"])
    lines.append("")
    lines.append("Cast:")
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
        print("Használat: python mdl_scrape.py <mydramalist_url>")
        print("Példa:     python mdl_scrape.py https://mydramalist.com/70241-ni-ye-you-jin-tian")
        print()
        print("TRANSLATION.local.md készítéséhez: python init_local.py <url>")
        sys.exit(1)

    url = sys.argv[1]
    if "mydramalist.com" not in url:
        print("Hiba: érvényes mydramalist.com URL kell.")
        sys.exit(1)

    try:
        data = scrape(url)
    except Exception as e:
        print(f"Hiba: {e}")
        sys.exit(1)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(format_output(data))


if __name__ == "__main__":
    main()
