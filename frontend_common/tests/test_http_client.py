"""Test del client HTTP tipizzato verso il backend."""
import httpx
import pytest

from pulse_fe_common import http_client as hc
from pulse_fe_common.http_client import (ApiAuthError, ApiClient, ApiError,
                                         ApiUnavailableError)


class FakeResponse:
    def __init__(self, status_code, body=None, raise_json=False,
                 reason="Reason"):
        self.status_code = status_code
        self._body = body
        self._raise_json = raise_json
        self.reason_phrase = reason

    def json(self):
        if self._raise_json:
            raise ValueError("no json")
        return self._body


def _patch(monkeypatch, capture=None, response=None, exc=None):
    def fake_request(method, url, **kwargs):
        if capture is not None:
            capture["method"] = method
            capture["url"] = url
            capture.update(kwargs)
        if exc is not None:
            raise exc
        return response
    monkeypatch.setattr(hc.httpx, "request", fake_request)


def test_get_success_200(monkeypatch):
    cap = {}
    _patch(monkeypatch, cap, FakeResponse(200, {"ok": True}))
    client = ApiClient("http://api/api/v1/")
    out = client.get("/users", token="tok", params={"page": 1, "q": None, "e": ""})
    assert out == {"ok": True}
    assert cap["url"] == "http://api/api/v1/users"
    assert cap["headers"]["Authorization"] == "Bearer tok"
    # None ed "" rimossi dai params
    assert cap["params"] == {"page": 1}


def test_no_token_no_auth_header(monkeypatch):
    cap = {}
    _patch(monkeypatch, cap, FakeResponse(200, {}))
    ApiClient("http://api").get("/x")
    assert "Authorization" not in cap["headers"]
    assert cap["params"] is None


def test_204_returns_none(monkeypatch):
    _patch(monkeypatch, response=FakeResponse(204))
    assert ApiClient("http://api").delete("/users/1") is None


def test_post_put_wrappers(monkeypatch):
    cap = {}
    _patch(monkeypatch, cap, FakeResponse(200, {"m": "ok"}))
    c = ApiClient("http://api")
    assert c.post("/x", token="t", json={"a": 1}) == {"m": "ok"}
    assert cap["method"] == "POST"
    assert cap["json"] == {"a": 1}
    c.put("/x", json={"b": 2})
    assert cap["method"] == "PUT"


def test_error_400_raises_apierror(monkeypatch):
    body = {"error": {"code": "BAD", "message": "brutto", "details": {"f": 1}}}
    _patch(monkeypatch, response=FakeResponse(400, body))
    with pytest.raises(ApiError) as ei:
        ApiClient("http://api").get("/x")
    assert ei.value.status_code == 400
    assert ei.value.code == "BAD"
    assert ei.value.details == {"f": 1}
    assert not isinstance(ei.value, ApiAuthError)


def test_error_401_raises_autherror(monkeypatch):
    _patch(monkeypatch, response=FakeResponse(401, {"error": {"code": "NOAUTH",
                                                              "message": "x"}}))
    with pytest.raises(ApiAuthError):
        ApiClient("http://api").get("/x")


def test_error_body_not_dict_uses_defaults(monkeypatch):
    _patch(monkeypatch, response=FakeResponse(500, ["not", "a", "dict"],
                                              reason="Server Error"))
    with pytest.raises(ApiError) as ei:
        ApiClient("http://api").get("/x")
    assert ei.value.status_code == 500
    assert ei.value.code == "ERROR"
    assert ei.value.message == "Server Error"


def test_network_error_raises_unavailable(monkeypatch):
    _patch(monkeypatch, exc=httpx.ConnectError("boom"))
    with pytest.raises(ApiUnavailableError):
        ApiClient("http://api").get("/x")
