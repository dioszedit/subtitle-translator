"""A szójegyzék-kinyerés promptépítői és a biztos/bizonytalan besorolás.

A promptépítők tiszta függvények — provider nélkül assertelhetők, ahogy a
tests/test_source_lang_pipeline.py teszi a fordító/regiszter promptjaival.
"""

import json

import pytest

from subtr.tasks import glossary_extract as ge


# ── count_occurrences ───────────────────────────────────────────────────────

SRT = """1
00:00:01,000 --> 00:00:03,000
Welcome to the Ascendance Sect.

2
00:00:04,000 --> 00:00:06,000
The Ascendance
Sect is our home.

3
00:00:07,000 --> 00:00:09,000
A sectarian dispute, nothing more.
"""


def test_count_occurrences_szohataron_all():
    # 2 találat, a "sectarian" NEM számít bele
    assert ge.count_occurrences("Sect", SRT) == 2


def test_count_occurrences_kis_nagybetu_fuggetlen():
    assert ge.count_occurrences("welcome", SRT) == 1


def test_count_occurrences_sortorest_atlep():
    """A többszavas kifejezést a felirat sortörése megszakíthatja."""
    assert ge.count_occurrences("Ascendance Sect", SRT) == 2


def test_count_occurrences_nem_alfanumerikus_veg():
    """A `\\b` a felkiáltójel után sosem illeszkedne — ezért feltételes."""
    assert ge.count_occurrences("Sect.", SRT) == 1


@pytest.mark.parametrize("term", ["", "   ", None])
def test_count_occurrences_ures_kifejezes(term):
    assert ge.count_occurrences(term, SRT) == 0


def test_count_occurrences_ures_szoveg():
    assert ge.count_occurrences("Sect", "") == 0


# ── validate_suggestions: a gépi fék ────────────────────────────────────────

def _sug(en, hu="x", cat="special_terms", conf="biztos", **kw):
    return dict({"en": en, "hu": hu, "category": cat, "context": "",
                 "confidence": conf}, **kw)


def test_ritka_kifejezes_bizonytalan_lesz_a_modell_ellenere():
    """A modell mindent "biztos"-nak jelöl — az előfordulásszám bírálja felül."""
    out = ge.validate_suggestions([_sug("sectarian")], set(), SRT)
    assert out[0]["confidence"] == "bizonytalan"
    assert out[0]["occurrences"] == 1


def test_tobbszor_elofordulo_marad_biztos():
    out = ge.validate_suggestions([_sug("Sect")], set(), SRT)
    assert out[0]["confidence"] == "biztos"
    assert out[0]["occurrences"] == 2


def test_modell_bizonytalansaga_nem_irhato_felul_felfele():
    """Sok előfordulás sem tesz biztossá egy bizonytalannak jelölt sort."""
    out = ge.validate_suggestions([_sug("Sect", conf="bizonytalan")], set(), SRT)
    assert out[0]["confidence"] == "bizonytalan"


def test_forrasszoveg_nelkul_nincs_gepi_fek():
    """Utólagos módban is működjön, ha nincs mihez mérni."""
    out = ge.validate_suggestions([_sug("bármi")], set(), "")
    assert out[0]["confidence"] == "biztos"


def test_meglevo_kifejezes_kiesik():
    assert ge.validate_suggestions([_sug("Sect")], {"sect"}, SRT) == []


def test_ismeretlen_kategoria_kiesik():
    assert ge.validate_suggestions([_sug("Sect", cat="nincs_ilyen")], set(), SRT) == []


def test_evidence_normalizalas():
    out = ge.validate_suggestions(
        [_sug("Sect", evidence=["  #1 „a” ", "", "#2 „b”", "c", "d", "e"])], set(), SRT)
    assert out[0]["evidence"] == ["#1 „a”", "#2 „b”", "c", "d"]


def test_hianyzo_evidence_ures_lista():
    out = ge.validate_suggestions([_sug("Sect")], set(), SRT)
    assert out[0]["evidence"] == []


# ── promptépítők: a szabályok és a szójegyzék tényleg átmennek ──────────────

GLOSSARY = {
    "place_names": [{"en": "Ascendance Sect", "hu": "Felemelkedés Rendje",
                     "context": "a sorozat központi rendje; „Sect” MINDIG „Rend”"}],
    "honorifics": [], "character_names": [], "special_terms": [], "phrases": [],
}

# A TRANSLATION.md-nél is hosszabb: a korábbi [:6000] csonkítás pont a végét
# vágta le, márpedig a subtr.context a TRANSLATION.local.md-t oda fűzi.
LONG_RULES = "x" * 8000 + "\n=== HELYI SOROZATKONTEXTUS ===\nSOROZATSPECIFIKUS-JELÖLŐ"


@pytest.mark.parametrize("build", [
    lambda **kw: ge.build_source_prompt("SRT", 1, 1, **kw),
    lambda **kw: ge.build_pair_prompt("SRT", "HU", 1, 1, **kw),
])
def test_a_helyi_kontextus_is_atmegy(build):
    """Regresszió: a szabályzat nincs 6000 karakterre vágva."""
    prompt = build(new_terms=set(), glossary_text="", claude_md=LONG_RULES)
    assert "SOROZATSPECIFIKUS-JELÖLŐ" in prompt


@pytest.mark.parametrize("build", [
    lambda **kw: ge.build_source_prompt("SRT", 1, 1, **kw),
    lambda **kw: ge.build_pair_prompt("SRT", "HU", 1, 1, **kw),
])
def test_a_jovahagyott_forditasok_atmennek(build):
    """Regresszió: korábban csak az "en" kulcsok mentek át, a "hu" nem —
    ezért javasolt a modell „szektá"-t oda, ahol a projektben „Rend" van."""
    prompt = build(new_terms=set(),
                   glossary_text=ge.as_prompt_text(GLOSSARY), claude_md="")
    assert "Felemelkedés Rendje" in prompt
    assert "MINDIG „Rend”" in prompt


@pytest.mark.parametrize("build", [
    lambda **kw: ge.build_source_prompt("SRT", 1, 1, **kw),
    lambda **kw: ge.build_pair_prompt("SRT", "HU", 1, 1, **kw),
])
def test_confidence_szabaly_a_promptban(build):
    prompt = build(new_terms=set(), glossary_text="", claude_md="")
    assert 'confidence="biztos"' in prompt
    assert '"evidence"' in prompt


def test_futas_kozbeni_javaslatok_felsorolasa():
    prompt = ge.build_source_prompt("SRT", 2, 3, new_terms={"lumi"},
                                    glossary_text="", claude_md="")
    assert "EBBEN A FUTÁSBAN MÁR JAVASOLT" in prompt
    assert "lumi" in prompt


def test_ures_kontextus_nem_hagy_ures_szakaszt():
    prompt = ge.build_source_prompt("SRT", 1, 1, new_terms=set(),
                                    glossary_text="", claude_md="")
    assert "SZABÁLYOK VÉGE" not in prompt
    assert "SZÓJEGYZÉK VÉGE" not in prompt


def test_forrasnyelv_megjelenik_a_promptban():
    assert "NÉMET FELIRAT" in ge.build_source_prompt(
        "SRT", 1, 1, new_terms=set(), glossary_text="", claude_md="", src_lang="ger")


# ── merge_into_glossary: a segédmezők nem szivárognak a fájlba ──────────────

def test_merge_nem_ir_ki_segedmezoket(tmp_path):
    glossary = {cat: [] for cat in ge.CATEGORIES}
    approved = ge.validate_suggestions(
        [_sug("Sect", hu="Rend", evidence=["#1 „a”"])], set(), SRT)
    assert ge.merge_into_glossary(glossary, approved) == 1

    path = tmp_path / "glossary.json"
    ge.save_glossary(str(path), glossary)
    entry = json.loads(path.read_text(encoding="utf-8"))["special_terms"][0]
    assert set(entry) == {"en", "hu", "context"}
    assert entry["hu"] == "Rend"
