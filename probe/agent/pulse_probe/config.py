"""Configurazione della Probe via variabili d'ambiente / .env (prefisso PULSE_PROBE_)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Impostazioni della Probe."""

    model_config = SettingsConfigDict(
        env_prefix="PULSE_PROBE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Identita' e porta ---
    probe_id: str | None = None
    api_port: int = 8444

    # --- Comunicazione col Server ---
    server_base_url: str = "https://localhost:9443"
    # token per-Probe (ottenuto via enrollment o preconfigurato)
    probe_token: str | None = None
    # token di enrollment monouso per il primo contatto
    enrollment_token: str | None = None
    hostname: str = "probe-local"

    # --- Autenticazione delle API di query (token presentato dal Server) ---
    server_query_token: str = "server-to-probe-token"

    # --- OpenSearch locale ---
    opensearch_url: str | None = None  # es. http://localhost:9200; se assente usa storage in-memory
    opensearch_user: str | None = None
    opensearch_password: str | None = None
    opensearch_verify_certs: bool = False
    heartbeat_index: str = "pulse-heartbeats"
    events_index: str = "pulse-events"
    nmap_scan_index: str = "pulse-nmap-scans"

    # --- Poller ---
    poll_default_interval_seconds: int = 30
    poll_default_timeout_seconds: int = 5
    config_refresh_seconds: int = 60
    rollup_window: str = "1h"
    poller_enabled: bool = True

    # --- mTLS (path certificati) ---
    tls_ca_cert_path: str | None = None
    tls_client_cert_path: str | None = None
    tls_client_key_path: str | None = None
    http_verify: bool = False

    # --- Scansioni NMAP (eseguite dalla Probe) ---
    # Timeout per singola scansione in secondi (default 1800, cap 3600).
    scan_timeout: int = 1800
    # Numero massimo di scansioni concorrenti.
    scan_max_concurrency: int = 2

    # --- Proxy nmap ESTERNO (host Windows) ---
    # Su Docker Desktop (Windows/WSL2) il container e' dietro NAT e non e' sul
    # segmento L2 fisico: le scansioni raw (-sS/-sU/-O) e la discovery della LAN
    # non funzionano dal container. Se configurato e raggiungibile, l'agent
    # delega l'esecuzione di nmap a un proxy esterno che gira sull'host Windows
    # (nmap nativo + Npcap). Se assente/irraggiungibile all'avvio -> nmap locale.
    # URL del proxy (es. https://host.docker.internal:8556). Vuoto -> disattivato.
    nmap_proxy_url: str | None = None
    # Token Bearer condiviso col proxy.
    nmap_proxy_token: str | None = None
    # mTLS: CA che firma il certificato del proxy + certificato/chiave client.
    nmap_proxy_ca_cert_path: str | None = None
    nmap_proxy_client_cert_path: str | None = None
    nmap_proxy_client_key_path: str | None = None
    # Timeout (s) delle chiamate HTTP al proxy (oltre al timeout scansione).
    nmap_proxy_connect_timeout: int = 10

    # --- Logging ---
    log_level: str = "info"

    @field_validator("scan_timeout")
    @classmethod
    def _cap_scan_timeout(cls, value: int) -> int:
        """Clamp del timeout di scansione a [1, 3600] secondi."""
        return max(1, min(value, 3600))

    @field_validator("scan_max_concurrency")
    @classmethod
    def _floor_concurrency(cls, value: int) -> int:
        return max(1, value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
