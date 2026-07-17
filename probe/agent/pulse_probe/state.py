"""Stato runtime della Probe (config effettiva, ultimi stati, code, metriche)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .scanner import run_nmap
from .server_client import ServerClient
from .store import Store

# Firma del runner nmap: (argv, timeout) -> (returncode, stdout, stderr).
ScanRunner = Callable[[list[str], int], tuple[int, str, str]]


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
    # --- Scansioni NMAP ---
    # Runner iniettabile (monkeypatch nei test); default: subprocess reale (argv lista).
    scan_runner: ScanRunner = run_nmap
    # Semaforo per limitare la concorrenza delle scansioni (inizializzato in __post_init__).
    scans_semaphore: threading.BoundedSemaphore = field(
        default_factory=lambda: threading.BoundedSemaphore(1)
    )
    # Disponibilita' di nmap (self-check all'avvio: locale o via proxy).
    nmap_available: bool = False
    nmap_version: str | None = None
    # Backend di esecuzione nmap effettivo: "local" (in-container) o "proxy"
    # (host esterno, es. Windows). Solo informativo (esposto in /status).
    scan_backend: str = "local"

    def __post_init__(self) -> None:
        # Dimensiona il semaforo secondo la concorrenza configurata.
        self.scans_semaphore = threading.BoundedSemaphore(self.settings.scan_max_concurrency)

    def uptime_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    def system_thresholds(self, system_id: str) -> dict[str, Any]:
        for s in self.systems:
            if s.get("system_id") == system_id:
                return s.get("thresholds") or {}
        return {}
