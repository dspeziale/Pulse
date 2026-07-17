"""Test del gateway/tunnel verso Nominatim (aggiunta su richiesta utente).

Nessun test contatta Nominatim reale: si usa httpx.MockTransport per l'upstream
e un clock/sleep iniettabile per throttle e cache.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from pulse_server import context, errors
from pulse_server.config import Settings, get_settings
from pulse_server.context import get_nominatim_gateway
from pulse_server.db import get_session
from pulse_server.main import create_app
from pulse_server.nominatim import (
    GatewayResponse,
    NominatimGateway,
    _CacheEntry,
)

Handler = Callable[[httpx.Request], httpx.Response]


# --------------------------------------------------------------------------- #
# Helper                                                                       #
# --------------------------------------------------------------------------- #


class _Clock:
    """Orologio monotonico controllabile; `sleep` fa avanzare il tempo."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class _SeqClock:
    """Restituisce valori predefiniti a ogni chiamata (per rami deterministici)."""

    def __init__(self, values: list[float]) -> None:
        self._values = values
        self.i = 0

    def monotonic(self) -> float:
        value = self._values[self.i]
        self.i += 1
        return value


def _fake_gateway(
    handler: Handler,
    settings: Settings,
    *,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> NominatimGateway:
    def factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    kwargs: dict[str, object] = {}
    if monotonic is not None:
        kwargs["monotonic"] = monotonic
    if sleep is not None:
        kwargs["sleep"] = sleep
    return NominatimGateway(settings, client_factory=factory, **kwargs)  # type: ignore[arg-type]


def _app(gateway: NominatimGateway, settings: Settings, *, db_session: object | None = None):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_nominatim_gateway] = lambda: gateway

    if db_session is not None:

        def _sess():
            yield db_session

    else:

        def _sess():
            yield None

    app.dependency_overrides[get_session] = _sess
    return app


def _ok_handler(records: list[httpx.Request]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        records.append(request)
        return httpx.Response(
            200, json={"place": "Rome"}, headers={"content-type": "application/json"}
        )

    return handler


# --------------------------------------------------------------------------- #
# Router: allowlist + auth                                                     #
# --------------------------------------------------------------------------- #


def test_endpoint_not_in_allowlist_returns_404() -> None:
    settings = Settings(nominatim_api_key="k")
    gw = _fake_gateway(_ok_handler([]), settings)
    with TestClient(_app(gw, settings)) as c:
        r = c.get("/api/v1/nominatim/evil?q=x", headers={"X-API-Key": "k"})
    assert r.status_code == 404


def test_missing_credentials_returns_401() -> None:
    settings = Settings(nominatim_api_key="k")
    gw = _fake_gateway(_ok_handler([]), settings)
    with TestClient(_app(gw, settings)) as c:
        r = c.get("/api/v1/nominatim/search?q=x")
    assert r.status_code == 401


def test_invalid_api_key_returns_401() -> None:
    settings = Settings(nominatim_api_key="k")
    gw = _fake_gateway(_ok_handler([]), settings)
    with TestClient(_app(gw, settings)) as c:
        r = c.get("/api/v1/nominatim/search?q=x", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_invalid_jwt_returns_401() -> None:
    settings = Settings()  # api_key vuota => solo JWT
    gw = _fake_gateway(_ok_handler([]), settings)
    with TestClient(_app(gw, settings)) as c:
        r = c.get(
            "/api/v1/nominatim/search?q=x",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert r.status_code == 401


def test_api_key_header_forwards_with_user_agent_and_query() -> None:
    settings = Settings(nominatim_api_key="secret-key")
    records: list[httpx.Request] = []
    gw = _fake_gateway(_ok_handler(records), settings)
    with TestClient(_app(gw, settings)) as c:
        r = c.get(
            "/api/v1/nominatim/search?q=Rome&format=json",
            headers={"X-API-Key": "secret-key"},
        )
    assert r.status_code == 200
    assert r.json()["place"] == "Rome"
    assert len(records) == 1
    upstream = records[0]
    assert upstream.url.host == "nominatim.openstreetmap.org"
    assert upstream.url.path == "/search"
    assert upstream.url.params.get("q") == "Rome"
    assert upstream.url.params.get("format") == "json"
    assert upstream.headers["user-agent"] == settings.nominatim_user_agent


def test_api_key_query_param_is_not_forwarded_upstream() -> None:
    settings = Settings(nominatim_api_key="secret-key")
    records: list[httpx.Request] = []
    gw = _fake_gateway(_ok_handler(records), settings)
    with TestClient(_app(gw, settings)) as c:
        r = c.get("/api/v1/nominatim/search?q=Rome&api_key=secret-key")
    assert r.status_code == 200
    assert len(records) == 1
    # L'api_key di autenticazione non deve finire su Nominatim.
    assert "api_key" not in dict(records[0].url.params)
    assert records[0].url.params.get("q") == "Rome"


def test_content_type_is_passed_through() -> None:
    settings = Settings(nominatim_api_key="k")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<xml/>", headers={"content-type": "application/xml"})

    gw = _fake_gateway(handler, settings)
    with TestClient(_app(gw, settings)) as c:
        r = c.get("/api/v1/nominatim/reverse?lat=1&lon=2", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")


def test_jwt_auth_ok(db_session) -> None:
    settings = Settings()  # api_key vuota => percorso JWT
    records: list[httpx.Request] = []
    gw = _fake_gateway(_ok_handler(records), settings)
    with TestClient(_app(gw, settings, db_session=db_session)) as c:
        token = c.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "ChangeMe123!"}
        ).json()["access_token"]
        r = c.get(
            "/api/v1/nominatim/search?q=Rome",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert len(records) == 1


# --------------------------------------------------------------------------- #
# Gateway: cache + throttle + errori                                          #
# --------------------------------------------------------------------------- #


def test_cache_avoids_second_upstream_within_ttl() -> None:
    settings = Settings(nominatim_cache_ttl_seconds=300, nominatim_min_interval_ms=0)
    records: list[httpx.Request] = []
    gw = _fake_gateway(_ok_handler(records), settings)
    first = gw.fetch("search", [("q", "Rome")])
    second = gw.fetch("search", [("q", "Rome")])
    assert len(records) == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.content == first.content


def test_cache_disabled_when_ttl_zero() -> None:
    settings = Settings(nominatim_cache_ttl_seconds=0, nominatim_min_interval_ms=0)
    records: list[httpx.Request] = []
    gw = _fake_gateway(_ok_handler(records), settings)
    gw.fetch("search", [("q", "Rome")])
    gw.fetch("search", [("q", "Rome")])
    assert len(records) == 2


def test_non_2xx_response_is_not_cached() -> None:
    settings = Settings(nominatim_cache_ttl_seconds=300, nominatim_min_interval_ms=0)
    records: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        records.append(request)
        return httpx.Response(500, json={"error": "boom"})

    gw = _fake_gateway(handler, settings)
    r1 = gw.fetch("search", [("q", "Rome")])
    r2 = gw.fetch("search", [("q", "Rome")])
    assert r1.status_code == 500
    assert r2.status_code == 500
    assert len(records) == 2  # nessuna cache degli errori


def test_cache_entry_expiry_triggers_refetch() -> None:
    clock = _Clock()
    settings = Settings(nominatim_cache_ttl_seconds=10, nominatim_min_interval_ms=0)
    records: list[httpx.Request] = []
    gw = _fake_gateway(_ok_handler(records), settings, monotonic=clock.monotonic, sleep=clock.sleep)
    gw.fetch("search", [("q", "Rome")])  # cache -> expires_at = 1010
    clock.now = 1005
    cached = gw.fetch("search", [("q", "Rome")])  # ancora valida
    clock.now = 1020
    refetched = gw.fetch("search", [("q", "Rome")])  # scaduta -> upstream
    assert cached.from_cache is True
    assert refetched.from_cache is False
    assert len(records) == 2


def test_inner_double_check_returns_cache_hit() -> None:
    """Ramo difensivo: un'altra richiesta riempie la cache prima del lock."""
    settings = Settings(nominatim_cache_ttl_seconds=300, nominatim_min_interval_ms=0)
    records: list[httpx.Request] = []
    # Clock: outer _cached vede la voce scaduta (100 > 200 = False),
    # inner _cached (dentro il lock) la vede valida (100 > 50 = True).
    clock = _SeqClock([200.0, 50.0])
    gw = _fake_gateway(_ok_handler(records), settings, monotonic=clock.monotonic)
    key = gw._cache_key("search", [("q", "x")])
    gw._cache[key] = _CacheEntry(
        expires_at=100.0,
        response=GatewayResponse(200, b"seed", "application/json"),
    )
    result = gw.fetch("search", [("q", "x")])
    assert result.from_cache is True
    assert result.content == b"seed"
    assert records == []  # upstream mai chiamato


def test_rate_limit_throttles_upstream_calls() -> None:
    clock = _Clock()
    settings = Settings(nominatim_min_interval_ms=1000, nominatim_cache_ttl_seconds=0)
    records: list[httpx.Request] = []
    gw = _fake_gateway(_ok_handler(records), settings, monotonic=clock.monotonic, sleep=clock.sleep)
    gw.fetch("search", [("q", "a")])  # prima chiamata: nessun throttle
    gw.fetch("search", [("q", "b")])  # subito dopo: attende ~1s
    assert clock.slept == [1.0]
    assert len(records) == 2


def test_no_throttle_when_interval_already_elapsed() -> None:
    clock = _Clock()
    settings = Settings(nominatim_min_interval_ms=1000, nominatim_cache_ttl_seconds=0)
    records: list[httpx.Request] = []
    gw = _fake_gateway(_ok_handler(records), settings, monotonic=clock.monotonic, sleep=clock.sleep)
    gw.fetch("search", [("q", "a")])
    clock.now = 1005  # trascorsi 5s > intervallo minimo
    gw.fetch("search", [("q", "b")])
    assert clock.slept == []
    assert len(records) == 2


def test_upstream_error_maps_to_503() -> None:
    settings = Settings()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    gw = _fake_gateway(handler, settings)
    with pytest.raises(errors.ApiError) as exc:
        gw.fetch("search", [("q", "x")])
    assert exc.value.status_code == 503


def test_real_client_factory_builds_httpx_client() -> None:
    gw = NominatimGateway(Settings())
    client = gw._client()
    try:
        assert isinstance(client, httpx.Client)
        assert client.follow_redirects is False
    finally:
        client.close()


def test_get_nominatim_gateway_is_singleton() -> None:
    context._nominatim_gateway = None
    settings = Settings()
    g1 = get_nominatim_gateway(settings)
    g2 = get_nominatim_gateway(settings)
    assert g1 is g2
    context._nominatim_gateway = None
