"""addons/srt-preclean/postclean_srt.py — a lefordított SDH-címkék és
hangjegyzetek törlése, címkártya megtartása, SDH-védelem, kimeneti fájl."""

import importlib.util
import json
from pathlib import Path

ADDON = Path(__file__).resolve().parent.parent / "addons" / "srt-preclean" / "postclean_srt.py"
_spec = importlib.util.spec_from_file_location("postclean_srt", ADDON)
postclean_srt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(postclean_srt)


def _srt(*cues):
    return "\n\n".join(
        f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\n" + "\n".join(lines)
        for i, lines in enumerate(cues, 1)) + "\n"


def _sdh_cues(n=6):
    return [[f"[Anna] Szia {i}!"] for i in range(n)]


def test_cimke_es_sorvegi_jegyzet_torlodik():
    assert postclean_srt.clean_line("[Anna] Igen.") == "Igen."
    assert postclean_srt.clean_line("Hadd... [sóhajt]") == "Hadd..."
    assert postclean_srt.clean_line("- [Anna] Szia!") == "- Szia!"
    assert postclean_srt.clean_line("[Anna] <i>Ott ült</i>") == "<i>Ott ült</i>"
    assert postclean_srt.clean_line("Én- [köhög] jól vagyok.") == "Én- jól vagyok."
    assert postclean_srt.clean_line("<i>[zene szól]</i>") == ""


def test_kerek_zarojeles_jegyzet_is_torlodik():
    assert postclean_srt.clean_line("Megjöttem. (nevet)") == "Megjöttem."


def test_csak_jegyzet_felirat_eldobodik_es_kotojel_lekerul():
    kept, dropped, _ = postclean_srt.postclean(
        [("t1", ["- [kattanás]", "- [motor zúg]"]),
         ("t2", ["-Ez az.", "-[ajtó nyílik]"]),
         ("t3", ["- Igen.", "- [Anna] Nem."])], set(), [])
    assert [ts for ts, _ in dropped] == ["t1"]
    assert kept == [("t2", ["Ez az."]), ("t3", ["- Igen.", "- Nem."])]


def test_cimkartya_megmarad(tmp_path):
    (tmp_path / "TRANSLATION.local.md").write_text(
        "Title: Berry Field (2026) (ベリーフィールド)\nHungarian title: Eperföld\n",
        encoding="utf-8")
    titles = postclean_srt.series_titles(tmp_path)
    assert titles == {"berry field", "ベリーフィールド", "eperföld"}
    kept, _, _ = postclean_srt.postclean(
        [("t1", ["[Eperföld]", "[BERRY FIELD]"])], titles, [])
    assert kept == [("t1", ["[Eperföld]", "[BERRY FIELD]"])]


def test_todo_magyar_cim_nem_cim(tmp_path):
    (tmp_path / "TRANSLATION.local.md").write_text(
        "Title: Spring Breeze (2026)\nHungarian title: TODO: magyar cím\n", encoding="utf-8")
    (tmp_path / "glossary.json").write_text(json.dumps({"meta": {"series": "Spring Breeze"}}),
                                           encoding="utf-8")
    assert postclean_srt.series_titles(tmp_path) == {"spring breeze"}


def test_keep_minta_vedi_a_sort():
    import re
    kept, _, _ = postclean_srt.postclean([("t1", ["[Szöul, 2019]"])], set(), [re.compile(r"^\[Szöul")])
    assert kept == [("t1", ["[Szöul, 2019]"])]


def test_sdh_felismeres():
    sdh = [("t", c) for c in _sdh_cues()]
    assert postclean_srt.looks_like_sdh(sdh)
    # nem SDH: a zárójel egész soros képi szöveg
    kepi = [("t", ["[Szöul, 2019]"])] * 10 + [("t", ["Szia!"])] * 10
    assert not postclean_srt.looks_like_sdh(kepi)
    sorvegi = [("t", ["Hadd... [sóhajt]"])] * 6
    assert postclean_srt.looks_like_sdh(sorvegi)


def test_main_kulon_fajlba_ir_es_nem_irja_felul(tmp_path):
    src = tmp_path / "X - S01E01.hun.srt"
    original = _srt(*_sdh_cues(), ["- [kattanás]", "- [zúgás]"])
    src.write_text(original, encoding="utf-8")
    assert postclean_srt.main([str(src), "--project-dir", str(tmp_path)]) == 0
    assert src.read_text(encoding="utf-8") == original
    out = tmp_path / "X - S01E01.hun.clean.srt"
    text = out.read_text(encoding="utf-8")
    assert "[" not in text
    assert text.startswith("1\n00:00:01,000 --> 00:00:01,500\nSzia 0!")
    assert text.count("-->") == 6


def test_main_nem_sdh_bemenetet_elutasit(tmp_path):
    src = tmp_path / "X.hun.srt"
    src.write_text(_srt(["[Szöul, 2019]"], ["Szia!"], ["Mi újság?"]), encoding="utf-8")
    assert postclean_srt.main([str(src), "--project-dir", str(tmp_path)]) == 1
    assert not (tmp_path / "X.hun.clean.srt").exists()
    assert postclean_srt.main([str(src), "--project-dir", str(tmp_path), "--force"]) == 0


def test_main_kimenet_nem_lehet_a_bemenet(tmp_path):
    src = tmp_path / "X.hun.srt"
    src.write_text(_srt(*_sdh_cues()), encoding="utf-8")
    assert postclean_srt.main([str(src), "-o", str(src)]) == 1
