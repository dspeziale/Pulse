"""Risoluzione probe_id -> nome per la dashboard SERVER.

Ovunque si referenzia una Sonda si vuole mostrarne il NOME, non il codice
(UUID/probe_id). Le risposte del backend spesso contengono solo il probe_id
(es. aggregate, allarmi, sistemi): per tradurlo in nome interroghiamo una volta
GET /api/v1/probes e costruiamo una mappa {id: name}, memorizzata in una piccola
cache per-processo con TTL breve (default 60s) — stesso pattern di ``tzsource``.

Fallback robusto: qualsiasi errore (permesso probes.read assente, backend giu',
id non presente in mappa) ripiega sul probe_id stesso, senza mai far fallire il
rendering. Gli URL (url_for) continuano a usare il probe_id: qui si traduce solo
il TESTO mostrato.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

#: TTL di default della cache dei nomi Sonda (secondi).
DEFAULT_TTL = 60.0
#: Numero massimo di Sonde risolte in un colpo (page_size della lista).
MAX_PROBES = 200


def fetch_probe_names(client, token) -> dict:
    """Costruisce la mappa {probe_id: name} da GET /probes (token di sessione)."""
    data = client.get("/probes", token=token, params={"page_size": MAX_PROBES})
    names: dict[str, str] = {}
    for item in (data.get("items") or []):
        pid = item.get("id")
        if pid is None:
            continue
        key = str(pid)
        names[key] = item.get("name") or key
    return names


def resolve_probe_names(
    cache: dict,
    fetch: Callable[[], dict],
    ttl: float = DEFAULT_TTL,
    now: Optional[float] = None,
) -> dict:
    """Mappa {id: name} corrente con cache TTL.

    ``cache`` e' un dict mutabile ({'value', 'exp'}) tipicamente conservato in
    ``app.config`` (isolato alla vita dell'app). Su errore ripiega su mappa vuota.
    """
    current = now if now is not None else time.monotonic()
    if cache.get("exp", 0.0) > current:
        return cache["value"]
    names: dict = {}
    try:
        names = fetch() or {}
    except Exception:  # errore backend/permessi: mappa vuota -> fallback all'id
        names = {}
    cache["value"] = names
    cache["exp"] = current + ttl
    return names


def probe_name(names: dict, probe_id) -> str:
    """Nome della Sonda dato il probe_id; ripiega sul probe_id se non in mappa."""
    if probe_id is None or probe_id == "":
        return "—"
    key = str(probe_id)
    return names.get(key, key)
