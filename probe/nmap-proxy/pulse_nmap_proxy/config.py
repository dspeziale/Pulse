"""Configurazione del proxy nmap (prefisso env PULSE_NMAP_PROXY_)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxySettings(BaseSettings):
    """Impostazioni del proxy nmap."""

    model_config = SettingsConfigDict(
        env_prefix="PULSE_NMAP_PROXY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bind: 0.0.0.0 per essere raggiungibile dal container via host.docker.internal.
    # La protezione e' mTLS + token (127.0.0.1 NON e' raggiungibile dal container).
    host: str = "0.0.0.0"
    port: int = 8556

    # Token Bearer condiviso con l'agent (obbligatorio in esecuzione reale).
    token: str | None = None

    # mTLS: certificato/chiave del server + CA che firma i certificati CLIENT.
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    tls_client_ca_path: str | None = None

    # Percorso del binario nmap nativo (Windows: nella PATH dopo l'installazione).
    nmap_path: str = "nmap"

    # Tetto massimo al timeout di scansione accettato (secondi).
    max_scan_timeout: int = 3600

    @field_validator("max_scan_timeout")
    @classmethod
    def _cap(cls, v: int) -> int:
        return max(1, min(v, 7200))


@lru_cache(maxsize=1)
def get_settings() -> ProxySettings:
    return ProxySettings()
