"""subtr.py consistency — szintetikus 3 részes sorozaton, hálózat és LLM nélkül."""

import json
import os

import pytest

from subtr.tasks import consistency as cons


def _ts(s):
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _write(path, cues):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{t}" for i, (a, b, t) in enumerate(cues, 1))
    path.write_text(body + "\n", encoding="utf-8")


SRC = [
    (0, 2, "[Old Mill Inn]"),
    (3, 5, "♪ The river remembers our names ♪"),
    (6, 8, "Protect the captain at all costs!"),
    (9, 11, "Yes."),
]


@pytest.fixture
def series(tmp_path):
    """Három rész: az E03 tábla- és dalfordítása eltér, a névírás is ingadozik."""
    hun = {
        "E01": ["[Malom-fogadó]", "♫ A folyó emlékszik a nevünkre ♫",
                "Védjétek a kapitányt mindenáron!", "Igen. Taolu elesett, Wu Si látta."],
        "E02": ["[Malom-fogadó]", "♫ A folyó emlékszik a nevünkre ♫",
                "Védjétek a kapitányt mindenáron!", "Jó. A Taolu nép, mondta Wu Si."],
        "E03": ["[Malom Fogadó]", "<i>A folyó emlékezik a nevünkre</i>",
                "Óvják a kapitányt mindenáron!", "Rendben. Ott van Taolú, és Wu Si."],
    }
    for ep, texts in hun.items():
        name = f"Sorozat - S01{ep}"
        _write(tmp_path / "input" / f"{name}.eng.srt", SRC)
        # a magyar fájl átszámozott és eltolt — az időzítés párosít, nem a sorszám
        _write(tmp_path / "Season 01" / f"{name}.hun.srt",
               [(a + 0.05, b - 0.05, t) for (a, b, _), t in zip(SRC, texts)])
    return tmp_path


def test_reports_caption_song_dialogue_and_spelling(series, capsys):
    assert cons.run([str(series)]) == 0
    out = capsys.readouterr().out
    assert "Képernyőszöveg ([…]) — azonos forrás, eltérő fordítás: 1" in out
    assert "→ többségi: [Malom-fogadó]" in out
    assert "Dalszöveg (♪) — azonos forrás, eltérő fordítás: 1" in out
    assert "Párbeszéd — azonos forrás, eltérő fordítás: 1" in out
    assert "Taolu" in out and "Taolú" in out          # írásmód-változat
    assert "Yes." not in out                           # rövid sor nem számít


def test_short_name_parts_are_not_confused(tmp_path):
    texts = [("S01E01", "1", "Itt van Wu Si, és ott Zhao Shi hadserege. Wu Si megjött. Zhao Shi népe ünnepel.")] * 3
    groups = cons.find_spelling_variants(texts)
    assert groups == []


def test_pinyin_h_variant_in_longer_names():
    texts = [("S01E01", "1", "Ez a Nagy Zen birodalom."), ("S01E02", "2", "Ez a Nagy Zhen birodalom."),
             ("S01E03", "3", "Wu Si megjött. Zhao Shi népe ünnepel.")]
    groups = cons.find_spelling_variants(texts)
    assert [sorted(f["form"] for f in g["forms"]) for g in groups] == [["Nagy Zen", "Nagy Zhen"]]


def test_hungarian_inflection_is_not_a_spelling_variant():
    texts = [("S01E01", "1", "Megtalálta a Jáde Szívet."), ("S01E02", "2", "Elvette a Jáde Szívét.")]
    assert cons.find_spelling_variants(texts) == []


def test_hyphenated_suffix_is_separate_category():
    texts = [("S01E01", "1", "Látta Fangot."), ("S01E02", "2", "Láttad Fang-ot?")]
    groups = cons.find_spelling_variants(texts)
    assert len(groups) == 1 and groups[0]["hyphen_only"]


def test_decisions_fix_minority_and_keep_target_markup(series, capsys):
    assert cons.run([str(series), "--decisions"]) == 0
    out = series / "output" / "Sorozat - S01E03.hun_consistency.json"
    decisions = {d["sorszam"]: d for d in json.loads(out.read_text(encoding="utf-8"))}
    assert decisions[1]["javaslat"] == "[Malom-fogadó]"
    # a dal szövege egységesül, de az E03 saját <i> jelölése marad
    assert decisions[2]["javaslat"] == "<i>A folyó emlékszik a nevünkre</i>"
    assert 3 not in decisions                          # párbeszédhez nincs automatikus javaslat
    assert not (series / "output" / "Sorozat - S01E01.hun_consistency.json").exists()


def test_multi_caption_cue_is_not_paired_by_order(tmp_path):
    _write(tmp_path / "input" / "S - S01E01.eng.srt", [(0, 2, "[North Gate] [South Gate]")])
    _write(tmp_path / "output" / "S - S01E01.hun.srt", [(0, 2, "[Déli kapu] [Északi kapu]")])
    occ = cons.collect_occurrences(str(tmp_path / "output" / "S - S01E01.hun.srt"),
                                   str(tmp_path / "input" / "S - S01E01.eng.srt"), 25)
    assert [o for o in occ if o["kind"] == "caption"] == []


def test_multiline_caption_is_recognised():
    assert cons.is_caption_cue(["[Mind your step", "on the old bridge]"])
    assert not cons.is_caption_cue(["[Old Mill Inn] Welcome!"])


def test_final_file_selection(tmp_path):
    files = [("output", "S - S01E01.hun.srt"), ("Season 01", "S - S01E01.hun.srt"),
             ("output", "S - S01E02.hun.srt"), ("output", "S - S01E02.hun.merge.srt"),
             ("output", "S - S01E02.hun.reflow.srt"), ("output", "S - S01E03.hun.srt"),
             ("Season 02", "S - S02E01.hun.srt")]
    for sub, name in files:
        _write(tmp_path / sub / name, [(0, 1, "x")])
    chosen = [os.path.relpath(e["path"], tmp_path).replace("\\", "/")
              for e in cons.final_subtitles(str(tmp_path))]
    assert chosen == ["Season 01/S - S01E01.hun.srt",        # a Season NN nyer
                      "output/S - S01E02.hun.merge.srt",     # resegment utáni végleges
                      "output/S - S01E03.hun.srt",
                      "Season 02/S - S02E01.hun.srt"]        # nem csak a Season 01


def test_no_subtitles_is_an_error(tmp_path, capsys):
    assert cons.run([str(tmp_path)]) == 1
    assert "nincs kész magyar felirat" in capsys.readouterr().out


# ── A deep review regressziós esetei ──────────────────────────────────────

def _two_eps_plus(tmp_path, third_hun, third_src=None):
    """E01–E02 egyező dal; az E03 tetszőleges magyar és forrás cue-kkal."""
    song = [(0, 4, "♪ The river remembers our names ♪")]
    for ep in ("E01", "E02"):
        _write(tmp_path / "input" / f"S - S01{ep}.eng.srt", song)
        _write(tmp_path / "output" / f"S - S01{ep}.hun.srt", [(0, 4, "♫ A folyó emlékszik a nevünkre ♫")])
    _write(tmp_path / "input" / "S - S01E03.eng.srt", third_src or song)
    _write(tmp_path / "output" / "S - S01E03.hun.srt", third_hun)
    return tmp_path


def _e03_decisions(base):
    p = base / "output" / "S - S01E03.hun_consistency.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def test_song_with_foreign_dialogue_line_is_not_rewritten(tmp_path):
    base = _two_eps_plus(tmp_path, [(0, 6, "♫ A folyó emlékezik a nevünkre ♫\n- Gyere!"), (6, 9, "Jövök.")],
                         [(0, 4, "♪ The river remembers our names ♪"), (5.5, 8.5, "Come!")])
    assert cons.run([str(base), "--decisions"]) == 0
    assert _e03_decisions(base) == []


def test_split_song_line_is_not_duplicated(tmp_path):
    base = _two_eps_plus(tmp_path, [(0, 2.5, "♫ A folyó emlékszik ♫"), (2.5, 4, "♫ a nevünkre ♫")])
    assert cons.run([str(base), "--decisions"]) == 0
    assert _e03_decisions(base) == []


def test_non_numeric_or_duplicate_cue_numbers_are_skipped(tmp_path):
    base = _two_eps_plus(tmp_path, [(0, 4, "♫ A folyó emlékezik a nevünkre ♫")])
    srt = base / "output" / "S - S01E03.hun.srt"
    srt.write_text(srt.read_text(encoding="utf-8").replace("1\n", "1a\n", 1), encoding="utf-8")
    assert cons.run([str(base), "--decisions"]) == 0        # nem száll el
    assert _e03_decisions(base) == []


def test_unreadable_file_does_not_stop_the_report(tmp_path, capsys):
    base = _two_eps_plus(tmp_path, [(0, 4, "♫ A folyó emlékezik a nevünkre ♫")])
    (base / "output" / "S - S01E04.hun.srt").write_bytes("1\n00:00:00,000 --> 00:00:01,000\nNincs\xe9kezet\n".encode("cp1250").replace(b"\xe9", b"\xe9\xff"))
    assert cons.run([str(base)]) == 0
    out = capsys.readouterr().out
    assert "nem olvasható, kihagyva" in out and "S01E04" in out
    assert "Dalszöveg (♪) — azonos forrás, eltérő fordítás: 1" in out


def test_stale_decision_file_is_removed(tmp_path):
    base = _two_eps_plus(tmp_path, [(0, 4, "♫ A folyó emlékezik a nevünkre ♫")])
    assert cons.run([str(base), "--decisions"]) == 0
    assert _e03_decisions(base)
    _write(base / "output" / "S - S01E03.hun.srt", [(0, 4, "♫ A folyó emlékszik a nevünkre ♫")])
    assert cons.run([str(base), "--decisions"]) == 0
    assert not (base / "output" / "S - S01E03.hun_consistency.json").exists()


@pytest.mark.parametrize("target, suggested, expected", [
    ("♫ Egy sor ♫\n♫ Másik sor ♫", "♫ One\nTwo ♫", "♫ One ♫\n♫ Two ♫"),
    ("- ♫ Egy sor ♫", "♫ One ♫", "- ♫ One ♫"),
    ("<i>Egy sor\nmásik</i>", "<i>One\nTwo</i>", "<i>One\nTwo</i>"),
])
def test_rewrap_keeps_target_markup(target, suggested, expected):
    assert cons.rewrap(target, suggested) == expected


def test_accent_variant_in_one_word_of_accented_name_is_found():
    texts = [("S01E01", "1", "Ott a Jade Szív."), ("S01E02", "2", "Ott a Jáde Szív.")]
    assert len(cons.find_spelling_variants(texts)) == 1


def test_source_lang_follows_env_like_review(tmp_path, monkeypatch):
    for lang, text in (("eng", "♪ The river remembers our names ♪"), ("chi", "♪ 河流记得我们的名字 ♪")):
        for ep in ("E01", "E02"):
            _write(tmp_path / "input" / f"S - S01{ep}.{lang}.srt", [(0, 4, text)])
    _write(tmp_path / "output" / "S - S01E01.hun.srt", [(0, 4, "♫ A folyó emlékszik ♫")])
    _write(tmp_path / "output" / "S - S01E02.hun.srt", [(0, 4, "♫ A folyó emlékezik ♫")])
    monkeypatch.setenv("SUBTR_SOURCE_LANG", "chi")
    groups = cons.find_conflicts([o | {"episode": "x", "path": "p"} for e in ("E01", "E02")
                                  for o in cons.collect_occurrences(
                                      str(tmp_path / "output" / f"S - S01{e}.hun.srt"),
                                      cons.find_source({"folder": str(tmp_path / "output"),
                                                        "stem": f"S - S01{e}"}, cons.config.resolve_source_lang(None)), 25)])
    assert groups and "河流" in groups[0]["source"]


# ── A második review regressziós esetei ───────────────────────────────────

def test_parallel_sign_and_dialogue_cues_are_both_compared(tmp_path, capsys):
    src = [(10, 15, "[Old Mill Inn]"), (11, 13, "Protect the captain at all costs!")]
    hun = {"E01": ("[Malom-fogadó]", "Védjétek a kapitányt mindenáron!"),
           "E02": ("[Malom-fogadó]", "Védjétek a kapitányt mindenáron!"),
           "E03": ("[Malom Fogadó]", "Óvják a kapitányt mindenáron!")}
    for ep, (sign, line) in hun.items():
        _write(tmp_path / "input" / f"S - S01{ep}.eng.srt", src)
        _write(tmp_path / "output" / f"S - S01{ep}.hun.srt", [(10, 15, sign), (11, 13, line)])
    assert cons.run([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Képernyőszöveg ([…]) — azonos forrás, eltérő fordítás: 1" in out
    assert "Párbeszéd — azonos forrás, eltérő fordítás: 1" in out


def test_unbracketed_sign_in_song_cue_is_not_overwritten(tmp_path):
    base = _two_eps_plus(tmp_path, [(0, 4, "<i>Malom-fogadó</i>\n♫ A folyó emlékezik a nevünkre ♫")],
                         [(0, 4, "[Old Mill Inn]"), (0, 4, "♪ The river remembers our names ♪")])
    assert cons.run([str(base), "--decisions"]) == 0
    assert _e03_decisions(base) == []


def test_dash_without_space_marks_dialogue_line(tmp_path):
    base = _two_eps_plus(tmp_path, [(0, 6, "♫ A folyó emlékezik a nevünkre ♫\n-Gyere!"), (6, 9, "Jövök.")],
                         [(0, 4, "♪ The river remembers our names ♪"), (5.8, 8.5, "Come!")])
    assert cons.run([str(base), "--decisions"]) == 0
    assert _e03_decisions(base) == []


def test_hungarian_word_inflection_with_ascii_form_is_ignored():
    texts = [("S01E01", "1", "Megmászta a Szent Hegyet."), ("S01E02", "2", "Látta a Szent Hegyét.")]
    assert cons.find_spelling_variants(texts) == []


def test_no_name_fragments_from_inside_words():
    assert list(cons.name_tokens("Vettem egy iPhone-t és macOS-t.")) == []


def test_hyphen_and_space_spellings_are_grouped():
    texts = [("S01E01", "1", "Ott a Malom-Fogadó."), ("S01E02", "2", "Ott a Malom Fogadó.")]
    assert len(cons.find_spelling_variants(texts)) == 1


def test_rewrap_keeps_markup_only_lines():
    assert cons.rewrap("♫\nA folyó emlékezik\n♫", "♫ A folyó emlékszik ♫") == "♫\nA folyó emlékszik\n♫"


def test_bad_source_keeps_hungarian_in_spelling_check(tmp_path, capsys):
    _write(tmp_path / "output" / "S - S01E01.hun.srt", [(0, 1, "Itt van Taolu.")])
    _write(tmp_path / "output" / "S - S01E02.hun.srt", [(0, 1, "Ott van Taolú.")])
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "S - S01E01.eng.srt").write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\n\xff\xfe\n")
    assert cons.run([str(tmp_path), "--source-lang", "eng"]) == 0
    out = capsys.readouterr().out
    assert "forrás (UnicodeDecodeError)" in out
    assert "Taolu" in out and "Taolú" in out


# ── Célzott review regressziós esetei ─────────────────────────────────────

@pytest.mark.parametrize("target, suggested, expected", [
    # eltérő soronkénti jelölés: a cue egészét fogja közre, a ♫ nem kerül középre
    ("<i>♪ a b</i>\n<i>c d ♪</i>", "x\ny\nz", "<i>♪ x\ny\nz ♪</i>"),
    ("<i>♪ a b</i>\n<i>c d ♪</i>", "x y", "<i>♪ x y ♪</i>"),
])
def test_rewrap_with_differing_line_markup(target, suggested, expected):
    assert cons.rewrap(target, suggested) == expected


def test_song_wrapped_sees_marks_behind_tags():
    assert cons._song_wrapped(["<i>♪ a", "b", "c ♪</i>"])
    assert cons._song_wrapped(["{\\an8}♫ a", "b ♫"])


def test_dialogue_line_after_ass_block_is_recognised():
    assert cons.DIALOGUE_LINE_RE.match("{\\an8}- Gyere!")


def test_synthetic_cue_number_is_not_targeted(tmp_path):
    base = _two_eps_plus(tmp_path, [(0, 4, "♫ A folyó emlékezik a nevünkre ♫")])
    srt = base / "output" / "S - S01E03.hun.srt"
    srt.write_text(srt.read_text(encoding="utf-8").split("\n", 1)[1], encoding="utf-8")  # sorszám-sor törölve
    assert cons.run([str(base), "--decisions"]) == 0
    assert _e03_decisions(base) == []
