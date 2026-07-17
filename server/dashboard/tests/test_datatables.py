"""Test dell'adattatore DataTables server-side della dashboard SERVER (dt.py).

Verifica (backend REST simulato da FakeApiClient, vedi conftest):
- /dt/<resource> risponde nel formato DataTables {draw, recordsTotal,
  recordsFiltered, data} mappando start/length->page/page_size, search->q,
  order->sort e inoltrando i filtri correnti;
- il rendering server-side delle celle conserva badge/azioni/date (RBAC incluso);
- le pagine di lista includono l'init DataTables (serverSide + ajax) e gli asset
  vendorizzati localmente (nessun CDN).
"""
from __future__ import annotations

import pytest


# -- Formato generico DataTables per tutte le risorse -------------------------
_RESOURCES = [
    (["users.read"], "users", "/users",
     {"id": "1", "username": "u", "full_name": "F", "email": "e@x",
      "status": "active", "roles": ["admin"]}),
    (["roles.read"], "roles", "/roles",
     {"id": "1", "name": "R", "description": "d", "is_builtin": False,
      "permissions": ["a", "b"]}),
    (["probes.read"], "probes", "/probes",
     {"id": "1", "name": "p", "location": "Milano", "contact_name": "Mario",
      "status": "online", "systems_count": 3,
      "last_seen_at": "2026-07-16T12:00:00Z"}),
    (["systems.read"], "systems", "/systems",
     {"id": "1", "system_id": "s1", "system_name": "S", "kind": "http",
      "heartbeat_url": "http://x", "probe_id": "p1", "enabled": True}),
    (["workflows.read"], "workflows", "/notification-workflows",
     {"id": "1", "name": "w", "trigger": "status_changed", "enabled": True}),
    (["notifications.read"], "channels", "/notification-channels",
     {"id": "1", "name": "c", "type": "email", "enabled": True,
      "inbound_enabled": False}),
    (["notifications.read"], "deliveries", "/notifications/history",
     {"created_at": "2026-07-16T12:00:00Z", "channel_id": "c1",
      "recipient": "r", "status": "sent", "error": None}),
    (["audit.read"], "audit", "/audit",
     {"id": "1", "timestamp": "2026-07-16T12:00:00Z", "actor_type": "user",
      "actor_id": "a", "action": "user.create", "entity_type": "user",
      "outcome": "success"}),
    (["syslog.read"], "logs", "/logs",
     {"timestamp": "2026-07-16T12:00:00Z", "component": "server",
      "level": "info", "logger": "l", "message": "m"}),
    (["workflows.read"], "alarms", "/alarms",
     {"id": "1", "system_id": "s1", "probe_id": "p1", "status": "active",
      "opened_at": "2026-07-16T12:00:00Z"}),
]


@pytest.mark.parametrize("perms,resource,path,item", _RESOURCES)
def test_dt_resource_json_shape(client, login, fake, perms, resource, path, item):
    login(perms)
    fake.set("GET", path, {"items": [item], "total": 7})
    r = client.get(f"/dt/{resource}?draw=9&start=0&length=25")
    assert r.status_code == 200
    body = r.get_json()
    assert body["draw"] == 9
    assert body["recordsTotal"] == 7 and body["recordsFiltered"] == 7
    assert len(body["data"]) == 1
    # start/length -> page/page_size inoltrati al backend
    params = fake.params[("GET", path)]
    assert params["page"] == 1 and params["page_size"] == 25


# -- Mappature start/length/search/order --------------------------------------
def test_dt_maps_paging_search_sort(client, login, fake):
    login(["users.read"])
    fake.set("GET", "/users", {"items": [], "total": 0})
    client.get("/dt/users?draw=2&start=50&length=25&search[value]=alice"
               "&order[0][column]=0&order[0][dir]=desc&columns[0][data]=username")
    params = fake.params[("GET", "/users")]
    assert params["page"] == 3          # 50 // 25 + 1
    assert params["page_size"] == 25
    assert params["q"] == "alice"
    assert params["sort"] == "-username"


def test_dt_forwards_filters(client, login, fake):
    login(["systems.read"])
    fake.set("GET", "/systems", {"items": [], "total": 0})
    client.get("/dt/systems?draw=1&start=0&length=25"
               "&kind=tcp&probe_id=p1&enabled=true")
    params = fake.params[("GET", "/systems")]
    assert params["kind"] == "tcp"
    assert params["probe_id"] == "p1"
    assert params["enabled"] == "true"


def test_dt_users_status_filter(client, login, fake):
    login(["users.read"])
    fake.set("GET", "/users", {"items": [], "total": 0})
    client.get("/dt/users?draw=1&start=0&length=25&status=locked")
    assert fake.params[("GET", "/users")]["status"] == "locked"


# -- Autorizzazione -----------------------------------------------------------
def test_dt_unknown_resource_404(client, login):
    login(["users.read"])
    assert client.get("/dt/pinco").status_code == 404


def test_dt_unauthenticated_401(client):
    assert client.get("/dt/users").status_code == 401


def test_dt_wrong_permission_403(client, login):
    login(["dashboard.read"])
    assert client.get("/dt/users").status_code == 403


def test_dt_heartbeats_wrong_permission_403(client, login):
    login(["dashboard.read"])
    assert client.get("/dt/heartbeats/1").status_code == 403


def test_dt_heartbeats_unauthenticated_401(client):
    assert client.get("/dt/heartbeats/1").status_code == 401


# -- Rendering delle celle (badge / azioni / date / RBAC) ---------------------
def _rows(client, resource, **q):
    r = client.get(f"/dt/{resource}?draw=1&start=0&length=25", **q)
    return r.get_json()["data"]


def test_render_users_actions_with_and_without_update(client, login, fake):
    fake.set("GET", "/users", {"items": [{"id": "1", "username": "u",
                                          "status": "active", "roles": []}],
                               "total": 1})
    login(["users.read"])
    row = _rows(client, "users")[0]
    assert 'href="/users/1"' in row["username"]
    assert "bi-eye" in row["actions"] and "bi-pencil" not in row["actions"]
    assert 'badge b-ok' in row["status"]
    login(["users.read", "users.update"])
    assert "bi-pencil" in _rows(client, "users")[0]["actions"]


def test_render_roles_builtin_hides_edit(client, login, fake):
    login(["roles.read", "roles.update"])
    fake.set("GET", "/roles", {"items": [
        {"id": "1", "name": "builtin", "description": "d", "is_builtin": True,
         "permissions": ["a"]},
        {"id": "2", "name": "custom", "description": "d", "is_builtin": False,
         "permissions": ["a", "b"]},
    ], "total": 2})
    rows = _rows(client, "roles")
    assert "bi-pencil" not in rows[0]["actions"]     # builtin: no edit
    assert "bi-pencil" in rows[1]["actions"]         # custom: edit
    assert rows[1]["permissions"] == "2"             # conteggio permessi


def test_render_probes_placeholder_and_localdt(client, login, fake):
    login(["probes.read"])
    fake.set("GET", "/probes", {"items": [
        {"id": "1", "name": "p", "location": None, "contact_name": None,
         "status": "online", "systems_count": 0,
         "last_seen_at": "2026-07-16T12:00:00Z"}], "total": 1})
    row = _rows(client, "probes")[0]
    assert row["location"] == "—" and row["contact_name"] == "—"
    assert "16/07/2026" in row["last_seen_at"]       # data localizzata
    assert "bi-pencil" not in row["actions"]          # niente update
    login(["probes.read", "probes.update"])
    assert "bi-pencil" in _rows(client, "probes")[0]["actions"]


def test_render_systems_http_and_tcp(client, login, fake):
    login(["systems.read", "systems.update"])
    fake.set("GET", "/systems", {"items": [
        {"id": "1", "system_id": "s1", "system_name": "S", "kind": "http",
         "heartbeat_url": "http://h", "probe_id": "p1", "enabled": True},
        {"id": "2", "system_id": "s2", "system_name": "T", "kind": "tcp",
         "tcp_host": "db", "tcp_port": 5432, "probe_id": "p1", "enabled": False},
    ], "total": 2})
    rows = _rows(client, "systems")
    assert ">HTTP<" in rows[0]["kind"] and "http://h" in rows[0]["target"]
    assert ">TCP<" in rows[1]["kind"] and "db:5432" in rows[1]["target"]
    assert "bi-pencil" in rows[0]["actions"]


def test_render_systems_without_update(client, login, fake):
    login(["systems.read"])
    fake.set("GET", "/systems", {"items": [
        {"id": "1", "system_id": "s1", "system_name": "S", "kind": "http",
         "heartbeat_url": "http://h", "probe_id": "p1", "enabled": True}],
        "total": 1})
    assert "bi-pencil" not in _rows(client, "systems")[0]["actions"]


def test_render_channels_icon_and_default(client, login, fake):
    login(["notifications.read", "notifications.update"])
    fake.set("GET", "/notification-channels", {"items": [
        {"id": "1", "name": "mail", "type": "email", "enabled": True,
         "inbound_enabled": True},
        {"id": "2", "name": "weird", "type": "carrier-pigeon", "enabled": False,
         "inbound_enabled": False},
    ], "total": 2})
    rows = _rows(client, "channels")
    assert "bi-envelope" in rows[0]["type"]
    assert "bi-broadcast" in rows[1]["type"]         # tipo ignoto -> default
    assert "bi-pencil" in rows[0]["actions"]


def test_render_workflows_and_without_update(client, login, fake):
    fake.set("GET", "/notification-workflows", {"items": [
        {"id": "1", "name": "w", "trigger": "status_changed", "enabled": True}],
        "total": 1})
    login(["workflows.read"])
    row = _rows(client, "workflows")[0]
    assert "<code>status_changed</code>" in row["trigger"]
    assert "bi-pencil" not in row["actions"]
    login(["workflows.read", "workflows.update"])
    assert "bi-pencil" in _rows(client, "workflows")[0]["actions"]


def test_render_audit_link_and_logs_level(client, login, fake):
    login(["audit.read"])
    fake.set("GET", "/audit", {"items": [
        {"id": "9", "timestamp": "2026-07-16T12:00:00Z", "actor_type": "user",
         "actor_id": "a", "action": "user.create", "entity_type": "user",
         "outcome": "success"}], "total": 1})
    row = _rows(client, "audit")[0]
    assert 'href="/audit/9"' in row["timestamp"] and "16/07/2026" in row["timestamp"]
    assert row["actor"] == "user:a"
    assert "<code>user.create</code>" in row["action"]

    login(["syslog.read"])
    fake.set("GET", "/logs", {"items": [
        {"timestamp": "2026-07-16T12:00:00Z", "component": "server",
         "level": "zzz", "logger": "l", "message": "m"}], "total": 1})
    # livello ignoto -> classe di default text-bg-secondary
    assert "text-bg-secondary" in _rows(client, "logs")[0]["level"]


def test_render_alarms_ack_and_placeholder(client, login, fake):
    fake.set("GET", "/alarms", {"items": [
        {"id": "1", "system_id": "s1", "probe_id": "p1", "status": "active",
         "opened_at": "2026-07-16T12:00:00Z"},
        {"id": "2", "system_id": "s2", "probe_id": "p1", "status": "resolved",
         "opened_at": "2026-07-16T12:00:00Z"},
    ], "total": 2})
    login(["workflows.read", "commands.execute"])
    rows = _rows(client, "alarms")
    assert 'action="/alarms/1/ack"' in rows[0]["actions"]  # active + can ack
    assert rows[1]["actions"].strip().endswith("—</span>")  # resolved -> dash
    # senza commands.execute anche l'allarme attivo mostra il segnaposto
    login(["workflows.read"])
    assert "ack" not in _rows(client, "alarms")[0]["actions"].lower()


# -- Adattatore heartbeat (dettaglio Sonda) -----------------------------------
def test_dt_heartbeats_json_and_filters(client, login, fake):
    login(["heartbeats.read"])
    fake.set("GET", "/probes/1/heartbeats", {"items": [
        {"@timestamp": "2026-07-16T12:00:00Z", "system_name": "S",
         "check_name": "C", "status": "ok", "response_ms": 5}], "total": 3})
    r = client.get("/dt/heartbeats/1?draw=4&start=0&length=50"
                   "&order[0][column]=0&order[0][dir]=desc"
                   "&columns[0][data]=@timestamp&status=ok&system_id=s1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["draw"] == 4 and body["recordsTotal"] == 3
    row = body["data"][0]
    assert "16/07/2026" in row["@timestamp"]
    assert "badge b-ok" in row["status"]
    params = fake.params[("GET", "/probes/1/heartbeats")]
    assert params["sort"] == "-@timestamp"
    assert params["status"] == "ok" and params["system_id"] == "s1"


# -- Pagine di lista: init DataTables + asset locali (no CDN) ------------------
_PAGES = [
    (["users.read"], "/users", "users"),
    (["roles.read"], "/roles", "roles"),
    (["probes.read"], "/probes", "probes"),
    (["workflows.read"], "/notification-workflows", "workflows"),
    (["notifications.read"], "/notification-channels", "channels"),
    (["notifications.read"], "/notifications/history", "deliveries"),
    (["audit.read"], "/audit", "audit"),
    (["syslog.read"], "/logs", "logs"),
    (["workflows.read"], "/alarms", "alarms"),
]


@pytest.mark.parametrize("perms,url,resource", _PAGES)
def test_list_page_has_datatables_init_and_local_assets(client, login, fake,
                                                        perms, url, resource):
    login(perms)
    fake.set("GET", url, {"items": [], "total": 0})
    fake.set("GET", "/probes", {"items": []})
    html = client.get(url).get_data(as_text=True)
    assert "PulseDT.init" in html
    assert f"/dt/{resource}" in html
    assert "ajax:" in html and "columns:" in html
    # asset vendorizzati localmente (serverSide:true e' impostato qui)
    assert "js/pulse-datatables.js" in html
    assert "vendor/jquery/jquery.min.js" in html
    assert "vendor/datatables/js/dataTables.min.js" in html
    assert "vendor/datatables/css/dataTables.bootstrap5.min.css" in html
    # nessun riferimento a CDN
    assert "cdn.datatables.net" not in html
    assert "code.jquery.com" not in html


def test_systems_page_datatables_and_kind_filter(client, login, fake):
    login(["systems.read"])
    fake.set("GET", "/systems", {"items": [], "total": 0})
    fake.set("GET", "/probes", {"items": []})
    html = client.get("/systems?kind=tcp").get_data(as_text=True)
    assert "PulseDT.init" in html
    assert "/dt/systems" in html
    # il kind attivo e' passato via ajax.data
    assert 'd.kind = "tcp"' in html


def test_table_meta_unknown_raises(app):
    import dt as dt_adapter
    with pytest.raises(KeyError):
        dt_adapter.table_meta("inesistente")


def test_paging_fallback_on_invalid_params(client, login, fake):
    """?page/?page_size non numerici: la view non va in errore (ripiego)."""
    login(["users.read"])
    fake.set("GET", "/users", {"items": [], "total": 0})
    assert client.get("/users?page=abc&page_size=xyz").status_code == 200


def test_probe_detail_has_heartbeat_datatable(client, login, fake):
    login(["probes.read"])
    fake.set("GET", "/probes/1", {"id": "1", "name": "p"})
    fake.set("GET", "/probes/1/status", {"status": "online"})
    fake.set("GET", "/dashboard/probe/1", {"systems": [], "generated_at": "x"})
    fake.set("GET", "/probes/1/heartbeats", {"items": [], "total": 0})
    html = client.get("/probes/1?status=error").get_data(as_text=True)
    assert "PulseDT.init" in html
    assert "/dt/heartbeats/1" in html
    # il filtro di drill-down (status) e' propagato ad ajax.data
    assert 'd.status = "error"' in html
