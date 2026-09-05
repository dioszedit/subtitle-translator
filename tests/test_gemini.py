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
