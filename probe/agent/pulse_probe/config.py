"""Configurazione della Probe via variabili d'ambiente / .env (prefisso PULSE_PROBE_)."""

from __future__ import annotations

from functools import lru_cache

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

    # --- Logging ---
    log_level: str = "info"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
