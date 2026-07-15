"""Unit test dei provider di notifica e helper (mock rete)."""

from __future__ import annotations

import pytest

from pulse_server import notifications
from pulse_server.notifications import (
    EmailNotifier,
    TelegramNotifier,
    WhatsAppNotifier,
    decrypt_config,
    encrypt_config,
    get_notifier,
    mask_config,
    render_template,
    set_notifier,
)
from pulse_server.security import SecretBox


def test_render_template() -> None:
    out = render_template("{{status}} on {{system_name}}", {"status": "error", "system_name": "app"})
    assert out == "error on app"


def test_encrypt_decrypt_mask_config() -> None:
    box = SecretBox("k")
    cfg = {"smtp_host": "h", "password": "p", "bot_token": None}
    enc = encrypt_config(box, cfg)
    assert enc["password"] != "p"
    assert enc["smtp_host"] == "h"
    assert enc["bot_token"] is None
    dec = decrypt_config(box, enc)
    assert dec["password"] == "p"
    masked = mask_config(enc)
    assert masked["password"] == "********"
    assert masked["smtp_host"] == "h"


def test_email_notifier_success(monkeypatch) -> None:
    sent = {}

    class _SMTP:
        def __init__(self, host, port, timeout=15):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(notifications.smtplib, "SMTP", _SMTP)
    cfg = {"smtp_host": "h", "smtp_port": 587, "use_tls": True, "username": "u", "password": "p", "from_address": "f@x"}
    res = EmailNotifier().send(cfg, "to@x", "hi")
    assert res.delivered is True
    assert sent["tls"] is True and sent["login"] == ("u", "p")


def test_email_notifier_no_login(monkeypatch) -> None:
    class _SMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def send_message(self, msg):
            pass

    monkeypatch.setattr(notifications.smtplib, "SMTP", _SMTP)
    cfg = {"smtp_host": "h", "smtp_port": 25, "use_tls": False}
    assert EmailNotifier().send(cfg, "to@x", "hi").delivered is True


class _Resp:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def test_telegram_notifier(monkeypatch) -> None:
    monkeypatch.setattr(notifications.httpx, "post", lambda *a, **k: _Resp(200))
    assert TelegramNotifier().send({"bot_token": "t"}, "chat", "m").delivered is True
    monkeypatch.setattr(notifications.httpx, "post", lambda *a, **k: _Resp(400, "bad"))
    assert TelegramNotifier().send({"bot_token": "t"}, "chat", "m").delivered is False


def test_whatsapp_notifier(monkeypatch) -> None:
    monkeypatch.setattr(notifications.httpx, "post", lambda *a, **k: _Resp(200))
    cfg = {"api_base": "https://g/", "api_token": "t", "phone_number_id": "1"}
    assert WhatsAppNotifier().send(cfg, "39333", "m").delivered is True
    monkeypatch.setattr(notifications.httpx, "post", lambda *a, **k: _Resp(500, "err"))
    assert WhatsAppNotifier().send(cfg, "39333", "m").delivered is False


def test_get_and_set_notifier() -> None:
    original = get_notifier("email")
    try:
        marker = EmailNotifier()
        set_notifier("email", marker)
        assert get_notifier("email") is marker
    finally:
        set_notifier("email", original)
