"""scripts/check_copyright.py — a commit előtti jogvédett-tartalom szűrő.

Minden fixture kitalált; a szabályokat sztringeken teszteljük, git nélkül.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_copyright.py"
_spec = importlib.util.spec_from_file_location("check_copyright", SCRIPT)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


# ── 1. tiltott útvonalak ──

@pytest.mark.parametrize("path", [
    ".env", ".env.local", "sub/.env",
    "TRANSLATION.local.md", "Season 01/TRANSLATION.local.md",
    "input/Sorozat - S01E01.eng.srt", "output/Sorozat - S01E01.hun.srt",
    "blocks/Sorozat - S01E01.eng/block_001.srt", "output/valami.txt",
    "output/Sorozat - S01E01.hun_REVIEW_GEMINI.json", "x_REVIEW_CLAUDE.txt",
    "decisions.json", ".translate.log", ".translate.log.1",
    ".translate_sys_prompt_abc.txt", ".review_claude_sys_prompt_x.txt",
    "anything.srt", "docs/sample.VTT", "movie.mkv", "audio.mp3",
    ".copyright-blocklist",
])
def test_tiltott_utvonal(path):
    assert cc.forbidden_path(path) is not None


@pytest.mark.parametrize("path", [
    ".env.example", ".copyright-blocklist.example", "TRANSLATION.md",
    "input/.gitkeep", "output/.gitkeep", "blocks/.gitkeep",
    "tests/test_srt.py", "README.md", "subtr/srt.py", "addons/vtt2srt/vtt2srt.py",
    "resegment_srt.md",           # a név tartalmazza az srt-t, de .md
])
def test_engedett_utvonal(path):
    assert cc.forbidden_path(path) is None


def test_windows_utvonal_is():
    assert cc.forbidden_path("output\\x.srt") is not None


# ── 2. titkok ──

@pytest.mark.parametrize("line,label", [
    ("key = 'sk-ant-api03-" + "a" * 40 + "'", "Anthropic kulcs"),
    ("AIza" + "B" * 35, "Google API kulcs"),
    ("XAI_API_KEY=xai-" + "c" * 30, "xAI kulcs"),
    ("token: ghp_" + "d" * 36, "GitHub token"),
    ("GEMINI_API_KEY=" + "e" * 39, "kitöltött GEMINI_API_KEY"),
    ("TMDB_API_KEY = \"" + "0123456789abcdef" * 2 + "\"", "kitöltött TMDB_API_KEY"),
])
def test_titok_felismeres(line, label):
    assert cc.secret_findings("x\n" + line + "\n") == [(2, label)]


@pytest.mark.parametrize("line", [
    "GEMINI_API_KEY=your-api-key-here",
    "# TMDB_API_KEY=your-tmdb-key-here",
    '"anthropic": "sk-ant-...",',
    '"google": "AIza..."',
    "XAI_API_KEY=xai-...",
    "GEMINI_API_KEY=",
    "GEMINI_API_KEY=${GEMINI_API_KEY}",
    "SUBTR_GEMINI_MODEL=gemini-3.6-flash",     # nem kulcs
])
def test_placeholder_nem_titok(line):
    assert cc.secret_findings(line) == []


# ── 3. felirat-tömeg ──

def _srt(n, lyric=False):
    return "".join(
        f"{i}\n00:00:{i % 60:02d},000 --> 00:00:{i % 60:02d},500\n{'♪ la ♪' if lyric else 'Szia!'}\n\n"
        for i in range(1, n + 1))


def test_kis_fixture_atmegy():
    assert cc.bulk_findings(_srt(16)) == []


def test_teljes_blokk_fennakad():
    msgs = cc.bulk_findings(_srt(150))
    assert len(msgs) == 1 and "150 SRT-időbélyeg" in msgs[0]


def test_dalszoveg_fennakad():
    assert cc.bulk_findings(_srt(7, lyric=True)) == []
    msgs = cc.bulk_findings(_srt(12, lyric=True))
    assert any("♪-sor" in m for m in msgs)


def test_pontos_ezredmasodperc_is_cue():
    assert cc.bulk_findings("00:00:01.000 --> 00:00:02.000\n" * 30)


# ── 4. terminusok ──

LOCAL_MD = """Title: Office Sparks (2024) (职场火花)
Hungarian title: Irodai szikrák
Country: China
Episodes: 36

Synopsis:
Valami.

Cast:

- Wang Zi Hao as Lu Yan (Main Role)
- Zhao Mei Lin as Shen Qing — Lu Yan főnöke (Main Role)
- Lin Xiao He (Support Role)
- TODO: szereplők

Megszólítási regiszter:   (frissítendő MINDEN epizód előtt)
  - TODO: Lu Yan → Shen Qing: MAGÁZ | TEGEZ  (viszony)
"""


def test_terms_from_local_md():
    t = cc.terms_from_local_md(LOCAL_MD)
    assert t == {"Office Sparks", "职场火花", "Irodai szikrák",
                 "Wang Zi Hao", "Lu Yan", "Zhao Mei Lin", "Shen Qing", "Lin Xiao He"}


def test_terms_from_local_md_todo_cim_kimarad():
    t = cc.terms_from_local_md("Title: X (2026)\nHungarian title: TODO: magyar cím\n")
    assert t == {"X"}


def test_terms_from_glossary():
    gl = ('{"meta": {"series": "Office Sparks"}, "honorifics": [{"en": "Chairman", "hu": "elnök úr"}],'
          ' "character_names": [{"en": "Lu Yan", "hu": "Lu Yan"}, {"en": "Old Wang", "hu": "Wang bácsi"}],'
          ' "special_terms": [], "place_names": [], "phrases": []}')
    assert cc.terms_from_glossary(gl) == {"Office Sparks", "Lu Yan", "Old Wang", "Wang bácsi"}
    assert cc.terms_from_glossary("{ broken") == set()


def test_terms_from_blocklist():
    assert cc.terms_from_blocklist("# komment\n\nPull Threads   # régi\n  A csendes kikötő\n") \
        == {"Pull Threads", "A csendes kikötő"}


def test_usable_terms_rovideket_kiszuri_es_hosszabb_elol():
    assert cc.usable_terms({"Yan", "Lu Yan", "Irodai szikrák", "Ab"}) == ["Irodai szikrák", "Lu Yan"]


def test_term_findings_egesz_szo_kisbetu():
    terms = cc.usable_terms({"Lu Yan", "Office Sparks"})
    text = "első sor\nEgy office sparks nevű sorozat\nLuYanka nem talál\nLU YAN igen\n"
    assert cc.term_findings(text, terms) == [(2, "office sparks"), (4, "LU YAN")]
    assert cc.term_findings("semmi", []) == []


def test_collect_terms_a_harom_forrasbol(tmp_path):
    (tmp_path / "TRANSLATION.local.md").write_text(LOCAL_MD, encoding="utf-8")
    (tmp_path / "glossary.json").write_text(
        '{"meta": {"series": "Office Sparks"}, "character_names": [{"en": "Old Wang", "hu": ""}]}',
        encoding="utf-8")
    (tmp_path / ".copyright-blocklist").write_text("Pull Threads\n", encoding="utf-8")
    terms = cc.collect_terms(tmp_path)
    assert "Pull Threads" in terms and "Old Wang" in terms and "Irodai szikrák" in terms
    assert cc.collect_terms(tmp_path / "nincs") == []


# ── az egész: check_files ──

def test_check_files_riport():
    terms = cc.usable_terms({"Office Sparks", "Lu Yan"})
    files = [
        ("README.md", "Tiszta doksi.\n".encode()),
        ("tests/test_x.py", "cue = 'Lu Yan!'\n".encode()),
        ("output/x.srt", b"1\n"),
        ("notes/Office Sparks.md", b"semmi"),
        ("bin.dat", b"\0\0Lu Yan"),                       # bináris: tartalom kimarad
        ("cfg.py", b"GEMINI_API_KEY='" + b"k" * 40 + b"'\n"),
    ]
    out = cc.check_files(files, terms)
    assert out == [
        "tests/test_x.py:1: SOROZAT-TERMINUS — „Lu Yan”",
        "output/x.srt: TILTOTT ÚTVONAL — munkamappa tartalma (input/ output/ blocks/)",
        "notes/Office Sparks.md: SOROZAT-TERMINUS a fájlnévben — „Office Sparks”",
        "cfg.py:1: TITOK — kitöltött GEMINI_API_KEY",
    ]


def test_check_files_tiszta():
    assert cc.check_files([("a.py", b"print(1)\n")], ["Office Sparks"]) == []


def test_main_skip_env(monkeypatch, capsys):
    monkeypatch.setenv("SKIP_COPYRIGHT_CHECK", "1")
    assert cc.main([]) == 0
    assert "kihagyva" in capsys.readouterr().out


def test_main_terms_lista(monkeypatch, capsys):
    monkeypatch.delenv("SKIP_COPYRIGHT_CHECK", raising=False)
    monkeypatch.setattr(cc, "collect_terms", lambda: ["Office Sparks"])
    assert cc.main(["--terms"]) == 0
    assert "Office Sparks" in capsys.readouterr().out


def test_main_talalatnal_1_es_riport(monkeypatch, capsys):
    monkeypatch.delenv("SKIP_COPYRIGHT_CHECK", raising=False)
    monkeypatch.setattr(cc, "collect_terms", lambda: ["Office Sparks"])
    monkeypatch.setattr(cc, "staged_files", lambda: [("x.md", "Office Sparks!\n".encode())])
    assert cc.main([]) == 1
    out = capsys.readouterr().out
    assert "LEÁLLÍTVA" in out and "x.md:1" in out and "SKIP_COPYRIGHT_CHECK" in out


def test_main_tiszta_0(monkeypatch, capsys):
    monkeypatch.delenv("SKIP_COPYRIGHT_CHECK", raising=False)
    monkeypatch.setattr(cc, "collect_terms", lambda: ["Office Sparks"])
    monkeypatch.setattr(cc, "staged_files", lambda: [("x.md", b"tiszta\n")])
    assert cc.main([]) == 0
    assert capsys.readouterr().out == ""
