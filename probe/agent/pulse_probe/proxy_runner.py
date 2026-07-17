"""Runner nmap che delega l'esecuzione a un PROXY esterno (host Windows).

Su Docker Desktop (Windows/WSL2) il container e' dietro NAT e non raggiunge il
segmento L2 fisico: le scansioni raw e la discovery della LAN locale non
funzionano dal container. Quando ``PULSE_PROBE_NMAP_PROXY_URL`` e' configurato e
il proxy risponde, l'agent usa questo runner al posto di ``scanner.run_nmap``:
l'argv (gia' costruito e validato) viene inviato al proxy su canale mTLS + token
Bearer; il proxy lo ri-valida, esegue nmap nativo e restituisce (rc, stdout,
stderr). La firma e' identica a ``run_nmap`` (argv, timeout) -> tupla: e' quindi
intercambiabile come ``state.scan_runner`` senza toccare ``execute_scan``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger("pulse_probe.proxy_runner")


class ProxyScanRunner:
    """Callable (argv, timeout) -> (rc, stdout, stderr) via proxy nmap esterno."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = (settings.nmap_proxy_url or "").rstrip("/")

    # -- HTTP client (mTLS) ---------------------------------------------------
    def _client(self, timeout: float) -> httpx.Client:
        s = self._settings
        cert: Any = None
        if s.nmap_proxy_client_cert_path and s.nmap_proxy_client_key_path:
            cert = (s.nmap_proxy_client_cert_path, s.nmap_proxy_client_key_path)
        # verify: CA dedicata se presente, altrimenti verifica standard.
        verify: Any = s.nmap_proxy_ca_cert_path if s.nmap_proxy_ca_cert_path else True
        return httpx.Client(timeout=timeout, cert=cert, verify=verify)

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self._settings.nmap_proxy_token:
            h["Authorization"] = f"Bearer {self._settings.nmap_proxy_token}"
        return h

    # -- Self-check -----------------------------------------------------------
    def health(self) -> tuple[bool, str | None]:
        """Verifica raggiungibilita' del proxy; ritorna (ok, versione nmap)."""
        if not self._base:
            return False, None
        url = f"{self._base}/health"
        try:
            with self._client(float(self._settings.nmap_proxy_connect_timeout)) as c:
                r = c.get(url, headers=self._headers())
        except (httpx.HTTPError, OSError) as exc:
            logger.info("Proxy nmap non raggiungibile (%s): %s", url, exc)
            return False, None
        if r.status_code != 200:
            logger.warning("Proxy nmap health status %s", r.status_code)
            return False, None
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return bool(data.get("nmap_available", True)), data.get("nmap_version")

    # -- Esecuzione scansione -------------------------------------------------
    def __call__(self, argv: list[str], timeout: int) -> tuple[int, str, str]:
        """Invia l'argv al proxy e ritorna (returncode, stdout, stderr).

        Non solleva mai: in caso di errore di trasporto/HTTP ritorna un
        returncode != 0 con un messaggio in stderr, cosi' ``execute_scan`` lo
        finalizza come 'failed' con una descrizione chiara.
        """
        if not self._base:
            return 1, "", "Proxy nmap non configurato."
        url = f"{self._base}/scan"
        # Concede al proxy il tempo di eseguire nmap (timeout scansione + margine).
        http_timeout = float(timeout + self._settings.nmap_proxy_connect_timeout)
        try:
            with self._client(http_timeout) as c:
                r = c.post(url, headers=self._headers(),
                           json={"argv": argv, "timeout": timeout})
        except httpx.TimeoutException:
            return 1, "", "Timeout nella comunicazione col proxy nmap."
        except (httpx.HTTPError, OSError) as exc:
            return 1, "", f"Proxy nmap non raggiungibile: {exc}"

        if r.status_code == 401 or r.status_code == 403:
            return 1, "", "Autenticazione col proxy nmap rifiutata (token/mTLS)."
        if r.status_code == 422:
            detail = _safe_detail(r)
            return 1, "", f"Argv rifiutato dal proxy nmap: {detail}"
        if r.status_code != 200:
            return 1, "", f"Proxy nmap ha risposto {r.status_code}: {_safe_detail(r)}"
        try:
            data = r.json()
        except ValueError:
            return 1, "", "Risposta non valida dal proxy nmap."
        return (
            int(data.get("returncode", 1)),
            str(data.get("stdout", "")),
            str(data.get("stderr", "")),
        )


def _safe_detail(r: httpx.Response) -> str:
    try:
        j = r.json()
        return str(j.get("detail", j))
    except ValueError:
        return (r.text or "").strip()[:500]
