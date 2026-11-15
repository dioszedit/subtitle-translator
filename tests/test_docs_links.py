"""A dokumentáció belső linkjei: minden relatív link célfájlja és horgonya létezik.

A README és a docs/ fejezetei sok kézi horgony-linket tartalmaznak (a
tartalomjegyzék, a fejezetek közti utalások, az előző/következő sor); egy
átnevezett címsor ezeket csendben eltörné — ez a teszt elkapja.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = sorted(
    [ROOT / "README.md", ROOT / "glossaries" / "README.md", ROOT / "addons" / "README.md"]
    + list((ROOT / "docs").glob("*.md"))
    + list((ROOT / "addons").glob("*/README.md"))
)
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
FENCE_RE = re.compile(r"```.*?```", re.S)


def github_slug(title: str) -> str:
    """A GitHub horgony-képzése: kisbetű, írásjelek ki (a kötőjel marad),
    szóköz → kötőjel; az ékezetes betűk maradnak."""
    t = re.sub(r"`", "", title.strip().lower())
    t = re.sub(r"[^\w\- ]", "", t)
    return t.replace(" ", "-")


def anchors(path: Path) -> set:
    text = FENCE_RE.sub("", path.read_text(encoding="utf-8"))
    return {github_slug(m.group(1)) for m in re.finditer(r"(?m)^#{1,6} (.*)$", text)}


def test_slug_matches_github_rules():
    assert github_slug("Hogyan készült — AI-asszisztált fejlesztés") == \
        "hogyan-készült--ai-asszisztált-fejlesztés"
    assert github_slug("Gemini kvóta — mennyi hívás van még ma? (`subtr.py quota`)") == \
        "gemini-kvóta--mennyi-hívás-van-még-ma-subtrpy-quota"


@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_internal_links_resolve(doc):
    text = FENCE_RE.sub("", doc.read_text(encoding="utf-8"))
    broken = []
    for target in LINK_RE.findall(text):
        if re.match(r"^[a-z]+:", target):          # http:, https:, mailto:
            continue
        path, _, fragment = target.partition("#")
        dest = (doc.parent / path).resolve() if path else doc
        if not dest.exists():
            broken.append(f"nincs ilyen fájl: {target}")
        elif fragment and dest.suffix == ".md" and fragment not in anchors(dest):
            broken.append(f"nincs ilyen horgony: {target}")
    assert not broken, "\n".join(broken)
