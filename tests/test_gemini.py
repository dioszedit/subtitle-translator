"""subtr.providers.gemini — a közös call_json: retry, kvóta-könyvelés, hibautak.
Hamis klienssel, hálózat nélkül; a sleep ki van iktatva."""

import pytest

from subtr.providers import gemini

pytestmark = pytest.mark.skipif(not gemini.DEPS_OK, reason="google-genai nincs telepítve")


class _Resp:
    def __init__(self, text=None, parsed=None):
        self.text, self.parsed = text, parsed


class _Client:
    """A válaszok sorban: _Resp → visszaadja, Exception → dobja."""
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = 0
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls += 1
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)


@pytest.fixture
def quota_log(monkeypatch):
    log = []
    fake = type("Q", (), {
        "record": staticmethod(lambda model: log.append(("record", model))),
        "note_limit_from_error": staticmethod(lambda model, e: log.append(("429", model))),
        "preflight": staticmethod(lambda model, needed=0: log.append(("preflight", needed))),
    })
    monkeypatch.setattr(gemini, "_gq", fake)
    return log


def _api_error(code):
    return gemini.genai_errors.APIError(code, {"error": {"message": "x", "status": "s"}})


def test_dict_schema_parses_text_and_records_quota(quota_log):
    client = _Client(_Resp(text='{"errors": []}'))
    parsed, err = gemini.call_json(client, "m", "p", schema={"type": "object"})
    assert (parsed, err) == ({"errors": []}, None)
    assert quota_log == [("record", "m")]


def test_pydantic_schema_returns_parsed_object():
    sentinel = object()
    client = _Client(_Resp(text="{}", parsed=sentinel))
    parsed, err = gemini.call_json(client, "m", "p", schema=object)
    assert parsed is sentinel and err is None


def test_empty_response_is_retried_then_fails(quota_log):
    client = _Client(_Resp(text=None), _Resp(text="nem json"), _Resp(text=""))
    parsed, err = gemini.call_json(client, "m", "p", schema={}, max_retries=3)
    assert parsed is None and "blokkolt" in err
    assert client.calls == 3
    # a blokkolt válasz is fogyaszt: mindhárom könyvelve
    assert quota_log.count(("record", "m")) == 3


def test_429_and_5xx_are_retried_and_limit_noted(quota_log):
    client = _Client(_api_error(429), _api_error(503), _Resp(text='{"ok": 1}'))
    parsed, err = gemini.call_json(client, "m", "p", schema={}, max_retries=4)
    assert parsed == {"ok": 1} and err is None
    assert ("429", "m") in quota_log
    assert quota_log.count(("record", "m")) == 1


def test_non_retryable_api_error_returns_immediately(quota_log):
    client = _Client(_api_error(400), _Resp(text="{}"))
    parsed, err = gemini.call_json(client, "m", "p", schema={})
    assert parsed is None and "API hiba" in err
    assert client.calls == 1 and quota_log == []


@pytest.fixture
def no_overload_fallback(monkeypatch):
    """Nincs tartalékmodell: a túlterhelés-váltás nem talál helyettesítőt."""
    from subtr import gemini_models
    monkeypatch.setattr(gemini_models, "fallback_candidates",
                        lambda model, tried=(), skipped=None: [])
    gemini.reset_switches()
    yield
    gemini.reset_switches()


def test_retries_exhausted_reports_last_api_error(no_overload_fallback):
    client = _Client(_api_error(503), _api_error(503))
    parsed, err = gemini.call_json(client, "m", "p", schema={}, max_retries=2)
    assert parsed is None and "API hiba" in err and "503" in err
    assert client.calls == 2


def test_transient_network_error_retried_unexpected_not():
    client = _Client(ConnectionError("reset"), _Resp(text="{}"))
    assert gemini.call_json(client, "m", "p", schema={}) == ({}, None)
    client = _Client(ValueError("bug"), _Resp(text="{}"))
    parsed, err = gemini.call_json(client, "m", "p", schema={})
    assert parsed is None and "Váratlan" in err and client.calls == 1


def test_is_transient_error():
    assert gemini.is_transient_error(TimeoutError())
    assert not gemini.is_transient_error(ValueError())


def test_make_client_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gemini.make_client()


def test_preflight_forwards_to_quota(quota_log):
    gemini.preflight("m", needed=4)
    assert quota_log == [("preflight", 4)]


# --- napi limit: modellváltás -------------------------------------------------

def _daily_429():
    return gemini.genai_errors.APIError(429, {"error": {
        "message": "Quota exceeded. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        "status": "RESOURCE_EXHAUSTED"}})


class _ModelClient(_Client):
    """Mint a _Client, de följegyzi, melyik modellel ment a hívás."""
    def __init__(self, *responses):
        super().__init__(*responses)
        self.models_used = []

    def generate_content(self, *, model, contents, config):
        self.models_used.append(model)
        return super().generate_content(model=model, contents=contents, config=config)


@pytest.fixture
def switching(monkeypatch, quota_log):
    from subtr import gemini_models, quota
    monkeypatch.setattr(gemini._gq, "is_daily_exhaustion",
                        staticmethod(quota.is_daily_exhaustion), raising=False)
    choices = []

    def fake_choose(model, tried=()):
        choices.append(model)
        return {"m": "m2"}.get(model)
    monkeypatch.setattr(gemini_models, "choose_fallback", fake_choose)
    gemini.reset_switches()
    yield choices
    gemini.reset_switches()


def test_daily_quota_switches_model_and_sticks(switching, quota_log):
    client = _ModelClient(_daily_429(), _Resp(text='{"ok": 1}'), _Resp(text='{"ok": 2}'))
    assert gemini.call_json(client, "m", "p", schema={}) == ({"ok": 1}, None)
    assert client.models_used == ["m", "m2"]
    assert ("record", "m2") in quota_log
    assert gemini.switches() == {"m": "m2"}
    # a következő hívás már egyből az új modellel megy, kérdés nélkül
    assert gemini.call_json(client, "m", "p", schema={}) == ({"ok": 2}, None)
    assert client.models_used[-1] == "m2" and switching == ["m"]


def test_daily_quota_without_switch_is_not_retried(switching):
    client = _ModelClient(_daily_429(), _daily_429(), _Resp(text="{}"))
    parsed, err = gemini.call_json(client, "x", "p", schema={}, max_retries=4)
    assert parsed is None and "429" in err
    assert client.calls == 1                               # nincs értelmetlen retry
    assert gemini.daily_quota_exhausted(err)
    # a döntés megmarad: másodszor már nem kérdez (és nem is küld kérést)
    gemini.call_json(_ModelClient(), "x", "p", schema={})
    assert switching == ["x"]


def test_text_only_daily_429_is_retried_not_switched(switching):
    """quotaId nélkül a „daily” szó nem elég a váltáshoz / a retry elhagyásához."""
    err = gemini.genai_errors.APIError(429, {"error": {
        "message": "Too many requests, try again (daily traffic spike)", "status": "x"}})
    client = _ModelClient(err, _Resp(text="{}"))
    assert gemini.call_json(client, "m", "p", schema={}) == ({}, None)
    assert client.models_used == ["m", "m"] and switching == []


def test_switch_summary(switching):
    client = _ModelClient(_daily_429(), _Resp(text="{}"))
    gemini.call_json(client, "m", "p", schema={})
    assert gemini.switch_summary() == "m → m2"


def test_meta_reports_model_actually_used(switching):
    client = _ModelClient(_daily_429(), _Resp(text="{}"))
    meta = {}
    gemini.call_json(client, "m", "p", schema={}, meta=meta)
    assert meta == {"model": "m2"}


def test_declined_model_is_not_called_again(switching):
    client = _ModelClient(_daily_429())
    parsed, err = gemini.call_json(client, "x", "p", schema={})
    assert parsed is None and client.calls == 1
    again = _ModelClient()                                 # nincs válasz: nem is hívhat
    assert gemini.call_json(again, "x", "p", schema={}) == (None, err)
    assert again.calls == 0 and gemini.daily_quota_exhausted(err)


# --- a váltás folyamatok között: a kvótanapló „exhausted” jelzése --------------

@pytest.fixture
def ledger_says_exhausted(monkeypatch, switching):
    """A napló szerint az „m” ma már kimerült (egy korábbi folyamat 429-et kapott)."""
    monkeypatch.setattr(gemini._gq, "status",
                        staticmethod(lambda model: {"exhausted": model == "m"}),
                        raising=False)
    return switching


def test_ledger_exhaustion_switches_before_first_request(ledger_says_exhausted, quota_log):
    """Új folyamat (pl. a következő rész): nem küld kérést a kimerült modellre."""
    client = _ModelClient(_Resp(text='{"ok": 1}'))
    meta = {}
    assert gemini.call_json(client, "m", "p", schema={}, meta=meta) == ({"ok": 1}, None)
    assert client.models_used == ["m2"] and meta == {"model": "m2"}
    assert ledger_says_exhausted == ["m"] and gemini.switches() == {"m": "m2"}


def test_ledger_exhaustion_without_fallback_still_tries_model(ledger_says_exhausted, monkeypatch):
    """Nincs tartalék → a modellt megpróbálja (a napló jelzése nem végleges ítélet)."""
    from subtr import gemini_models
    monkeypatch.setattr(gemini_models, "choose_fallback", lambda model, tried=(): None)
    client = _ModelClient(_Resp(text="{}"))
    assert gemini.call_json(client, "m", "p", schema={}) == ({}, None)
    assert client.models_used == ["m"]
    # a napló csak egyszer kerül elő: a második hívás nem kérdez újra
    assert gemini.call_json(_ModelClient(_Resp(text="{}")), "m", "p", schema={}) == ({}, None)


# --- tartós túlterhelés (5xx): váltás a tartaléklistára, kérdés nélkül ---------

def _server_error(code, message="x"):
    return gemini.genai_errors.APIError(code, {"error": {"message": message, "status": "s"}})


@pytest.fixture
def overload(monkeypatch, quota_log):
    """A tartaléklista az „m” helyett „m2”-t ad; a napi-limit kérdés nem fut."""
    from subtr import gemini_models
    monkeypatch.setattr(gemini_models, "on_quota_mode", lambda: "ask")
    monkeypatch.setattr(gemini_models, "fallback_candidates",
                        lambda model, tried=(), skipped=None:
                        [{"model": "m2"}] if model == "m" else [])
    monkeypatch.setattr(gemini_models, "choose_fallback",
                        lambda *a, **k: pytest.fail("a túlterhelés nem kérdezhet"))
    gemini.reset_switches()
    yield
    gemini.reset_switches()


def test_high_demand_503_switches_immediately(overload):
    """A „high demand” 503 tartós túlterhelés: a várakozás nem segít, azonnal vált."""
    client = _ModelClient(_server_error(503, "This model is currently experiencing high demand."),
                          _Resp(text='{"ok": 1}'), _Resp(text='{"ok": 2}'))
    meta = {}
    assert gemini.call_json(client, "m", "p", schema={}, meta=meta) == ({"ok": 1}, None)
    assert client.models_used == ["m", "m2"] and meta == {"model": "m2"}
    # a futás hátralévő hívásai is a tartalékkal mennek
    assert gemini.call_json(client, "m", "p", schema={}) == ({"ok": 2}, None)
    assert client.models_used[-1] == "m2" and gemini.switches() == {"m": "m2"}


def test_two_consecutive_5xx_switch(overload):
    client = _ModelClient(_server_error(504), _server_error(500), _Resp(text="{}"))
    assert gemini.call_json(client, "m", "p", schema={}) == ({}, None)
    assert client.models_used == ["m", "m", "m2"]


def test_single_5xx_is_retried_on_same_model(overload):
    client = _ModelClient(_server_error(500), _Resp(text="{}"))
    assert gemini.call_json(client, "m", "p", schema={}) == ({}, None)
    assert client.models_used == ["m", "m"] and gemini.switches() == {}


def test_429_between_5xx_resets_the_count(overload):
    client = _ModelClient(_server_error(500), _server_error(429), _server_error(503),
                          _Resp(text="{}"))
    assert gemini.call_json(client, "m", "p", schema={}) == ({}, None)
    assert client.models_used == ["m"] * 4 and gemini.switches() == {}


def test_overload_off_mode_does_not_switch(overload, monkeypatch):
    from subtr import gemini_models
    monkeypatch.setattr(gemini_models, "on_quota_mode", lambda: "off")
    client = _ModelClient(_server_error(503, "overloaded"), _server_error(503, "overloaded"))
    parsed, err = gemini.call_json(client, "m", "p", schema={}, max_retries=2)
    assert parsed is None and "503" in err and client.models_used == ["m", "m"]


def test_overload_is_not_marked_exhausted(overload):
    """A túlterhelés átmeneti: a modell nem kerül a kimerültek (_DECLINED) közé."""
    client = _ModelClient(_server_error(503, "high demand"), _Resp(text="{}"))
    gemini.call_json(client, "m", "p", schema={})
    assert "m" not in gemini._DECLINED


def test_transient_errors_exhausted_switch(overload):
    client = _ModelClient(TimeoutError(), TimeoutError(), _Resp(text="{}"))
    assert gemini.call_json(client, "m", "p", schema={}, max_retries=2) == ({}, None)
    assert client.models_used == ["m", "m", "m2"]


def test_overload_off_mode_notes_once(overload, monkeypatch, capsys):
    from subtr import gemini_models
    monkeypatch.setattr(gemini_models, "on_quota_mode", lambda: "off")
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    client = _ModelClient(*[_server_error(503, "overloaded")] * 4)
    gemini.call_json(client, "m", "p", schema={}, max_retries=4)
    assert capsys.readouterr().out.count("túlterhelt") == 1


def test_overload_skips_quota_declined_model(overload, monkeypatch):
    from subtr import gemini_models
    seen = {}
    monkeypatch.setattr(gemini_models, "fallback_candidates",
                        lambda model, tried=(), skipped=None: seen.update(tried=set(tried)) or [])
    gemini._DECLINED["m2"] = "[kimerült]"
    gemini._switch_after_overload("m", "503 high demand")
    assert "m2" in seen["tried"]


# --- kérésenkénti időkorlát -----------------------------------------------------

@pytest.fixture
def no_timeout_env(monkeypatch):
    for key in ("SUBTR_GEMINI_TIMEOUT", "SUBTR_REGISTER_GEMINI_TIMEOUT",
                "SUBTR_GLOSSARY_GEMINI_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)
    from subtr import config
    monkeypatch.setattr(config, "_DEFAULTS", {}, raising=False)


def test_request_timeout_defaults_per_task(no_timeout_env):
    assert gemini.request_timeout("register") == 120
    assert gemini.request_timeout("glossary") == 120
    assert gemini.request_timeout() == gemini.DEFAULT_TIMEOUT == 1200


def test_request_timeout_resolution_order(no_timeout_env, monkeypatch):
    monkeypatch.setenv("SUBTR_GEMINI_TIMEOUT", "300")
    assert gemini.request_timeout("register") == 300 and gemini.request_timeout() == 300
    monkeypatch.setenv("SUBTR_REGISTER_GEMINI_TIMEOUT", "90")
    assert gemini.request_timeout("register") == 90
    assert gemini.request_timeout("glossary") == 300


def test_request_timeout_invalid_value_falls_back(no_timeout_env, monkeypatch, capsys):
    monkeypatch.setenv("SUBTR_REGISTER_GEMINI_TIMEOUT", "abc")
    assert gemini.request_timeout("register") == 120
    assert "érvénytelen SUBTR_REGISTER_GEMINI_TIMEOUT" in capsys.readouterr().out


def test_request_timeout_invalid_task_value_uses_general(no_timeout_env, monkeypatch):
    monkeypatch.setenv("SUBTR_GEMINI_TIMEOUT", "300")
    monkeypatch.setenv("SUBTR_REGISTER_GEMINI_TIMEOUT", "abc")
    assert gemini.request_timeout("register") == 300


def test_translate_and_review_pass_their_task():
    from pathlib import Path
    root = Path(gemini.__file__).resolve().parent.parent / "tasks"
    assert 'make_client(task="translate")' in (root / "translate.py").read_text(encoding="utf-8")
    assert 'make_client(task="review")' in (root / "review.py").read_text(encoding="utf-8")


def test_make_client_sets_timeout_in_ms(no_timeout_env, monkeypatch):
    seen = {}
    monkeypatch.setattr(gemini.genai, "Client", lambda **kw: seen.update(kw) or "client")
    assert gemini.make_client(api_key="k", task="register") == "client"
    assert seen["api_key"] == "k" and seen["http_options"].timeout == 120_000
