"""Configurazione dei frontend Flask, letta da variabili d'ambiente.

Tutte le impostazioni sono sovrascrivibili via env (requisito: config via env).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return float(raw)


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


@dataclass(frozen=True)
class ServerDashboardConfig:
    """Configurazione della dashboard del SERVER."""

    #: URL base del backend FastAPI del Server (sezione BACKEND del DOCUMENTO_API).
    api_base_url: str
    #: Chiave segreta Flask per firmare la sessione.
    secret_key: str
    #: Timeout (secondi) delle chiamate HTTP verso il backend.
    request_timeout: float
    #: Verifica dei certificati TLS nelle chiamate HTTP.
    verify_tls: bool
    #: Porta di ascolto dell'app Flask.
    port: int
    #: Nome del cookie di sessione Flask. DEVE differire da quello della Probe:
    #: i cookie non distinguono la porta su localhost, quindi un nome condiviso
    #: farebbe sovrascrivere a vicenda le due sessioni (deautenticazione).
    session_cookie_name: str = "pulse_server_session"
    #: Attributo Secure del cookie di sessione (True solo dietro HTTPS).
    session_cookie_secure: bool = False

    @classmethod
    def from_env(cls) -> "ServerDashboardConfig":
        return cls(
            api_base_url=os.environ.get(
                "PULSE_SERVER_API_BASE", "http://localhost:8000/api/v1"
            ).rstrip("/"),
            secret_key=os.environ.get("PULSE_SERVER_SECRET_KEY", "dev-server-secret"),
            request_timeout=_get_float("PULSE_HTTP_TIMEOUT", 10.0),
            verify_tls=_get_bool("PULSE_VERIFY_TLS", True),
            port=_get_int("PULSE_SERVER_DASH_PORT", 5000),
            session_cookie_name=os.environ.get(
                "PULSE_SERVER_SESSION_COOKIE_NAME", "pulse_server_session"
            ),
            session_cookie_secure=_get_bool(
                "PULSE_SERVER_SESSION_COOKIE_SECURE", False
            ),
        )


@dataclass(frozen=True)
class ProbeDashboardConfig:
    """Configurazione della dashboard della PROBE."""

    #: URL base del probe agent (sezione BACKEND, endpoint sulla PROBE).
    agent_base_url: str
    #: Token Bearer per interrogare gli endpoint del probe agent (vedi FE-03).
    agent_token: str
    #: Credenziali di login locale della dashboard Probe (vedi FE-02).
    dash_user: str
    dash_password: str
    #: Chiave segreta Flask per firmare la sessione.
    secret_key: str
    #: Timeout (secondi) delle chiamate HTTP verso il probe agent.
    request_timeout: float
    #: Verifica dei certificati TLS nelle chiamate HTTP.
    verify_tls: bool
    #: Porta di ascolto dell'app Flask.
    port: int
    #: Nome del cookie di sessione Flask. DEVE differire da quello del Server:
    #: i cookie non distinguono la porta su localhost, quindi un nome condiviso
    #: farebbe sovrascrivere a vicenda le due sessioni (deautenticazione).
    session_cookie_name: str = "pulse_probe_session"
    #: Attributo Secure del cookie di sessione (True solo dietro HTTPS).
    session_cookie_secure: bool = False
    #: Fuso orario (IANA) per la visualizzazione delle date-ora. La dashboard
    #: Probe non ha accesso alla config del Server, quindi lo legge da env.
    timezone: str = "Europe/Rome"

    @classmethod
    def from_env(cls) -> "ProbeDashboardConfig":
        return cls(
            agent_base_url=os.environ.get(
                "PULSE_PROBE_API_BASE", "http://localhost:8444/api/v1"
            ).rstrip("/"),
            agent_token=os.environ.get("PULSE_PROBE_AGENT_TOKEN", ""),
            dash_user=os.environ.get("PULSE_PROBE_DASH_USER", "probe"),
            dash_password=os.environ.get("PULSE_PROBE_DASH_PASSWORD", "probe"),
            secret_key=os.environ.get("PULSE_PROBE_SECRET_KEY", "dev-probe-secret"),
            request_timeout=_get_float("PULSE_HTTP_TIMEOUT", 10.0),
            verify_tls=_get_bool("PULSE_VERIFY_TLS", True),
            port=_get_int("PULSE_PROBE_DASH_PORT", 5001),
            session_cookie_name=os.environ.get(
                "PULSE_PROBE_SESSION_COOKIE_NAME", "pulse_probe_session"
            ),
            session_cookie_secure=_get_bool(
                "PULSE_PROBE_SESSION_COOKIE_SECURE", False
            ),
            timezone=os.environ.get("PULSE_PROBE_TIMEZONE", "Europe/Rome"),
        )
