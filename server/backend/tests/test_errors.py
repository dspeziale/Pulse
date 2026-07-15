"""Test degli handler di errore standard e casi 405/422."""

from __future__ import annotations


def test_error_body_shape(client) -> None:
    r = client.get("/api/v1/users")  # 401 senza token
    body = r.json()
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_validation_error_422(client) -> None:
    # login senza campi richiesti -> RequestValidationError -> 422 nel formato standard
    r = client.post("/api/v1/auth/login", json={"username": "admin"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNPROCESSABLE_ENTITY"
    assert "errors" in r.json()["error"]["details"]


def test_method_not_allowed(client) -> None:
    # /api/v1/health accetta GET, non DELETE -> StarletteHTTPException 405
    r = client.delete("/api/v1/health")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_not_found_route(client) -> None:
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
