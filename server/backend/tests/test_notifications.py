"""Test area Notifiche / Canali (§1.10)."""

from __future__ import annotations

import pytest

from pulse_server.notifications import DeliveryResult, get_notifier, set_notifier


class _FakeNotifier:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[dict, str, str]] = []

    def send(self, config, recipient, message):  # type: ignore[no-untyped-def]
        self.calls.append((config, recipient, message))
        return DeliveryResult(self.ok, "ok" if self.ok else "fail")


@pytest.fixture(autouse=True)
def restore_notifiers():
    originals = {t: get_notifier(t) for t in ("email", "telegram", "whatsapp")}
    yield
    for t, n in originals.items():
        set_notifier(t, n)


def _email_channel(client, headers, name="email-1", inbound=False):
    return client.post(
        "/api/v1/notification-channels",
        headers=headers,
        json={
            "name": name, "type": "email", "enabled": True, "inbound_enabled": inbound,
            "config": {
                "smtp_host": "smtp.local", "smtp_port": 587, "use_tls": True,
                "username": "u", "password": "secret-pass", "from_address": "pulse@local",
            },
        },
    )


def test_channel_crud_masks_secrets(client, auth_headers) -> None:
    created = _email_channel(client, auth_headers)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert created.json()["config"]["password"] == "********"
    assert created.json()["config"]["smtp_host"] == "smtp.local"

    got = client.get(f"/api/v1/notification-channels/{cid}", headers=auth_headers)
    assert got.json()["config"]["password"] == "********"

    upd = client.put(
        f"/api/v1/notification-channels/{cid}",
        headers=auth_headers,
        json={"enabled": False, "config": {"smtp_port": 2525}},
    )
    assert upd.status_code == 200 and upd.json()["enabled"] is False
    assert upd.json()["config"]["smtp_port"] == 2525

    listed = client.get("/api/v1/notification-channels?type=email&enabled=false", headers=auth_headers)
    assert listed.json()["total"] >= 1

    deleted = client.delete(f"/api/v1/notification-channels/{cid}", headers=auth_headers)
    assert deleted.status_code == 204


def test_channel_duplicate_name_conflict(client, auth_headers) -> None:
    _email_channel(client, auth_headers, name="dupch")
    r = _email_channel(client, auth_headers, name="dupch")
    assert r.status_code == 409


def test_channel_test_send_success(client, auth_headers) -> None:
    fake = _FakeNotifier(ok=True)
    set_notifier("email", fake)
    cid = _email_channel(client, auth_headers, name="testable").json()["id"]
    r = client.post(
        f"/api/v1/notification-channels/{cid}/test",
        headers=auth_headers,
        json={"recipient": "ops@local", "message": "ciao"},
    )
    assert r.status_code == 200 and r.json()["delivered"] is True
    # la config decifrata deve arrivare al notifier col segreto in chiaro
    assert fake.calls[0][0]["password"] == "secret-pass"


def test_channel_test_send_failure(client, auth_headers) -> None:
    set_notifier("email", _FakeNotifier(ok=False))
    cid = _email_channel(client, auth_headers, name="failable").json()["id"]
    r = client.post(
        f"/api/v1/notification-channels/{cid}/test",
        headers=auth_headers,
        json={"recipient": "ops@local"},
    )
    assert r.status_code == 200 and r.json()["delivered"] is False


def test_channel_test_exception(client, auth_headers) -> None:
    class _Boom:
        def send(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("provider down")

    set_notifier("email", _Boom())
    cid = _email_channel(client, auth_headers, name="boom").json()["id"]
    r = client.post(
        f"/api/v1/notification-channels/{cid}/test",
        headers=auth_headers,
        json={"recipient": "x@local"},
    )
    assert r.status_code == 200 and r.json()["delivered"] is False


def test_channel_delete_in_use_conflict(client, auth_headers) -> None:
    cid = _email_channel(client, auth_headers, name="usedch").json()["id"]
    client.post(
        "/api/v1/notification-workflows",
        headers=auth_headers,
        json={
            "name": "wf-uses-ch", "description": "", "enabled": True, "trigger": "status_changed",
            "scope": {"probe_ids": [], "system_ids": [], "check_ids": []},
            "conditions": [], "suppression": {"cooldown_seconds": 0, "dedup_window_seconds": 0, "respect_maintenance": True},
            "actions": [{"step_order": 0, "channel_id": cid, "recipients": ["a@b"], "template": "t", "delay_seconds": 0}],
        },
    )
    r = client.delete(f"/api/v1/notification-channels/{cid}", headers=auth_headers)
    assert r.status_code == 409


def test_channel_not_found(client, auth_headers) -> None:
    ghost = "00000000-0000-0000-0000-0000000000ac"
    assert client.get(f"/api/v1/notification-channels/{ghost}", headers=auth_headers).status_code == 404
    assert client.put(f"/api/v1/notification-channels/{ghost}", headers=auth_headers, json={"enabled": True}).status_code == 404
    assert client.delete(f"/api/v1/notification-channels/{ghost}", headers=auth_headers).status_code == 404
    assert client.post(f"/api/v1/notification-channels/{ghost}/test", headers=auth_headers, json={"recipient": "x"}).status_code == 404


def test_history_filters(client, auth_headers) -> None:
    set_notifier("email", _FakeNotifier(ok=True))
    cid = _email_channel(client, auth_headers, name="histch").json()["id"]
    client.post(
        f"/api/v1/notification-channels/{cid}/test", headers=auth_headers, json={"recipient": "h@local"}
    )
    r = client.get(
        f"/api/v1/notifications/history?channel_id={cid}&status=sent&from=2020-01-01T00:00:00Z&to=2100-01-01T00:00:00Z",
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json()["total"] >= 1


def test_history_bad_timestamp(client, auth_headers) -> None:
    r = client.get("/api/v1/notifications/history?from=not-a-date", headers=auth_headers)
    assert r.status_code == 400
