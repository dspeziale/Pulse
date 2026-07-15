"""Test aree Workflow notifiche (§1.11) e Allarmi (§1.12)."""

from __future__ import annotations

import datetime as dt


def _channel(client, headers, name="wf-ch"):
    return client.post(
        "/api/v1/notification-channels",
        headers=headers,
        json={
            "name": name, "type": "telegram", "enabled": True, "inbound_enabled": False,
            "config": {"bot_token": "123:abc", "webhook_secret": "s"},
        },
    ).json()["id"]


def _workflow_body(cid, **over):
    body = {
        "name": over.get("name", "wf-1"),
        "description": "WF",
        "enabled": True,
        "trigger": over.get("trigger", "status_changed"),
        "scope": {"probe_ids": [], "system_ids": [], "check_ids": []},
        "conditions": [{"field": "status", "op": "eq", "value": "error", "group": "g1"}],
        "suppression": {"cooldown_seconds": 0, "dedup_window_seconds": 0, "respect_maintenance": True},
        "actions": [
            {"step_order": 0, "channel_id": cid, "recipients": ["chat1"], "template": "{{status}}", "delay_seconds": 0}
        ],
    }
    body.update({k: v for k, v in over.items() if k in body})
    return body


def test_workflow_crud_flow(client, auth_headers) -> None:
    cid = _channel(client, auth_headers)
    created = client.post("/api/v1/notification-workflows", headers=auth_headers, json=_workflow_body(cid))
    assert created.status_code == 201, created.text
    wid = created.json()["id"]
    assert created.json()["conditions"][0]["field"] == "status"
    assert created.json()["actions"][0]["recipients"] == ["chat1"]

    got = client.get(f"/api/v1/notification-workflows/{wid}", headers=auth_headers)
    assert got.status_code == 200

    upd = client.put(
        f"/api/v1/notification-workflows/{wid}",
        headers=auth_headers,
        json={"description": "changed", "conditions": [], "actions": [{"step_order": 0, "channel_id": cid, "recipients": ["c2"], "template": "t", "delay_seconds": 5}]},
    )
    assert upd.status_code == 200 and upd.json()["description"] == "changed"

    en = client.put(f"/api/v1/notification-workflows/{wid}/enabled", headers=auth_headers, json={"enabled": False})
    assert en.status_code == 200 and en.json()["enabled"] is False

    listed = client.get("/api/v1/notification-workflows?enabled=false&q=wf-1", headers=auth_headers)
    assert listed.json()["total"] >= 1

    deleted = client.delete(f"/api/v1/notification-workflows/{wid}", headers=auth_headers)
    assert deleted.status_code == 204


def test_workflow_duplicate_name_conflict(client, auth_headers) -> None:
    cid = _channel(client, auth_headers, name="dupwf-ch")
    client.post("/api/v1/notification-workflows", headers=auth_headers, json=_workflow_body(cid, name="dupwf"))
    r = client.post("/api/v1/notification-workflows", headers=auth_headers, json=_workflow_body(cid, name="dupwf"))
    assert r.status_code == 409


def test_workflow_invalid_trigger_422(client, auth_headers) -> None:
    cid = _channel(client, auth_headers, name="badtrig-ch")
    r = client.post("/api/v1/notification-workflows", headers=auth_headers, json=_workflow_body(cid, name="badtrig", trigger="nope"))
    assert r.status_code == 422


def test_workflow_unknown_channel_422(client, auth_headers) -> None:
    body = _workflow_body("00000000-0000-0000-0000-0000000000fa", name="badch")
    r = client.post("/api/v1/notification-workflows", headers=auth_headers, json=body)
    assert r.status_code == 422


def test_workflow_simulate_match_and_nomatch(client, auth_headers) -> None:
    cid = _channel(client, auth_headers, name="sim-ch")
    wid = client.post("/api/v1/notification-workflows", headers=auth_headers, json=_workflow_body(cid, name="sim")).json()["id"]
    matched = client.post(
        f"/api/v1/notification-workflows/{wid}/simulate",
        headers=auth_headers,
        json={"event": {"type": "status_changed", "status": "error"}},
    )
    assert matched.status_code == 200 and matched.json()["matched"] is True
    assert len(matched.json()["planned_actions"]) == 1

    nomatch = client.post(
        f"/api/v1/notification-workflows/{wid}/simulate",
        headers=auth_headers,
        json={"event": {"type": "status_changed", "status": "ok"}},
    )
    assert nomatch.json()["matched"] is False


def test_workflow_not_found(client, auth_headers) -> None:
    ghost = "00000000-0000-0000-0000-0000000000fb"
    assert client.get(f"/api/v1/notification-workflows/{ghost}", headers=auth_headers).status_code == 404
    assert client.put(f"/api/v1/notification-workflows/{ghost}", headers=auth_headers, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/notification-workflows/{ghost}", headers=auth_headers).status_code == 404
    assert client.put(f"/api/v1/notification-workflows/{ghost}/enabled", headers=auth_headers, json={"enabled": True}).status_code == 404
    assert client.post(f"/api/v1/notification-workflows/{ghost}/simulate", headers=auth_headers, json={"event": {}}).status_code == 404


def test_alarms_list_and_ack(client, auth_headers, db_session) -> None:
    from pulse_server.models import Alarm

    alarm = Alarm(status="active", dedup_key="k1", opened_at=dt.datetime.now(dt.timezone.utc))
    db_session.add(alarm)
    db_session.flush()
    aid = str(alarm.id)

    listed = client.get("/api/v1/alarms?status=active", headers=auth_headers)
    assert listed.status_code == 200 and listed.json()["total"] >= 1

    acked = client.post(f"/api/v1/alarms/{aid}/ack", headers=auth_headers, json={"note": "handled"})
    assert acked.status_code == 200 and acked.json()["status"] == "acknowledged"

    # ack di allarme risolto -> 409
    alarm.status = "resolved"
    db_session.flush()
    again = client.post(f"/api/v1/alarms/{aid}/ack", headers=auth_headers, json={})
    assert again.status_code == 409


def test_ack_not_found(client, auth_headers) -> None:
    r = client.post("/api/v1/alarms/00000000-0000-0000-0000-0000000000fc/ack", headers=auth_headers, json={})
    assert r.status_code == 404


def test_alarms_filters(client, auth_headers) -> None:
    r = client.get(
        "/api/v1/alarms?from=2020-01-01T00:00:00Z&to=2100-01-01T00:00:00Z", headers=auth_headers
    )
    assert r.status_code == 200
