"""Applicazione FastAPI del Server centrale Pulse.

Assembla tutti i router del DOCUMENTO_API.md (sezione BACKEND), registra gli
handler di errore standard e configura i metadati OpenAPI.

Avvio locale:
    uvicorn pulse_server.main:app --host 0.0.0.0 --port 8443
"""

from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .errors import register_exception_handlers
from .middleware import security_headers_middleware
from .routers import (
    auth,
    dashboard,
    health,
    inbound,
    notifications,
    observability,
    probe_comm,
    probes,
    roles,
    systems,
    users,
    workflows,
)

_DESCRIPTION = """
API REST del **Server centrale Pulse** (monitoraggio connettivita'/stato applicativo).

Implementa la sezione BACKEND del `DOCUMENTO_API.md`:
autenticazione JWT, RBAC deny-by-default (40 permessi), gestione utenti/ruoli/permessi,
Probe (enrollment/rotazione), sistemi monitorati, drill-down heartbeat via proxy verso
le Probe, dashboard aggregata, canali e workflow di notifica, allarmi, comandi in
ingresso, audit immutabile, log di sistema e configurazione.
"""

_TAGS_METADATA = [
    {"name": "auth", "description": "Autenticazione ed emissione token."},
    {"name": "users", "description": "Gestione utenti."},
    {"name": "roles", "description": "Gestione ruoli."},
    {"name": "permissions", "description": "Catalogo permessi (fisso)."},
    {"name": "probes", "description": "Gestione Probe ed enrollment."},
    {"name": "systems", "description": "Sistemi monitorati."},
    {"name": "checks", "description": "Check scoperti."},
    {"name": "heartbeats-dashboard", "description": "Drill-down heartbeat e dashboard."},
    {"name": "probe-comm", "description": "Endpoint dedicati Server<->Probe (mTLS+token)."},
    {"name": "notifications", "description": "Canali notifica e storico invii."},
    {"name": "workflows", "description": "Workflow notifiche e allarmi."},
    {"name": "inbound", "description": "Comandi in ingresso e identita' di canale."},
    {"name": "audit", "description": "Audit log (immutabile)."},
    {"name": "logs", "description": "Log di sistema."},
    {"name": "config", "description": "Configurazione applicativa."},
    {"name": "health", "description": "Liveness/readiness."},
]


def create_app() -> FastAPI:
    """Factory dell'app (usata da uvicorn e dai test)."""
    app = FastAPI(
        title="Pulse Server API",
        version=__version__,
        description=_DESCRIPTION,
        openapi_tags=_TAGS_METADATA,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
    )
    register_exception_handlers(app)
    app.middleware("http")(security_headers_middleware)

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(roles.router)
    app.include_router(roles.perm_router)
    app.include_router(probes.router)
    app.include_router(systems.router)
    app.include_router(systems.checks_router)
    app.include_router(dashboard.router)
    app.include_router(probe_comm.router)
    app.include_router(notifications.router)
    app.include_router(notifications.history_router)
    app.include_router(workflows.router)
    app.include_router(workflows.alarms_router)
    app.include_router(inbound.router)
    app.include_router(inbound.identities_router)
    app.include_router(observability.audit_router)
    app.include_router(observability.logs_router)
    app.include_router(observability.config_router)
    app.include_router(health.router)
    return app


app = create_app()
