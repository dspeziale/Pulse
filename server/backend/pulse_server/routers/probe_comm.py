"""Area Comunicazione Server<->Probe (DOCUMENTO_API §1.9).

Endpoint dedicati agli attori Probe. Autenticazione: mTLS (a livello di
trasporto) + Bearer probe_token (a livello applicativo). L'enrollment usa un
token monouso a scadenza.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Request
from sqlalchemy import select

from .. import errors, schemas
from ..audit import write_audit
from ..context import SecretBoxDep
from ..deps import AuthedProbeDep, SessionDep, SettingsDep, client_ip
from ..models import (
    Configuration,
    EnrollmentToken,
    MonitoredSystem,
    Probe,
    ProbeRollup,
)
from ..security import generate_opaque_token, hash_token, verify_token_hash
from ..workflow import process_event

router = APIRouter(prefix="/api/v1/probe", tags=["probe-comm"])


@router.post("/register", response_model=schemas.ProbeRegisterResponse)
def register(
    body: schemas.ProbeRegisterRequest,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> schemas.ProbeRegisterResponse:
    now = dt.datetime.now(dt.timezone.utc)
    token_hash = hash_token(body.enrollment_token)
    enrollment = session.execute(
        select(EnrollmentToken).where(EnrollmentToken.token_hash == token_hash)
    ).scalar_one_or_none()
    if enrollment is None or enrollment.used_at is not None or enrollment.expires_at <= now:
        raise errors.unauthorized("Token di enrollment non valido, scaduto o gia' usato.")
    probe = session.get(Probe, enrollment.probe_id)
    if probe is None:  # pragma: no cover - irraggiungibile: FK enrollment_tokens.probe_id ON DELETE CASCADE
        raise errors.not_found("Probe inesistente.")
    if not probe.enabled:
        raise errors.forbidden("Probe disabilitata.")

    probe_token = generate_opaque_token()
    probe.token_hash = hash_token(probe_token)
    probe.version = body.version
    probe.status = "online"
    probe.last_seen_at = now
    probe.config_version = now.strftime("%Y%m%d%H%M%S")
    enrollment.used_at = now

    ca_cert = ""
    if settings.tls_ca_cert_path:
        try:
            with open(settings.tls_ca_cert_path, encoding="utf-8") as fh:
                ca_cert = fh.read()
        except OSError:  # pragma: no cover - dipende dal filesystem/PKI reale
            ca_cert = ""

    write_audit(
        session,
        actor_type="probe",
        actor_id=str(probe.id),
        action="probe.register",
        outcome="success",
        entity_type="probe",
        entity_id=str(probe.id),
        ip=client_ip(request),
        details={"hostname": body.hostname, "version": body.version},
    )
    session.commit()
    return schemas.ProbeRegisterResponse(
        probe_id=str(probe.id),
        probe_token=probe_token,
        client_certificate=None,
        ca_certificate=ca_cert,
        server_probe_endpoint=settings.server_probe_endpoint,
    )


def _threshold(system: MonitoredSystem) -> schemas.Thresholds:
    return schemas.Thresholds(
        response_ms_warn=system.response_ms_warn,
        response_ms_error=system.response_ms_error,
    )


@router.get("/config", response_model=schemas.ProbeConfigResponse)
def get_config(
    probe: AuthedProbeDep,
    session: SessionDep,
    settings: SettingsDep,
) -> schemas.ProbeConfigResponse:
    db_probe = session.get(Probe, probe.id)
    assert db_probe is not None
    systems = (
        session.execute(
            select(MonitoredSystem).where(MonitoredSystem.probe_id == probe.id)
        )
        .scalars()
        .all()
    )
    config_version = db_probe.config_version or dt.datetime.now(dt.timezone.utc).strftime(
        "%Y%m%d%H%M%S"
    )
    return schemas.ProbeConfigResponse(
        probe_id=str(probe.id),
        poll_defaults={"offline_timeout_seconds": settings.probe_offline_timeout_seconds},
        systems=[
            schemas.ProbeConfigSystem(
                system_id=s.system_id,
                system_name=s.system_name,
                heartbeat_url=s.heartbeat_url,
                poll_interval_seconds=s.poll_interval_seconds,
                timeout_seconds=s.timeout_seconds,
                enabled=s.enabled,
                thresholds=_threshold(s),
            )
            for s in systems
        ],
        config_version=config_version,
    )


@router.post("/heartbeat", response_model=schemas.ProbeLivenessResponse)
def probe_liveness(
    body: schemas.ProbeLivenessRequest,
    probe: AuthedProbeDep,
    session: SessionDep,
) -> schemas.ProbeLivenessResponse:
    db_probe = session.get(Probe, probe.id)
    assert db_probe is not None
    now = dt.datetime.now(dt.timezone.utc)
    db_probe.last_seen_at = now
    db_probe.last_sync_at = now
    db_probe.version = body.version
    db_probe.status = "online"
    db_probe.last_error = None if body.opensearch_healthy else "OpenSearch non healthy"
    session.commit()
    return schemas.ProbeLivenessResponse(config_version=db_probe.config_version or "")


@router.post("/events", response_model=schemas.ProbeEventsResponse, status_code=202)
def probe_events(
    body: schemas.ProbeEventsRequest,
    probe: AuthedProbeDep,
    session: SessionDep,
    box: SecretBoxDep,
) -> schemas.ProbeEventsResponse:
    now = dt.datetime.now(dt.timezone.utc)
    for event in body.events:
        payload = event.model_dump()
        payload["probe_id"] = str(probe.id)
        process_event(session, payload, box=box, now=now)
    session.commit()
    return schemas.ProbeEventsResponse(accepted=len(body.events))


@router.post("/rollup", response_model=schemas.ProbeRollupResponse, status_code=202)
def probe_rollup(
    body: schemas.ProbeRollupRequest,
    probe: AuthedProbeDep,
    session: SessionDep,
) -> schemas.ProbeRollupResponse:
    session.add(
        ProbeRollup(
            probe_id=probe.id,
            window=body.window,
            payload=body.model_dump(),
        )
    )
    session.commit()
    return schemas.ProbeRollupResponse(accepted=True)


# riferimenti usati indirettamente (silenzia linters su import non evidenti)
_ = (Configuration, verify_token_hash)
