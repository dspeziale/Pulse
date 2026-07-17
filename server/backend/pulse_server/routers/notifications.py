"""Area Notifiche / Canali (DOCUMENTO_API §1.10)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..context import SecretBoxDep
from ..deps import CurrentUser, SessionDep, client_ip, require_permission
from ..models import NotificationChannel, NotificationDelivery, WorkflowAction
from ..notifications import decrypt_config, encrypt_config, get_notifier
from ._helpers import clamp_pagination, commit_or_conflict, offset, parse_uuid, sort_clause

router = APIRouter(prefix="/api/v1/notification-channels", tags=["notifications"])
history_router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=schemas.ChannelList)
def list_channels(
    session: SessionDep,
    type: str | None = None,
    enabled: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    sort: str | None = None,
    _: CurrentUser = Depends(require_permission("notifications.read")),
) -> schemas.ChannelList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(NotificationChannel)
    count_stmt = select(func.count(NotificationChannel.id))
    if type is not None:
        stmt = stmt.where(NotificationChannel.type == type)
        count_stmt = count_stmt.where(NotificationChannel.type == type)
    if enabled is not None:
        stmt = stmt.where(NotificationChannel.enabled.is_(enabled))
        count_stmt = count_stmt.where(NotificationChannel.enabled.is_(enabled))
    total = int(session.execute(count_stmt).scalar_one())
    order = sort_clause(
        sort,
        {
            "name": NotificationChannel.name,
            "type": NotificationChannel.type,
            "created_at": NotificationChannel.created_at,
            "enabled": NotificationChannel.enabled,
        },
        NotificationChannel.created_at.asc(),
    )
    rows = (
        session.execute(
            stmt.order_by(order).offset(offset(page, page_size)).limit(page_size)
        )
        .scalars()
        .all()
    )
    return schemas.ChannelList(items=[serializers.channel_out(c) for c in rows], total=total)


@router.post("", response_model=schemas.ChannelOut, status_code=201)
def create_channel(
    body: schemas.ChannelCreate,
    session: SessionDep,
    box: SecretBoxDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("notifications.create")),
) -> schemas.ChannelOut:
    channel = NotificationChannel(
        name=body.name,
        type=body.type,
        enabled=body.enabled,
        inbound_enabled=body.inbound_enabled,
        config=encrypt_config(box, body.config),
    )
    session.add(channel)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="notifications.create",
        outcome="success",
        entity_type="notification_channel",
        entity_id=None,
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Nome canale gia' esistente.")
    session.refresh(channel)
    return serializers.channel_out(channel)


@router.get("/{channel_id}", response_model=schemas.ChannelOut)
def get_channel(
    channel_id: str,
    session: SessionDep,
    _: CurrentUser = Depends(require_permission("notifications.read")),
) -> schemas.ChannelOut:
    channel = session.get(NotificationChannel, parse_uuid(channel_id, what="channel_id"))
    if channel is None:
        raise errors.not_found("Canale inesistente.")
    return serializers.channel_out(channel)


@router.put("/{channel_id}", response_model=schemas.ChannelOut)
def update_channel(
    channel_id: str,
    body: schemas.ChannelUpdate,
    session: SessionDep,
    box: SecretBoxDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("notifications.update")),
) -> schemas.ChannelOut:
    channel = session.get(NotificationChannel, parse_uuid(channel_id, what="channel_id"))
    if channel is None:
        raise errors.not_found("Canale inesistente.")
    if body.name is not None:
        channel.name = body.name
    if body.enabled is not None:
        channel.enabled = body.enabled
    if body.inbound_enabled is not None:
        channel.inbound_enabled = body.inbound_enabled
    if body.config is not None:
        # Fonde la config esistente (decifrata) con i nuovi valori, poi cifra.
        merged = decrypt_config(box, channel.config)
        merged.update(body.config)
        channel.config = encrypt_config(box, merged)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="notifications.update",
        outcome="success",
        entity_type="notification_channel",
        entity_id=str(channel.id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Nome canale gia' esistente.")
    session.refresh(channel)
    return serializers.channel_out(channel)


@router.delete("/{channel_id}", status_code=204)
def delete_channel(
    channel_id: str,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("notifications.delete")),
) -> Response:
    channel = session.get(NotificationChannel, parse_uuid(channel_id, what="channel_id"))
    if channel is None:
        raise errors.not_found("Canale inesistente.")
    used = session.execute(
        select(func.count(WorkflowAction.id)).where(WorkflowAction.channel_id == channel.id)
    ).scalar_one()
    if int(used) > 0:
        raise errors.conflict("Canale usato da uno o piu' workflow.")
    session.delete(channel)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="notifications.delete",
        outcome="success",
        entity_type="notification_channel",
        entity_id=str(channel_id),
        ip=client_ip(request),
    )
    commit_or_conflict(session, message="Canale usato da uno o piu' workflow.")
    return Response(status_code=204)


@router.post("/{channel_id}/test", response_model=schemas.ChannelTestResponse)
def test_channel(
    channel_id: str,
    body: schemas.ChannelTestRequest,
    session: SessionDep,
    box: SecretBoxDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("notifications.test")),
) -> schemas.ChannelTestResponse:
    channel = session.get(NotificationChannel, parse_uuid(channel_id, what="channel_id"))
    if channel is None:
        raise errors.not_found("Canale inesistente.")
    message = body.message or "Pulse: messaggio di prova."
    plain_cfg = decrypt_config(box, channel.config)
    notifier = get_notifier(channel.type)
    delivered = False
    detail = ""
    try:
        result = notifier.send(plain_cfg, body.recipient, message)
        delivered, detail = result.delivered, result.detail
    except Exception as exc:  # noqa: BLE001 - errori provider mappati a esito test
        delivered, detail = False, f"Errore invio: {exc}"
    session.add(
        NotificationDelivery(
            channel_id=channel.id,
            recipient=body.recipient,
            status="sent" if delivered else "failed",
            error=None if delivered else detail,
        )
    )
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="notifications.test",
        outcome="success" if delivered else "failure",
        entity_type="notification_channel",
        entity_id=str(channel.id),
        ip=client_ip(request),
        details={"recipient": body.recipient},
    )
    session.commit()
    if not delivered:
        # Esito test riportato con 200 (delivered=false) per coerenza col contratto,
        # ma un errore di provider e' comunque un 503 utile alla UI se preferito.
        return schemas.ChannelTestResponse(delivered=False, detail=detail)
    return schemas.ChannelTestResponse(delivered=True, detail=detail)


@history_router.get("/history", response_model=schemas.DeliveryList)
def notifications_history(
    session: SessionDep,
    channel_id: str | None = None,
    workflow_id: str | None = None,
    status: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    sort: str | None = None,
    _: CurrentUser = Depends(require_permission("notifications.read")),
) -> schemas.DeliveryList:
    page, page_size = clamp_pagination(page, page_size)
    stmt = select(NotificationDelivery)
    count_stmt = select(func.count(NotificationDelivery.id))
    if channel_id is not None:
        cid = parse_uuid(channel_id, what="channel_id")
        stmt = stmt.where(NotificationDelivery.channel_id == cid)
        count_stmt = count_stmt.where(NotificationDelivery.channel_id == cid)
    if workflow_id is not None:
        wid = parse_uuid(workflow_id, what="workflow_id")
        stmt = stmt.where(NotificationDelivery.workflow_id == wid)
        count_stmt = count_stmt.where(NotificationDelivery.workflow_id == wid)
    if status is not None:
        stmt = stmt.where(NotificationDelivery.status == status)
        count_stmt = count_stmt.where(NotificationDelivery.status == status)
    if from_ is not None:
        start = _parse_iso(from_)
        stmt = stmt.where(NotificationDelivery.created_at >= start)
        count_stmt = count_stmt.where(NotificationDelivery.created_at >= start)
    if to is not None:
        end = _parse_iso(to)
        stmt = stmt.where(NotificationDelivery.created_at <= end)
        count_stmt = count_stmt.where(NotificationDelivery.created_at <= end)
    total = int(session.execute(count_stmt).scalar_one())
    order = sort_clause(
        sort,
        {
            "created_at": NotificationDelivery.created_at,
            "status": NotificationDelivery.status,
            "channel_id": NotificationDelivery.channel_id,
        },
        NotificationDelivery.created_at.desc(),
    )
    rows = (
        session.execute(
            stmt.order_by(order)
            .offset(offset(page, page_size))
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return schemas.DeliveryList(items=[serializers.delivery_out(d) for d in rows], total=total)


def _parse_iso(value: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise errors.bad_request(f"Timestamp ISO-8601 non valido: {value}")
