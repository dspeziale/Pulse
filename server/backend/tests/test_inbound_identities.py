"""Test area Comandi in ingresso (webhook) e identita' di canale (§1.13)."""

from __future__ import annotations

import hashlib
import hmac
import json


def _telegram_channel(client, headers, secret="tg-secret"):
    return client.post(
        "/api/v1/notification-channels",
        headers=headers,
        json={
            "name": "tg-inbound", "type": "telegram", "enabled": True, "inbound_enabled": True,
            "config": {"bot_token": "123:abc", "webhook_secret": secret},
        },
    ).json()["id"]


def _associate(client, headers, channel_type, external_id):
    return client.post(
        "/api/v1/channel-identities",
        headers=headers,
        json={"channel_type": channel_type, "external_id": external_id, "verification_code": "123456"},
    )


def test_identity_crud(client, auth_headers) -> None:
    created = _associate(client, auth_headers, "telegram", "chat-100")
    assert created.status_code == 201, created.text
    iid = created.json()["id"]

    listed = client.get("/api/v1/channel-identities", headers=auth_headers)
    assert listed.status_code == 200 and any(i["id"] == iid for i in listed.json()["items"])

    dup = _associate(client, auth_headers, "telegram", "chat-100")
    assert dup.status_code == 409

    deleted = client.delete(f"/api/v1/channel-identities/{iid}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.delete(f"/api/v1/channel-identities/{iid}", headers=auth_headers).status_code == 404


def test_identity_missing_code(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/channel-identities",
        headers=auth_headers,
        json={"channel_type": "telegram", "external_id": "x", "verification_code": "  "},
    )
    assert r.status_code == 400


def test_telegram_webhook_help_command(client, auth_headers) -> None:
    _telegram_channel(client, auth_headers, secret="tg-secret")
    _associate(client, auth_headers, "telegram", "chat-777")
    r = client.post(
        "/api/v1/inbound/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
        json={"message": {"chat": {"id": 777}, "from": {"id": 777}, "text": "/help"}},
    )
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_telegram_webhook_bad_secret(client, auth_headers) -> None:
    _telegram_channel(client, auth_headers, secret="right")
    r = client.post(
        "/api/v1/inbound/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        json={"message": {"chat": {"id": 1}, "text": "/help"}},
    )
    assert r.status_code == 401


def test_telegram_no_channel_configured(client) -> None:
    r = client.post(
        "/api/v1/inbound/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "x"},
        json={"message": {"chat": {"id": 1}, "text": "/help"}},
    )
    assert r.status_code == 401


def test_telegram_empty_message(client, auth_headers) -> None:
    _telegram_channel(client, auth_headers, secret="tg-secret")
    r = client.post(
        "/api/v1/inbound/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret"},
        json={"message": {"chat": {"id": 1}}},
    )
    assert r.status_code == 400


def test_email_inbound(client, auth_headers) -> None:
    client.post(
        "/api/v1/notification-channels",
        headers=auth_headers,
        json={
            "name": "email-inbound", "type": "email", "enabled": True, "inbound_enabled": True,
            "config": {"smtp_host": "h", "smtp_port": 25, "use_tls": False, "username": "u", "password": "p", "from_address": "f@x", "webhook_secret": "mail-secret"},
        },
    )
    _associate(client, auth_headers, "email", "ops@company.com")
    ok = client.post(
        "/api/v1/inbound/email",
        json={"from": "ops@company.com", "subject": "/status", "body": "", "verification_token": "mail-secret"},
    )
    assert ok.status_code == 200
    bad = client.post(
        "/api/v1/inbound/email",
        json={"from": "ops@company.com", "subject": "/status", "body": "", "verification_token": "wrong"},
    )
    assert bad.status_code == 401


def test_whatsapp_handshake_and_webhook(client, auth_headers) -> None:
    client.post(
        "/api/v1/notification-channels",
        headers=auth_headers,
        json={
            "name": "wa-inbound", "type": "whatsapp", "enabled": True, "inbound_enabled": True,
            "config": {"provider": "meta", "api_base": "https://graph", "api_token": "t", "phone_number_id": "1", "webhook_secret": "wa-secret"},
        },
    )
    _associate(client, auth_headers, "whatsapp", "39333")

    handshake = client.get("/api/v1/inbound/whatsapp?hub.mode=subscribe&hub.verify_token=wa-secret&hub.challenge=42")
    assert handshake.status_code == 200 and handshake.text == "42"

    bad_handshake = client.get("/api/v1/inbound/whatsapp?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42")
    assert bad_handshake.status_code == 401

    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "39333", "text": {"body": "/help"}}]}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"wa-secret", raw, hashlib.sha256).hexdigest()
    ok = client.post("/api/v1/inbound/whatsapp", headers={"X-Hub-Signature-256": sig}, content=raw)
    assert ok.status_code == 200

    bad = client.post("/api/v1/inbound/whatsapp", headers={"X-Hub-Signature-256": "sha256=bad"}, content=raw)
    assert bad.status_code == 401
