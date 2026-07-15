"""Stato runtime della Probe (config effettiva, ultimi stati, code, metriche)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .server_client import ServerClient
from .store import Store


@dataclass
class RuntimeState:
    """Contenitore mutabile dello stato del processo Probe."""

    settings: Settings
    store: Store
    server: ServerClient
    probe_token: str | None = None
    probe_id: str | None = None
    config_version: str | None = None
    systems: list[dict[str, Any]] = field(default_factory=list)
    # ultimo stato normalizzato per (system_id, check_id)
    last_statuses: dict[tuple[str, str], str] = field(default_factory=dict)
    last_poll_at: str | None = None
    systems_polled: int = 0
    pending_events: int = 0
    poller_running: bool = False
    started_at: float = field(default_factory=time.monotonic)

    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    def system_thresholds(self, system_id: str) -> dict[str, Any]:
        for s in self.systems:
            if s.get("system_id") == system_id:
                return s.get("thresholds") or {}
        return {}
