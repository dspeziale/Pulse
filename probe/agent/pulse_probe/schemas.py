"""Schemi Pydantic v2 della Probe (API di query e stato). Aderenti al DOCUMENTO_API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
