"""Configurazione del Server backend via variabili d'ambiente / file .env.

Precedenza (02_specifica_tecnica.md §6.3): variabili d'ambiente (bootstrap/segreti)
> valori scaricati dal Server (tabella configuration) > default applicativi.
Qui gestiamo il livello "variabili d'ambiente + default"; i parametri runtime
modificabili (TTL token, soglie, retention) sono nella tabella `configuration`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Impostazioni applicative del Server."""

    model_config = SettingsConfigDict(
        env_prefix="PULSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database (PostgreSQL) ---
    database_url: str = "postgresql+psycopg://pulse:pulse@localhost:5432/pulse"

    # --- Porte applicative (03_architettura.md, DOCUMENTO_API §Convenzioni) ---
    api_port: int = 8443
    probe_endpoint_port: int = 9443

    # --- JWT / sicurezza ---
    jwt_secret: str = "change-me-in-production-please-set-PULSE_JWT_SECRET"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1209600
    failed_login_threshold: int = 5

    # --- Cifratura segreti a riposo (RNF-004) ---
    # Chiave Fernet (urlsafe base64, 32 byte). Se assente ne deriva una da jwt_secret.
    secrets_encryption_key: str | None = None

    # --- Enrollment Probe ---
    enrollment_token_ttl_seconds: int = 3600
    probe_offline_timeout_seconds: int = 120

    # --- mTLS / PKI (path certificati, QT-02) ---
    tls_ca_cert_path: str | None = None
    tls_server_cert_path: str | None = None
    tls_server_key_path: str | None = None
    server_probe_endpoint: str = "https://localhost:9443"

    # --- Client HTTP verso le Probe (drill-down) ---
    probe_http_timeout_seconds: float = 10.0
    probe_client_cert_path: str | None = None
    probe_client_key_path: str | None = None

    # --- Logging ---
    log_level: str = "info"

    # --- Rate limiting inbound (webhook) ---
    inbound_rate_limit_per_minute: int = 60


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Restituisce le impostazioni (cache singleton)."""
    return Settings()
