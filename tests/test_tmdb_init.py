"""addons/tmdb-init — a TRANSLATION.local.md összeállítása a TMDB API-ból (hálózat nélkül)."""

import importlib.util
import json
import sys
from pathlib import Path

import io
import urllib.error

import pytest

ADDON_DIR = Path(__file__).resolve().parent.parent / "addons" / "tmdb-init"
sys.path.insert(0, str(ADDON_DIR))

_spec = importlib.util.spec_from_file_location("tmdb_init_local", ADDON_DIR / "init_local.py")
init_local = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_local)

import tmdb_fetch  # noqa: E402


SAMPLE = {
    "title": "Office Sparks (2024)",
    "native_title": "职场火花",
    "country": "China",
    "episodes": "36",
    "duration": "45 min.",
    "genres": "Comedy, Business, Romance",
    "tags": "Boss Male Lead, Office Setting",
    "synopsis": "Első bekezdés.\n\nMásodik bekezdés.\n\n(Source: Viki)\n\n~~ Adapted from a novel.",
    "cast": [
        ("Lin Xiao He", "Su Wan", "Support Role"),
        ("Wang Zi Hao", "Lu Yan", "Main Role"),
        ("Zhao Mei Lin", "Shen Qing", "Main Role"),
        ("Vendég Elek", "Futár", "Guest Role"),
    ],
}


def _build(**kwargs):
    opts = dict(hu_title="TODO: magyar cím", url="https://www.themoviedb.org/tv/1-x",
                max_cast=12, include_guests=False)
    opts.update(kwargs)
    return init_local.build_document(SAMPLE, opts["hu_title"], opts["url"],
                                     opts["max_cast"], opts["include_guests"])


def _mock_fetch(monkeypatch, data):
    """A CLI-út hálózat nélkül: a fetch_series/map_series páros helyett kész dict."""
    monkeypatch.setattr(init_local, "fetch_series", lambda tmdb_id: {"id": tmdb_id})
    monkeypatch.setattr(init_local, "map_series", lambda payload, main_limit: dict(data))


def test_fejlec_a_translation_md_sablonjat_koveti():
    doc = _build()
    assert doc.startswith("Title: Office Sparks (2024) (职场火花)\n")
    assert "Hungarian title: TODO: magyar cím" in doc
    assert "Country: China" in doc
    assert "Episodes: 36" in doc


def test_hu_cim_atveve():
    assert "Hungarian title: Irodai szikrák" in _build(hu_title="Irodai szikrák")


def test_szinopszis_forrasjegyzet_nelkul():
    doc = _build()
    assert "Első bekezdés.\n\nMásodik bekezdés." in doc
    assert "Source: Viki" not in doc
    assert "Adapted from" not in doc


def test_foszereplok_elore_kerulnek_vendeg_kimarad():
    doc = _build()
    cast_block = doc.split("Cast:")[1].split("Megszólítási regiszter")[0]
    sorok = [s for s in cast_block.splitlines() if s.startswith("- ")]
    assert sorok[0].endswith("(Main Role)")
    assert sorok[1].endswith("(Main Role)")
    assert "Futár" not in cast_block


def test_vendegszereplo_kapcsoloval_bekerul():
    assert "Futár" in _build(include_guests=True)


def test_max_cast_vagja_a_listat():
    doc = _build(max_cast=2)
    sorok = [s for s in doc.splitlines() if s.startswith("- ")]
    assert len(sorok) == 2


def test_regiszter_nem_talal_ki_viszonyt():
    """A főszereplőkből csak vázat ír — konkrét MAGÁZ/TEGEZ döntést nem hoz."""
    doc = _build()
    regiszter = doc.split("Megszólítási regiszter")[1]
    assert "TODO: Lu Yan → Shen Qing: MAGÁZ | TEGEZ" in regiszter
    assert "alapértelmezés idegenekkel: MAGÁZ" in regiszter



def test_ures_cast_eseten_todo():
    adat = dict(SAMPLE, cast=[])
    doc = init_local.build_document(adat, "x", "u", 12, False)
    assert "TODO: szereplők" in doc


# ────────────────────────────────────────────────────────────────────────────
# Glossary-magok: a sorozat- és forrásmű-címek felvétele
# ────────────────────────────────────────────────────────────────────────────

ADAPTED_NOTE = (
    'Egy sima szinopszis. (Source: Viki) ~~ Adapted from the web novel '
    '"Jing Gang Ye Hua" (静港夜话) by Bai Yun Ke (白云客).'
)


@pytest.mark.parametrize("text,expected", [
    (ADAPTED_NOTE, {"work": "Jing Gang Ye Hua", "native": "静港夜话",
                    "author": "Bai Yun Ke"}),
    ('~~ Adapted from the novel "Spring Breeze" by Someone.',
     {"work": "Spring Breeze", "author": "Someone"}),
    ('~~ Adapted from the web novel "No Author Here".', {"work": "No Author Here"}),
    ("Semmi adaptációs lábjegyzet.", {}),
    ("", {}),
])
def test_adaptacios_labjegyzet_kiolvasasa(text, expected):
    assert init_local.parse_adapted_from(text) == expected


def _seed(title="The Quiet Harbor", native="静港夜话", synopsis=ADAPTED_NOTE,
          hu="A csendes kikötő"):
    return init_local.build_glossary_seed(
        {"title": title, "native_title": native, "synopsis": synopsis}, hu)


def test_seed_felveszi_a_sorozat_es_forrasmu_cimet():
    ens = [e["en"] for e in _seed()]
    assert ens == ["The Quiet Harbor", "静港夜话", "Jing Gang Ye Hua"]
    # a forrásmű natív címe itt AZONOS a sorozatéval — ne kerüljön be kétszer
    assert len(ens) == len(set(ens))


def test_seed_en_es_hu_azonos_es_special_term():
    for e in _seed():
        assert e["en"] == e["hu"], "a címet nem fordítjuk"
        assert e["category"] == "special_terms"


def test_seed_context_kimondja_a_cimkartya_kivetelt():
    """A glossary a fordítónak KÖTELEZŐ, ezért ha csak annyi állna benne, hogy
    a címet nem fordítjuk, a modell a sorozatcím-kártyáról is lehagyná a magyar
    címet. A context ezért nevezi meg a kivételt."""
    series = _seed()[0]
    assert "Címkártya" in series["context"]
    assert "A csendes kikötő" in series["context"]


def test_seed_todo_magyar_cimet_nem_hivatkozza():
    assert "TODO" not in _seed(hu="TODO: magyar cím")[0]["context"]
    assert "TODO" not in _seed(hu="")[0]["context"]


def test_seed_kihagyja_az_na_es_ures_cimeket():
    assert [e["en"] for e in _seed(native="N/A", synopsis="")] == ["The Quiet Harbor"]
    assert [e["en"] for e in _seed(native="", synopsis="")] == ["The Quiet Harbor"]


def test_seed_nem_vesz_fel_szereploneveket():
    """A TMDB írásmódja gyakran eltér a feliratétól (»Lin Wan Er« vs.
    »Lin Waner«) — rossz alak egy kötelező szójegyzékben rosszabb a hiánynál."""
    entries = init_local.build_glossary_seed(
        {"title": "X", "native_title": "", "synopsis": "",
         "cast": [("Zhou Yu Tong", "Lin Wan Er", "Main Role")]}, "")
    assert all("Shang" not in e["en"] for e in entries)


def test_write_seed_uj_fajlt_hoz_letre_sema_szerint(tmp_path):
    p = tmp_path / "glossary.json"
    added = init_local.write_glossary_seed(_seed(), p)
    assert [e["en"] for e in added] == ["The Quiet Harbor", "静港夜话", "Jing Gang Ye Hua"]
    import json
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "meta" in data
    for cat in init_local.CATEGORIES:
        assert cat in data
    assert len(data["special_terms"]) == 3


def test_write_seed_idempotens_es_nem_ir_felul(tmp_path):
    p = tmp_path / "glossary.json"
    init_local.write_glossary_seed(_seed(), p)
    assert init_local.write_glossary_seed(_seed(), p) == []


def test_write_seed_megorzi_a_meglevo_bejegyzeseket_es_bak_ot_ir(tmp_path):
    import json
    p = tmp_path / "glossary.json"
    p.write_text(json.dumps({
        "meta": {"series": "X"},
        "special_terms": [{"en": "The Quiet Harbor", "hu": "KÉZI ALAK", "context": "ne írd felül"}],
        "character_names": [{"en": "Luke", "hu": "Luke", "context": ""}],
    }, ensure_ascii=False), encoding="utf-8")

    added = init_local.write_glossary_seed(_seed(), p)
    assert "The Quiet Harbor" not in [e["en"] for e in added], "meglévő en-t nem írunk felül"

    data = json.loads(p.read_text(encoding="utf-8"))
    kept = [e for e in data["special_terms"] if e["en"] == "The Quiet Harbor"]
    assert kept[0]["hu"] == "KÉZI ALAK"
    assert len(data["character_names"]) == 1
    assert (tmp_path / "glossary.json.bak").exists()


def test_write_seed_nem_ir_bak_ot_ha_nincs_uj(tmp_path):
    p = tmp_path / "glossary.json"
    init_local.write_glossary_seed(_seed(), p)
    (tmp_path / "glossary.json.bak").unlink(missing_ok=True)
    init_local.write_glossary_seed(_seed(), p)
    assert not (tmp_path / "glossary.json.bak").exists()


def test_glossary_only_nem_nyul_a_local_md_hez(tmp_path, monkeypatch, capsys):
    """Már futó sorozatnál a TRANSLATION.local.md kézzel hangolt (regiszter,
    special terms) — a címfelvétel nem írhatja felül, és a hiánya miatt sem
    állhat le."""
    local = tmp_path / "TRANSLATION.local.md"
    local.write_text("KÉZZEL HANGOLT TARTALOM\n", encoding="utf-8")
    gloss = tmp_path / "glossary.json"

    _mock_fetch(monkeypatch, {
        "title": "The Quiet Harbor", "native_title": "静港夜话",
        "synopsis": ADAPTED_NOTE, "cast": [],
        "country": "China", "episodes": "24", "duration": "45 min.",
        "genres": "Romance", "tags": "", "hu_title": "",
    })
    monkeypatch.setattr(sys, "argv", [
        "init_local.py", "https://www.themoviedb.org/tv/1-x", "--glossary-only",
        "--out", str(local), "--glossary", str(gloss)])
    init_local.main()

    assert local.read_text(encoding="utf-8") == "KÉZZEL HANGOLT TARTALOM\n"
    assert not (tmp_path / "TRANSLATION.local.md.bak").exists()
    import json
    assert len(json.loads(gloss.read_text(encoding="utf-8"))["special_terms"]) == 3
    assert "érintetlen" in capsys.readouterr().out


@pytest.mark.parametrize("raw,expected", [
    ("Office Sparks (2024)", "Office Sparks"),
    ("Silent Keeper (2026)", "Silent Keeper"),
    ("Let’s Not Argue! (2026)", "Let’s Not Argue!"),
    ("The Quiet Harbor", "The Quiet Harbor"),          # nincs mit levágni
    ("Reply 1988", "Reply 1988"),                      # évszám, de nem zárójelben
    ("Something (Special)", "Something (Special)"),    # zárójel, de nem évszám
    ("", ""),
])
def test_evszam_toldalek_levagasa(raw, expected):
    """A TMDB oldalcíme az évszámot is viseli, a felirat sosem —
    évszámmal a szójegyzék-bejegyzés soha nem illeszkedne."""
    assert init_local.strip_year(raw) == expected


def test_seed_evszam_nelkuli_cimet_vesz_fel():
    ens = [e["en"] for e in init_local.build_glossary_seed(
        {"title": "Office Sparks (2024)", "native_title": "职场火花", "synopsis": ""}, "Irodai szikrák")]
    assert ens == ["Office Sparks", "职场火花"]


def test_kimenetek_cwd_relativak(tmp_path, monkeypatch):
    """Minden sorozatnak SAJÁT másolata van a repóból. Ha a célfájlokat a script
    helyéből számolnánk, egy másik mappából hívott példány csendben a MÁSIK
    sorozat glossary.json-jába írna — ez egyszer meg is történt."""
    assert not init_local.DEFAULT_OUT.is_absolute()
    assert not init_local.DEFAULT_GLOSSARY.is_absolute()

    monkeypatch.chdir(tmp_path)
    _mock_fetch(monkeypatch, {
        "title": "X (2026)", "native_title": "", "synopsis": "", "cast": [],
        "country": "", "episodes": "", "duration": "", "genres": "", "tags": "",
        "hu_title": "",
    })
    monkeypatch.setattr(sys, "argv", ["init_local.py", "https://www.themoviedb.org/tv/1-x",
                                      "--glossary-only"])
    init_local.main()
    # a MUNKAKÖNYVTÁRBA írt, nem a script repójába
    assert (tmp_path / "glossary.json").is_file()


# ── parse_adapted_from: a törzsben álló "adapted from" ne adjon hamis címet ──

def test_adapted_from_a_torzsben_nem_ad_hamis_cimet():
    text = ('Body text adapted from real events. He said "hello" to her.\n\n'
            '~~ Adapted from the web novel "Real Work" by Author.')
    assert init_local.parse_adapted_from(text) == {"work": "Real Work", "author": "Author"}
    # csak törzsbeli, mondathatáron átfutó találat: nincs cím
    assert init_local.parse_adapted_from(
        'Adapted from real events. He said "hello" to her.') == {}


def test_szerzonev_ponttal():
    assert init_local.parse_adapted_from('~~ Adapted from the novel "Book" by J.K. Rowling.') \
        == {"work": "Book", "author": "J.K. Rowling"}


# ── write_glossary_seed: sérült/BOM-os fájl, meta.series ──

def test_serult_glossary_json_hibauzenet_nem_traceback(tmp_path):
    path = tmp_path / "glossary.json"
    path.write_text("{ broken", encoding="utf-8")
    with pytest.raises(init_local.GlossaryError):
        init_local.write_glossary_seed(
            [{"en": "X", "hu": "X", "category": "special_terms", "context": ""}], path)
    assert path.read_text(encoding="utf-8") == "{ broken"   # nem nyúlt hozzá


def test_bom_os_es_null_en_glossary_json(tmp_path):
    path = tmp_path / "glossary.json"
    path.write_text('﻿{"meta": {}, "special_terms": [{"en": null, "hu": "x"}]}',
                    encoding="utf-8")
    added = init_local.write_glossary_seed(
        [{"en": "X", "hu": "X", "category": "special_terms", "context": ""}], path)
    assert [e["en"] for e in added] == ["X"]


def test_uj_glossary_meta_series(tmp_path):
    path = tmp_path / "glossary.json"
    init_local.write_glossary_seed(
        [{"en": "X", "hu": "X", "category": "special_terms", "context": ""}], path,
        series="Office Sparks")
    assert json.loads(path.read_text(encoding="utf-8"))["meta"]["series"] == "Office Sparks"


def test_clean_synopsis_inline_labjegyzet_is_kiesik():
    """A lábjegyzet nem mindig áll külön sorban — a bekezdésen belüli
    "~~ ..." farok és "(Source: ...)" is menjen."""
    assert init_local.clean_synopsis(
        'Egy sima szinopszis. (Source: Viki) ~~ Adapted from the novel "X".'
    ) == "Egy sima szinopszis."
    assert init_local.clean_synopsis(
        'Első bekezdés.\nMásodik vége. ~~ Adapted from "Y".'
    ) == "Első bekezdés.\n\nMásodik vége."
    # ha csak lábjegyzet volt, TODO marad
    assert init_local.clean_synopsis('~~ Adapted from "Z".') == "TODO: szinopszis"


# ────────────────────────────────────────────────────────────────────────────
# tmdb_fetch: link → id, JSON → dict, szerep-besorolás, hibák
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("https://www.themoviedb.org/tv/236033-the-double", 236033),
    ("https://www.themoviedb.org/tv/236033", 236033),
    ("https://www.themoviedb.org/tv/236033-the-double?language=hu-HU#cast", 236033),
    ("themoviedb.org/tv/94796-crash-landing-on-you/season/1", 94796),
    ("  94796 ", 94796),
])
def test_parse_tmdb_url(text, expected):
    assert tmdb_fetch.parse_tmdb_url(text) == expected


@pytest.mark.parametrize("text,uzenet", [
    ("https://www.themoviedb.org/movie/550-fight-club", "film-link"),
    ("https://example.com/valami", "nem TMDB sorozat-link"),
    ("", "nem TMDB sorozat-link"),
])
def test_parse_tmdb_url_hibas_link(text, uzenet):
    with pytest.raises(ValueError, match=uzenet):
        tmdb_fetch.parse_tmdb_url(text)


# Kitalált sorozat — a TMDB válaszának ALAKJÁT követi, nem valódi adat.
PAYLOAD = {
    "id": 4242,
    "name": "Office Sparks",
    "original_name": "职场火花",
    "first_air_date": "2024-03-01",
    "origin_country": ["CN"],
    "number_of_episodes": 36,
    "episode_run_time": [],
    "last_episode_to_air": {"runtime": 45},
    "genres": [{"id": 35, "name": "Comedy"}, {"id": 10749, "name": "Romance"}],
    "overview": "Első bekezdés.\n\nMásodik bekezdés.",
    "keywords": {"results": [{"id": 1, "name": "office"}, {"id": 2, "name": "boss"}]},
    "aggregate_credits": {"cast": [
        {"name": "Zhao Mei Lin", "order": 1, "total_episode_count": 36,
         "roles": [{"character": "Shen Qing", "episode_count": 36}]},
        {"name": "Wang Zi Hao", "order": 0, "total_episode_count": 36,
         "roles": [{"character": "Lu Yan", "episode_count": 36}]},
        {"name": "Lin Xiao He", "order": 5, "total_episode_count": 30,
         "roles": [{"character": "Su Wan", "episode_count": 30}]},
        {"name": "Vendég Elek", "order": 9, "total_episode_count": 2,
         "roles": [{"character": "Futár", "episode_count": 2}]},
    ]},
    "translations": {"translations": [
        {"iso_639_1": "en", "iso_3166_1": "US", "data": {"name": "Office Sparks"}},
        {"iso_639_1": "hu", "iso_3166_1": "HU", "data": {"name": "Irodai szikrák"}},
    ]},
}


def test_map_series_fejlec_mezok():
    d = tmdb_fetch.map_series(PAYLOAD)
    assert d["title"] == "Office Sparks (2024)"        # évszám, mint az oldalcímben
    assert d["native_title"] == "职场火花"
    assert d["country"] == "China"                     # ISO-kód → név
    assert d["episodes"] == "36"
    assert d["genres"] == "Comedy, Romance"
    assert d["tags"] == "office, boss"                 # keywords → tags
    assert d["synopsis"] == "Első bekezdés.\n\nMásodik bekezdés."
    assert d["hu_title"] == "Irodai szikrák"
    assert d["tmdb_id"] == 4242


def test_map_series_duration_fallback_lanc():
    assert tmdb_fetch.map_series(PAYLOAD)["duration"] == "45 min."   # last_episode_to_air
    assert tmdb_fetch.map_series(dict(PAYLOAD, episode_run_time=[60]))["duration"] == "60 min."
    assert tmdb_fetch.map_series(dict(PAYLOAD, last_episode_to_air=None))["duration"] == "N/A"


def test_map_series_cast_sorrend_es_cimkek():
    cast = tmdb_fetch.map_series(PAYLOAD)["cast"]
    assert cast == [
        ("Wang Zi Hao", "Lu Yan", "Main Role"),        # order 0 — a TMDB sorrendje nyer
        ("Zhao Mei Lin", "Shen Qing", "Main Role"),
        ("Lin Xiao He", "Su Wan", "Support Role"),     # order 5 > main_limit
        ("Vendég Elek", "Futár", "Guest Role"),        # 2 epizód
    ]
    # ugyanazok a címkék, amiket a dokumentum-építő vár
    doc = init_local.build_document(tmdb_fetch.map_series(PAYLOAD), "x", "u", 12, False)
    assert "TODO: Lu Yan → Shen Qing: MAGÁZ | TEGEZ" in doc
    assert "Futár" not in doc


def test_map_series_main_limit_allithato():
    cast = tmdb_fetch.map_series(PAYLOAD, main_limit=6)["cast"]
    assert cast[2] == ("Lin Xiao He", "Su Wan", "Main Role")


def test_map_series_hianyzo_mezok_nem_dobnak():
    d = tmdb_fetch.map_series({"name": "Csupasz"})
    assert d["title"] == "Csupasz"                     # nincs évszám → nincs zárójel
    assert d["native_title"] == "N/A"
    assert d["country"] == "N/A"
    assert d["episodes"] == "N/A"
    assert d["duration"] == "N/A"
    assert d["cast"] == []
    assert d["hu_title"] == ""
    assert init_local.clean_synopsis(d["synopsis"]) == "TODO: szinopszis"


def test_map_series_ismeretlen_orszagkod_marad():
    assert tmdb_fetch.map_series(dict(PAYLOAD, origin_country=["KR", "XX"]))["country"] \
        == "South Korea, XX"


@pytest.mark.parametrize("order,total,n,expected", [
    (0, 36, 36, "Main Role"),
    (3, 27, 36, "Main Role"),        # pont 75 %
    (3, 26, 36, "Support Role"),     # 75 % alatt: cameo a lista elején sem fő
    (4, 36, 36, "Support Role"),     # a main_limit (4) fölött
    (0, 4, 36, "Support Role"),      # a vendég-határ (36 // 10 = 3) fölött
    (0, 3, 36, "Guest Role"),        # pont a határon
    (0, 2, 36, "Guest Role"),
    (0, 10, 100, "Guest Role"),      # 10 % → vendég
    (0, 0, 36, "Guest Role"),        # ismeretlen epizódszám a szereplőnél
    (0, 5, 0, "Main Role"),          # a sorozat epizódszáma ismeretlen: a sorrend dönt
])
def test_classify_role(order, total, n, expected):
    assert tmdb_fetch.classify_role(order, total, n) == expected


def test_api_key_hianya_erthetoen_hibazik(monkeypatch):
    monkeypatch.setattr(tmdb_fetch, "_load_dotenv", lambda: None)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    with pytest.raises(tmdb_fetch.TmdbError, match="settings/api"):
        tmdb_fetch.api_key()


def _http_error(code, body=b'{"status_message": "x"}'):
    return urllib.error.HTTPError("https://api.themoviedb.org/3/tv/1", code, "err",
                                  {}, io.BytesIO(body))


@pytest.mark.parametrize("code,uzenet", [
    (401, "érvénytelen TMDB_API_KEY"),
    (404, "nincs ilyen sorozat"),
    (500, "TMDB HTTP 500"),
])
def test_fetch_json_http_hibak(monkeypatch, code, uzenet):
    monkeypatch.setattr(tmdb_fetch, "_load_dotenv", lambda: None)
    monkeypatch.setenv("TMDB_API_KEY", "teszt")

    def fake_urlopen(req, timeout=0, context=None):
        raise _http_error(code)
    monkeypatch.setattr(tmdb_fetch.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(tmdb_fetch.TmdbError, match=uzenet):
        tmdb_fetch.fetch_json("/tv/1")


def test_fetch_json_a_kulcsot_es_a_parametereket_kuldi(monkeypatch):
    monkeypatch.setattr(tmdb_fetch, "_load_dotenv", lambda: None)
    monkeypatch.setenv("TMDB_API_KEY", "teszt")
    latott = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0, context=None):
        latott["url"] = req.full_url
        return Resp(b'{"id": 1}')
    monkeypatch.setattr(tmdb_fetch.urllib.request, "urlopen", fake_urlopen)
    assert tmdb_fetch.fetch_series(1) == {"id": 1}
    assert latott["url"].startswith("https://api.themoviedb.org/3/tv/1?")
    assert "api_key=teszt" in latott["url"]
    assert "aggregate_credits" in latott["url"]


# ── CLI-út: a magyar cím forrása ──

def test_cli_magyar_cim_a_tmdb_rol(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _mock_fetch(monkeypatch, dict(tmdb_fetch.map_series(PAYLOAD)))
    monkeypatch.setattr(sys, "argv", ["init_local.py", "4242", "--stdout"])
    init_local.main()
    out = capsys.readouterr().out
    assert "Hungarian title: Irodai szikrák" in out
    assert "Magyar cím a TMDB-ről" in out
    assert "Lekérés: TMDB tv/4242" in out


def test_cli_hu_title_kapcsolo_felulirja(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _mock_fetch(monkeypatch, dict(tmdb_fetch.map_series(PAYLOAD)))
    monkeypatch.setattr(sys, "argv", ["init_local.py", "4242", "--stdout",
                                      "--hu-title", "Kézi cím"])
    init_local.main()
    out = capsys.readouterr().out
    assert "Hungarian title: Kézi cím" in out
    assert "Magyar cím a TMDB-ről" not in out


def test_cli_film_link_parser_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["init_local.py",
                                      "https://www.themoviedb.org/movie/550-x", "--stdout"])
    with pytest.raises(SystemExit):
        init_local.main()
    assert "film-link" in capsys.readouterr().err


def test_cli_tmdb_hiba_nem_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def boom(tmdb_id):
        raise tmdb_fetch.TmdbError("nincs ilyen sorozat a TMDB-n (HTTP 404): /tv/1")
    monkeypatch.setattr(init_local, "fetch_series", boom)
    monkeypatch.setattr(sys, "argv", ["init_local.py", "1", "--stdout"])
    with pytest.raises(SystemExit):
        init_local.main()
    assert "HIBA a lekérésnél: nincs ilyen sorozat" in capsys.readouterr().out


def test_main_cast_kapcsolo_atmegy(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    latott = {}
    monkeypatch.setattr(init_local, "fetch_series", lambda i: PAYLOAD)

    def spy(payload, main_limit):
        latott["main_limit"] = main_limit
        return tmdb_fetch.map_series(payload, main_limit)
    monkeypatch.setattr(init_local, "map_series", spy)
    monkeypatch.setattr(sys, "argv", ["init_local.py", "4242", "--stdout", "--main-cast", "6"])
    init_local.main()
    assert latott["main_limit"] == 6
    assert "- Lin Xiao He as Su Wan (Main Role)" in capsys.readouterr().out
