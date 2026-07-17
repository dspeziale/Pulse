"""Schemi Pydantic v2 della Probe (API di query e stato). Aderenti al DOCUMENTO_API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import nmap_scan


class _Model(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class HeartbeatList(_Model):
    items: list[dict[str, Any]]
    total: int


class QueryFilter(_Model):
    field: str
    op: str
    value: Any = None


class QueryAggregation(_Model):
    type: Literal["avg", "min", "max", "count", "uptime"]
    field: str | None = None
    interval: str | None = None


class QueryRequest(_Model):
    filters: list[QueryFilter] = Field(default_factory=list)
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    aggregations: list[QueryAggregation] | None = None
    page: int | None = None
    page_size: int | None = None
    sort: str | None = None


class QueryResponse(_Model):
    items: list[dict[str, Any]]
    aggregations: dict[str, Any]
    total: int


class ProbeSystemOut(_Model):
    system_id: str
    system_name: str
    # Tipo di controllo (esteso su richiesta utente): 'http' o 'tcp'.
    kind: str = "http"
    # heartbeat_url e' None per i sistemi TCP: nullable per non far fallire la serializzazione.
    heartbeat_url: str | None = None
    tcp_host: str | None = None
    tcp_port: int | None = None
    poll_interval_seconds: int
    timeout_seconds: int
    enabled: bool


class ProbeSystemsList(_Model):
    items: list[ProbeSystemOut]


class ProbeStatusOut(_Model):
    probe_id: str | None
    version: str
    uptime_seconds: int
    opensearch_healthy: bool
    poller_running: bool
    systems_polled: int
    last_poll_at: str | None
    config_version: str | None
    pending_events: int
    # Self-check: nmap disponibile nel container e relativa versione.
    nmap_available: bool = False
    nmap_version: str | None = None


# ============================ Scansioni NMAP ==============================


class ScanRequest(_Model):
    """Opzioni di una scansione NMAP (stesso contratto usato dal FE).

    Ogni campo e' validato con whitelist/regex; le stringhe non raggiungono mai
    una shell (l'esecuzione usa argv come lista).
    """

    target: str
    timing: Literal["T0", "T1", "T2", "T3", "T4", "T5"] = "T3"
    technique: Literal["connect", "syn", "udp", "ping"] = "connect"
    ports: str | None = None
    top_ports: int | None = Field(default=None, ge=1, le=65535)
    service_version: bool = False
    version_intensity: int | None = Field(default=None, ge=0, le=9)
    os_detection: bool = False
    no_ping: bool = False
    scripts: list[str] = Field(default_factory=list)
    script_args: str | None = None
    min_rate: int | None = Field(default=None, ge=1)
    max_rate: int | None = Field(default=None, ge=1)
    max_retries: int | None = Field(default=None, ge=0, le=20)
    extra: str | None = None

    @field_validator("target")
    @classmethod
    def _v_target(cls, value: str) -> str:
        nmap_scan.validate_target(value)  # solleva -> 422
        return value

    @field_validator("ports")
    @classmethod
    def _v_ports(cls, value: str | None) -> str | None:
        return nmap_scan.validate_ports(value) if value is not None else None

    @field_validator("scripts")
    @classmethod
    def _v_scripts(cls, value: list[str]) -> list[str]:
        return nmap_scan.validate_scripts(value)

    @field_validator("script_args")
    @classmethod
    def _v_script_args(cls, value: str | None) -> str | None:
        return nmap_scan.validate_script_args(value) if value is not None else None

    @field_validator("extra")
    @classmethod
    def _v_extra(cls, value: str | None) -> str | None:
        if value is not None:
            nmap_scan.validate_extra(value)  # solleva -> 422
        return value


class ScanStartResponse(_Model):
    scan_id: str
    status: str
    started_at: str
    target: str


class ScanSummary(_Model):
    hosts_up: int
    hosts_total: int
    ports_open: int


class ScanListItem(_Model):
    scan_id: str
    target: str
    status: str
    started_at: str
    finished_at: str | None = None
    summary: dict[str, Any] | None = None


class ScanList(_Model):
    items: list[ScanListItem]
    total: int


class ScanDetail(_Model):
    scan_id: str
    target: str
    options: dict[str, Any]
    status: str
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None
    hosts: list[dict[str, Any]] = Field(default_factory=list)
