"""Pulse — Codice comune per i frontend Flask (Server e Probe).

Contiene:
- config: lettura configurazione da variabili d'ambiente.
- http_client: client HTTP tipizzato verso le API REST del backend.
- auth: gestione sessione/JWT, decoratori login/permessi, error handlers.
- rbac: utilità di controllo permessi lato UI.

NB: questo pacchetto NON accede mai direttamente a DB o OpenSearch: effettua
solo chiamate REST agli endpoint definiti in docs/api/DOCUMENTO_API.md.
"""

__all__ = ["config", "http_client", "auth", "rbac"]

__version__ = "1.0.0"
