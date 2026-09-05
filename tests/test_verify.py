"""A subtr.tasks.verify visszatérő-hiba mintáinak tesztjei.

A `main()` `sys.exit`-tel zár és nyolc blokknyi kimenetet nyomtat, ezért a
tesztek a tiszta `scan_warn_patterns()` függvényt hívják.
"""

import pytest

from subtr import context
from subtr.tasks import verify


def _sections(*texts):
    """Szekciólista a parse_sections alakjában, csak a szöveg számít."""
    return [{"num": str(i), "timestamp": "00:00:01,000 --> 00:00:02,000", "text": t}
            for i, t in enumerate(texts, start=1)]


def _hits(*texts, korean=True):
    return verify.scan_warn_patterns(_sections(*texts), include_korean_names=korean)


def _name_hits(*texts, korean=True):
    """Csak a koreai név-minta találatai."""
    return [h for num, msg, h in _hits(*texts, korean=korean)
            if msg == verify.KOREAN_NAME_MSG]


# --- a koreai név-minta ---------------------------------------------------

def test_valodi_kotojeles_nev_talalat():
    assert _name_hits("Ki-jun, gyere ide!") == ["Ki-jun"]


@pytest.mark.parametrize("text, alak", [
    ("Ah-ra vár rád", "Ah-ra"),          # -ra rag
    ("Joo-nak adtam", "Joo-nak"),        # -nak rag
    ("a York-i divat", "York-i"),        # -i képző
    ("egy Rend-beli tanítvány", "Rend-beli"),  # -beli képző
])
def test_magyar_ragos_alak_nem_talalat(text, alak):
    """A rag/képző utáni alak ragozott magyar szó, nem koreai átírás."""
    assert alak not in _name_hits(text)


def test_rag_utan_allo_betu_nem_szur_ki_nevet():
    """A 'Ki-il' nem eshet ki az 'i' képző miatt: a rag után nem állhat betű."""
    assert _name_hits("Ki-il megérkezett") == ["Ki-il"]


def test_magyar_osszetetel_ismert_korlat():
    """A kötőjeles összetételt a minta ma is találatnak veszi — ez a kapuzás
    létjogosultsága, ezért rögzítjük."""
    assert _name_hits("A Keleti-tengeren túl") == ["Keleti-tengeren"]


# --- a kapuzás ------------------------------------------------------------

def test_nem_koreai_sorozatnal_a_nevminta_nem_fut():
    assert _name_hits("Ki-jun, gyere ide!", korean=False) == []


def test_a_kapuzas_nem_erinti_a_tobbi_mintat():
    """A 9 univerzális minta országtól függetlenül ugyanazt találja."""
    texts = ("Jó munka", "a 3. epizód", "a csapatvezető szólt")
    assert _hits(*texts, korean=True) == _hits(*texts, korean=False)
    assert len(_hits(*texts, korean=False)) == 3


def test_warn_patterns_mar_nem_tartalmazza_a_nevmintat():
    """Szerkezeti invariáns: a WARN_PATTERNS csak univerzális minta lehet."""
    assert len(verify.WARN_PATTERNS) == 9
    assert all("koreai" not in msg for _, msg in verify.WARN_PATTERNS)


def test_talalat_a_szekcioszamot_adja_vissza():
    hits = _hits("semmi", "Ki-jun")
    assert hits == [("2", verify.KOREAN_NAME_MSG, "Ki-jun")]


# --- context.series_country / is_korean_series ----------------------------

def _write_local(tmp_path, monkeypatch, body):
    (tmp_path / context.LOCAL_CONTEXT_FILE).write_text(body, encoding="utf-8")
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize("ertek, orszag, koreai", [
    ("South Korea", "South Korea", True),
    ("  Korea  ", "Korea", True),
    ("China", "China", False),
    ("[Ország]", None, False),        # kitöltetlen sablon
])
def test_series_country_ertekek(tmp_path, monkeypatch, ertek, orszag, koreai):
    _write_local(tmp_path, monkeypatch, f"Title: X\nCountry: {ertek}\nEpisodes: 22\n")
    assert context.series_country() == orszag
    assert context.is_korean_series() is koreai


def test_hianyzo_country_sor(tmp_path, monkeypatch):
    _write_local(tmp_path, monkeypatch, "Title: X\nEpisodes: 22\n")
    assert context.series_country() is None
    assert context.is_korean_series() is False


def test_hianyzo_fajl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert context.series_country() is None
    assert context.is_korean_series() is False


# ── üres szekció: csak akkor hiba, ha a forrás cue-ja nem üres ─────────────

def test_ures_szekcio_csak_nem_ures_forrasnal_hiba():
    orig = [{"num": "1", "timestamp": "t", "text": "Hello"},
            {"num": "2", "timestamp": "t", "text": ""},       # legitim üres cue
            {"num": "3", "timestamp": "t", "text": "Bye"}]
    trans = [{"num": "1", "timestamp": "t", "text": "Szia"},
             {"num": "2", "timestamp": "t", "text": ""},      # a forrás is üres → OK
             {"num": "3", "timestamp": "t", "text": "  "}]    # a forrásban van szöveg → hiba
    hits = verify.find_empty_sections(orig, trans)
    assert [s["num"] for s in hits] == ["3"]


def test_ures_szekcio_ismeretlen_sorszamnal_hiba():
    """Ha a sorszám a forrásban nincs meg (elcsúszott fájl), az üres cue hiba."""
    trans = [{"num": "9", "timestamp": "t", "text": ""}]
    assert verify.find_empty_sections([], trans) == trans
