"""addons/hardsub-ocr — a motorfüggetlen mag: SRT, mintavétel, szűrés,
jelöltválasztás, igazítás, fájlnevek, beállítások. A motort egy hamis motor
helyettesíti, így se Vision, se RapidOCR, se ffmpeg nem kell."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from subtr import config

ADDON_DIR = Path(__file__).resolve().parent.parent / "addons" / "hardsub-ocr"
_spec = importlib.util.spec_from_file_location("ocr_subs", ADDON_DIR / "ocr_subs.py")
ocr = importlib.util.module_from_spec(_spec)
sys.modules["ocr_subs"] = ocr
_spec.loader.exec_module(ocr)
engines = ocr.engines

SRT = """1
00:00:01,000 --> 00:00:03,000
Hello.

2
00:00:04,000 --> 00:00:04,500
Short.

3
00:00:10,000 --> 00:00:14,000
<i>Song lyrics</i>
second line
"""


@pytest.fixture
def cfg(monkeypatch):
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    return ocr.resolve(ocr.build_parser().parse_args(["x.mp4"]))


# ── SRT ────────────────────────────────────────────────────────────────────

def test_parse_ts():
    assert ocr.parse_ts("00:01:02,345") == pytest.approx(62.345)
    assert ocr.parse_ts("1:00:00.5") == pytest.approx(3600.5)
    with pytest.raises(ValueError):
        ocr.parse_ts("hello")


def test_read_cues_keeps_numbers_and_timestamps(tmp_path):
    p = tmp_path / "Sorozat - S01E01.eng.srt"
    p.write_text("﻿" + SRT, encoding="utf-8")
    cues = ocr.read_cues(p)
    assert [c["num"] for c in cues] == ["1", "2", "3"]
    assert cues[0]["timestamp"] == "00:00:01,000 --> 00:00:03,000"
    assert cues[2]["start"] == 10 and cues[2]["end"] == 14


def test_read_cues_bad_timestamp_is_fail(tmp_path):
    p = tmp_path / "x.srt"
    p.write_text("1\nnope --> 00:00:01,000\nHi\n", encoding="utf-8")
    with pytest.raises(ocr.Fail):
        ocr.read_cues(p)


def test_read_cues_empty_is_fail(tmp_path):
    p = tmp_path / "x.srt"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ocr.Fail):
        ocr.read_cues(p)


def test_output_uses_dash_for_empty(tmp_path):
    p = tmp_path / "in.srt"
    p.write_text(SRT, encoding="utf-8")
    cues = ocr.read_cues(p)
    out = tmp_path / "out.srt"
    ocr.write_srt(str(out), ocr.output_sections(cues, ["你好", "", "歌词"]))
    text = out.read_text(encoding="utf-8")
    assert text == ("1\n00:00:01,000 --> 00:00:03,000\n你好\n\n"
                    "2\n00:00:04,000 --> 00:00:04,500\n—\n\n"
                    "3\n00:00:10,000 --> 00:00:14,000\n歌词\n")


# ── mintavétel ─────────────────────────────────────────────────────────────

def test_sample_frames_two_points_for_long_cue():
    # 10–14 mp, 4 fps: 35% → 11,4 mp → 46. kocka; 70% → 12,8 mp → 51.
    assert ocr.sample_frames(10, 14, 4) == [46, 51]


def test_sample_frames_middle_for_short_cue():
    assert ocr.sample_frames(4.0, 4.5, 4) == [17]   # 4,25 mp × 4


def test_sample_frames_dedupes():
    # ritka mintavételnél a két pont ugyanarra a kockára esik: egyszer kell
    assert ocr.sample_frames(10, 10.9, 0.5) == [5]


def test_retry_frames_all_when_few():
    # csak a cue belseje: 1,25–1,75 mp (a 4. és a 8. kocka a határon van)
    assert ocr.retry_frames(1.0, 2.0, 4, 8) == [5, 6, 7]


def test_retry_frames_short_cue_stays_inside():
    assert ocr.retry_frames(4.0, 4.2, 4, 8) == [16]      # 4,0 mp: épp a cue eleje
    assert ocr.retry_frames(4.05, 4.2, 4, 8) == []       # nincs rácspont a cue-ban
    assert ocr.retry_frames(4.0, 4.0, 4, 8) == []


def test_sample_frames_never_before_or_after_short_cue():
    """0,3 mp-es cue a 4,1–4,4 mp-ben: a felénél (4,25) → 17. kocka; a kerekítés
    nem viheti a cue elé (16 = 4,0 mp) vagy utána (18 = 4,5 mp)."""
    for start, end in ((4.1, 4.4), (4.01, 4.3), (4.2, 4.49)):
        for n in ocr.sample_frames(start, end, 4):
            assert start <= n / 4 < end, (start, end, n)


def test_retry_frames_capped_and_spread():
    frames = ocr.retry_frames(0, 10, 4, 8)   # 40 kocka közül 8
    assert len(frames) == 8
    assert frames == sorted(frames)
    assert frames[0] < 10 and frames[-1] > 30   # nem csak az eleje


def test_retry_frames_zero_disables():
    assert ocr.retry_frames(0, 10, 4, 0) == []


# ── sáv ────────────────────────────────────────────────────────────────────

def test_band_relative_scales_with_resolution():
    assert ocr.band_pixels(0.833, 0.986, 720) == (600, 110)
    y, h = ocr.band_pixels(0.833, 0.986, 1080)
    assert (y, h) == (900, 165)


def test_band_pixels_absolute():
    assert ocr.band_pixels(600, 710, 720) == (600, 110)


def test_band_too_narrow_or_reversed():
    with pytest.raises(ocr.Fail):
        ocr.band_pixels(0.9, 0.5, 720)


def test_parse_edge():
    assert ocr.parse_edge("0.8") == 0.8
    assert ocr.parse_edge("600px") == 600
    with pytest.raises(ValueError):
        ocr.parse_edge("600.5")
    with pytest.raises(ValueError):
        ocr.parse_edge("-1")


# ── szűrés ─────────────────────────────────────────────────────────────────

def test_chinese_filter_drops_ads_latin_and_non_cjk():
    f = ocr.LineFilter("chi")
    lines = [("我已经找到线索了", 1.0),
             ("官方娱乐平台", 1.0),          # reklám-kulcsszó
             ("www.example.com", 0.9),        # URL
             ("扫码领取88元", 1.0),           # kulcsszó + szám
             ("CSGO竞猜", 1.0),               # kulcsszó + latin betű
             ("客服电话13800138000", 1.0),    # hosszú számsor
             ("WWW BET CASINO 体育", 1.0),    # túlnyomóan latin betűs
             ("...", 0.5),                    # nincs benne írásjegy
             ("  你  再等等 ", 0.5),
             ("我等了你10年", 0.9),            # rövid szám: valódi párbeszéd
             ("３天后见", 0.9),                # teljes szélességű szám is
             ("我是CEO", 0.9),                 # rövid latin szó a mondatban
             ("他是娱乐公司的老板", 0.9),       # egyetlen kulcsszó: hétköznapi szó
             ("我们和他们结成联盟", 0.9)]
    assert f(lines) == [("我已经找到线索了", 1.0), ("你 再等等", 0.5),
                        ("我等了你10年", 0.9), ("３天后见", 0.9), ("我是CEO", 0.9),
                        ("他是娱乐公司的老板", 0.9), ("我们和他们结成联盟", 0.9)]


@pytest.mark.parametrize("line", [
    "他是星辰娱乐的CEO", "娱乐圈混了10年", "这个平台有3000万用户", "你喜欢足球还是篮球",
    "Linda来了", "你的iPhone呢", "我给你10000块", "他欠了我1000000元", "全部投注",
])
def test_chinese_everyday_lines_are_kept(line):
    """Név, márka, pénzösszeg, hétköznapi „kulcsszó” — valódi párbeszéd."""
    assert ocr.LineFilter("chi")([(line, 0.9)]) == [(line, 0.9)]


@pytest.mark.parametrize("line", ["50000원만 줘", "Instagram에 올려", "YouTube 봤어?"])
def test_korean_everyday_lines_are_kept(line):
    assert ocr.LineFilter("kor")([(line, 0.9)]) == [(line, 0.9)]


@pytest.mark.parametrize("line", [
    "官方娱乐平台", "扫码领取88元", "CSGO竞猜", "加微信13812345678", "WECHAT 欢",
    "WWW BET CASINO 体育", "投注提现",
])
def test_chinese_ads_are_dropped(line):
    assert ocr.LineFilter("chi")([(line, 1.0)]) == []


def test_korean_filter_wants_hangul():
    f = ocr.LineFilter("kor")
    lines = [("괜찮아요", 0.9), ("我已经", 1.0), ("ABC123", 1.0), ("지금 3시야", 1.0),
             ("문의 01012345678", 1.0), ("오늘 TV 봤어?", 1.0), ("SNS에 올렸어", 1.0)]
    # a kínai írásjegy nem koreai; a hosszú számsor reklám; a rövid szám és a
    # rövid latin szó (TV, SNS) nem; az ABC123-ban nincs hangul
    assert f(lines) == [("괜찮아요", 0.9), ("지금 3시야", 1.0), ("오늘 TV 봤어?", 1.0),
                        ("SNS에 올렸어", 1.0)]


def test_latin_language_keeps_latin_and_digits():
    f = ocr.LineFilter("eng")
    lines = [("See you at 3 o'clock.", 0.9), ("Visit www.bet.example", 1.0),
             ("你好", 1.0), ("---", 0.8)]
    assert f(lines) == [("See you at 3 o'clock.", 0.9)]


def test_drop_latin_override():
    heavy = [("WECHAT ID 欢迎", 1.0)]   # 8 latin betű, 2 írásjegy
    assert ocr.LineFilter("chi")(heavy) == []
    assert ocr.LineFilter("chi", drop_latin=False)(heavy) == heavy
    assert ocr.LineFilter("eng")([("Call 0612345678", 1.0)]) == [("Call 0612345678", 1.0)]
    assert ocr.LineFilter("eng", drop_latin=True)([("Call 0612345678", 1.0)]) == []


def test_ad_extra_extends_list():
    f = ocr.LineFilter("kor", ad_extra="광고|이벤트")
    assert f([("광고 문의", 1.0), ("괜찮아", 1.0)]) == [("괜찮아", 1.0)]


def test_ad_words_not_chinese_for_other_languages():
    # a kínai kulcsszólista nem érvényes a koreaira (ott a 平台 nem is hangul)
    assert ocr.LineFilter("chi").is_ad("官方娱乐平台")
    assert not ocr.LineFilter("kor").is_ad("官方娱乐平台")


def test_every_lang_has_script():
    for lang in ocr.LANG_SCRIPT.values():
        assert lang in ocr.SCRIPTS
    assert set(ocr.LANG_SCRIPT) <= set(config.SOURCE_LANGS)


# ── jelöltválasztás ────────────────────────────────────────────────────────

def test_candidate_joins_lines_min_conf():
    assert ocr.candidate([("你好", 1.0), ("再见", 0.5)]) == ("你好 再见", 0.5)
    assert ocr.candidate([]) is None


def test_best_candidate_conf_then_length():
    cands = [("短", 1.0), ("长一点的句子", 0.5), None, ("长一点", 1.0)]
    assert ocr.best_candidate(cands) == ("长一点", 1.0)


def test_best_candidate_threshold():
    assert ocr.best_candidate([("你好", 0.3)], 0.5) == ("", 0.0)
    assert ocr.best_candidate([None, None]) == ("", 0.0)


# ── igazítás hamis motorral ────────────────────────────────────────────────

class FakeEngine:
    name = "fake"

    def __init__(self, answers):
        self.answers = answers   # fájlnév → sorok
        self.calls = []

    def recognize(self, paths):
        self.calls.append(list(paths))
        return [self.answers.get(Path(p).name, []) for p in paths]


def make_frames(d, ns):
    for n in ns:
        ocr.frame_file(d, n).write_bytes(b"")


def test_align_main_pass_and_retry(tmp_path, cfg):
    cues = [{"num": "1", "timestamp": "", "start": 1.0, "end": 3.0},
            {"num": "2", "timestamp": "", "start": 4.0, "end": 4.5},
            {"num": "3", "timestamp": "", "start": 10.0, "end": 12.0}]
    make_frames(tmp_path, range(0, 60))
    answers = {
        # 1. cue: 35% → 1,7 mp → 7. kocka, 70% → 2,4 mp → 10. kocka
        "000007.png": [("你好", 0.5)],
        "000010.png": [("你好吗", 1.0), ("官方娱乐平台", 1.0)],
        # 2. cue: semmi a fő körben, a pótlásban csak a binarizált kocka ad biztos találatot
        "000017.png": [("快", 0.3)],
        "bin_000017.png": [("很快", 1.0)],
        # 3. cue: a pótlásban is csak gyenge találat → üres marad
        "000041.png": [("歌", 0.3)],
    }
    rec = ocr.Recognizer(FakeEngine(answers), ocr.LineFilter("chi"))
    cfg["min_conf"] = 0.4

    def binarizer(paths):
        out = {}
        for p in paths:
            b = tmp_path / f"bin_{p.name}"
            b.write_bytes(b"")
            out[p] = b
        return out

    texts, stats = ocr.align(cues, tmp_path, rec, cfg, binarizer, log=lambda *_: None)
    assert texts == ["你好吗", "很快", ""]
    assert stats == {"cues": 3, "first_empty": 2, "retried": 1, "empty": 1}


def test_recognizer_reads_each_frame_once_and_skips_missing(tmp_path):
    make_frames(tmp_path, [1, 2])
    eng = FakeEngine({"000001.png": [("你好", 1.0)]})
    rec = ocr.Recognizer(eng, ocr.LineFilter("chi"))
    p1, p2, p9 = (ocr.frame_file(tmp_path, n) for n in (1, 2, 9))
    rec.run([p1, p2, p9, p1])
    rec.run([p1, p2])
    assert eng.calls == [[p1, p2]]
    assert rec.get(p1) == ("你好", 1.0) and rec.get(p2) is None and rec.get(p9) is None


class NoneEngine(FakeEngine):
    """Minden képre None: a motor elromlott (pl. hiányzó modell)."""
    last_error = "RuntimeError: nincs modell"

    def recognize(self, paths):
        self.calls.append(list(paths))
        return [None for _ in paths]


def test_align_fails_when_engine_reads_nothing(tmp_path, cfg):
    """Ne legyen csupa `—` kimenet, amit a következő futás késznek hinne — és a
    pótló kör (cue-nként 8 kocka + binarizálás) el se induljon."""
    cues = [{"num": "1", "timestamp": "", "start": 1.0, "end": 3.0}]
    make_frames(tmp_path, range(20))
    eng = NoneEngine({})
    rec = ocr.Recognizer(eng, ocr.LineFilter("chi"))
    with pytest.raises(engines.EngineError, match="nincs modell"):
        ocr.align(cues, tmp_path, rec, cfg, lambda ps: pytest.fail("pótló kör"),
                  log=lambda *_: None)
    assert len(eng.calls) == 1


def test_engine_failure_stops_the_batch(tmp_path, monkeypatch, capsys):
    """Motorhibánál a többi rész sem indul (ugyanígy járna)."""
    videos = []
    for i in (1, 2):
        v = tmp_path / f"Sorozat - S01E0{i}.mp4"
        v.write_bytes(b"")
        (tmp_path / f"Sorozat - S01E0{i}.eng.srt").write_text(SRT, encoding="utf-8")
        videos.append(str(v))
    monkeypatch.setattr(ocr, "require_tools", lambda: None)
    monkeypatch.setattr(ocr, "load_dotenv", lambda: None)
    monkeypatch.setattr(ocr.engines, "create", lambda *a: NoneEngine({}))
    seen = []

    def fake_process(video, ref, dest, recognizer, cfg):
        seen.append(video)
        raise engines.EngineError("halott motor")
    monkeypatch.setattr(ocr, "process", fake_process)
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    rc = ocr.main([*videos, "--ref-dir", str(tmp_path), "--out-dir", str(tmp_path)])
    assert rc == 1 and seen == videos[:1]
    assert "halott motor" in capsys.readouterr().err


def test_overlay_line_is_dropped(tmp_path, cfg):
    """A minden cue-ban ott lévő sor (vízjel) nem kerül a szövegbe."""
    cues = [{"num": str(i), "timestamp": "", "start": 2.0 * i, "end": 2.0 * i + 1.5}
            for i in range(12)]
    make_frames(tmp_path, range(0, 100))
    answers = {}
    for c in cues:
        for n in ocr.sample_frames(c["start"], c["end"], 4.0):
            answers[ocr.frame_file(tmp_path, n).name] = [("字幕组出品", 1.0), (f"第{c['num']}句话", 0.9)]
    rec = ocr.Recognizer(FakeEngine(answers), ocr.LineFilter("chi"))
    texts, _ = ocr.align(cues, tmp_path, rec, cfg, None, log=lambda *_: None)
    assert texts == [f"第{c['num']}句话" for c in cues]


def test_single_char_noise_needs_confidence(tmp_path, cfg):
    """Egy írásjegy gyenge megbízhatósággal (él → 一) nem tölti ki a cue-t; erősen igen (嗯)."""
    cues = [{"num": "1", "timestamp": "", "start": 1.0, "end": 3.0},
            {"num": "2", "timestamp": "", "start": 5.0, "end": 7.0}]
    make_frames(tmp_path, range(40))
    answers = {}
    for n in ocr.sample_frames(1.0, 3.0, 4.0):
        answers[ocr.frame_file(tmp_path, n).name] = [("一", 0.3)]
    for n in ocr.sample_frames(5.0, 7.0, 4.0):
        answers[ocr.frame_file(tmp_path, n).name] = [("嗯", 0.95)]
    cfg["retry_frames"] = 0
    rec = ocr.Recognizer(FakeEngine(answers), ocr.LineFilter("chi"))
    texts, _ = ocr.align(cues, tmp_path, rec, cfg, None, log=lambda *_: None)
    assert texts == ["", "嗯"]


def test_overlay_variant_reading_is_dropped(tmp_path, cfg):
    """A vízjel kissé eltérő kiolvasása (rész-szöveg, egy betű eltérés) is kimarad."""
    rec = ocr.Recognizer(FakeEngine({}), ocr.LineFilter("chi"))
    rec.overlay = {"腾讯视频独播"}
    assert ocr.is_overlay("腾讯视频", rec.overlay)            # rész-szöveg
    assert ocr.is_overlay("腾讯視频独播", rec.overlay)        # egy írásjegy eltér
    assert not ocr.is_overlay("我们走吧", rec.overlay)
    assert not ocr.is_overlay("好", {"好的"})                # rövid vízjelnél csak pontos


def test_retry_winner_repeated_in_many_cues_is_dropped(tmp_path, cfg):
    """Felirat nélküli cue-kban csak a vízjel látszik: ha a pótló körben sok üres
    cue-ban ugyanaz „nyer”, az nem felirat."""
    cues = [{"num": str(i), "timestamp": "", "start": 3.0 * i, "end": 3.0 * i + 2.0}
            for i in range(30)]
    make_frames(tmp_path, range(0, 400))
    main = {ocr.frame_file(tmp_path, n).name
            for c in cues for n in ocr.sample_frames(c["start"], c["end"], 4.0)}
    answers = {f"{n:06d}.png": [("腾讯视", 0.9)] for n in range(400)
               if f"{n:06d}.png" not in main}
    answers[ocr.frame_file(tmp_path, 1).name] = [("你好", 0.9)]
    rec = ocr.Recognizer(FakeEngine(answers), ocr.LineFilter("chi"))
    texts, stats = ocr.align(cues, tmp_path, rec, cfg, None, log=lambda *_: None)
    assert "腾讯视" not in texts and stats["retried"] == 0


def test_too_few_frames_is_fail(tmp_path, cfg):
    """A videó rövidebb a forrás SRT-nél: ne legyen csupa `—` kimenet."""
    cues = [{"num": str(i), "timestamp": "", "start": 3.0 * i, "end": 3.0 * i + 2.0}
            for i in range(10)]
    rec = ocr.Recognizer(FakeEngine({}), ocr.LineFilter("chi"))
    with pytest.raises(ocr.Fail, match="rövidebb"):
        ocr.align(cues, tmp_path, rec, cfg, None, extractor=lambda ns: make_frames(tmp_path, [0, 1]),
                  log=lambda *_: None)


def test_retry_dedupes_overlapping_frames(tmp_path, cfg):
    cues = [{"num": "1", "timestamp": "", "start": 1.0, "end": 3.0},
            {"num": "2", "timestamp": "", "start": 1.5, "end": 3.5}]   # átfedő cue-k
    make_frames(tmp_path, range(40))
    got = []

    def binarizer(paths):
        got.extend(paths)
        return {}
    rec = ocr.Recognizer(FakeEngine({}), ocr.LineFilter("chi"))
    ocr.align(cues, tmp_path, rec, cfg, binarizer, log=lambda *_: None)
    assert len(got) == len(set(got)) > 0


def test_recognizer_tolerates_few_unreadable(tmp_path):
    make_frames(tmp_path, [1, 2, 3])

    class Mixed(FakeEngine):
        def recognize(self, paths):
            return [None if Path(p).name == "000001.png" else [] for p in paths]
    rec = ocr.Recognizer(Mixed({}), ocr.LineFilter("chi"))
    rec.run([ocr.frame_file(tmp_path, n) for n in (1, 2, 3)])
    assert (rec.read, rec.unreadable) == (3, 1)
    rec.check()   # 1/3 olvashatatlan: még nem motorhiba
    rec.reset()
    assert (rec.read, rec.unreadable, rec.cache) == (0, 0, {})


def test_align_extracts_only_needed_frames(tmp_path, cfg):
    """A fő kör a mintavételi kockákat kéri, a pótló kör csak az újakat."""
    cues = [{"num": "1", "timestamp": "", "start": 1.0, "end": 3.0},
            {"num": "2", "timestamp": "", "start": 10.0, "end": 11.0}]
    asked = []

    def extractor(nums):
        asked.append(set(nums))
        make_frames(tmp_path, nums)

    answers = {"000007.png": [("你好", 1.0)]}
    rec = ocr.Recognizer(FakeEngine(answers), ocr.LineFilter("chi"))
    texts, _ = ocr.align(cues, tmp_path, rec, cfg, None, extractor, log=lambda *_: None)
    assert texts == ["你好", ""]
    main = set(ocr.sample_frames(1.0, 3.0, 4.0)) | set(ocr.sample_frames(10.0, 11.0, 4.0))
    assert asked[0] == main
    assert asked[1] == set(ocr.retry_frames(10.0, 11.0, 4.0, 8)) - main
    assert len(asked) == 2


def test_select_expr_merges_runs_into_balanced_tree():
    assert ocr.select_expr([12, 3, 10, 11, 40, 3]) == \
        "(eq(n\\,3)+(between(n\\,10\\,12)+eq(n\\,40)))"
    deep = ocr.select_expr(range(0, 40000, 2))   # 20 000 különálló tag
    assert max(_depths(deep)) <= 20   # log2(20 000) ≈ 15 szint + az eq( zárójele


def _depths(expr):
    d = 0
    for ch in expr:
        d += ch == "("
        d -= ch == ")"
        yield d


def _ffmpeg():
    for cand in ("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", shutil.which("ffmpeg")):
        if cand and Path(cand).exists():
            return cand
    return None


@pytest.mark.skipif(not _ffmpeg(), reason="nincs ffmpeg")
def test_extract_frames_maps_to_container_time(tmp_path):
    """Az n. kocka a videó n/fps időpontjában látható kép — akkor is, ha a
    képsáv 1 mp-cel a hang után indul —, és több száz különálló sorszám is
    megy (az ffmpeg a lapos `eq+eq+…` láncot 100 tag fölött elutasítja).

    A forrás minden képkockája más fényességű (Y = 2 × kockaszám), így a
    kivágott kép középső pixeléből visszaolvasható, melyik forráskocka az."""
    import subprocess
    ff = _ffmpeg()
    src_fps, offset = 25, 1.0
    video = tmp_path / "v.mkv"
    # A képsáv 1 mp-es késése: előbb a nyers kép, aztán a muxolás -itsoffset-tel
    # a (0-ról induló) hang mellé.
    raw = tmp_path / "raw.mkv"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"nullsrc=size=64x64:rate={src_fps},format=gray,geq=lum='2*N'",
                    "-t", "4", "-c:v", "ffv1", str(raw)], check=True)
    subprocess.run([ff, "-v", "error", "-y", "-itsoffset", str(offset), "-i", str(raw),
                    "-f", "lavfi", "-t", "5", "-i", "anullsrc=r=8000:cl=mono",
                    "-map", "0:v", "-map", "1:a", "-c", "copy", "-c:a", "pcm_s16le",
                    str(video)], check=True)
    fps = 4.0
    wanted = list(range(4, 20)) + list(range(0, 2000, 3))   # sok különálló tag is
    sel = tmp_path / "sel"
    sel.mkdir()
    ocr.extract_frames(video, sel, fps, 16, 32, wanted)

    def source_frame(png):
        out = subprocess.run([ff, "-v", "error", "-i", str(png), "-vf", "format=gray,crop=1:1:32:16",
                              "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
        return round(out[0] / 2)

    # A forrás kockái 1,0 mp-től 5,0 mp-ig: 16 ≤ n < 20 (4–5 mp) a vége
    for n in (4, 5, 7, 10, 13, 19):
        t = n / fps
        expected = int((t - offset) * src_fps + 1e-9)   # az n/fps-kor (vagy épp előtte) látható
        assert source_frame(ocr.frame_file(sel, n)) == expected, n
    assert not ocr.frame_file(sel, 1998).exists()   # a videó vége után nincs kocka


def test_align_without_retry(tmp_path, cfg):
    cues = [{"num": "1", "timestamp": "", "start": 1.0, "end": 3.0}]
    make_frames(tmp_path, range(20))
    cfg["retry_frames"] = 0
    eng = FakeEngine({})
    texts, stats = ocr.align(cues, tmp_path, ocr.Recognizer(eng, ocr.LineFilter("chi")),
                             cfg, None, log=lambda *_: None)
    assert texts == [""] and stats["empty"] == 1 and len(eng.calls) == 1


# ── fájlnevek ──────────────────────────────────────────────────────────────

def test_out_path_uses_lang_and_strips_video_lang_tag():
    assert ocr.out_path("Season 01/Sorozat - S01E01.mp4", "chi", "input") == \
        Path("input/Sorozat - S01E01.chi.ocr.srt")
    assert ocr.out_path("Sorozat - S01E01.kor.mkv", "kor", "x") == Path("x/Sorozat - S01E01.kor.ocr.srt")
    assert ocr.out_path("Sorozat - S01E01.mkv", "eng", "input") == Path("input/Sorozat - S01E01.eng.ocr.srt")


def test_out_path_is_machine_marked_and_keeps_lang():
    p = ocr.out_path("Sorozat - S01E01.mp4", "kor", "input")
    assert config.is_ocr_path(p) and config.is_machine_path(p)
    assert config.detect_source_lang(p) == "kor"
    assert p.name.endswith(f".kor{config.OCR_SUFFIX}.srt")


def test_find_ref_prefers_english(tmp_path):
    for code in ("kor", "eng"):
        (tmp_path / f"Sorozat - S01E01.{code}.srt").write_text("x")
    ref, err = ocr.find_ref("Season 01/Sorozat - S01E01.mp4", "chi", tmp_path)
    assert err is None and ref.name == "Sorozat - S01E01.eng.srt"


def test_find_ref_skips_ocr_language(tmp_path):
    (tmp_path / "Sorozat - S01E01.chi.srt").write_text("x")   # az OCR nyelve: nem forrás
    (tmp_path / "Sorozat - S01E01.eng.ocr.srt").write_text("x")   # gépi kinyerés: soha
    (tmp_path / "Sorozat - S01E01.ger.srt").write_text("x")
    ref, err = ocr.find_ref("Sorozat - S01E01.mp4", "chi", tmp_path)
    assert err is None and ref.name == "Sorozat - S01E01.ger.srt"


def test_find_ref_missing_or_ambiguous(tmp_path):
    ref, err = ocr.find_ref("Sorozat - S01E01.mp4", "chi", tmp_path)
    assert ref is None and "--ref" in err
    for code in ("ger", "fre"):
        (tmp_path / f"Sorozat - S01E01.{code}.srt").write_text("x")
    ref, err = ocr.find_ref("Sorozat - S01E01.mp4", "chi", tmp_path)
    assert ref is None and "--ref" in err


# ── beállítások ────────────────────────────────────────────────────────────

def test_defaults(cfg):
    assert cfg["lang"] == "chi" and cfg["engine"] == "auto"
    assert cfg["top"] == pytest.approx(0.833) and cfg["fps"] == 4.0
    assert cfg["retry_min_conf"] == 0.5 and cfg["retry_frames"] == 8
    assert cfg["drop_latin"] is None and cfg["lang_src"] == "alap"


def test_switch_beats_env_beats_default(monkeypatch):
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("HARDSUB_OCR_LANG", "ko")
    monkeypatch.setenv("HARDSUB_OCR_FPS", "2")
    c = ocr.resolve(ocr.build_parser().parse_args(["x.mp4", "--fps", "3"]))
    assert c["lang"] == "kor" and c["lang_src"] == ".env"
    assert c["fps"] == 3.0 and c["fps_src"] == "kapcsoló"


@pytest.mark.parametrize("argv", [["--lang", "xx"], ["--engine", "tesseract"],
                                  ["--min-conf", "2"], ["--bin-threshold", "300"],
                                  ["--ad-extra", "(unclosed"], ["--fps", "abc"],
                                  ["--drop-latin", "maybe"]])
def test_bad_values_exit(monkeypatch, argv):
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    with pytest.raises(SystemExit):
        ocr.resolve(ocr.build_parser().parse_args(["x.mp4", *argv]))


def test_existing_output_is_skipped_without_force(tmp_path, monkeypatch, capsys):
    video = tmp_path / "Sorozat - S01E01.mp4"
    video.write_bytes(b"")
    (tmp_path / "Sorozat - S01E01.eng.srt").write_text(SRT, encoding="utf-8")
    dest = tmp_path / "Sorozat - S01E01.chi.ocr.srt"
    dest.write_text("régi", encoding="utf-8")
    monkeypatch.setattr(ocr, "require_tools", lambda: None)
    monkeypatch.setattr(ocr, "load_dotenv", lambda: None)
    monkeypatch.setattr(ocr.engines, "create", lambda *a: pytest.fail("nem kellett volna motor"))
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    rc = ocr.main([str(video), "--ref-dir", str(tmp_path), "--out-dir", str(tmp_path)])
    assert rc == 0 and dest.read_text(encoding="utf-8") == "régi"
    assert "KÉSZ, kihagyva" in capsys.readouterr().out


def test_output_never_overwrites_ref(tmp_path, monkeypatch):
    video = tmp_path / "Sorozat - S01E01.mp4"
    video.write_bytes(b"")
    ref = tmp_path / "Sorozat - S01E01.eng.ocr.srt"   # (rossz) forrásnak egy korábbi kimenet
    ref.write_text(SRT, encoding="utf-8")
    monkeypatch.setattr(ocr, "require_tools", lambda: None)
    monkeypatch.setattr(ocr, "load_dotenv", lambda: None)
    monkeypatch.setattr(ocr.engines, "create", lambda *a: pytest.fail("nem kellett volna motor"))
    for env, *_ in ocr.SETTINGS.values():
        monkeypatch.delenv(env, raising=False)
    rc = ocr.main([str(video), "--ref", str(ref), "--lang", "eng", "--out-dir", str(tmp_path),
                   "--force"])
    assert rc == 1 and ref.read_text(encoding="utf-8") == SRT


# ── motorok (csak a motorfüggetlen részük) ─────────────────────────────────

def test_pick_engine():
    assert engines.pick_engine("auto", "darwin") == "vision"
    assert engines.pick_engine("auto", "win32") == "rapidocr"
    assert engines.pick_engine("auto", "linux") == "rapidocr"
    assert engines.pick_engine("rapidocr", "darwin") == "rapidocr"


def test_parse_vision_output():
    out = engines.parse_vision_output('[["你好", 1.0], ["再见", 0.5]]\nnull\n[]\n', 3)
    assert out == [[("你好", 1.0), ("再见", 0.5)], None, []]
    with pytest.raises(engines.EngineError):
        engines.parse_vision_output("[]\n", 2)


def test_binary_name_changes_with_source(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDSUB_OCR_CACHE_DIR", str(tmp_path))
    src = tmp_path / "a.swift"
    src.write_text("print(1)")
    a = engines.binary_path(src, "swift 6")
    src.write_text("print(2)")
    b = engines.binary_path(src, "swift 6")
    assert a != b and a.parent == tmp_path
    assert engines.binary_path(src, "swift 7") != b


def test_vision_engine_lang_tolerates_spaces(monkeypatch):
    monkeypatch.setattr(engines.sys, "platform", "darwin")
    monkeypatch.setattr(engines, "build_vision_helper", lambda: Path("vocr"))
    monkeypatch.setattr(engines.VisionEngine, "supported",
                        lambda self: ["zh-Hans", "zh-Hant", "en-US"])
    eng = engines.VisionEngine("chi", " zh-Hant, zh-Hans ,")
    assert eng.lang == "zh-Hant,zh-Hans"
    with pytest.raises(engines.EngineError, match="xx-YY"):
        engines.VisionEngine("chi", "zh-Hans, xx-YY")


def test_vision_helper_build_uses_unique_part_file(tmp_path, monkeypatch):
    """Két egyszerre induló első futás ne írjon ugyanabba a félkész fájlba."""
    monkeypatch.setenv("HARDSUB_OCR_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(engines, "find_swiftc", lambda: "swiftc")
    outs = []

    class R:
        returncode, stdout, stderr = 0, "swift 6", ""

    def fake_run(cmd, input=None):
        if "-o" in cmd:
            out = Path(cmd[cmd.index("-o") + 1])
            assert out.exists()   # a mkstemp már létrehozta
            out.write_bytes(b"bin")
            outs.append(out)
        return R()
    monkeypatch.setattr(engines, "_run", fake_run)
    exe = engines.build_vision_helper()
    assert exe.read_bytes() == b"bin" and exe.parent == tmp_path
    assert outs[0].name.startswith(exe.name + ".") and outs[0].name.endswith(".part")
    assert not outs[0].exists()
    assert engines.build_vision_helper() == exe and len(outs) == 1   # második futás: kész


def test_engine_lang_maps_cover_filter_langs():
    """Minden nyelvhez, amit a szűrő ismer, legyen legalább az egyik motorban leképezés."""
    for lang in ocr.LANG_SCRIPT:
        assert lang in engines.VISION_LANGS or lang in engines.RAPID_LANGS


def _fake_rapidocr(monkeypatch, fail_on, calls):
    """Hamis `rapidocr` modul: a konstruktor mindig sikerül (mint a valódi, lusta
    betöltésnél), a bemelegítő hívás a `fail_on` modellnél hibázik (ocr_version
    neve, None = alapmodell)."""
    import enum
    import types
    mod = types.ModuleType("rapidocr")

    class LangRec(enum.Enum):
        CH, KOREAN, LATIN = "ch", "korean", "latin"

    class OCRVersion(enum.Enum):
        V4, V5, V6 = "PP-OCRv4", "PP-OCRv5", "PP-OCRv6"

    class ModelType(enum.Enum):
        MOBILE, SMALL = "mobile", "small"

    class Out:
        txts, scores = ("안녕",), (0.9,)

    class RapidOCR:
        def __init__(self, params):
            self.params = params
            self.use_det = self.use_cls = self.use_rec = True

        def _load_det_model(self):
            calls.append(("det", self.params.get("Rec.ocr_version")))

        def _load_cls_model(self):
            calls.append(("cls", self.params.get("Rec.ocr_version")))

        def __call__(self, img, use_det=None, use_cls=None, use_rec=None):
            ver = self.params.get("Rec.ocr_version")
            if not isinstance(img, str) and (ver.value if ver else None) in fail_on:
                raise ValueError(f"Unsupported rec.lang_type for {ver}")
            for k, v in (("use_det", use_det), ("use_cls", use_cls), ("use_rec", use_rec)):
                if v is not None:
                    setattr(self, k, v)   # a valódi RapidOCR is megjegyzi
            calls.append(("call", ver, self.use_det, self.use_cls, self.use_rec))
            return Out()

    mod.LangRec, mod.OCRVersion, mod.ModelType, mod.RapidOCR = LangRec, OCRVersion, ModelType, RapidOCR
    monkeypatch.setitem(sys.modules, "rapidocr", mod)
    np = types.ModuleType("numpy")
    np.zeros = lambda shape, dtype=None: ("zeros", shape)
    np.uint8 = "uint8"
    monkeypatch.setitem(sys.modules, "numpy", np)
    return mod


def test_rapidocr_falls_back_to_older_model_and_restores_steps(monkeypatch):
    calls = []
    mod = _fake_rapidocr(monkeypatch, fail_on={None}, calls=calls)   # az alapmodell nem tud koreaiul
    eng = engines.RapidOcrEngine("kor")
    assert eng._ocr.params["Rec.ocr_version"] == mod.OCRVersion("PP-OCRv5")
    assert ("det", mod.OCRVersion("PP-OCRv5")) in calls and ("cls", mod.OCRVersion("PP-OCRv5")) in calls
    calls.clear()
    assert eng.recognize(["a.png"]) == [[("안녕", 0.9)]]
    # a bemelegítés use_det=False-a nem marad meg: a képet kereséssel olvassa
    assert calls == [("call", mod.OCRVersion("PP-OCRv5"), True, True, True)]


def test_rapidocr_native_v6_code_then_latin_fallback(monkeypatch):
    calls = []
    _fake_rapidocr(monkeypatch, fail_on={None}, calls=calls)
    eng = engines.RapidOcrEngine("ger")
    # az alapmodell a „de” kódot kapta (szövegként), a tartalék a közös latin modellt
    assert eng._ocr.params["Rec.lang_type"].value == "latin"


def test_rapidocr_all_models_fail_is_engine_error(monkeypatch):
    calls = []
    _fake_rapidocr(monkeypatch, fail_on={None, "PP-OCRv4", "PP-OCRv5", "PP-OCRv6"}, calls=calls)
    with pytest.raises(engines.EngineError, match="Próbálkozások"):
        engines.RapidOcrEngine("kor")


def test_rapidocr_missing_package_message(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name.startswith("rapidocr"):
            raise ImportError(name)
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(engines.EngineError, match="pip install"):
        engines.RapidOcrEngine("chi")
