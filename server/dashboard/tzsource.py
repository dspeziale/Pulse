"""Sorgente del fuso orario per la dashboard SERVER.

Il fuso orario di visualizzazione e' un parametro di configurazione del backend
(GET /api/v1/config, item con key == 'timezone'). Per non interrogare /config a
ogni richiesta usiamo una piccola cache per-processo con TTL breve (default 60s):
al salvataggio della configurazione il nuovo valore viene quindi raccolto entro
il TTL. Qualsiasi errore (config non leggibile, permesso assente, backend giu')
ripiega silenziosamente su DEFAULT_TIMEZONE, senza mai far fallire il rendering
ne' disconnettere l'utente.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from pulse_fe_common.datetimes import DEFAULT_TIMEZONE

#: TTL di default della cache del fuso orario (secondi).
DEFAULT_TTL = 60.0


def fetch_config_timezone(client, token) -> Optional[str]:
    """Ritorna il valore dell'item di config 'timezone', o None se assente."""
    data = client.get("/config", token=token)
    for item in (data.get("items") or []):
        if item.get("key") == "timezone":
            return item.get("value")
    return None


def resolve_timezone(
    cache: dict,
    fetch: Callable[[], Optional[str]],
    ttl: float = DEFAULT_TTL,
    now: Optional[float] = None,
) -> str:
    """Fuso orario corrente con cache TTL.

    ``cache`` e' un dict mutabile ({'value', 'exp'}) tipicamente conservato in
    ``app.config`` per isolarne la vita a quella dell'app. ``fetch`` e' una
    callable senza argomenti che ritorna il fuso configurato o None.
    """
    current = now if now is not None else time.monotonic()
    if cache.get("exp", 0.0) > current:
        return cache["value"]
    tz = DEFAULT_TIMEZONE
    try:
        value = fetch()
        if value:
            tz = str(value)
    except Exception:  # errore backend/permessi: ripiego sul default
        tz = DEFAULT_TIMEZONE
    cache["value"] = tz
    cache["exp"] = current + ttl
    return tz
