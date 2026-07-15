"""Client della Probe verso il Server centrale (endpoint dedicati §1.9).

Comunicazione su canale mTLS + Bearer probe_token. Espone enrollment, pull della
configurazione, liveness, invio eventi e rollup.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger("pulse_probe.server_client")


class ServerClient:
    """Wrapper HTTP verso gli endpoint /api/v1/probe/* del Server."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = settings.server_base_url.rstrip("/")

    def _client(self) -> httpx.Client:
        cert: Any = None
        if self._settings.tls_client_cert_path and self._settings.tls_client_key_path:
            cert = (self._settings.tls_client_cert_path, self._settings.tls_client_key_path)
        verify: Any = self._settings.tls_ca_cert_path or self._settings.http_verify
        return httpx.Client(timeout=15.0, cert=cert, verify=verify)

    def _auth_headers(self, token: str | None) -> dict[str, str]:
        if not token:
            raise RuntimeError("probe_token non configurato.")
        return {"Authorization": f"Bearer {token}"}

    def register(self, enrollment_token: str, version: str) -> dict[str, Any]:
        url = f"{self._base}/api/v1/probe/register"
        payload = {
            "enrollment_token": enrollment_token,
            "hostname": self._settings.hostname,
            "version": version,
        }
        with self._client() as client:
            resp = client.post(url, json=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    def get_config(self, token: str) -> dict[str, Any]:
        url = f"{self._base}/api/v1/probe/config"
        with self._client() as client:
            resp = client.get(url, headers=self._auth_headers(token))
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    def send_liveness(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/api/v1/probe/heartbeat"
        with self._client() as client:
            resp = client.post(url, headers=self._auth_headers(token), json=body)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    def send_events(self, token: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        url = f"{self._base}/api/v1/probe/events"
        with self._client() as client:
            resp = client.post(url, headers=self._auth_headers(token), json={"events": events})
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    def send_rollup(self, token: str, rollup: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/api/v1/probe/rollup"
        with self._client() as client:
            resp = client.post(url, headers=self._auth_headers(token), json=rollup)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data
