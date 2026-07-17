"""Client proxy Server -> Probe per il drill-down (AR-01, API-02).

Il Server inoltra le query alla API di query della Probe su canale mTLS+token.
La classe e' sostituibile nei test tramite dependency override.
"""

from __future__ import annotations

from typing import Any

import httpx

from . import errors
from .config import Settings


class ProbeQueryClient:
    """Inoltra richieste di query all'endpoint di query di una Probe."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client(self) -> httpx.Client:
        cert: Any = None
        if self._settings.probe_client_cert_path and self._settings.probe_client_key_path:
            cert = (self._settings.probe_client_cert_path, self._settings.probe_client_key_path)
        verify: Any = self._settings.tls_ca_cert_path or True
        return httpx.Client(timeout=self._settings.probe_http_timeout_seconds, cert=cert, verify=verify)

    def get_heartbeats(
        self, base_url: str, token: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        url = base_url.rstrip("/") + "/api/v1/query/heartbeats"
        return self._request("GET", url, token, params=params)

    def post_query(self, base_url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        url = base_url.rstrip("/") + "/api/v1/query"
        return self._request("POST", url, token, json=body)

    # -- Scansioni NMAP (proxy verso Probe, aggiunta su richiesta utente) -----
    def post_scan(self, base_url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        url = base_url.rstrip("/") + "/api/v1/scan"
        return self._request("POST", url, token, json=body)

    def get_scans(self, base_url: str, token: str, params: dict[str, Any]) -> dict[str, Any]:
        url = base_url.rstrip("/") + "/api/v1/scans"
        return self._request("GET", url, token, params=params)

    def get_scan(self, base_url: str, token: str, scan_id: str) -> dict[str, Any]:
        url = base_url.rstrip("/") + f"/api/v1/scan/{scan_id}"
        # allow_404: se la Probe non conosce lo scan_id, propaga un 404 (non 503).
        return self._request("GET", url, token, allow_404=True)

    def _request(
        self,
        method: str,
        url: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with self._client() as client:
                resp = client.request(method, url, headers=headers, params=params, json=json)
        except httpx.HTTPError as exc:
            raise errors.service_unavailable(f"Probe non raggiungibile: {exc}")
        if allow_404 and resp.status_code == 404:
            raise errors.not_found("Risorsa inesistente sulla Probe.")
        if resp.status_code == 400:
            raise errors.bad_request("Query non valida sulla Probe.")
        if resp.status_code >= 500:
            raise errors.service_unavailable(f"Errore Probe/OpenSearch (HTTP {resp.status_code}).")
        if resp.status_code != 200:
            raise errors.service_unavailable(f"Risposta Probe inattesa (HTTP {resp.status_code}).")
        data: dict[str, Any] = resp.json()
        return data
