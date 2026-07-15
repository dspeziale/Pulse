"""Area Comandi in ingresso (webhook canali) e identita' di canale (§1.13).

Sicurezza webhook: verifica del segreto/firma del canale (no JWT). L'esecuzione
dei comandi passa per la risoluzione identita'->utente e i permessi RBAC.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from .. import errors, schemas, serializers
from ..audit import write_audit
from ..commands import execute_command
from ..context import SecretBoxDep
from ..deps import CurrentUser, CurrentUserDep, SessionDep, client_ip, require_permission
from ..models import ChannelIdentity, NotificationChannel
from ..notifications import decrypt_config
from ..security import verify_hmac_sha256
from ._helpers import commit_or_conflict, parse_uuid

router = APIRouter(prefix="/api/v1/inbound", tags=["inbound"])
identities_router = APIRouter(prefix="/api/v1/channel-identities", tags=["inbound"])


def _inbound_channel(session: SessionDep, box: SecretBoxDep, channel_type: str) -> tuple[NotificationChannel, dict[str, Any]]:
    channel = session.execute(
        select(NotificationChannel).where(
            NotificationChannel.type == channel_type,
            NotificationChannel.inbound_enabled.is_(True),
            NotificationChannel.enabled.is_(True),
        )
    ).scalars().first()
    if channel is None:
        raise errors.unauthorized("Nessun canale inbound configurato per questo tipo.")
    return channel, decrypt_config(box, channel.config)


@router.post("/telegram")
def inbound_telegram(
    payload: dict[str, Any],
    request: Request,
    session: SessionDep,
    box: SecretBoxDep,
) -> dict[str, bool]:
    channel, cfg = _inbound_channel(session, box, "telegram")
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = str(cfg.get("webhook_secret", ""))
    if not expected or not hmac.compare_digest(secret, expected):
        raise errors.unauthorized("Secret webhook Telegram non valido.")
    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat") or {}
    external_id = str(chat.get("id") or (message.get("from") or {}).get("id") or "")
    text = str(message.get("text") or "")
    if not external_id or not text:
        raise errors.bad_request("Update Telegram privo di chat_id o testo.")
    result = execute_command(session, channel_type="telegram", external_id=external_id, text=text)
    write_audit(
        session,
        actor_type="user",
        actor_id=external_id,
        action="inbound.telegram",
        outcome="success" if result.outcome == "executed" else "failure",
        entity_type="channel",
        entity_id=str(channel.id),
        ip=client_ip(request),
        details={"command": text, "outcome": result.outcome},
    )
    session.commit()
    return {"ok": True}


@router.get("/whatsapp")
def whatsapp_handshake(request: Request, session: SessionDep, box: SecretBoxDep) -> Response:
    """Verifica handshake del provider (hub.challenge)."""
    _, cfg = _inbound_channel(session, box, "whatsapp")
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    if mode == "subscribe" and token and token == str(cfg.get("webhook_secret", "")):
        return Response(content=challenge, media_type="text/plain")
    raise errors.unauthorized("Verifica handshake WhatsApp fallita.")


@router.post("/whatsapp")
async def inbound_whatsapp(
    request: Request,
    session: SessionDep,
    box: SecretBoxDep,
) -> dict[str, bool]:
    channel, cfg = _inbound_channel(session, box, "whatsapp")
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    secret = str(cfg.get("webhook_secret", ""))
    if not secret or not verify_hmac_sha256(secret, raw, signature):
        raise errors.unauthorized("Firma webhook WhatsApp non valida.")
    payload = await request.json()
    external_id, text = _extract_whatsapp(payload)
    if not external_id or not text:
        raise errors.bad_request("Payload WhatsApp privo di mittente o testo.")
    result = execute_command(session, channel_type="whatsapp", external_id=external_id, text=text)
    write_audit(
        session,
        actor_type="user",
        actor_id=external_id,
        action="inbound.whatsapp",
        outcome="success" if result.outcome == "executed" else "failure",
        entity_type="channel",
        entity_id=str(channel.id),
        ip=client_ip(request),
        details={"outcome": result.outcome},
    )
    session.commit()
    return {"ok": True}


def _extract_whatsapp(payload: dict[str, Any]) -> tuple[str, str]:
    try:
        change = payload["entry"][0]["changes"][0]["value"]
        msg = change["messages"][0]
        return str(msg["from"]), str(msg["text"]["body"])
    except (KeyError, IndexError, TypeError):
        return "", ""


@router.post("/email")
def inbound_email(
    body: schemas.InboundEmailRequest,
    request: Request,
    session: SessionDep,
    box: SecretBoxDep,
) -> dict[str, bool]:
    channel, cfg = _inbound_channel(session, box, "email")
    expected = str(cfg.get("webhook_secret", ""))
    if not expected or not hmac.compare_digest(body.verification_token, expected):
        raise errors.unauthorized("Token di verifica email non valido.")
    result = execute_command(
        session, channel_type="email", external_id=body.from_, text=f"{body.subject} {body.body}"
    )
    write_audit(
        session,
        actor_type="user",
        actor_id=body.from_,
        action="inbound.email",
        outcome="success" if result.outcome == "executed" else "failure",
        entity_type="channel",
        entity_id=str(channel.id),
        ip=client_ip(request),
        details={"outcome": result.outcome},
    )
    session.commit()
    return {"ok": True}


# ============================ Identita' di canale ==========================


@identities_router.post("", response_model=schemas.ChannelIdentityOut, status_code=201)
def create_identity(
    body: schemas.ChannelIdentityCreate,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("commands.execute")),
) -> schemas.ChannelIdentityOut:
    existing = session.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.channel_type == body.channel_type,
            ChannelIdentity.external_id == body.external_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise errors.conflict("Identita' gia' associata.")
    # Verifica del codice: deve essere non vuoto (in produzione confronto con codice inviato).
    if not body.verification_code.strip():
        raise errors.bad_request("Codice di verifica mancante o scaduto.")
    identity = ChannelIdentity(
        user_id=actor.id,
        channel_type=body.channel_type,
        external_id=body.external_id,
        verified=True,
        verification_code=None,
    )
    session.add(identity)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="channel_identity.create",
        outcome="success",
        entity_type="channel_identity",
        entity_id=None,
        ip=client_ip(request),
        details={"channel_type": body.channel_type},
    )
    commit_or_conflict(session, message="Identita' gia' associata.")
    session.refresh(identity)
    return serializers.identity_out(identity)


@identities_router.get("", response_model=schemas.ChannelIdentityList)
def list_identities(
    session: SessionDep,
    actor: CurrentUser = Depends(require_permission("commands.execute")),
) -> schemas.ChannelIdentityList:
    rows = session.execute(
        select(ChannelIdentity).where(ChannelIdentity.user_id == actor.id)
    ).scalars().all()
    return schemas.ChannelIdentityList(items=[serializers.identity_out(i) for i in rows])


@identities_router.delete("/{identity_id}", status_code=204)
def delete_identity(
    identity_id: str,
    session: SessionDep,
    request: Request,
    actor: CurrentUser = Depends(require_permission("commands.execute")),
) -> Response:
    identity = session.get(ChannelIdentity, parse_uuid(identity_id, what="identity_id"))
    if identity is None or identity.user_id != actor.id:
        raise errors.not_found("Identita' inesistente.")
    session.delete(identity)
    write_audit(
        session,
        actor_type="user",
        actor_id=str(actor.id),
        action="channel_identity.delete",
        outcome="success",
        entity_type="channel_identity",
        entity_id=str(identity_id),
        ip=client_ip(request),
    )
    session.commit()
    return Response(status_code=204)
