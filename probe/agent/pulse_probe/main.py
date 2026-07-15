"""Applicazione FastAPI della Probe (API di query + comunicazione col Server).

Avvio locale:
    uvicorn pulse_probe.main:app --host 0.0.0.0 --port 8444
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from . import __version__, errors, schemas
from .config import Settings, get_settings
from .deps import get_state, require_server_token
from .poller import poll_once
from .server_client import ServerClient
from .state import RuntimeState
from .store import build_store

logger = logging.getLogger("pulse_probe")


def bootstrap_state(settings: Settings) -> RuntimeState:
    """Costruisce lo stato runtime (store + client), senza effettuare rete."""
    store = build_store(settings)
    server = ServerClient(settings)
    return RuntimeState(
        settings=settings,
        store=store,
        server=server,
        probe_token=settings.probe_token,
        probe_id=settings.probe_id,
    )


def sync_config(state: RuntimeState) -> None:
    """Enrollment (se necessario) e pull della configurazione dal Server."""
    settings = state.settings
    if not state.probe_token and settings.enrollment_token:
        data = state.server.register(settings.enrollment_token, __version__)
        state.probe_token = data.get("probe_token")
        state.probe_id = data.get("probe_id")
    if state.probe_token:
        config = state.server.get_config(state.probe_token)
        state.systems = config.get("systems", [])
        state.config_version = config.get("config_version")
        state.probe_id = config.get("probe_id", state.probe_id)


async def _poller_loop(app: FastAPI) -> None:  # pragma: no cover - loop periodico runtime
    state: RuntimeState = app.state.runtime
    state.poller_running = True
    interval = state.settings.poll_default_interval_seconds
    try:
        while True:
            try:
                with httpx.Client(verify=state.settings.http_verify) as client:
                    await asyncio.to_thread(poll_once, state, client)
                if state.probe_token:
                    await asyncio.to_thread(_send_liveness, state)
            except Exception as exc:  # noqa: BLE001  # pragma: no cover - loop difensivo
                logger.warning("Ciclo di polling fallito: %s", exc)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:  # pragma: no cover - shutdown
        pass
    finally:
        state.poller_running = False


def _send_liveness(state: RuntimeState) -> None:
    body = {
        "version": __version__,
        "uptime_seconds": state.uptime_seconds(),
        "opensearch_healthy": state.store.healthy(),
        "systems_polled": state.systems_polled,
        "last_poll_at": state.last_poll_at or "",
    }
    assert state.probe_token is not None
    resp = state.server.send_liveness(state.probe_token, body)
    new_version = resp.get("config_version")
    if new_version and new_version != state.config_version:
        sync_config(state)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Riusa uno stato gia' iniettato (es. nei test) altrimenti lo costruisce.
    state: RuntimeState = getattr(app.state, "runtime", None)  # type: ignore[assignment]
    if state is None:
        settings = get_settings()
        state = bootstrap_state(settings)
        app.state.runtime = state
    else:
        settings = state.settings
    with contextlib.suppress(Exception):  # bootstrap best-effort: l'app parte comunque
        sync_config(state)
    task: asyncio.Task[None] | None = None
    if settings.poller_enabled:  # pragma: no cover - avviato solo in esecuzione reale
        task = asyncio.create_task(_poller_loop(app))
    try:
        yield
    finally:
        if task is not None:  # pragma: no cover - shutdown
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app(settings: Settings | None = None) -> FastAPI:
    """Factory dell'app. Se `settings` e' fornito, lo stato e' inizializzato senza rete."""
    app = FastAPI(
        title="Pulse Probe API",
        version=__version__,
        description="API di query della Probe (OpenSearch locale) e stato interno. Vedi DOCUMENTO_API §1.9.",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url="/api/v1/redoc",
        lifespan=lifespan,
    )
    errors.register_exception_handlers(app)

    if settings is not None:
        app.state.runtime = bootstrap_state(settings)

    @app.get("/api/v1/query/heartbeats", response_model=schemas.HeartbeatList, tags=["query"])
    def query_heartbeats(
        state: RuntimeState = Depends(get_state),
        _: None = Depends(require_server_token),
        system_id: str | None = None,
        check_id: str | None = None,
        status: str | None = None,
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
        sort: str | None = None,
    ) -> schemas.HeartbeatList:
        filters: list[dict[str, Any]] = []
        if system_id is not None:
            filters.append({"field": "system_id", "op": "eq", "value": system_id})
        if check_id is not None:
            filters.append({"field": "check_id", "op": "eq", "value": check_id})
        if status is not None:
            filters.append({"field": "status", "op": "eq", "value": status})
        items, total, _aggs = state.store.search_heartbeats(
            filters=filters, frm=from_, to=to, sort=sort or "-@timestamp", page=page, page_size=page_size
        )
        return schemas.HeartbeatList(items=items, total=total)

    @app.post("/api/v1/query", response_model=schemas.QueryResponse, tags=["query"])
    def query_advanced(
        body: schemas.QueryRequest,
        state: RuntimeState = Depends(get_state),
        _: None = Depends(require_server_token),
    ) -> schemas.QueryResponse:
        filters = [f.model_dump() for f in body.filters]
        aggregations = [a.model_dump() for a in (body.aggregations or [])]
        items, total, aggs = state.store.search_heartbeats(
            filters=filters,
            frm=body.from_,
            to=body.to,
            aggregations=aggregations,
            sort=body.sort,
            page=body.page,
            page_size=body.page_size,
        )
        return schemas.QueryResponse(items=items, aggregations=aggs, total=total)

    @app.get("/api/v1/systems", response_model=schemas.ProbeSystemsList, tags=["query"])
    def probe_systems(
        state: RuntimeState = Depends(get_state),
        _: None = Depends(require_server_token),
    ) -> schemas.ProbeSystemsList:
        items = [
            schemas.ProbeSystemOut(
                system_id=s["system_id"],
                system_name=s.get("system_name", s["system_id"]),
                heartbeat_url=s.get("heartbeat_url", ""),
                poll_interval_seconds=s.get("poll_interval_seconds", 0),
                timeout_seconds=s.get("timeout_seconds", 0),
                enabled=s.get("enabled", True),
            )
            for s in state.systems
        ]
        return schemas.ProbeSystemsList(items=items)

    @app.get("/api/v1/status", response_model=schemas.ProbeStatusOut, tags=["query"])
    def probe_status(
        state: RuntimeState = Depends(get_state),
        _: None = Depends(require_server_token),
    ) -> schemas.ProbeStatusOut:
        return schemas.ProbeStatusOut(
            probe_id=state.probe_id,
            version=__version__,
            uptime_seconds=state.uptime_seconds(),
            opensearch_healthy=state.store.healthy(),
            poller_running=state.poller_running,
            systems_polled=state.systems_polled,
            last_poll_at=state.last_poll_at,
            config_version=state.config_version,
            pending_events=state.pending_events,
        )

    @app.get("/api/v1/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/health/ready", tags=["health"])
    def ready(state: RuntimeState = Depends(get_state)) -> JSONResponse:
        healthy = state.store.healthy()
        checks = {"opensearch": "ok" if healthy else "error", "poller": "ok" if state.poller_running else "idle"}
        status_code = 200 if healthy else 503
        return JSONResponse(status_code=status_code, content={"status": "ready" if healthy else "not_ready", "checks": checks})

    return app


app = create_app()
