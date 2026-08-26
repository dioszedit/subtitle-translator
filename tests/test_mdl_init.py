"""addons/mdl-init — a TRANSLATION.local.md összeállítása (hálózat nélkül)."""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("bs4", reason="az mdl-init add-on külön függősége: pip install -e '.[addons]'")

ADDON_DIR = Path(__file__).resolve().parent.parent / "addons" / "mdl-init"
sys.path.insert(0, str(ADDON_DIR))

_spec = importlib.util.spec_from_file_location("mdl_init_local", ADDON_DIR / "init_local.py")
init_local = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_local)

import mdl_scrape  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402


SAMPLE = {
    "title": "My Boss (2024)",
    "native_title": "你也有今天",
    "country": "China",
    "episodes": "36",
    "duration": "45 min.",
    "genres": "Comedy, Law, Romance",
    "tags": "Lawyer Male Lead, Cohabitation",
    "synopsis": "Első bekezdés.\n\nMásodik bekezdés.\n\n(Source: Viki)\n\n~~ Adapted from a novel.",
    "cast": [
        ("Chen Xiao Yun", "Cheng Xi", "Support Role"),
        ("Chen Xing Xu", "Qian Heng", "Main Role"),
        ("Zhang Ruo Nan", "Cheng Yao", "Main Role"),
        ("Vendég Elek", "Futár", "Guest Role"),
    ],
}


def _build(**kwargs):
    opts = dict(hu_title="TODO: magyar cím", url="https://mydramalist.com/1-x",
                max_cast=12, include_guests=False)
    opts.update(kwargs)
    return init_local.build_document(SAMPLE, opts["hu_title"], opts["url"],
                                     opts["max_cast"], opts["include_guests"])


def test_fejlec_a_translation_md_sablonjat_koveti():
    doc = _build()
    assert doc.startswith("Title: My Boss (2024) (你也有今天)\n")
    assert "Hungarian title: TODO: magyar cím" in doc
    assert "Country: China" in doc
    assert "Episodes: 36" in doc


def test_hu_cim_atveve():
    assert "Hungarian title: A főnököm" in _build(hu_title="A főnököm")


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
    assert "TODO: Qian Heng → Cheng Yao: MAGÁZ | TEGEZ" in regiszter
    assert "alapértelmezés idegenekkel: MAGÁZ" in regiszter


def test_szinopszis_read_more_hataran_nem_vesz_el_a_szokoz():
    """A MyDramaList a "read more" határán <span>-t nyit — a szegmensenkénti
    strip elnyelné a határon álló szóközt ("...superiorat the office")."""
    html = """
    <div class="show-synopsis">
      <span>Első bekezdés vége itt.

Qian Heng turns out to be her direct superior<span class="read-more-hidden"> at
the office, and he is hard to please.</span></span>
    </div>
    """
    text = mdl_scrape.extract_synopsis(BeautifulSoup(html, "html.parser"))
    assert "direct superior at the office" in text
    assert "superiorat" not in text
    assert "\n\n" in text, "a bekezdéshatárnak meg kell maradnia"


def test_ures_cast_eseten_todo():
    adat = dict(SAMPLE, cast=[])
    doc = init_local.build_document(adat, "x", "u", 12, False)
    assert "TODO: szereplők" in doc


# ────────────────────────────────────────────────────────────────────────────
# Glossary-magok: a sorozat- és forrásmű-címek felvétele
# ────────────────────────────────────────────────────────────────────────────

ADAPTED_NOTE = (
    'Egy sima szinopszis. (Source: MyDramaList) ~~ Adapted from the web novel '
    '"Zao Chun Qing Lang" (早春晴朗) by Gu Niang Bie Ku (姑娘别哭).'
)


@pytest.mark.parametrize("text,expected", [
    (ADAPTED_NOTE, {"work": "Zao Chun Qing Lang", "native": "早春晴朗",
                    "author": "Gu Niang Bie Ku"}),
    ('~~ Adapted from the novel "Spring Breeze" by Someone.',
     {"work": "Spring Breeze", "author": "Someone"}),
    ('~~ Adapted from the web novel "No Author Here".', {"work": "No Author Here"}),
    ("Semmi adaptációs lábjegyzet.", {}),
    ("", {}),
])
def test_adaptacios_labjegyzet_kiolvasasa(text, expected):
    assert init_local.parse_adapted_from(text) == expected


def _seed(title="The Early Spring", native="早春晴朗", synopsis=ADAPTED_NOTE,
          hu="Derűs kora tavasz"):
    return init_local.build_glossary_seed(
        {"title": title, "native_title": native, "synopsis": synopsis}, hu)


def test_seed_felveszi_a_sorozat_es_forrasmu_cimet():
    ens = [e["en"] for e in _seed()]
    assert ens == ["The Early Spring", "早春晴朗", "Zao Chun Qing Lang"]
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
    assert "Derűs kora tavasz" in series["context"]


def test_seed_todo_magyar_cimet_nem_hivatkozza():
    assert "TODO" not in _seed(hu="TODO: magyar cím")[0]["context"]
    assert "TODO" not in _seed(hu="")[0]["context"]


def test_seed_kihagyja_az_na_es_ures_cimeket():
    assert [e["en"] for e in _seed(native="N/A", synopsis="")] == ["The Early Spring"]
    assert [e["en"] for e in _seed(native="", synopsis="")] == ["The Early Spring"]


def test_seed_nem_vesz_fel_szereploneveket():
    """A MyDramaList írásmódja gyakran eltér a feliratétól (»Shang Zhi Tao« vs.
    »Shang Zhitao«) — rossz alak egy kötelező szójegyzékben rosszabb a hiánynál."""
    entries = init_local.build_glossary_seed(
        {"title": "X", "native_title": "", "synopsis": "",
         "cast": [("Sun Qian", "Shang Zhi Tao", "Main Role")]}, "")
    assert all("Shang" not in e["en"] for e in entries)


def test_write_seed_uj_fajlt_hoz_letre_sema_szerint(tmp_path):
    p = tmp_path / "glossary.json"
    added = init_local.write_glossary_seed(_seed(), p)
    assert [e["en"] for e in added] == ["The Early Spring", "早春晴朗", "Zao Chun Qing Lang"]
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
        "special_terms": [{"en": "The Early Spring", "hu": "KÉZI ALAK", "context": "ne írd felül"}],
        "character_names": [{"en": "Luke", "hu": "Luke", "context": ""}],
    }, ensure_ascii=False), encoding="utf-8")

    added = init_local.write_glossary_seed(_seed(), p)
    assert "The Early Spring" not in [e["en"] for e in added], "meglévő en-t nem írunk felül"

    data = json.loads(p.read_text(encoding="utf-8"))
    kept = [e for e in data["special_terms"] if e["en"] == "The Early Spring"]
    assert kept[0]["hu"] == "KÉZI ALAK"
    assert len(data["character_names"]) == 1
    assert (tmp_path / "glossary.json.bak").exists()


def test_write_seed_nem_ir_bak_ot_ha_nincs_uj(tmp_path):
    p = tmp_path / "glossary.json"
    init_local.write_glossary_seed(_seed(), p)
    (tmp_path / "glossary.json.bak").unlink(missing_ok=True)
    init_local.write_glossary_seed(_seed(), p)
    assert not (tmp_path / "glossary.json.bak").exists()
