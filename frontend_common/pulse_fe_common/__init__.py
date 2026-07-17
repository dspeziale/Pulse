"""Pulse — Codice comune per i frontend Flask (Server e Probe).

Contiene:
- config: lettura configurazione da variabili d'ambiente.
- http_client: client HTTP tipizzato verso le API REST del backend.
- auth: gestione sessione/JWT, decoratori login/permessi, error handlers.
- rbac: utilità di controllo permessi lato UI.
- datetimes: formattazione delle date-ora nel fuso orario configurato.
- datatables: adattatore server-side per DataTables.js (parsing + risposta).

NB: questo pacchetto NON accede mai direttamente a DB o OpenSearch: effettua
solo chiamate REST agli endpoint definiti in docs/api/DOCUMENTO_API.md.
"""

from .datetimes import (DEFAULT_FORMAT, DEFAULT_TIMEZONE, format_datetime,
                        time_presets)

__all__ = [
    "config", "http_client", "auth", "rbac", "datetimes", "datatables",
    "format_datetime", "time_presets", "DEFAULT_TIMEZONE", "DEFAULT_FORMAT",
]

__version__ = "1.0.0"
