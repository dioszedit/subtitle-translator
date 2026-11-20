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
    reflow = [("00:00:38,440 --> 00:00:40,800", ["[Magyar cím]", "[Original]"]),
              ("00:00:40,920 --> 00:00:43,680", ["[1. rész]"]),
              ("00:00:47,000 --> 00:00:49,000", ["Kérjük, küldjenek át", "egy udvari orvost."])]
    merged = [("00:00:38,440 --> 00:00:43,680", ["[Magyar cím] [Her", "Original] [1. rész]"]),
              ("00:00:47,000 --> 00:00:49,000", ["Kérjük, küldjenek át", "egy udvari orvost."])]
    Path(f"{stem}.reflow.srt").write_text(_srt(reflow), encoding="utf-8")
    Path(f"{stem}.merge.srt").write_text(_srt(merged), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["postmerge.py", str(stem)])
    pm.main()
    out = Path(f"{stem}.merge.srt").read_text(encoding="utf-8")
    assert out == _srt([reflow[0], reflow[1],
                        ("00:00:47,000 --> 00:00:49,000", ["Kérjük, küldjenek át egy udvari orvost."])])
