"""Test SEC-01: header di sicurezza HTTP e banner Server neutralizzato."""

from __future__ import annotations


def test_security_headers_present(client) -> None:
    r = client.get("/api/v1/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_server_banner_neutralized(client) -> None:
    r = client.get("/api/v1/health")
    # il banner dello stack (uvicorn) e' sostituito
    assert r.headers.get("Server") == "Pulse"


def test_hsts_absent_by_default(client) -> None:
    r = client.get("/api/v1/health")
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_present_when_enabled(monkeypatch) -> None:
    """HSTS emesso solo quando abilitato via config (servizio in HTTPS)."""
    from fastapi.testclient import TestClient

    import pulse_server.middleware as mw
    from pulse_server.config import Settings
    from pulse_server.main import create_app

    app = create_app()
    monkeypatch.setattr(mw, "get_settings", lambda: Settings(hsts_enabled=True))
    with TestClient(app) as c:
        r = c.get("/api/v1/health")
    assert "max-age=63072000" in r.headers["Strict-Transport-Security"]
    assert "includeSubDomains" in r.headers["Strict-Transport-Security"]
