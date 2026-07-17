"""Area Heartbeat/Query proxy e Dashboard (DOCUMENTO_API §1.8)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from .. import errors, schemas, serializers
from ..audit import write_audit, write_system_log
from ..context import ProbeClientDep
from ..deps import CurrentUser, SessionDep, SettingsDep, client_ip, require_permission
from ..models import Alarm, MonitoredSystem, Probe, ProbeRollup

router = APIRouter(prefix="/api/v1", tags=["heartbeats-dashboard"])

_NORMALIZED = ("ok", "warn", "error", "down", "unknown")


def _require_probe(session: SessionDep, probe_id: str) -> Probe:
    from ._helpers import parse_uuid

    probe = session.get(Probe, parse_uuid(probe_id, what="probe_id"))
    if probe is None:
        raise errors.not_found("Probe inesistente.")
    return probe


def _probe_base_url(probe: Probe) -> str:
    if not probe.query_endpoint:
        raise errors.service_unavailable("Endpoint di query della Probe non configurato.")
    return probe.query_endpoint


@router.get("/probes/{probe_id}/heartbeats", response_model=schemas.HeartbeatList)
def get_heartbeats(
    probe_id: str,
    session: SessionDep,
    settings: SettingsDep,
    client: ProbeClientDep,
    system_id: str | None = None,
    check_id: str | None = None,
    status: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort: str | None = None,
    _: CurrentUser = Depends(require_permission("heartbeats.read")),
) -> schemas.HeartbeatList:
    probe = _require_probe(session, probe_id)
    params: dict[str, Any] = {
        "system_id": system_id,
        "check_id": check_id,
        "status": status,
        "from": from_,
        "to": to,
        "page": page,
        "page_size": page_size,
        "sort": sort,
    }
    params = {k: v for k, v in params.items() if v is not None}
    data = client.get_heartbeats(_probe_base_url(probe), settings.probe_query_token, params)
    return schemas.HeartbeatList(items=data.get("items", []), total=int(data.get("total", 0)))


@router.post("/probes/{probe_id}/query", response_model=schemas.QueryResponse)
def post_query(
    probe_id: str,
    body: schemas.QueryRequest,
    session: SessionDep,
    settings: SettingsDep,
    client: ProbeClientDep,
    _: CurrentUser = Depends(require_permission("heartbeats.query")),
) -> schemas.QueryResponse:
    probe = _require_probe(session, probe_id)
    payload = body.model_dump(by_alias=True, exclude_none=True)
    data = client.post_query(_probe_base_url(probe), settings.probe_query_token, payload)
    return schemas.QueryResponse(
        items=data.get("items", []),
        aggregations=data.get("aggregations", {}),
        total=int(data.get("total", 0)),
    )


def _latest_rollup(session: SessionDep, probe_id: Any) -> ProbeRollup | None:
    return session.execute(
        select(ProbeRollup)
        .where(ProbeRollup.probe_id == probe_id)
        .order_by(ProbeRollup.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _system_name_map(session: SessionDep, probe_id: Any) -> dict[str, str]:
    """Mappa {system_id -> system_name} dei sistemi registrati per la Probe.

    I rollup della Sonda espongono solo `system_id`; questa mappa consente di
    arricchire ogni voce con il nome leggibile registrato lato Server. La
    chiave `system_id` di MonitoredSystem e' unique globale.
    """
    rows = session.execute(
        select(MonitoredSystem.system_id, MonitoredSystem.system_name).where(
            MonitoredSystem.probe_id == probe_id
        )
    ).all()
    return {row.system_id: row.system_name for row in rows}


def _enrich_systems(
    systems: list[dict[str, Any]], name_map: dict[str, str]
) -> list[dict[str, Any]]:
    """Aggiunge/valorizza `system_name` a ogni voce dei sistemi del rollup.

    Fallback al `system_id` se il sistema non e' (piu') registrato lato Server.
    """
    enriched: list[dict[str, Any]] = []
    for sysrec in systems:
        item = dict(sysrec)
        system_id = str(item.get("system_id", ""))
        item["system_name"] = name_map.get(system_id, system_id)
        enriched.append(item)
    return enriched


@router.get("/dashboard/aggregate", response_model=schemas.DashboardAggregate)
def dashboard_aggregate(
    session: SessionDep,
    request: Request,
    window: str = "24h",
    _: CurrentUser = Depends(require_permission("dashboard.read")),
) -> schemas.DashboardAggregate:
    probes = session.execute(select(Probe)).scalars().all()
    summary = {k: 0 for k in _NORMALIZED}
    probe_summaries: list[schemas.DashboardProbeSummary] = []
    for probe in probes:
        total = int(
            session.execute(
                select(func.count(MonitoredSystem.id)).where(MonitoredSystem.probe_id == probe.id)
            ).scalar_one()
        )
        rollup = _latest_rollup(session, probe.id)
        down = 0
        if rollup is not None:
            for sysrec in rollup.payload.get("systems", []):
                st = sysrec.get("status", "unknown")
                st = st if st in summary else "unknown"
                summary[st] += 1
                if st == "down":
                    down += 1
        probe_summaries.append(
            schemas.DashboardProbeSummary(
                probe_id=str(probe.id), status=probe.status, systems_total=total, systems_down=down
            )
        )
    active_alarms = int(
        session.execute(
            select(func.count(Alarm.id)).where(Alarm.status.in_(["active", "acknowledged"]))
        ).scalar_one()
    )
    return schemas.DashboardAggregate(
        probes=probe_summaries,
        systems_summary=schemas.SystemsSummary(**summary),
        active_alarms=active_alarms,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )


@router.get("/dashboard/probe/{probe_id}", response_model=schemas.DashboardProbeResponse)
def dashboard_probe(
    probe_id: str,
    session: SessionDep,
    window: str = "24h",
    _: CurrentUser = Depends(require_permission("dashboard.read")),
) -> schemas.DashboardProbeResponse:
    probe = _require_probe(session, probe_id)
    rollup = _latest_rollup(session, probe.id)
    systems = rollup.payload.get("systems", []) if rollup is not None else []
    systems = _enrich_systems(systems, _system_name_map(session, probe.id))
    return schemas.DashboardProbeResponse(
        probe=serializers.probe_out(session, probe),
        systems=systems,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )


# ==================== Scansioni NMAP (proxy verso Probe) ===================
# (aggiunta su richiesta utente: NMAP). Riusa il pattern di get_heartbeats:
# ProbeClient + _probe_base_url(probe) + settings.probe_query_token.


@router.post("/probes/{probe_id}/scan", response_model=schemas.ScanStartOut, tags=["scans"])
def start_scan(
    probe_id: str,
    body: schemas.ScanRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    client: ProbeClientDep,
    user: CurrentUser = Depends(require_permission("scans.run")),
) -> schemas.ScanStartOut:
    """Avvia una scansione NMAP sulla Probe (proxy) e traccia un audit."""
    probe = _require_probe(session, probe_id)
    payload = body.model_dump(exclude_none=True)
    data = client.post_scan(_probe_base_url(probe), settings.probe_query_token, payload)
    # Audit: non logga l'intero `extra`, solo un riassunto degli estremi.
    write_audit(
        session,
        actor_type="user",
        actor_id=str(user.id),
        action="scans.run",
        outcome="success",
        entity_type="probe",
        entity_id=probe_id,
        ip=client_ip(request),
        details={"target": body.target, "technique": body.technique, "timing": body.timing},
    )
    write_system_log(
        session,
        component="probe",
        level="info",
        logger="scans",
        message=f"Scansione avviata su '{probe.name}' target {body.target}.",
        probe_id=probe.id,
        context={"target": body.target, "technique": body.technique, "timing": body.timing},
    )
    session.commit()
    return schemas.ScanStartOut.model_validate(data)


@router.get("/probes/{probe_id}/scans", response_model=schemas.ScanList, tags=["scans"])
def list_scans(
    probe_id: str,
    session: SessionDep,
    settings: SettingsDep,
    client: ProbeClientDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: CurrentUser = Depends(require_permission("scans.read")),
) -> schemas.ScanList:
    """Elenca le scansioni note alla Probe (proxy)."""
    probe = _require_probe(session, probe_id)
    data = client.get_scans(
        _probe_base_url(probe),
        settings.probe_query_token,
        {"page": page, "page_size": page_size},
    )
    return schemas.ScanList(items=data.get("items", []), total=int(data.get("total", 0)))


@router.get(
    "/probes/{probe_id}/scan/{scan_id}", response_model=schemas.ScanDetail, tags=["scans"]
)
def get_scan(
    probe_id: str,
    scan_id: str,
    session: SessionDep,
    settings: SettingsDep,
    client: ProbeClientDep,
    _: CurrentUser = Depends(require_permission("scans.read")),
) -> schemas.ScanDetail:
    """Dettaglio di una scansione NMAP sulla Probe (proxy); 404 se inesistente."""
    probe = _require_probe(session, probe_id)
    data = client.get_scan(_probe_base_url(probe), settings.probe_query_token, scan_id)
    return schemas.ScanDetail.model_validate(data)
