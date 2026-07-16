"""Area Sistemi monitorati (DOCUMENTO_API §1.6) e Check (§1.7)."""

from __future__ import annotations

import datetime as dt
import socket
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, or_, select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..deps import CurrentUser, SessionDep, client_ip, require_any_permission, require_permission
from ..models import DiscoveredCheck, MaintenanceWindow, MonitoredSystem, Probe
from ._helpers import clamp_pagination, commit_or_conflict, flush_or_conflict, offset, parse_uuid

# Numero massimo di documenti canonici restituiti dal test heartbeat.
_MAX_TEST_DOCUMENTS = 20
# Campi obbligatori essenziali dello schema canonico Pulse.
_REQUIRED_CANONICAL_FIELDS = ("system_id", "check_id", "status")

router = APIRouter(prefix="/api/v1/systems", tags=["systems"])
checks_router = APIRouter(prefix="/api/v1/checks", tags=["checks"])


def _require_probe(session: SessionDep, probe_id: str) -> Probe:
    try:
        pid = parse_uuid(probe_id, what="probe_id")
    except errors.ApiError:
        raise errors.unprocessable("Probe inesistente.")
    probe = session.get(Probe, pid)
    if probe is None:
        raise errors.unprocessable("Probe inesistente.")
    return probe


def _bump_probe_config_version(session: SessionDep, probe_id: uuid.UUID) -> None:
    """Aggiorna `config_version` della Probe indicata a un nuovo timestamp.

    Segnala alla Probe (che confronta il config_version restituito dal liveness)
    che la propria configurazione e' cambiata e va ri-scaricata (create/update/
    delete di un sistema monitorato assegnato). Non fa commit: lo fa il chiamante,
    nella stessa transazione dell'operazione (atomicita').
    """
    probe = session.get(Probe, probe_id)
    if probe is not None:
        probe.config_version = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")


def _replace_windows(session: SessionDep, system: MonitoredSystem, windows: list[schemas.MaintenanceWindowIn]) -> None:
    session.execute(
        delete(MaintenanceWindow).where(MaintenanceWindow.system_id == system.id)
    )
    for win in windows:
        if win.end <= win.start:
            raise errors.unprocessable("Finestra di manutenzione con intervallo non valido.")
        session.add(
            MaintenanceWindow(
                system_id=system.id,
                probe_id=system.probe_id,
                start_at=win.start,
                end_at=win.end,
                note=win.note,
            )
        )


@router.get("", response_model=schemas.SystemList)
def list_systems(
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = None,
    probe_id: str | None = None,
    enabled: bool | None = None,
    _: CurrentUser = Depends(require_permission("systems.read")),
) -> schemas.SystemList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(MonitoredSystem)
    count_stmt = select(func.count(MonitoredSystem.id))
    if probe_id is not None:
        pid = parse_uuid(probe_id, what="probe_id")
        stmt = stmt.where(MonitoredSystem.probe_id == pid)
        count_stmt = count_stmt.where(MonitoredSystem.probe_id == pid)
    if enabled is not None:
        stmt = stmt.where(MonitoredSystem.enabled.is_(enabled))
        count_stmt = count_stmt.where(MonitoredSystem.enabled.is_(enabled))
    if q:
        like = f"%{q}%"
        cond = or_(MonitoredSystem.system_id.ilike(like), MonitoredSystem.system_name.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int(session.execute(count_stmt).scalar_one())
    rows = (
        session.execute(
            stmt.order_by(MonitoredSystem.created_at).offset(offset(page, page_size)).limit(page_size)
        )
        .scalars()
        .all()
    )
    return schemas.SystemList(items=[serializers.system_out(session, s) for s in rows], total=total)


@router.post("", response_model=schemas.SystemOut, status_code=201)
def create_system(
    body: schemas.SystemCreate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("systems.create")),
) -> schemas.SystemOut:
    probe = _require_probe(session, body.probe_id)
    th = body.thresholds or schemas.Thresholds()
    system = MonitoredSystem(
        system_id=body.system_id,
        system_name=body.system_name,
        kind=body.kind,
        heartbeat_url=body.heartbeat_url,
        tcp_host=body.tcp_host,
        tcp_port=body.tcp_port,
        probe_id=probe.id,
        poll_interval_seconds=body.poll_interval_seconds,
        timeout_seconds=body.timeout_seconds,
        enabled=body.enabled,
        response_ms_warn=th.response_ms_warn,
        response_ms_error=th.response_ms_error,
    )
    session.add(system)
    flush_or_conflict(session, message="system_id gia' esistente.")
    if body.maintenance_windows:
        _replace_windows(session, system, body.maintenance_windows)
    # La config della Probe assegnata e' cambiata: segnala il re-sync.
    _bump_probe_config_version(session, probe.id)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="systems.create",
        outcome="success",
        entity_type="system",
        entity_id=str(system.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="system_id gia' esistente.")
    session.refresh(system)
    return serializers.system_out(session, system)


@router.get("/{system_id}", response_model=schemas.SystemOut)
def get_system(
    system_id: str, session: SessionDep, _: CurrentUser = Depends(require_permission("systems.read"))
) -> schemas.SystemOut:
    system = session.get(MonitoredSystem, parse_uuid(system_id, what="system_id"))
    if system is None:
        raise errors.not_found("Sistema inesistente.")
    return serializers.system_out(session, system)


@router.put("/{system_id}", response_model=schemas.SystemOut)
def update_system(
    system_id: str,
    body: schemas.SystemUpdate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("systems.update")),
) -> schemas.SystemOut:
    system = session.get(MonitoredSystem, parse_uuid(system_id, what="system_id"))
    if system is None:
        raise errors.not_found("Sistema inesistente.")
    previous_probe_id = system.probe_id
    if body.probe_id is not None:
        system.probe_id = _require_probe(session, body.probe_id).id
    if body.system_name is not None:
        system.system_name = body.system_name
    if body.kind is not None:
        system.kind = body.kind
    if body.heartbeat_url is not None:
        system.heartbeat_url = body.heartbeat_url
    if body.tcp_host is not None:
        system.tcp_host = body.tcp_host
    if body.tcp_port is not None:
        system.tcp_port = body.tcp_port
    if body.poll_interval_seconds is not None:
        system.poll_interval_seconds = body.poll_interval_seconds
    if body.timeout_seconds is not None:
        system.timeout_seconds = body.timeout_seconds
    if body.enabled is not None:
        system.enabled = body.enabled
    if body.thresholds is not None:
        system.response_ms_warn = body.thresholds.response_ms_warn
        system.response_ms_error = body.thresholds.response_ms_error
    if body.maintenance_windows is not None:
        _replace_windows(session, system, body.maintenance_windows)
    # La config e' cambiata: bump della Probe corrente e, in caso di
    # riassegnazione, anche di quella precedente (che perde il sistema).
    _bump_probe_config_version(session, system.probe_id)
    if system.probe_id != previous_probe_id:
        _bump_probe_config_version(session, previous_probe_id)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="systems.update",
        outcome="success",
        entity_type="system",
        entity_id=str(system.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="system_id gia' esistente.")
    session.refresh(system)
    return serializers.system_out(session, system)


@router.delete("/{system_id}", status_code=204)
def delete_system(
    system_id: str,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("systems.delete")),
) -> Response:
    system = session.get(MonitoredSystem, parse_uuid(system_id, what="system_id"))
    if system is None:
        raise errors.not_found("Sistema inesistente.")
    owner_probe_id = system.probe_id
    session.delete(system)
    session.flush()
    # La Probe che possedeva il sistema deve ri-scaricare la config.
    _bump_probe_config_version(session, owner_probe_id)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="systems.delete",
        outcome="success",
        entity_type="system",
        entity_id=str(system_id),
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)


def _build_test_client(timeout_seconds: float) -> httpx.Client:
    """Costruisce il client HTTP per il test heartbeat (isolabile nei test)."""
    return httpx.Client(timeout=timeout_seconds)


def _open_tcp_connection(host: str, port: int, timeout: float) -> None:
    """Apre e chiude subito una connessione TCP verso host:port (isolabile nei test).

    Solleva OSError (inclusi socket.timeout/ConnectionError) se la connessione non
    riesce entro il timeout.
    """
    with socket.create_connection((host, port), timeout=timeout):
        pass


def _test_tcp(body: schemas.SystemTestRequest) -> schemas.SystemTestResponse:
    """Test di connettivita' TCP (esteso su richiesta utente).

    Apre una connessione a `tcp_host:tcp_port` col timeout indicato, misura il
    tempo di connessione e ritorna un singolo documento sintetico check_id='tcp'.
    L'irraggiungibilita' NON e' un errore HTTP: ritorna 200 con reachable=false.
    """
    # host/port garantiti non-None dalla validazione dello schema (kind='tcp').
    assert body.tcp_host is not None and body.tcp_port is not None
    host, port = body.tcp_host, body.tcp_port
    start = time.perf_counter()
    try:
        _open_tcp_connection(host, port, float(body.timeout_seconds))
    except OSError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        doc = schemas.SystemTestDocument(
            system_id=host,
            check_id="tcp",
            check_name="Connettivita' TCP",
            status="down",
            response_ms=elapsed,
            message=f"Connessione TCP fallita verso {host}:{port}: {exc}",
        )
        return schemas.SystemTestResponse(
            reachable=False,
            http_status=None,
            response_ms=elapsed,
            valid_schema=False,
            checks_count=1,
            documents=[doc],
            error=f"Connessione TCP fallita verso {host}:{port}: {exc}",
        )
    elapsed = int((time.perf_counter() - start) * 1000)
    doc = schemas.SystemTestDocument(
        system_id=host,
        check_id="tcp",
        check_name="Connettivita' TCP",
        status="ok",
        response_ms=elapsed,
        message=f"Connessione TCP riuscita verso {host}:{port}.",
    )
    return schemas.SystemTestResponse(
        reachable=True,
        http_status=None,
        response_ms=elapsed,
        valid_schema=True,
        checks_count=1,
        documents=[doc],
        error=None,
    )


def _parse_canonical(payload: Any) -> tuple[bool, list[schemas.SystemTestDocument], int]:
    """Interpreta `payload` come schema canonico Pulse (oggetto singolo o array).

    Ritorna `(valid_schema, documents, checks_count)`. Lo schema e' valido se e'
    un oggetto o un array non vuoto di oggetti che espongono i campi obbligatori
    essenziali (system_id, check_id, status). I documenti sono troncati a
    `_MAX_TEST_DOCUMENTS`, mentre `checks_count` conteggia tutti quelli trovati.
    """
    if isinstance(payload, dict):
        raw_docs: list[Any] = [payload]
    elif isinstance(payload, list):
        raw_docs = payload
    else:
        return False, [], 0
    if not raw_docs:
        return False, [], 0
    documents: list[schemas.SystemTestDocument] = []
    for item in raw_docs:
        if not isinstance(item, dict):
            return False, [], 0
        if any(item.get(field) is None for field in _REQUIRED_CANONICAL_FIELDS):
            return False, [], 0
        if len(documents) < _MAX_TEST_DOCUMENTS:
            documents.append(
                schemas.SystemTestDocument(
                    system_id=str(item["system_id"]),
                    system_name=item.get("system_name"),
                    check_id=str(item["check_id"]),
                    check_name=item.get("check_name"),
                    status=str(item["status"]),
                    response_ms=item.get("response_ms"),
                    message=item.get("message"),
                )
            )
    return True, documents, len(raw_docs)


@router.post(
    "/test",
    response_model=schemas.SystemTestResponse,
    summary="Testa un sistema HTTP o TCP (aggiunta/estesa su richiesta utente)",
    description=(
        "Testa un sistema senza persistere nulla ne' crearlo. Per `kind='http'` "
        "esegue una GET diagnostica verso `heartbeat_url`, misura il tempo di "
        "risposta e prova a interpretare la risposta come schema canonico Pulse "
        "(oggetto singolo o array). Per `kind='tcp'` apre una connessione TCP a "
        "`tcp_host:tcp_port` e restituisce un documento sintetico check_id='tcp'. "
        "L'irraggiungibilita' del target NON e' un errore HTTP: ritorna 200 con "
        "`reachable=false` ed `error` valorizzato. Permesso: `systems.create` "
        "OPPURE `systems.update`."
    ),
)
def test_system_endpoint(
    body: schemas.SystemTestRequest,
    _: CurrentUser = Depends(require_any_permission("systems.create", "systems.update")),
) -> schemas.SystemTestResponse:
    if body.kind == "tcp":
        return _test_tcp(body)
    # kind == 'http': heartbeat_url garantito non-None dalla validazione.
    assert body.heartbeat_url is not None
    start = time.perf_counter()
    try:
        with _build_test_client(float(body.timeout_seconds)) as client:
            resp = client.get(body.heartbeat_url)
    except httpx.HTTPError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return schemas.SystemTestResponse(
            reachable=False,
            http_status=None,
            response_ms=elapsed,
            valid_schema=False,
            checks_count=0,
            documents=[],
            error=f"Target non raggiungibile: {exc}",
        )
    elapsed = int((time.perf_counter() - start) * 1000)
    try:
        payload = resp.json()
    except ValueError:
        return schemas.SystemTestResponse(
            reachable=True,
            http_status=resp.status_code,
            response_ms=elapsed,
            valid_schema=False,
            checks_count=0,
            documents=[],
            error="La risposta del target non e' in formato JSON.",
        )
    valid, documents, count = _parse_canonical(payload)
    error = None if valid else "La risposta JSON non e' conforme allo schema canonico Pulse."
    return schemas.SystemTestResponse(
        reachable=True,
        http_status=resp.status_code,
        response_ms=elapsed,
        valid_schema=valid,
        checks_count=count,
        documents=documents,
        error=error,
    )


@router.get("/{system_id}/checks", response_model=schemas.SystemChecksList)
def system_checks(
    system_id: str,
    session: SessionDep,
    _: CurrentUser = Depends(require_permission("checks.read")),
) -> schemas.SystemChecksList:
    system = session.get(MonitoredSystem, parse_uuid(system_id, what="system_id"))
    if system is None:
        raise errors.not_found("Sistema inesistente.")
    rows = (
        session.execute(select(DiscoveredCheck).where(DiscoveredCheck.system_id == system.id))
        .scalars()
        .all()
    )
    return schemas.SystemChecksList(items=[serializers.check_out(c) for c in rows])


@checks_router.get("", response_model=schemas.GlobalChecksList)
def list_checks(
    session: SessionDep,
    system_id: str | None = None,
    probe_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: CurrentUser = Depends(require_permission("checks.read")),
) -> schemas.GlobalChecksList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(DiscoveredCheck, MonitoredSystem.system_id).join(
        MonitoredSystem, MonitoredSystem.id == DiscoveredCheck.system_id
    )
    count_stmt = select(func.count(DiscoveredCheck.id)).join(
        MonitoredSystem, MonitoredSystem.id == DiscoveredCheck.system_id
    )
    if system_id is not None:
        stmt = stmt.where(MonitoredSystem.system_id == system_id)
        count_stmt = count_stmt.where(MonitoredSystem.system_id == system_id)
    if probe_id is not None:
        pid = parse_uuid(probe_id, what="probe_id")
        stmt = stmt.where(DiscoveredCheck.probe_id == pid)
        count_stmt = count_stmt.where(DiscoveredCheck.probe_id == pid)
    total = int(session.execute(count_stmt).scalar_one())
    rows = session.execute(stmt.offset(offset(page, page_size)).limit(page_size)).all()
    items = [
        schemas.GlobalCheckOut(
            system_id=business_system_id,
            check_id=c.check_id,
            check_name=c.check_name,
            probe_id=str(c.probe_id) if c.probe_id else None,
            last_status=c.last_status,
            last_seen_at=c.last_seen_at,
        )
        for c, business_system_id in rows
    ]
    return schemas.GlobalChecksList(items=items, total=total)
