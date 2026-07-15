"""Motore di invio notifiche multi-canale: Email (SMTP), Telegram, WhatsApp.

Ogni provider implementa `send()` e ritorna (delivered, detail). Le dipendenze
di rete (smtplib/httpx) sono isolate per consentire il mocking nei test.
I segreti nella config sono decifrati just-in-time dal SecretBox.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Protocol

import httpx

from .security import SecretBox

# Chiavi di config considerate segrete (cifrate a riposo, mascherate in output).
SENSITIVE_KEYS: set[str] = {
    "password",
    "bot_token",
    "api_token",
    "webhook_secret",
}

MASK = "********"


class DeliveryResult:
    """Esito di un invio."""

    def __init__(self, delivered: bool, detail: str) -> None:
        self.delivered = delivered
        self.detail = detail


class Notifier(Protocol):
    def send(self, config: dict[str, Any], recipient: str, message: str) -> DeliveryResult: ...


class EmailNotifier:
    """Invio via SMTP."""

    def send(self, config: dict[str, Any], recipient: str, message: str) -> DeliveryResult:
        msg = EmailMessage()
        msg["From"] = config.get("from_address", config.get("username", "pulse@localhost"))
        msg["To"] = recipient
        msg["Subject"] = "Pulse notification"
        msg.set_content(message)
        host = str(config["smtp_host"])
        port = int(config["smtp_port"])
        use_tls = bool(config.get("use_tls", True))
        with smtplib.SMTP(host, port, timeout=15) as server:
            if use_tls:
                server.starttls()
            username = config.get("username")
            password = config.get("password")
            if username and password:
                server.login(str(username), str(password))
            server.send_message(msg)
        return DeliveryResult(True, f"Email inviata a {recipient} via {host}:{port}")


class TelegramNotifier:
    """Invio via Telegram Bot API."""

    def send(self, config: dict[str, Any], recipient: str, message: str) -> DeliveryResult:
        bot_token = str(config["bot_token"])
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = httpx.post(url, json={"chat_id": recipient, "text": message}, timeout=15.0)
        if resp.status_code == 200:
            return DeliveryResult(True, f"Telegram inviato a chat {recipient}")
        return DeliveryResult(False, f"Telegram errore HTTP {resp.status_code}: {resp.text}")


class WhatsAppNotifier:
    """Invio via WhatsApp Business API di un provider (WF-01/WF-06)."""

    def send(self, config: dict[str, Any], recipient: str, message: str) -> DeliveryResult:
        api_base = str(config["api_base"]).rstrip("/")
        api_token = str(config["api_token"])
        phone_number_id = str(config.get("phone_number_id", ""))
        url = f"{api_base}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": message},
        }
        headers = {"Authorization": f"Bearer {api_token}"}
        resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        if resp.status_code in (200, 201):
            return DeliveryResult(True, f"WhatsApp inviato a {recipient}")
        return DeliveryResult(False, f"WhatsApp errore HTTP {resp.status_code}: {resp.text}")


_PROVIDERS: dict[str, Notifier] = {
    "email": EmailNotifier(),
    "telegram": TelegramNotifier(),
    "whatsapp": WhatsAppNotifier(),
}


def get_notifier(channel_type: str) -> Notifier:
    if channel_type not in _PROVIDERS:  # pragma: no cover - guardia; type validato a monte
        raise ValueError(f"Tipo canale non supportato: {channel_type}")
    return _PROVIDERS[channel_type]


def set_notifier(channel_type: str, notifier: Notifier) -> None:
    """Sostituisce un provider (usato dai test)."""
    _PROVIDERS[channel_type] = notifier


# --- Cifratura / mascheramento della config canale --------------------------


def encrypt_config(box: SecretBox, config: dict[str, Any]) -> dict[str, Any]:
    """Cifra i valori segreti della config prima della persistenza."""
    out: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and value is not None:
            out[key] = box.encrypt(str(value))
        else:
            out[key] = value
    return out


def decrypt_config(box: SecretBox, config: dict[str, Any]) -> dict[str, Any]:
    """Decifra i valori segreti della config per l'uso in invio."""
    out: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and value is not None:
            out[key] = box.decrypt(str(value))
        else:
            out[key] = value
    return out


def mask_config(config: dict[str, Any]) -> dict[str, Any]:
    """Maschera i valori segreti per l'esposizione via API."""
    out: dict[str, Any] = {}
    for key, value in config.items():
        if key in SENSITIVE_KEYS and value is not None:
            out[key] = MASK
        else:
            out[key] = value
    return out


def render_template(template: str, context: dict[str, Any]) -> str:
    """Sostituisce i segnaposto {{campo}} (07_workflow_notifiche.md §6)."""
    result = template
    for key, value in context.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result
