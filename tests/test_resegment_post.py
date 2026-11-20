"""addons/resegment-post/postmerge.py — kártya-visszabontás és egysorosítás.
Valós tmp fájlokon, hálózat nélkül."""

import importlib.util
import sys
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addons" / "resegment-post" / "postmerge.py"
_spec = importlib.util.spec_from_file_location("postmerge", ADDON)
pm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pm)


@pytest.mark.parametrize("lines, ok", [
    (["Kérjük, küldjenek át", "egy udvari orvost."], True),
    (["Idáig jutottunk.", "Nincs visszaút."], False),          # két mondat
    (["♪A múlt kuszaságát", "hogyan rendezzük el♪"], False),    # dal
    (["- Ki az?", "- Én vagyok."], False),                      # párbeszéd
    (["♫A múlt kuszaságát", "hogyan rendezzük el♫"], False),    # dal, ♫ jellel
    (["<i>- Ki az?", "- Én vagyok.</i>"], False),               # dőlt párbeszéd
    (["– Ki az?", "– Én vagyok."], False),                      # nagykötőjeles párbeszéd
    (["[A császárné alattvalója]", "[Her Willing Subject]"], False),  # címkártya
    (["[Lu Qingcang,", "Dasheng régense]"], True),              # egy kártya, két sorban
    (["Ez egy nagyon hosszú első sor,", "és még egy hosszú második sor."], False),  # >42
    (["Egyetlen sor."], False),
])
def test_can_unbreak(lines, ok):
    assert pm.can_unbreak(lines, 42) is ok


def _srt(cues):
    return "\n\n".join(f"{i}\n{t}\n" + "\n".join(lines) for i, (t, lines) in enumerate(cues, 1)) + "\n"


def test_unmerges_card_and_unbreaks(tmp_path, monkeypatch):
    stem = tmp_path / "S - S01E01.hun"
    reflow = [("00:00:38,440 --> 00:00:40,800", ["[Magyar cím]", "[Her Willing Subject]"]),
              ("00:00:40,920 --> 00:00:43,680", ["[1. rész]"]),
              ("00:00:47,000 --> 00:00:49,000", ["Kérjük, küldjenek át", "egy udvari orvost."])]
    merged = [("00:00:38,440 --> 00:00:43,680", ["[Magyar cím] [Her", "Willing Subject] [1. rész]"]),
              ("00:00:47,000 --> 00:00:49,000", ["Kérjük, küldjenek át", "egy udvari orvost."])]
    Path(f"{stem}.reflow.srt").write_text(_srt(reflow), encoding="utf-8")
    Path(f"{stem}.merge.srt").write_text(_srt(merged), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["postmerge.py", str(stem)])
    pm.main()
    out = Path(f"{stem}.merge.srt").read_text(encoding="utf-8")
    assert out == _srt([reflow[0], reflow[1],
                        ("00:00:47,000 --> 00:00:49,000", ["Kérjük, küldjenek át egy udvari orvost."])])


def _run(tmp_path, monkeypatch, reflow, merged, raw_merge=None, args=()):
    stem = tmp_path / "S - S01E01.hun"
    Path(f"{stem}.reflow.srt").write_text(_srt(reflow), encoding="utf-8")
    Path(f"{stem}.merge.srt").write_text(raw_merge or _srt(merged), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["postmerge.py", str(stem), *args])
    pm.main()
    return Path(f"{stem}.merge.srt").read_text(encoding="utf-8")


def test_sound_tag_merge_is_kept(tmp_path, monkeypatch):
    """A mondatba ékelt hangjelzés ([nevet]) nem kártya — az összevonás marad."""
    reflow = [("00:00:01,000 --> 00:00:01,800", ["Ne már [nevet]"]),
              ("00:00:01,900 --> 00:00:03,000", ["ezt komolyan mondod?"])]
    merged = [("00:00:01,000 --> 00:00:03,000", ["Ne már [nevet]", "ezt komolyan mondod?"])]
    out = _run(tmp_path, monkeypatch, reflow, merged, args=["--no-unbreak"])
    assert out == _srt(merged)


def test_edited_card_cue_is_not_reverted(tmp_path, monkeypatch, capsys):
    """Kézzel javított kártyás cue: a .reflow.srt-ből nem írjuk vissza."""
    reflow = [("00:00:01,000 --> 00:00:02,000", ["[Lu Qincang, régens]"]),
              ("00:00:02,100 --> 00:00:03,000", ["Üdvözöllek."])]
    merged = [("00:00:01,000 --> 00:00:03,000", ["[Lu Qingcang, régens]", "Üdvözöllek."])]
    out = _run(tmp_path, monkeypatch, reflow, merged, args=["--no-unbreak"])
    assert out == _srt(merged) and "FIGYELEM" in capsys.readouterr().out


def test_card_without_fitting_pieces_is_kept(tmp_path, monkeypatch):
    """Ha a reflow-darabok nem férnek a cue idősávjába, a cue nem tűnhet el."""
    reflow = [("00:00:00,500 --> 00:00:02,000", ["[Cím]"]),
              ("00:00:02,100 --> 00:00:03,500", ["[1. rész]"])]
    merged = [("00:00:01,000 --> 00:00:03,000", ["[Cím] [1. rész]"])]
    assert _run(tmp_path, monkeypatch, reflow, merged) == _srt(merged)


def test_load_tolerates_extra_blank_lines(tmp_path, monkeypatch):
    reflow = [("00:00:01,000 --> 00:00:02,000", ["Egy"]),
              ("00:00:03,000 --> 00:00:04,000", ["Kettő"])]
    raw = ("1\r\n00:00:01,000 --> 00:00:02,000\r\nEgy\r\n\r\n \r\n\r\n"
           "2\n00:00:03,000 --> 00:00:04,000\nKettő\n\n\n")
    assert _run(tmp_path, monkeypatch, reflow, None, raw_merge=raw) == _srt(reflow)
