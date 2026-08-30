"""addons/srt-preclean — SDH-cue szűrés: formázott cue-k, párbeszéd-kötőjel,
üres sor nélküli feliratok, több sorra tört cue."""

import importlib.util
from pathlib import Path

ADDON = Path(__file__).resolve().parent.parent / "addons" / "srt-preclean" / "preclean_srt.py"
_spec = importlib.util.spec_from_file_location("preclean_srt", ADDON)
preclean_srt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preclean_srt)


def test_formazott_hangcue_is_tiszta_cue():
    assert preclean_srt.is_pure_cue_line("<i>[tense music]</i>", [])
    assert preclean_srt.is_pure_cue_line("{\\an8}[music]", [])
    assert preclean_srt.is_pure_cue_line("<i>♪</i>", [])
    assert not preclean_srt.is_pure_cue_line("<i>Szia</i>", [])


def test_parbeszed_kotojel_megmarad_a_cimke_levetelekor():
    assert preclean_srt.strip_leading_label("- [Anna] Szia!", []) == "- Szia!"
    assert preclean_srt.strip_leading_label("- ANNA: Szia!", []) == "- Szia!"
    assert preclean_srt.strip_leading_label("[Anna] Szia!", []) == "Szia!"
    # vegyes írású kettőspont NEM címke
    assert preclean_srt.strip_leading_label("Listen: ez fontos", []) == "Listen: ez fontos"


def test_ures_sor_nelkuli_feliratok_nem_olvadnak_ossze():
    subs = preclean_srt.parse_srt(
        "1\n00:00:01,000 --> 00:00:02,000\nA\n2\n00:00:03,000 --> 00:00:04,000\nB\n")
    assert subs == [("00:00:01,000 --> 00:00:02,000", ["A"]),
                    ("00:00:03,000 --> 00:00:04,000", ["B"])]


def test_tobb_sorra_tort_cue_torlodik():
    kept, dropped = preclean_srt.preclean(
        [("t1", ["[dramatic music", "continues]"]), ("t2", ["Szia!", "[sighs]"])], [], False)
    assert dropped == 1
    assert kept == [("t2", ["Szia!"])]


def test_style_blokk_folytatassorai_is_torlodnek():
    """A ::cue { ... } blokk belseje (color: white;) és a záró } is artefaktum —
    a blokk a feliratok határán is átfuthat."""
    subs = [("t1", ["::cue(v[voice=Anna]) {", "color: white;", "}", "Szia!"]),
            ("t2", ["STYLE", "::cue { color: red }"]),
            ("t3", ["::cue {", "background: black;"]),
            ("t4", ["}", "Ez már szöveg"])]
    kept, dropped = preclean_srt.preclean(subs, [], False)
    assert kept == [("t1", ["Szia!"]), ("t4", ["Ez már szöveg"])]
    assert dropped == 2
