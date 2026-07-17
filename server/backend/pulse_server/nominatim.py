"""Gateway/tunnel HTTP GET verso Nominatim (aggiunta su richiesta utente).

Scopo: consentire a Sonde e ALTRI SERVIZI che NON raggiungono direttamente
Nominatim di geocodificare passando dal Server (che invece lo raggiunge).

Sicurezza (anti-SSRF):
 - la base URL e' FISSA da configurazione (`nominatim_url`): il chiamante NON puo'
   scegliere host/schema;
 - il chiamante controlla SOLO l'endpoint (validato contro una allowlist nel
   router) e i query params;
 - i redirect di httpx sono DISABILITATI (`follow_redirects=False`) e l'header
   `Location` upstream NON viene propagato: il gateway non seguira' mai e non
   inoltrera' mai un redirect verso host arbitrari.

Rispetto ToS Nominatim:
 - viene impostato un `User-Agent` identificativo (`nominatim_user_agent`);
 - le chiamate upstream sono SERIALIZZATE e limitate a ~1 req/s
   (`nominatim_min_interval_ms`): in caso di burst la chiamata attende
   brevemente (throttle in-process) invece di rispondere 429, cosi' da non
   perdere richieste legittime rispettando comunque il rate upstream;
 - una cache in-process con TTL (`nominatim_cache_ttl_seconds`) evita di colpire
   upstream per richieste GET identiche ravvicinate.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

import httpx

from . import errors
from .config import Settings

# Timeout ragionevole verso Nominatim (secondi).
_UPSTREAM_TIMEOUT_SECONDS = 15.0

# Query pairs del chiamante da inoltrare (lista di coppie chiave/valore).
QueryItems = list[tuple[str, str]]


@dataclass(frozen=True)
class GatewayResponse:
    """Risposta upstream normalizzata restituita dal gateway."""

    status_code: int
    content: bytes
    content_type: str
    from_cache: bool = False


@dataclass
class _CacheEntry:
    expires_at: float
    response: GatewayResponse


class NominatimGateway:
    """Client proxy verso Nominatim con throttle + cache in-process.

    Deve essere usato come SINGLETON (vedi `context.get_nominatim_gateway`) affinche'
    throttle e cache siano condivisi fra le richieste.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[], httpx.Client] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_call: float | None = None
        self._cache: dict[str, _CacheEntry] = {}

    # -- httpx client -------------------------------------------------------
    def _client(self) -> httpx.Client:
        if self._client_factory is not None:
            return self._client_factory()
        # follow_redirects=False: il gateway non segue redirect verso host arbitrari.
        return httpx.Client(timeout=_UPSTREAM_TIMEOUT_SECONDS, follow_redirects=False)

    # -- cache helpers ------------------------------------------------------
    @staticmethod
    def _cache_key(endpoint: str, query_items: QueryItems) -> str:
        return f"{endpoint}?{urlencode(query_items)}"

    def _cached(self, key: str) -> GatewayResponse | None:
        entry = self._cache.get(key)
        if entry is not None and entry.expires_at > self._monotonic():
            return GatewayResponse(
                status_code=entry.response.status_code,
                content=entry.response.content,
                content_type=entry.response.content_type,
                from_cache=True,
            )
        return None

    # -- throttle -----------------------------------------------------------
    def _throttle(self) -> None:
        """Attende (se necessario) per rispettare l'intervallo minimo upstream."""
        if self._last_call is None:
            return
        min_interval = self._settings.nominatim_min_interval_ms / 1000.0
        wait = min_interval - (self._monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)

    # -- upstream call ------------------------------------------------------
    def _request(self, endpoint: str, query_items: QueryItems) -> GatewayResponse:
        base = self._settings.nominatim_url.rstrip("/")
        url = f"{base}/{endpoint}"
        headers = {"User-Agent": self._settings.nominatim_user_agent}
        params = httpx.QueryParams(cast("list[tuple[str, Any]]", query_items))
        try:
            with self._client() as client:
                resp = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise errors.service_unavailable(f"Nominatim non raggiungibile: {exc}")
        content_type = resp.headers.get("content-type", "application/json")
        return GatewayResponse(
            status_code=resp.status_code,
            content=resp.content,
            content_type=content_type,
        )

    # -- API ----------------------------------------------------------------
    def fetch(self, endpoint: str, query_items: QueryItems) -> GatewayResponse:
        """Inoltra una GET a Nominatim, con cache TTL e throttle upstream."""
        key = self._cache_key(endpoint, query_items)
        cached = self._cached(key)
        if cached is not None:
            return cached
        # Serializza le chiamate upstream (throttle) e ricontrolla la cache dentro
        # il lock: piu' richieste identiche concorrenti colpiscono upstream una volta.
        with self._lock:
            cached = self._cached(key)
            if cached is not None:
                return cached
            self._throttle()
            response = self._request(endpoint, query_items)
            self._last_call = self._monotonic()
            ttl = self._settings.nominatim_cache_ttl_seconds
            # Cache solo le risposte positive (2xx): errori/limiti upstream non
            # vanno "congelati" per tutto il TTL.
            if ttl > 0 and 200 <= response.status_code < 300:
                self._cache[key] = _CacheEntry(
                    expires_at=self._monotonic() + ttl, response=response
                )
            return response
