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


def test_retries_exhausted_reports_last_api_error():
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
