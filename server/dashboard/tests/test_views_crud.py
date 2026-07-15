"""Test viste: dashboard, utenti, ruoli, permessi, sonde, sistemi."""


# -- P-02 Dashboard -----------------------------------------------------------
def test_dashboard_index(client, login, fake):
    login(["dashboard.read"])
    fake.set("GET", "/dashboard/aggregate", {
        "systems_summary": {"ok": 3, "warn": 1, "error": 0, "down": 0, "unknown": 0},
        "active_alarms": 2,
        "probes": [{"probe_id": "p1", "status": "online", "systems_total": 4,
                    "systems_down": 0}],
    })
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/alarms", {"items": [{"system_id": "s1", "status": "error",
                                           "opened_at": "2026-07-15T00:00:00Z"}]})
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert b"Dashboard aggregata" in r.data


# -- P-06 Utenti --------------------------------------------------------------
def test_users_list(client, login, fake):
    login(["users.read"])
    fake.set("GET", "/users", {"items": [{"id": "1", "username": "a",
                                          "status": "active", "roles": []}],
                               "total": 1})
    r = client.get("/users?q=a&status=active&page=1")
    assert r.status_code == 200


def test_users_new_and_create(client, login, fake):
    login(["users.create"])
    fake.set("GET", "/roles", {"items": []})
    assert client.get("/users/new").status_code == 200
    fake.set("POST", "/users", {"id": "1"})
    r = client.post("/users/new", data={"username": "a", "email": "a@x",
                                        "full_name": "A", "password": "p",
                                        "role_ids": ["r1"], "status": "active"})
    assert r.status_code == 302


def test_users_detail_edit_update(client, login, fake):
    login(["users.read", "users.update"])
    fake.set("GET", "/users/1", {"id": "1", "username": "a", "roles": []})
    assert client.get("/users/1").status_code == 200
    fake.set("GET", "/roles", {"items": []})
    assert client.get("/users/1/edit").status_code == 200
    fake.set("PUT", "/users/1", {"id": "1"})
    r = client.post("/users/1/edit", data={"email": "b@x", "full_name": "B",
                                           "status": "disabled"})
    assert r.status_code == 302


def test_users_roles_reset_delete(client, login, fake):
    login(["users.assign_roles", "users.update", "users.delete"])
    fake.set("PUT", "/users/1/roles", {"id": "1"})
    assert client.post("/users/1/roles", data={"role_ids": ["r1", "r2"]}).status_code == 302
    fake.set("POST", "/users/1/reset-password", None)
    assert client.post("/users/1/reset-password", data={"new_password": "x"}).status_code == 302
    fake.set("DELETE", "/users/1", None)
    assert client.post("/users/1/delete").status_code == 302


def test_users_forbidden(client, login):
    login(["dashboard.read"])
    assert client.get("/users").status_code == 403


# -- P-07 Ruoli ---------------------------------------------------------------
def test_roles_full_cycle(client, login, fake):
    login(["roles.read", "roles.create", "roles.update",
           "roles.assign_permissions", "roles.delete"])
    fake.set("GET", "/roles", {"items": [], "total": 0})
    assert client.get("/roles").status_code == 200
    fake.set("GET", "/permissions", {"items": []})
    assert client.get("/roles/new").status_code == 200
    fake.set("POST", "/roles", {"id": "1"})
    assert client.post("/roles/new", data={"name": "R", "description": "d",
                                           "permission_codes": ["users.read"]}).status_code == 302
    fake.set("GET", "/roles/1", {"id": "1", "name": "R", "permissions": []})
    assert client.get("/roles/1").status_code == 200
    assert client.get("/roles/1/edit").status_code == 200
    fake.set("PUT", "/roles/1", {"id": "1"})
    assert client.post("/roles/1/edit", data={"name": "R2", "description": "d"}).status_code == 302
    fake.set("PUT", "/roles/1/permissions", {"id": "1"})
    assert client.post("/roles/1/permissions", data={"permission_codes": ["a"]}).status_code == 302
    fake.set("DELETE", "/roles/1", None)
    assert client.post("/roles/1/delete").status_code == 302


# -- P-08 Permessi ------------------------------------------------------------
def test_permissions_grouped(client, login, fake):
    login(["permissions.read"])
    fake.set("GET", "/permissions", {"items": [
        {"code": "users.read", "area": "Utenti", "description": "d"},
        {"code": "users.create", "area": "Utenti", "description": "d"},
        {"code": "roles.read", "area": "Ruoli", "description": "d"},
    ]})
    r = client.get("/permissions")
    assert r.status_code == 200
    assert b"Utenti" in r.data and b"Ruoli" in r.data


# -- P-03/P-09 Sonde ----------------------------------------------------------
def test_probes_list_and_create(client, login, fake):
    login(["probes.read", "probes.create"])
    fake.set("GET", "/probes", {"items": [], "total": 0})
    assert client.get("/probes").status_code == 200
    assert client.get("/probes/new").status_code == 200
    fake.set("POST", "/probes", {"probe": {"id": "1"},
                                 "enrollment_token": "TOK",
                                 "enrollment_expires_at": "2026-07-16T00:00:00Z"})
    r = client.post("/probes/new", data={"name": "p", "description": "d",
                                         "query_endpoint": "http://x",
                                         "tags": "a, b", "enabled": "on"})
    assert r.status_code == 200
    assert b"TOK" in r.data


def test_probes_detail_edit_update_delete_rotate(client, login, fake):
    login(["probes.read", "probes.update", "probes.delete", "probes.rotate_key"])
    fake.set("GET", "/probes/1", {"id": "1", "name": "p"})
    fake.set("GET", "/probes/1/status", {"status": "online"})
    fake.set("GET", "/dashboard/probe/1", {"systems": [], "generated_at": "x"})
    fake.set("GET", "/probes/1/heartbeats", {"items": []})
    assert client.get("/probes/1").status_code == 200
    assert client.get("/probes/1/edit").status_code == 200
    fake.set("PUT", "/probes/1", {"id": "1"})
    assert client.post("/probes/1/edit", data={"name": "p2", "description": "",
                                               "query_endpoint": "", "tags": "",
                                               "enabled": ""}).status_code == 302
    fake.set("DELETE", "/probes/1", None)
    assert client.post("/probes/1/delete").status_code == 302
    fake.set("POST", "/probes/1/rotate-credentials",
             {"enrollment_token": "NEW", "enrollment_expires_at": "x"})
    r = client.post("/probes/1/rotate")
    assert b"NEW" in r.data


# -- P-10 Sistemi -------------------------------------------------------------
def test_systems_full_cycle(client, login, fake):
    login(["systems.read", "systems.create", "systems.update", "systems.delete"])
    fake.set("GET", "/systems", {"items": [], "total": 0})
    fake.set("GET", "/probes", {"items": []})
    assert client.get("/systems?probe_id=p1").status_code == 200
    assert client.get("/systems/new").status_code == 200
    fake.set("POST", "/systems", {"id": "1"})
    r = client.post("/systems/new", data={
        "system_id": "s1", "system_name": "S", "heartbeat_url": "http://x",
        "probe_id": "p1", "poll_interval_seconds": "30", "timeout_seconds": "",
        "enabled": "on", "response_ms_warn": "500", "response_ms_error": ""})
    assert r.status_code == 302
    fake.set("GET", "/systems/1", {"id": "1", "system_name": "S", "thresholds": {},
                                   "maintenance_windows": []})
    fake.set("GET", "/systems/1/checks", {"items": []})
    assert client.get("/systems/1").status_code == 200
    assert client.get("/systems/1/edit").status_code == 200
    fake.set("PUT", "/systems/1", {"id": "1"})
    assert client.post("/systems/1/edit", data={
        "system_id": "s1", "system_name": "S2", "heartbeat_url": "http://x",
        "probe_id": "p1", "poll_interval_seconds": "60", "timeout_seconds": "5",
        "enabled": "", "response_ms_warn": "", "response_ms_error": "900"}).status_code == 302
    fake.set("DELETE", "/systems/1", None)
    assert client.post("/systems/1/delete").status_code == 302
