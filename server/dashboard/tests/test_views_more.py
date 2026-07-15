"""Test viste: query/charts, notifiche, workflow, allarmi, identità, audit,
log, config, profilo, e enforcement RBAC nel menu."""


# -- P-04/P-05 Query & Charts -------------------------------------------------
def test_query_builder_get(client, login, fake):
    login(["heartbeats.query"])
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/systems/s1/checks", {"items": []})
    r = client.get("/query?probe_id=p1&system_id=s1")
    assert r.status_code == 200


def test_query_builder_get_no_selection(client, login, fake):
    login(["heartbeats.query"])
    fake.set("GET", "/probes", {"items": []})
    assert client.get("/query").status_code == 200


def test_query_run_success(client, login, fake):
    login(["heartbeats.query"])
    fake.set("POST", "/probes/p1/query", {"items": [], "aggregations": {}, "total": 0})
    fake.set("GET", "/probes", {"items": []})
    r = client.post("/query", data={"probe_id": "p1", "from": "", "to": "",
                                    "filters": "[]", "aggregations": "[]"})
    assert r.status_code == 200


def test_query_run_empty_json_defaults(client, login, fake):
    login(["heartbeats.query"])
    fake.set("POST", "/probes/p1/query", {"items": [], "aggregations": {}, "total": 0})
    fake.set("GET", "/probes", {"items": []})
    r = client.post("/query", data={"probe_id": "p1", "filters": "",
                                    "aggregations": ""})
    assert r.status_code == 200


def test_query_run_no_probe(client, login, fake):
    login(["heartbeats.query"])
    r = client.post("/query", data={"probe_id": ""})
    assert r.status_code == 302


def test_query_run_invalid_json(client, login, fake):
    login(["heartbeats.query"])
    r = client.post("/query", data={"probe_id": "p1", "filters": "{bad"})
    assert r.status_code == 302


def test_charts_get_empty(client, login, fake):
    login(["heartbeats.read"])
    fake.set("GET", "/probes", {"items": []})
    assert client.get("/charts").status_code == 200


def test_charts_get_with_data(client, login, fake):
    login(["heartbeats.read"])
    fake.set("GET", "/probes", {"items": []})
    fake.set("POST", "/probes/p1/query", {"items": [], "aggregations": {"uptime": 99}})
    fake.set("GET", "/probes/p1/heartbeats", {"items": []})
    r = client.get("/charts?probe_id=p1&system_id=s1&from=a&to=b")
    assert r.status_code == 200


# -- P-11/P-13 Notifiche ------------------------------------------------------
def test_channels_list_and_types(client, login, fake):
    login(["notifications.read", "notifications.create"])
    fake.set("GET", "/notification-channels", {"items": [], "total": 0})
    assert client.get("/notification-channels").status_code == 200
    assert client.get("/notification-channels/new").status_code == 200
    fake.set("POST", "/notification-channels", {"id": "1"})
    for ch in ("email", "telegram", "whatsapp"):
        data = {"name": "c", "type": ch, "enabled": "on", "inbound_enabled": "on",
                "smtp_port": "587", "imap_port": "993"}
        assert client.post("/notification-channels/new", data=data).status_code == 302


def test_channel_detail_edit_delete_test(client, login, fake):
    login(["notifications.read", "notifications.update", "notifications.delete",
           "notifications.test"])
    fake.set("GET", "/notification-channels/1", {"id": "1", "type": "email",
                                                 "config": {}})
    assert client.get("/notification-channels/1").status_code == 200
    assert client.get("/notification-channels/1/edit").status_code == 200
    fake.set("PUT", "/notification-channels/1", {"id": "1"})
    assert client.post("/notification-channels/1/edit",
                       data={"type": "email", "smtp_port": "1", "imap_port": "2"}).status_code == 302
    fake.set("DELETE", "/notification-channels/1", None)
    assert client.post("/notification-channels/1/delete").status_code == 302
    fake.set("POST", "/notification-channels/1/test", {"delivered": True, "detail": "ok"})
    assert client.post("/notification-channels/1/test",
                       data={"recipient": "x", "message": "m"}).status_code == 302
    fake.set("POST", "/notification-channels/1/test", {"delivered": False, "detail": "ko"})
    assert client.post("/notification-channels/1/test", data={"recipient": "x"}).status_code == 302


def test_notifications_history(client, login, fake):
    login(["notifications.read"])
    fake.set("GET", "/notifications/history", {"items": [], "total": 0})
    assert client.get("/notifications/history?status=sent").status_code == 200


# -- P-12 Workflow ------------------------------------------------------------
def test_workflows_cycle(client, login, fake):
    login(["workflows.read", "workflows.create", "workflows.update",
           "workflows.delete"])
    fake.set("GET", "/notification-workflows", {"items": [], "total": 0})
    assert client.get("/notification-workflows").status_code == 200
    fake.set("GET", "/notification-channels", {"items": []})
    assert client.get("/notification-workflows/new").status_code == 200
    fake.set("POST", "/notification-workflows", {"id": "1"})
    good = {"name": "w", "description": "", "enabled": "on", "trigger": "status_changed",
            "scope": "{}", "conditions": "[]", "suppression": "{}", "actions": "[]"}
    assert client.post("/notification-workflows/new", data=good).status_code == 302
    fake.set("GET", "/notification-workflows/1", {"id": "1", "scope": {},
                                                  "conditions": [], "actions": [],
                                                  "suppression": {}})
    assert client.get("/notification-workflows/1").status_code == 200
    assert client.get("/notification-workflows/1/edit").status_code == 200
    fake.set("PUT", "/notification-workflows/1", {"id": "1"})
    assert client.post("/notification-workflows/1/edit", data=good).status_code == 302
    fake.set("PUT", "/notification-workflows/1/enabled", {"id": "1"})
    assert client.post("/notification-workflows/1/enabled", data={"enabled": "on"}).status_code == 302
    fake.set("POST", "/notification-workflows/1/simulate",
             {"matched": True, "planned_actions": [], "suppressed_by": None})
    assert client.post("/notification-workflows/1/simulate",
                       data={"event": "{}"}).status_code == 200
    fake.set("DELETE", "/notification-workflows/1", None)
    assert client.post("/notification-workflows/1/delete").status_code == 302


def test_workflow_create_empty_json_defaults(client, login, fake):
    login(["workflows.create"])
    fake.set("POST", "/notification-workflows", {"id": "1"})
    # Campi JSON assenti -> ramo default di _json_field.
    r = client.post("/notification-workflows/new",
                    data={"name": "w", "trigger": "status_changed"})
    assert r.status_code == 302


def test_workflows_invalid_json_branches(client, login, fake):
    login(["workflows.create", "workflows.update"])
    bad = {"name": "w", "scope": "{bad"}
    assert client.post("/notification-workflows/new", data=bad).status_code == 302
    assert client.post("/notification-workflows/1/edit", data=bad).status_code == 302
    assert client.post("/notification-workflows/1/simulate",
                       data={"event": "{bad"}).status_code == 302


# -- P-14 Allarmi -------------------------------------------------------------
def test_alarms(client, login, fake):
    login(["workflows.read", "commands.execute"])
    fake.set("GET", "/alarms", {"items": [], "total": 0})
    assert client.get("/alarms?status=active").status_code == 200
    fake.set("POST", "/alarms/1/ack", {"id": "1", "status": "acknowledged"})
    assert client.post("/alarms/1/ack", data={"note": "ok"}).status_code == 302


# -- P-15 Identità ------------------------------------------------------------
def test_identities(client, login, fake):
    login(["commands.execute"])
    fake.set("GET", "/channel-identities", {"items": []})
    assert client.get("/channel-identities").status_code == 200
    fake.set("POST", "/channel-identities", {"id": "1"})
    assert client.post("/channel-identities", data={"channel_type": "telegram",
                                                    "external_id": "x",
                                                    "verification_code": "123"}).status_code == 302
    fake.set("DELETE", "/channel-identities/1", None)
    assert client.post("/channel-identities/1/delete").status_code == 302


# -- P-16/P-17 Audit & Log ----------------------------------------------------
def test_audit(client, login, fake):
    login(["audit.read"])
    fake.set("GET", "/audit", {"items": [], "total": 0})
    assert client.get("/audit?outcome=success").status_code == 200
    fake.set("GET", "/audit/1", {"id": "1", "details": {}})
    assert client.get("/audit/1").status_code == 200


def test_logs(client, login, fake):
    login(["syslog.read"])
    fake.set("GET", "/logs", {"items": [], "total": 0})
    assert client.get("/logs?component=server&level=error").status_code == 200


# -- P-18 Config --------------------------------------------------------------
def test_config_show_and_update(client, login, fake):
    login(["config.read", "config.update"])
    fake.set("GET", "/config", {"items": []})
    assert client.get("/config").status_code == 200
    fake.set("PUT", "/config", {"updated": ["k1"], "requires_restart": ["k1"]})
    r = client.post("/config", data={"value:k1": "v1", "other": "ignored"})
    assert r.status_code == 302


def test_config_update_no_restart(client, login, fake):
    login(["config.update"])
    fake.set("PUT", "/config", {"updated": [], "requires_restart": []})
    assert client.post("/config", data={"value:k1": "v"}).status_code == 302


# -- P-19 Profilo -------------------------------------------------------------
def test_profile(client, login, fake):
    login(["profile.read", "profile.update"])
    fake.set("GET", "/auth/me", {"username": "u", "roles": [], "permissions": []})
    assert client.get("/profile").status_code == 200
    fake.set("POST", "/auth/change-password", None)
    assert client.post("/profile/change-password",
                       data={"current_password": "a", "new_password": "b"}).status_code == 302


# -- RBAC UI enforcement ------------------------------------------------------
def test_nav_hides_items_without_permission(client, login, fake):
    login(["dashboard.read"])  # solo dashboard
    fake.set("GET", "/dashboard/aggregate",
             {"systems_summary": {"ok": 0, "warn": 0, "error": 0, "down": 0,
                                  "unknown": 0}, "active_alarms": 0, "probes": []})
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/alarms", {"items": []})
    html = client.get("/dashboard").data
    assert b"/users" not in html      # niente voce Utenti
    assert b"/config" not in html     # niente voce Config
    assert b"/audit" not in html      # niente voce Audit


def test_nav_shows_items_with_permission(client, login, fake):
    login(["dashboard.read", "users.read", "config.read"])
    fake.set("GET", "/dashboard/aggregate",
             {"systems_summary": {"ok": 0, "warn": 0, "error": 0, "down": 0,
                                  "unknown": 0}, "active_alarms": 0, "probes": []})
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/alarms", {"items": []})
    html = client.get("/dashboard").data
    assert b"/users" in html
    assert b"/config" in html
