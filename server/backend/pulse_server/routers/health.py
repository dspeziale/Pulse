"""Area Healthcheck (DOCUMENTO_API §1.17). Nessuna autenticazione."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..deps import SessionDep

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("")
def health() -> dict[str, str]:
    """Liveness: il processo risponde."""
    return {"status": "ok"}


@router.get("/ready")
def ready(session: SessionDep) -> JSONResponse:
    """Readiness: verifica la connettivita' al database Server."""
    checks: dict[str, str] = {}
    ok = True
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - qualsiasi errore DB => non pronto
        checks["database"] = "error"
        ok = False
    if ok:
        return JSONResponse(status_code=200, content={"status": "ready", "checks": checks})
    return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})
