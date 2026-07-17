"""Esecuzione delle scansioni nmap in background e finalizzazione su storage.

SICUREZZA: nmap e' eseguito con `subprocess.run` passando l'ARGV COME LISTA e
senza shell (`shell=False`, il default). Nessun input utente raggiunge una shell.
"""

from __future__ import annotations

import datetime as dt
import logging
import subprocess
from typing import TYPE_CHECKING, Any

from . import nmap_scan

if TYPE_CHECKING:  # pragma: no cover - solo per i tipi
    from .state import RuntimeState

logger = logging.getLogger("pulse_probe.scanner")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_nmap(argv: list[str], timeout: int) -> tuple[int, str, str]:
    """Esegue nmap (argv lista, NIENTE shell). Ritorna (returncode, stdout, stderr)."""
    proc = subprocess.run(  # noqa: S603 - argv lista validata, shell=False
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def detect_nmap() -> tuple[bool, str | None]:
    """Self-check: verifica se nmap e' disponibile e ne ritorna la prima riga di versione."""
    try:
        rc, stdout, _ = run_nmap(["nmap", "--version"], timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False, None
    if rc != 0:
        return False, None
    first_line = stdout.strip().splitlines()[0] if stdout.strip() else None
    return True, first_line


def _classify_error(returncode: int, stderr: str) -> str:
    """Traduce lo stderr nmap in un messaggio d'errore chiaro."""
    low = stderr.lower()
    if "root privileges" in low or "requires root" in low or "cap_net_raw" in low or "requires privilege" in low:
        return (
            "La scansione richiede privilegi elevati (CAP_NET_RAW): -sS/-sU/-O "
            "necessitano cap_net_raw/cap_net_admin sul container. Dettaglio: "
            + stderr.strip()
        )
    detail = stderr.strip() or f"nmap ha restituito codice {returncode}."
    return f"Errore nmap: {detail}"


def _finalize(state: RuntimeState, scan_id: str, **fields: Any) -> None:
    """Aggiorna il documento della scansione (merge) e lo re-indicizza."""
    doc = state.store.get_scan(scan_id)
    if doc is None:  # pragma: no cover - difensivo: il doc 'running' esiste sempre
        return
    doc.update(fields)
    doc["finished_at"] = _now_iso()
    state.store.index_scan(doc)


def execute_scan(state: RuntimeState, scan_id: str, argv: list[str]) -> None:
    """Esegue la scansione (in background) e finalizza il documento su storage.

    Rispetta il limite di concorrenza tramite il semaforo dello stato. Cattura
    timeout, nmap mancante, errori di privilegi e XML non valido -> status failed.
    """
    with state.scans_semaphore:
        try:
            returncode, stdout, stderr = state.scan_runner(argv, state.settings.scan_timeout)
        except subprocess.TimeoutExpired:
            _finalize(state, scan_id, status="failed", error="Timeout della scansione superato.")
            return
        except OSError as exc:
            _finalize(
                state,
                scan_id,
                status="failed",
                error=f"Impossibile eseguire nmap (installato nel container?): {exc}",
            )
            return

        if returncode != 0:
            _finalize(state, scan_id, status="failed", error=_classify_error(returncode, stderr))
            return

        try:
            parsed = nmap_scan.parse_nmap_xml(stdout)
        except nmap_scan.ScanValidationError as exc:
            _finalize(state, scan_id, status="failed", error=str(exc))
            return

        _finalize(
            state,
            scan_id,
            status="done",
            error=None,
            summary=parsed["summary"],
            hosts=parsed["hosts"],
        )
