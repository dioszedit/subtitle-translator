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


def test_ures_cast_eseten_todo():
    adat = dict(SAMPLE, cast=[])
    doc = init_local.build_document(adat, "x", "u", 12, False)
    assert "TODO: szereplők" in doc
