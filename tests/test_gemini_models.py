"""subtr.gemini_models — a rate-limit oldal / docs-oldalak feldolgozása, név →
kód párosítás, kivezetések, modellváltás napi limitnél. Hálózat nélkül."""

import json
from datetime import date

import pytest

from subtr import config, gemini_models as gm, quota

# Az AI Studio rate-limit oldal kimásolt szövege (soronként tagolva, ahogy a
# böngésző a Ctrl+A / Ctrl+C-t adja), rövidítve.
PAGE = """Gemini API Rate Limit
Free tier
Project
SubTitle
Rate limits by model
All models
Model

Category

RPM

TPM

RPD
Charts

Gemini 3.8 Flash
Text-out models
4 / 5

38.32K / 250K

17 / 20

bar_chart

Gemini 4 Argon
Text-out models
0 / 0

0 / 0

0 / 0

bar_chart

Gemini 3.1 Flash Lite
Text-out models
0 / 15

0 / 250K

0 / 500

bar_chart

Gemma 4 31B
Other models
0 / 30

0 / 16K

0 / 14.4K

bar_chart

Gemini 3.8 Live
Live API
0 / Unlimited

0 / 65K

0 / Unlimited

bar_chart

Tools
Gemini 2
info
Search grounding - -
0 / 1.5K
"""

DOCS = """<pre>
{% card badge=&quot;Stable&quot; href=&quot;/docs/models/gemini-3.8-flash&quot; title=&quot;Gemini 3.8 Flash&quot; variant=&quot;model&quot; /%}
{% table variant=&quot;model&quot; %}
  * Model
  * Description
  * Endpoint

  ---

  * [Gemini 3.1 Flash-Lite](/docs/models/gemini-3.1-flash-lite)
  * Cheap and fast.
  * `gemini-3.1-flash-lite`

  ---

  * [Gemini 3 Flash](/docs/models/gemini-3-flash-preview)
  * `gemini-3-flash-preview`

  ---

  * [Gemini 2.0 Flash](/docs/models/gemini-2.0-flash) (Shut down)
  * Old.
  * `gemini-2.0-flash`
{% /table %}
</pre>"""

DEPRECATIONS = """<pre>
{% table %}
  * Model
  * Release date
  * Shutdown date
  * Recommended replacement

  ---

  * `gemini-3.8-flash`
  * September 2, 2026
  * No shutdown date announced
  *

  ---

  * `gemini-3.7-flash`
  * August 13, 2026
  * N/A
  * `gemini-3.8-flash` (the endpoint is not shutting down and automatically routes
    API requests to `gemini-3.8-flash`)

  ---

  * `gemini-2.5-flash`
  * June 17, 2025
  * December 1, 2026
  * `gemini-3.5-flash-lite` (effective December 1, 2026, API requests will
    automatically route to `gemini-3.5-flash-lite`)
{% /table %}
</pre>"""


@pytest.fixture
def data_file(tmp_path, monkeypatch):
    """Rögzített adatfájl + üres kvótanapló + üres gépszintű fájl + ismert
    beállítások."""
    def write(data):
        path = tmp_path / "gemini_models.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(gm, "DATA_PATH", path)
        gm.clear_cache()
    monkeypatch.setenv("GEMINI_QUOTA_FILE", str(tmp_path / "usage.json"))
    monkeypatch.setenv("GEMINI_MODELS_LOCAL_FILE", str(tmp_path / "models.json"))
    monkeypatch.setenv("GEMINI_API_KEY", "teszt-kulcs")
    monkeypatch.setattr(config, "_DEFAULTS", {})
    for key in (gm.ON_QUOTA_KEY, gm.FALLBACK_KEY):
        monkeypatch.delenv(key, raising=False)
    yield write
    gm.clear_cache()


def _models(**rpd):
    return {"models": {m.replace("_", "-"): {"category": gm.TEXT_CATEGORY, "rpd": v}
                       for m, v in rpd.items()}, "deprecations": {}}


# --- rate-limit oldal ---------------------------------------------------------

@pytest.mark.parametrize("text,value", [
    ("250K", 250_000), ("14.4K", 14_400), ("14,4K", 14_400), ("1M", 1_000_000),
    ("20", 20), ("0", 0), ("Unlimited", None), ("1,500", 1_500), ("10,000", 10_000)])
def test_parse_amount(text, value):
    assert gm.parse_amount(text) == value


def test_parse_amount_rejects_garbage():
    with pytest.raises(ValueError):
        gm.parse_amount("bar_chart")


def test_parse_rate_limit_page():
    page = gm.parse_rate_limit_page(PAGE)
    assert page["tier"] == "Free tier"
    rows = {r["label"]: r for r in page["rows"]}
    assert list(rows) == ["Gemini 3.8 Flash", "Gemini 4 Argon", "Gemini 3.1 Flash Lite",
                          "Gemma 4 31B", "Gemini 3.8 Live"]   # a Tools szakasz kimarad
    flash = rows["Gemini 3.8 Flash"]
    assert (flash["category"], flash["rpm"], flash["tpm"], flash["rpd"]) == \
        ("Text-out models", 5, 250_000, 20)
    assert flash["used"] == {"rpm": 4, "tpm": 38_320, "rpd": 17}
    assert rows["Gemma 4 31B"]["rpd"] == 14_400
    assert rows["Gemini 3.8 Live"]["rpd"] is None


def test_parse_rate_limit_page_tab_separated():
    text = ("Free tier\nModel\tCategory\tRPM\tTPM\tRPD\n"
            "Gemini 3.8 Flash\tText-out models\t4 / 5\t38.32K / 250K\t17 / 20\tbar_chart\n")
    rows = gm.parse_rate_limit_page(text)["rows"]
    assert [(r["label"], r["rpd"]) for r in rows] == [("Gemini 3.8 Flash", 20)]


def test_parse_rate_limit_page_without_table():
    assert gm.parse_rate_limit_page("valami teljesen más szöveg")["rows"] == []


# --- docs-oldalak -------------------------------------------------------------

def test_parse_docs_models():
    docs = gm.parse_docs_models(DOCS)
    assert docs["names"]["Gemini 3.1 Flash-Lite"] == "gemini-3.1-flash-lite"
    assert docs["names"]["Gemini 3 Flash"] == "gemini-3-flash-preview"
    assert docs["names"]["Gemini 3.8 Flash"] == "gemini-3.8-flash"
    assert docs["status"] == {"gemini-3.8-flash": "Stable"}
    assert docs["shut_down"] == ["gemini-2.0-flash"]


def test_parse_deprecations():
    deps = gm.parse_deprecations(DEPRECATIONS)
    assert "gemini-3.8-flash" not in deps          # se leállás, se utód
    assert deps["gemini-3.7-flash"]["replacement"] == "gemini-3.8-flash"
    assert deps["gemini-3.7-flash"]["routes"] is True
    assert deps["gemini-3.7-flash"]["routes_from"] is None
    assert deps["gemini-3.7-flash"]["shutdown"] is None
    # „Effective December 1, 2026 … will automatically route”: csak akkortól
    assert deps["gemini-2.5-flash"] == {**deps["gemini-2.5-flash"],
                                        "replacement": "gemini-3.5-flash-lite",
                                        "shutdown": "2026-12-01", "routes": True,
                                        "routes_from": "2026-12-01"}


def test_future_effective_routing_is_not_active_yet(data_file):
    data_file({"models": {}, "deprecations": gm.parse_deprecations(DEPRECATIONS)})
    assert gm.active_replacement("gemini-2.5-flash", date(2026, 11, 15)) is None
    assert gm.upcoming_shutdown("gemini-2.5-flash", date(2026, 11, 15)) == \
        ("2026-12-01", "gemini-3.5-flash-lite")
    assert gm.active_replacement("gemini-2.5-flash", date(2026, 12, 1))[0] == \
        "gemini-3.5-flash-lite"
    assert gm.active_replacement("gemini-3.7-flash", date(2026, 11, 15))[0] == \
        "gemini-3.8-flash"


# --- név → kód ----------------------------------------------------------------

def test_match_label_sources():
    docs = gm.parse_docs_models(DOCS)["names"]
    api = {"gemini-3.8-flash": "Gemini 3.8 Flash", "gemma-4-31b-it": "Gemma 4 31B IT",
           "gemma-4-26b-a4b-it": "Gemma 4 26B A4B IT",
           "gemini-2.5-flash-lite": "Gemini 2.5 Flash-Lite",
           "gemini-x-preview": "Gemini X Preview", "gemini-x": "Gemini X"}
    assert gm.match_label("Gemini 3.1 Flash Lite", docs, api) == "gemini-3.1-flash-lite"
    assert gm.match_label("Gemini 3 Flash", docs, api) == "gemini-3-flash-preview"
    assert gm.match_label("Gemini 2.5 Flash Lite", docs, api) == "gemini-2.5-flash-lite"
    assert gm.match_label("Gemma 4 31B", docs, api) == "gemma-4-31b-it"
    assert gm.match_label("Gemma 4 26B", docs, api) == "gemma-4-26b-a4b-it"
    assert gm.match_label("Gemini X", docs, api) == "gemini-x"   # nem-preview előnyben
    assert gm.match_label("Gemini 2 Flash", docs, api) is None
    # API nélkül a névből képzett kód
    assert gm.match_label("Gemini 4 Hydrogen", {}, None) == "gemini-4-hydrogen"


def test_build_data_keeps_what_did_not_download():
    old = {"tier": "Free tier", "updated": "2026-01-01",
           "models": {"gemini-a": {"label": "Gemini A", "rpd": 20}},
           "deprecations": {"gemini-old": {"replacement": "gemini-a"}}}
    new = gm.build_data(old, None, None, None, {"gemini-b": "Gemini B"},
                        today=date(2026, 11, 15))
    assert new["models"]["gemini-a"]["rpd"] == 20            # a limitek maradtak
    assert "in_api" not in new["models"]["gemini-a"]         # kulcsfüggő: nem a repóba
    assert "api_only" not in new
    assert new["deprecations"] == old["deprecations"]
    assert new["updated"] == "2026-01-01"                    # limit nem frissült


def test_build_data_page_without_docs_keeps_status():
    old = {"models": {"gemini-3.8-flash": {"label": "Gemini 3.8 Flash", "rpd": 20,
                                           "status": "Stable", "shut_down": False}}}
    new = gm.build_data(old, gm.parse_rate_limit_page(PAGE), None, None, None,
                        today=date(2026, 11, 15))
    assert new["models"]["gemini-3.8-flash"]["status"] == "Stable"
    assert new["models"]["gemini-3.8-flash"]["shut_down"] is False


def test_build_data_from_page():
    page = gm.parse_rate_limit_page(PAGE)
    docs = gm.parse_docs_models(DOCS)
    new = gm.build_data({}, page, docs, gm.parse_deprecations(DEPRECATIONS), None,
                        today=date(2026, 11, 15))
    assert new["updated"] == "2026-11-15" and new["tier"] == "Free tier"
    assert new["models"]["gemini-3.8-flash"]["status"] == "Stable"
    assert new["models"]["gemini-4-argon"]["rpd"] == 0
    assert "gemini-2.5-flash" in new["deprecations"]
    assert any("gemini-3.8-flash" in line for line in gm.diff_lines({}, new))


# --- kivezetések --------------------------------------------------------------

def test_active_replacement_and_upcoming(data_file):
    data_file({"models": {}, "deprecations": {
        "a": {"replacement": "b", "routes": True},
        "b": {"replacement": "c", "shutdown": "2026-01-01"},
        "c": {"replacement": "d", "shutdown": "2027-01-01"},
        "x": {"replacement": "y"},
    }})
    today = date(2026, 11, 15)
    assert gm.active_replacement("a", today)[0] == "c"   # a → b → c, c még él
    assert gm.active_replacement("c", today) is None
    assert gm.upcoming_shutdown("c", today) == ("2027-01-01", "d")
    assert gm.active_replacement("x", today) is None     # csak javasolt utód
    assert gm.active_replacement("ismeretlen", today) is None


# --- modellváltás -------------------------------------------------------------

def test_fallback_candidates_skip_unusable(data_file, monkeypatch):
    data = _models(gemini_a=20, gemini_b=0, gemini_c=500, gemini_d=20, gemini_e=20)
    data["models"]["gemini-live"] = {"category": "Live API", "rpd": None}
    data["deprecations"]["gemini-old"] = {"replacement": "gemini-a", "routes": True}
    data_file(data)
    monkeypatch.setenv(gm.FALLBACK_KEY, "gemini-old, gemini-b gemini-elirt,gemini-live,"
                                        "gemini-c,gemini-d,gemini-e")
    quota.record("gemini-d", n=20)                       # a d mára elfogyott
    gm.save_local_api({m: m for m in ("gemini-a", "gemini-b", "gemini-c", "gemini-d")})
    gm.clear_cache()
    skipped = []
    cands = gm.fallback_candidates("gemini-a", skipped=skipped)
    # old → a (ugyanaz, ami kimerült), b: RPD 0, elírt: nincs a fájlban,
    # live: nem szöveges, d: elfogyott, e: a kulcs API-listáján nincs
    assert [c["model"] for c in cands] == ["gemini-c"]
    assert cands[0]["remaining"] == 500
    assert [m for m, _ in skipped] == ["gemini-b", "gemini-elirt", "gemini-live",
                                       "gemini-d", "gemini-e"]


def test_unknown_fallback_is_never_chosen(data_file, monkeypatch, capsys):
    data_file(_models(gemini_a=20))
    monkeypatch.setenv(gm.FALLBACK_KEY, "gemini-3.6-flsh")
    assert gm.choose_fallback("gemini-a", mode="auto") is None
    assert "gemini-3.6-flsh" in capsys.readouterr().out


def test_choose_fallback_modes(data_file, monkeypatch, capsys):
    data_file(_models(gemini_a=20, gemini_b=20, gemini_c=500))
    monkeypatch.setenv(gm.FALLBACK_KEY, "gemini-b,gemini-c")
    assert gm.choose_fallback("gemini-a", mode="off") is None
    assert gm.choose_fallback("gemini-a", mode="auto") == "gemini-b"
    assert gm.choose_fallback("gemini-a", mode="auto", tried={"gemini-b"}) == "gemini-c"
    # ask, de nincs terminál (pl. Claude Code futtatja): úgy vált, mint az auto
    assert gm.choose_fallback("gemini-a", mode="ask", interactive=False) == "gemini-b"
    answers = iter(["9", "2"])
    assert gm.choose_fallback("gemini-a", mode="ask", interactive=True,
                              input_fn=lambda _: next(answers)) == "gemini-c"
    assert gm.choose_fallback("gemini-a", mode="ask", interactive=True,
                              input_fn=lambda _: "") == "gemini-b"
    assert gm.choose_fallback("gemini-a", mode="ask", interactive=True,
                              input_fn=lambda _: "0") is None
    out = capsys.readouterr().out
    assert "gemini-c" in out and "500" in out


def test_choose_fallback_mode_from_settings(data_file, monkeypatch):
    data_file(_models(gemini_a=20, gemini_b=20))
    monkeypatch.setenv(gm.FALLBACK_KEY, "gemini-b")
    monkeypatch.setenv(gm.ON_QUOTA_KEY, "auto")
    assert gm.choose_fallback("gemini-a") == "gemini-b"
    monkeypatch.setenv(gm.ON_QUOTA_KEY, "turbo")          # érvénytelen → off
    assert gm.choose_fallback("gemini-a") is None


def test_choose_fallback_empty_list(data_file, monkeypatch):
    data_file(_models(gemini_a=20))
    assert gm.choose_fallback("gemini-a", mode="auto") is None


# --- kvóta-integráció ---------------------------------------------------------

def test_quota_uses_data_file_limit(data_file):
    data_file(_models(gemini_c=500, gemini_z=0))
    st = quota.status("gemini-c")
    assert st["limit"] == 500 and st["limit_source"].startswith("AI Studio")
    assert quota.status("ismeretlen-modell")["limit"] == quota.DEFAULT_LIMIT
    assert quota.preflight("gemini-z", quiet=True) is False   # RPD 0


def test_quota_learned_limit_for_unknown_model(data_file):
    data_file(_models(gemini_c=500))
    quota.note_limit("gemini-q", 7)
    st = quota.status("gemini-q")
    assert (st["limit"], st["limit_source"]) == (7, "mért (429)")


def test_ctrl_c_at_prompt_is_not_a_decline(data_file, monkeypatch):
    data_file(_models(gemini_a=20, gemini_b=20))
    monkeypatch.setenv(gm.FALLBACK_KEY, "gemini-b")

    def interrupt(_):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        gm.choose_fallback("gemini-a", mode="ask", interactive=True, input_fn=interrupt)


def test_prompt_on_worker_thread_is_cancellable(monkeypatch):
    import threading
    import time
    release = threading.Event()
    outcome = {}

    def blocking_input(_):
        release.wait(5)             # a „felhasználó” nem válaszol
        return "1"

    def worker():
        try:
            gm._ask("? ", blocking_input)
        except KeyboardInterrupt:
            outcome["interrupted"] = True
    monkeypatch.setattr(gm, "CANCEL", threading.Event())
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.1)
    gm.CANCEL.set()
    t.join(2)
    release.set()
    assert not t.is_alive() and outcome == {"interrupted": True}


def test_quota_unlimited_and_learned_priority(data_file):
    data = _models(gemini_c=500)
    data["models"]["gemini-live"] = {"category": "Live API", "rpd": None}
    data_file(data)
    st = quota.status("gemini-live")
    assert st["limit"] == quota.UNLIMITED_LIMIT and "korlátlan" in st["limit_source"]
    assert quota.fmt_limit(st["limit"]) == "∞"
    # a kulcsodra 429-ből tanult limit erősebb a fájlbelinél
    quota.note_limit("gemini-c", 10_000)
    st = quota.status("gemini-c")
    assert (st["limit"], st["limit_source"]) == (10_000, "mért (429)")
    warns = gm.config_warnings(gm.load(), None, {"gemini-c": 10_000})
    assert any("forget-limit gemini-c" in w for w in warns)


def test_local_api_file_is_per_key(data_file, monkeypatch):
    data_file(_models(gemini_a=20))
    assert gm.in_api("gemini-a") is None                 # még nincs letöltve
    gm.save_local_api({"gemini-a": "Gemini A"})
    gm.clear_cache()
    assert gm.in_api("gemini-a") is True and gm.in_api("gemini-x") is False
    monkeypatch.setenv("GEMINI_API_KEY", "masik-kulcs")
    gm.clear_cache()
    assert gm.in_api("gemini-a") is None                 # más kulcs: nem ismert


def _args(**kw):
    base = dict(no_limits=False, open=False, file=None, stdin=False, no_docs=True,
                no_api=True, force=False, dry_run=False, local=False)
    return type("A", (), {**base, **kw})


def test_refresh_refuses_partial_page(data_file, tmp_path, capsys):
    data_file(_models(gemini_a=20))
    page = tmp_path / "page.txt"
    page.write_text(PAGE, encoding="utf-8")              # csak 5 modell-sor
    args = _args(file=str(page))
    assert gm.cmd_refresh(args) == 1
    assert "All models" in capsys.readouterr().out
    assert list(gm.load()["models"]) == ["gemini-a"]     # a fájl érintetlen


def test_deprecations_columns_by_header():
    page = """{% table %}
  * Model
  * Release date
  * Deprecation date
  * Shutdown date
  * Recommended replacement

  ---

  * `gemini-x`
  * May 1, 2026
  * June 1, 2026
  * January 5, 2030
  * `gemini-y`
{% /table %}"""
    dep = gm.parse_deprecations(page)["gemini-x"]
    assert dep["shutdown"] == "2030-01-05" and dep["replacement"] == "gemini-y"
    # ismeretlen fejlécű táblázatot kihagy, nem találgat
    assert gm.parse_deprecations(page.replace("Shutdown date", "Valami")) == {}


def test_config_warnings_use_new_data_and_report_shut_down(data_file, monkeypatch):
    data_file(_models(gemini_a=20))                       # a betöltött: régi adat
    monkeypatch.setenv("SUBTR_GEMINI_MODEL", "gemini-old")
    monkeypatch.setenv(gm.FALLBACK_KEY, "gemini-soon")
    new = {"models": {}, "deprecations": {
        "gemini-old": {"replacement": "gemini-a", "shutdown": "2020-01-01", "routes": False},
        "gemini-soon": {"replacement": "gemini-a", "shutdown": "2999-01-01", "routes": False},
    }}
    warns = " | ".join(gm.config_warnings(new))
    assert "leállt" in warns and "ezt hívja: gemini-a" in warns     # már leállt
    assert "2999-01-01" in warns                                   # közelgő, az ÚJ adatból


def test_learned_limit_unblocks_rpd0_fallback(data_file, monkeypatch):
    data_file(_models(gemini_a=20, gemini_pro=0))
    monkeypatch.setenv(gm.FALLBACK_KEY, "gemini-pro")
    assert gm.fallback_candidates("gemini-a") == []
    quota.note_limit("gemini-pro", 50)                    # más tierű kulcs: van keret
    assert [c["model"] for c in gm.fallback_candidates("gemini-a")] == ["gemini-pro"]


def test_ask_needs_terminal_on_both_ends(data_file, monkeypatch):
    data_file(_models(gemini_a=20, gemini_b=20))
    monkeypatch.setenv(gm.FALLBACK_KEY, "gemini-b")
    monkeypatch.setattr(gm.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(gm.sys.stdout, "isatty", lambda: False, raising=False)

    def never(_):
        raise AssertionError("átirányított kimenetnél nem szabad kérdezni")
    assert gm.choose_fallback("gemini-a", mode="ask", input_fn=never) == "gemini-b"


def test_unlimited_remaining_stays_unlimited(data_file):
    data = _models()
    data["models"]["gemini-live"] = {"category": "Live API", "rpd": None}
    data_file(data)
    quota.record("gemini-live", n=3)
    st = quota.status("gemini-live")
    assert quota.fmt_limit(st["remaining"]) == "∞"


def test_text_only_daily_429_does_not_mark_exhausted(data_file):
    data_file(_models(gemini_a=20))
    quota.note_limit_from_error("gemini-a", Exception("429 RESOURCE_EXHAUSTED daily spike"))
    assert quota.status("gemini-a")["exhausted"] is False
    quota.note_limit_from_error("gemini-a", Exception(
        "429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
    assert quota.status("gemini-a")["exhausted"] is True


def test_without_api_previous_mapping_beats_slug():
    old = {"models": {"gemma-4-31b-it": {"label": "Gemma 4 31B", "rpd": 1}}}
    page = gm.parse_rate_limit_page(PAGE)
    new = gm.build_data(old, page, None, None, None, today=date(2026, 11, 15))
    assert "gemma-4-31b-it" in new["models"] and "gemma-4-31b" not in new["models"]


def test_without_api_unmatched_stay_unmatched_and_no_collisions():
    old = {"models": {}, "unmatched_labels": ["Gemma 4 31B"]}
    page = gm.parse_rate_limit_page(PAGE)
    new = gm.build_data(old, page, None, None, None, today=date(2026, 11, 15))
    assert "gemma-4-31b" not in new["models"] and "Gemma 4 31B" in new["unmatched_labels"]
    twice = {"tier": "Free tier", "rows": page["rows"][:1] * 2}
    new = gm.build_data({}, twice, None, None, None, today=date(2026, 11, 15))
    assert list(new["models"]) == ["gemini-3.8-flash"] and len(new["unmatched_labels"]) == 1


def test_own_tier_limits_override_repo_for_this_key(data_file, monkeypatch):
    data_file(_models(gemini_a=20, gemini_pro=0))
    assert quota.status("gemini-pro")["limit"] == 0
    gm.save_local_limits({"gemini-pro": {"category": gm.TEXT_CATEGORY, "rpd": 1000,
                                         "rpm": 150, "tpm": 2_000_000}}, "Tier 1")
    st = quota.status("gemini-pro")
    assert st["limit"] == 1000 and "saját limit: Tier 1" in st["limit_source"]
    assert quota.status("gemini-a")["limit"] == 20            # nem szereplő: repó adat
    assert gm.data_date() == "" and gm.load()["models"]["gemini-pro"]["rpd"] == 0
    monkeypatch.setenv("GEMINI_API_KEY", "masik-kulcs")       # másik kulcs: repó adat
    gm.clear_cache()
    assert quota.status("gemini-pro")["limit"] == 0
    monkeypatch.setenv("GEMINI_API_KEY", "teszt-kulcs")
    gm.clear_cache()
    assert gm.reset_local_limits() is True
    assert quota.status("gemini-pro")["limit"] == 0 and gm.reset_local_limits() is False


def test_refresh_paid_tier_needs_local(data_file, tmp_path, capsys):
    data_file(_models(gemini_a=20))
    paid = PAGE.replace("Free tier", "Tier 1") + "".join(
        f"Model {i}\nText-out models\n0 / 5\n0 / 250K\n0 / 20\n" for i in range(10))
    paid = paid.replace("Tools\n", "") + "Tools\n"
    page = tmp_path / "paid.txt"
    page.write_text(paid, encoding="utf-8")
    assert gm.cmd_refresh(_args(file=str(page))) == 1
    assert "--local" in capsys.readouterr().out
    assert list(gm.load()["models"]) == ["gemini-a"]          # a repó fájl érintetlen
    assert gm.cmd_refresh(_args(file=str(page), local=True)) == 0
    assert gm.local_limits()["tier"] == "Tier 1"
    assert list(gm.load()["models"]) == ["gemini-a"]
