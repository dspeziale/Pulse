"""Test viste: dashboard, utenti, ruoli, permessi, sonde, sistemi."""

from views.dashboard import _build_context, _probe_led


# -- P-02 Dashboard -----------------------------------------------------------
def _dash(fake, summary=None, active_alarms=0, probes=None, alarms_items=None):
    fake.set("GET", "/dashboard/aggregate", {
        "systems_summary": summary or {"ok": 0, "warn": 0, "error": 0,
                                       "down": 0, "unknown": 0},
        "active_alarms": active_alarms,
        "probes": probes or [],
    })
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/alarms", {"items": alarms_items or []})


def test_dashboard_index(client, login, fake):
    login(["dashboard.read"])
    _dash(fake,
          summary={"ok": 3, "warn": 1, "error": 0, "down": 0, "unknown": 0},
          active_alarms=2,
          probes=[{"probe_id": "p1", "status": "online", "systems_total": 4,
                   "systems_down": 0}],
          alarms_items=[{"system_id": "s1", "status": "error",
                         "opened_at": "2026-07-15T00:00:00Z"}])
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert b"Dashboard aggregata" in r.data
    # KPI arricchite + LED complessivo presenti.
    assert b"Sistemi totali" in r.data
    assert b"Sonde online" in r.data
    assert b"Sonde offline" in r.data
    assert b"pulse-led" in r.data


def test_dashboard_overall_ok(client, login, fake):
    login(["dashboard.read"])
    _dash(fake, summary={"ok": 5, "warn": 0, "error": 0, "down": 0, "unknown": 0},
          probes=[{"probe_id": "p1", "status": "online", "systems_total": 5,
                   "systems_down": 0}])
    r = client.get("/dashboard")
    assert b'data-overall-status="ok"' in r.data
    assert b"Tutto regolare" in r.data
    assert b"led-ok" in r.data


def test_dashboard_overall_warn(client, login, fake):
    login(["dashboard.read"])
    _dash(fake, summary={"ok": 2, "warn": 3, "error": 0, "down": 0, "unknown": 0})
    r = client.get("/dashboard")
    assert b'data-overall-status="warn"' in r.data
    assert b"3 in warning" in r.data


def test_dashboard_overall_error_by_status(client, login, fake):
    login(["dashboard.read"])
    _dash(fake, summary={"ok": 1, "warn": 0, "error": 2, "down": 0, "unknown": 0})
    r = client.get("/dashboard")
    assert b'data-overall-status="error"' in r.data
    # Label esplicita col conteggio, non piu' generica.
    assert b"2 in errore, 0 non raggiungibili" in r.data


def test_dashboard_overall_error_by_down_only(client, login, fake):
    login(["dashboard.read"])
    _dash(fake, summary={"ok": 1, "warn": 0, "error": 0, "down": 3, "unknown": 0})
    r = client.get("/dashboard")
    assert b'data-overall-status="error"' in r.data
    assert b"0 in errore, 3 non raggiungibili" in r.data


def test_dashboard_alarms_do_not_color_led(client, login, fake):
    # Allarmi attivi ma nessun check problematico -> LED VERDE (colore = check).
    login(["dashboard.read"])
    _dash(fake, summary={"ok": 4, "warn": 0, "error": 0, "down": 0, "unknown": 0},
          active_alarms=5)
    r = client.get("/dashboard")
    assert b'data-overall-status="ok"' in r.data
    assert b"Tutto regolare" in r.data
    # Gli allarmi restano visibili come voce separata.
    assert b"Allarmi attivi" in r.data
    assert b"incidenti" in r.data


def test_dashboard_probe_leds(client, login, fake):
    login(["dashboard.read"])
    _dash(fake, summary={"ok": 1, "warn": 0, "error": 0, "down": 0, "unknown": 0},
          probes=[
              {"probe_id": "on", "status": "online", "systems_total": 3, "systems_down": 0},
              {"probe_id": "off", "status": "offline", "systems_total": 2, "systems_down": 0},
              {"probe_id": "deg", "status": "online", "systems_total": 4, "systems_down": 1},
          ])
    r = client.get("/dashboard")
    assert b"led-ok" in r.data
    assert b"led-error" in r.data
    assert b"led-warn" in r.data


def test_dashboard_no_probes(client, login, fake):
    login(["dashboard.read"])
    _dash(fake)
    r = client.get("/dashboard")
    assert b"Nessuna Sonda registrata." in r.data


def test_dashboard_missing_aggregate_is_safe(client, login, fake):
    # Nessuna risposta pre-registrata: la view non deve andare in errore.
    login(["dashboard.read"])
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/alarms", {"items": []})
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert b'data-overall-status="ok"' in r.data


# -- Unita': logica LED / KPI -------------------------------------------------
def test_probe_led_states():
    assert _probe_led("online", 0) == "ok"
    assert _probe_led("online", 2) == "warn"
    assert _probe_led("offline", 0) == "error"
    assert _probe_led("down", 0) == "error"
    assert _probe_led("weird", 0) == "error"   # stato ignoto -> rosso
    assert _probe_led("", 0) == "ok"           # assenza stato: verde se no down
    assert _probe_led("ok", 0) == "ok"


def test_build_context_counts():
    ctx = _build_context(
        {"systems_summary": {"ok": 1, "warn": 2, "error": 3, "down": 4, "unknown": 5},
         "active_alarms": 6,
         "probes": [
             {"probe_id": "a", "status": "online", "systems_total": 2, "systems_down": 0},
             {"probe_id": "b", "status": "offline", "systems_total": 1, "systems_down": 0},
         ]},
        {"items": []}, {"items": []})
    k = ctx["kpis"]
    assert k["systems_total"] == 15
    assert k["active_alarms"] == 6
    assert k["probes_total"] == 2
    assert k["probes_online"] == 1
    assert k["probes_offline"] == 1
    assert ctx["overall"] == "error"
    assert ctx["overall_target_status"] == "error"


def test_build_context_defensive_non_numeric():
    ctx = _build_context(
        {"systems_summary": {"ok": None, "warn": "x", "error": None,
                             "down": None, "unknown": None},
         "active_alarms": None, "probes": None},
        None, None)
    assert ctx["kpis"]["systems_total"] == 0
    assert ctx["overall"] == "ok"
    assert ctx["overall_target_status"] is None


def test_build_context_overall_ignores_alarms():
    # Allarmi > 0 ma nessun check problematico -> overall verde.
    ctx = _build_context(
        {"systems_summary": {"ok": 3, "warn": 0, "error": 0, "down": 0, "unknown": 0},
         "active_alarms": 9, "probes": []},
        {"items": []}, {"items": []})
    assert ctx["overall"] == "ok"
    assert ctx["overall_label"] == "Tutto regolare"


def test_build_context_target_down_when_only_down():
    ctx = _build_context(
        {"systems_summary": {"ok": 0, "warn": 0, "error": 0, "down": 2, "unknown": 0},
         "active_alarms": 0, "probes": []},
        {"items": []}, {"items": []})
    assert ctx["overall_target_status"] == "down"
    assert ctx["overall_label"] == "0 in errore, 2 non raggiungibili"


def test_build_context_target_warn():
    ctx = _build_context(
        {"systems_summary": {"ok": 0, "warn": 5, "error": 0, "down": 0, "unknown": 0},
         "active_alarms": 0, "probes": []},
        {"items": []}, {"items": []})
    assert ctx["overall_target_status"] == "warn"


def test_build_context_single_probe_drill():
    ctx = _build_context(
        {"systems_summary": {"ok": 0, "warn": 0, "error": 1, "down": 0, "unknown": 0},
         "active_alarms": 0,
         "probes": [{"probe_id": "solo", "status": "online",
                     "systems_total": 3, "systems_down": 0}]},
        {"items": []}, {"items": []})
    assert ctx["single_probe_id"] == "solo"
    assert ctx["drill_probe_id"] == "solo"


def test_build_context_multi_probe_drill_first_problem():
    ctx = _build_context(
        {"systems_summary": {"ok": 0, "warn": 0, "error": 0, "down": 1, "unknown": 0},
         "active_alarms": 0,
         "probes": [
             {"probe_id": "ok1", "status": "online", "systems_total": 2, "systems_down": 0},
             {"probe_id": "bad", "status": "online", "systems_total": 2, "systems_down": 1},
         ]},
        {"items": []}, {"items": []})
    assert ctx["single_probe_id"] is None
    assert ctx["drill_probe_id"] == "bad"           # prima Sonda interessata
    # La riga per-Sonda con sistemi down punta ai check 'down'.
    rows = {r["probe_id"]: r for r in ctx["probe_rows"]}
    assert rows["bad"]["drill"] == "down"
    assert rows["ok1"]["drill"] == ""


def test_build_context_multi_probe_all_ok_no_drill():
    ctx = _build_context(
        {"systems_summary": {"ok": 4, "warn": 0, "error": 0, "down": 0, "unknown": 0},
         "active_alarms": 0,
         "probes": [
             {"probe_id": "a", "status": "online", "systems_total": 2, "systems_down": 0},
             {"probe_id": "b", "status": "online", "systems_total": 2, "systems_down": 0},
         ]},
        {"items": []}, {"items": []})
    assert ctx["single_probe_id"] is None
    assert ctx["drill_probe_id"] is None


# -- Drill-down link nella pagina (single vs multi probe) ---------------------
def test_dashboard_tiles_link_single_probe(client, login, fake):
    login(["dashboard.read", "probes.read"])
    _dash(fake, summary={"ok": 1, "warn": 0, "error": 1, "down": 0, "unknown": 0},
          probes=[{"probe_id": "P1", "status": "online", "systems_total": 2,
                   "systems_down": 0}])
    r = client.get("/dashboard")
    # La tile Error linka al dettaglio della sola Sonda filtrato per status=error.
    assert b"/probes/P1?status=error" in r.data
    # Il LED complessivo punta allo stesso target.
    assert b'data-overall-status="error"' in r.data


def test_dashboard_tiles_not_linked_multi_probe(client, login, fake):
    login(["dashboard.read", "probes.read"])
    _dash(fake, summary={"ok": 0, "warn": 0, "error": 2, "down": 0, "unknown": 0},
          probes=[
              {"probe_id": "PA", "status": "online", "systems_total": 2, "systems_down": 1},
              {"probe_id": "PB", "status": "online", "systems_total": 2, "systems_down": 0},
          ])
    r = client.get("/dashboard")
    # Con piu' Sonde la tile globale NON e' un link diretto ai check...
    assert b"Vedi il dettaglio per singola Sonda" in r.data
    # ...ma il LED complessivo punta alla prima Sonda interessata (PA con down).
    assert b"/probes/PA?status=error" in r.data
    # e la mini-card per-Sonda con sistemi down linka a status=down.
    assert b"/probes/PA?status=down" in r.data


# -- P-06 Utenti --------------------------------------------------------------
def test_users_list(client, login, fake):
    login(["users.read"])
    fake.set("GET", "/users", {"items": [{"id": "1", "username": "a",
                                          "status": "active", "roles": []}],
                               "total": 1})
    r = client.get("/users?q=a&status=active&page=1&page_size=10")
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
                                         "tags": "a, b", "enabled": "on",
                                         "location": " Milano DC1 ",
                                         "contact_name": "Mario Rossi",
                                         "contact_email": "mario@example.com",
                                         "contact_phone": "+39 02 1"})
    assert r.status_code == 200
    assert b"TOK" in r.data
    # I campi anagrafici sono inoltrati al backend (ripuliti dagli spazi).
    sent = fake.sent[("POST", "/probes")]
    assert sent["location"] == "Milano DC1"
    assert sent["contact_name"] == "Mario Rossi"
    assert sent["contact_email"] == "mario@example.com"
    assert sent["contact_phone"] == "+39 02 1"


def test_probes_create_omits_empty_profile(client, login, fake):
    """Campi anagrafici vuoti -> null (non stringa vuota) per evitare 422."""
    login(["probes.create"])
    fake.set("POST", "/probes", {"probe": {"id": "1"}, "enrollment_token": "T",
                                 "enrollment_expires_at": "x"})
    client.post("/probes/new", data={"name": "p", "contact_email": "  "})
    sent = fake.sent[("POST", "/probes")]
    assert sent["contact_email"] is None
    assert sent["location"] is None
    assert sent["contact_name"] is None
    assert sent["contact_phone"] is None


def test_probes_detail_edit_update_delete_rotate(client, login, fake):
    login(["probes.read", "probes.update", "probes.delete", "probes.rotate_key"])
    fake.set("GET", "/probes/1", {"id": "1", "name": "p",
                                  "location": "Milano DC1",
                                  "contact_name": "Mario Rossi",
                                  "contact_email": "mario@example.com",
                                  "contact_phone": "+39 02 1"})
    fake.set("GET", "/probes/1/status", {"status": "online"})
    fake.set("GET", "/dashboard/probe/1", {"systems": [], "generated_at": "x"})
    fake.set("GET", "/probes/1/heartbeats", {"items": []})
    detail = client.get("/probes/1")
    assert detail.status_code == 200
    # Il dettaglio mostra l'anagrafica.
    body = detail.get_data(as_text=True)
    assert "Anagrafica" in body
    assert "Milano DC1" in body
    assert "Mario Rossi" in body
    assert "mario@example.com" in body
    assert "+39 02 1" in body
    # La form di modifica precompila i campi anagrafici.
    edit = client.get("/probes/1/edit")
    assert edit.status_code == 200
    edit_body = edit.get_data(as_text=True)
    assert 'name="location"' in edit_body
    assert 'name="contact_name"' in edit_body
    assert 'name="contact_email"' in edit_body
    assert 'name="contact_phone"' in edit_body
    assert 'value="Milano DC1"' in edit_body
    assert 'value="Mario Rossi"' in edit_body
    fake.set("PUT", "/probes/1", {"id": "1"})
    assert client.post("/probes/1/edit",
                       data={"name": "p2", "description": "",
                             "query_endpoint": "", "tags": "", "enabled": "",
                             "location": "Roma", "contact_name": "Anna",
                             "contact_email": "anna@example.com",
                             "contact_phone": "111"}).status_code == 302
    # Update inoltra i campi anagrafici al backend.
    put_sent = fake.sent[("PUT", "/probes/1")]
    assert put_sent["location"] == "Roma"
    assert put_sent["contact_name"] == "Anna"
    assert put_sent["contact_email"] == "anna@example.com"
    assert put_sent["contact_phone"] == "111"
    fake.set("DELETE", "/probes/1", None)
    assert client.post("/probes/1/delete").status_code == 302
    fake.set("POST", "/probes/1/rotate-credentials",
             {"enrollment_token": "NEW", "enrollment_expires_at": "x"})
    r = client.post("/probes/1/rotate")
    assert b"NEW" in r.data


def test_probes_detail_profile_placeholder(client, login, fake):
    """Anagrafica assente -> segnaposto '—' nel dettaglio."""
    login(["probes.read"])
    fake.set("GET", "/probes/1", {"id": "1", "name": "p"})
    fake.set("GET", "/probes/1/status", {"status": "online"})
    fake.set("GET", "/dashboard/probe/1", {"systems": [], "generated_at": "x"})
    fake.set("GET", "/probes/1/heartbeats", {"items": []})
    body = client.get("/probes/1").get_data(as_text=True)
    assert "Anagrafica" in body
    assert "—" in body  # posizione/referente/email/telefono assenti


def test_probes_new_form_has_empty_profile_fields(client, login, fake):
    """La form di creazione espone i campi anagrafici (vuoti)."""
    login(["probes.create"])
    body = client.get("/probes/new").get_data(as_text=True)
    for field in ("location", "contact_name", "contact_email", "contact_phone"):
        assert ('name="%s"' % field) in body
    assert 'type="email"' in body  # email referente


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


# -- P-10 TAB per tipo (Applicazioni http / Connettività tcp) -----------------
def test_systems_tabs_default_http(client, login, fake):
    """Senza ?kind: default 'http', tab Applicazioni attivo, backend con kind=http."""
    login(["systems.read"])
    fake.set("GET", "/systems", {"items": [], "total": 0})
    fake.set("GET", "/probes", {"items": []})
    html = client.get("/systems").get_data(as_text=True)
    assert "nav-tabs" in html
    assert "Applicazioni" in html and "Connettività" in html
    # Il backend riceve kind=http.
    assert fake.params[("GET", "/systems")]["kind"] == "http"
    # Tab Applicazioni attivo (la voce con href kind=http porta class active).
    assert 'href="/systems?kind=http"' in html
    assert 'href="/systems?kind=tcp"' in html


def test_systems_tab_tcp_active_and_backend_kind(client, login, fake):
    """?kind=tcp: tab Connettività attivo e backend interrogato con kind=tcp."""
    login(["systems.read"])
    fake.set("GET", "/systems", {"items": [], "total": 0})
    fake.set("GET", "/probes", {"items": []})
    html = client.get("/systems?kind=tcp").get_data(as_text=True)
    assert fake.params[("GET", "/systems")]["kind"] == "tcp"
    # Il link della tab TCP e' quello attivo: verifica presenza classe active
    # sulla voce Connettività (nav-link active ... kind=tcp).
    import re
    m = re.search(r'<a class="nav-link active"[^>]*kind=tcp', html)
    assert m is not None
    # E la tab http NON e' attiva.
    assert 'class="nav-link active" href="/systems?kind=http"' not in html


def test_systems_invalid_kind_falls_back_http(client, login, fake):
    login(["systems.read"])
    fake.set("GET", "/systems", {"items": [], "total": 0})
    fake.set("GET", "/probes", {"items": []})
    client.get("/systems?kind=bogus")
    assert fake.params[("GET", "/systems")]["kind"] == "http"


def test_systems_pagination_preserves_kind(client, login, fake):
    """I link di paginazione conservano il kind attivo."""
    login(["systems.read"])
    fake.set("GET", "/systems", {"items": [{"id": "1", "system_id": "s1",
                                            "system_name": "S", "kind": "tcp"}],
                                 "total": 50})
    fake.set("GET", "/probes", {"items": []})
    html = client.get("/systems?kind=tcp&page_size=10").get_data(as_text=True)
    # Deve esistere almeno un link di pagina con kind=tcp preservato.
    assert "kind=tcp" in html
    assert "page=2" in html


def test_systems_new_form_preselects_kind_from_tab(client, login, fake):
    """Il pulsante Nuovo passa ?kind=<attivo> e la form preseleziona il tipo."""
    login(["systems.create"])
    fake.set("GET", "/probes", {"items": []})
    html = client.get("/systems/new?kind=tcp").get_data(as_text=True)
    # L'option TCP risulta selected.
    import re
    assert re.search(r'<option value="tcp"[^>]*selected', html) is not None


# -- P-10 Auto-popolamento sistemi per Sonda (proxy) --------------------------
def test_systems_by_probe_returns_items(client, login, fake):
    login(["systems.read"])
    fake.set("GET", "/systems", {"items": [
        {"id": "1", "system_id": "s1", "system_name": "S1", "extra": "ignored"},
        {"id": "2", "system_id": "s2", "system_name": "S2"},
    ]})
    r = client.get("/systems-by-probe?probe_id=p1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["items"] == [
        {"id": "1", "system_id": "s1", "system_name": "S1"},
        {"id": "2", "system_id": "s2", "system_name": "S2"},
    ]
    # il filtro probe_id è propagato al backend
    assert fake.params[("GET", "/systems")] == {"probe_id": "p1"}


def test_systems_by_probe_empty_without_probe(client, login, fake):
    login(["systems.read"])
    r = client.get("/systems-by-probe")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}
    # senza probe_id non chiama il backend
    assert ("GET", "/systems") not in fake.calls


def test_systems_by_probe_forbidden(client, login):
    login(["dashboard.read"])
    assert client.get("/systems-by-probe?probe_id=p1").status_code == 403


def test_systems_by_probe_non_dict_backend(client, login, fake):
    login(["systems.read"])
    fake.set("GET", "/systems", ["unexpected"])
    r = client.get("/systems-by-probe?probe_id=p1")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}


# -- P-10 Form HTTP/TCP: rendering condizionale e invio campi ------------------
def test_systems_form_has_kind_and_tcp_fields(client, login, fake):
    login(["systems.create"])
    fake.set("GET", "/probes", {"items": []})
    r = client.get("/systems/new")
    assert r.status_code == 200
    assert b'id="kind"' in r.data
    assert b'name="tcp_host"' in r.data
    assert b'name="tcp_port"' in r.data
    assert b"test-tcp-btn" in r.data
    assert b'data-kind="http"' in r.data and b'data-kind="tcp"' in r.data


def test_systems_edit_tcp_system_preselects_kind(client, login, fake):
    login(["systems.update"])
    fake.set("GET", "/systems/1", {"id": "1", "system_name": "S", "kind": "tcp",
                                   "tcp_host": "db", "tcp_port": 5432,
                                   "thresholds": {}})
    fake.set("GET", "/probes", {"items": []})
    r = client.get("/systems/1/edit")
    assert r.status_code == 200
    assert b'value="tcp" selected' in r.data
    assert b"5432" in r.data


def test_systems_create_http_payload(client, login, fake):
    login(["systems.create"])
    fake.set("POST", "/systems", {"id": "1"})
    r = client.post("/systems/new", data={
        "system_id": "s1", "system_name": "S", "kind": "http",
        "heartbeat_url": "http://x", "tcp_host": "ignored", "tcp_port": "999",
        "probe_id": "p1", "poll_interval_seconds": "30", "timeout_seconds": "5",
        "enabled": "on"})
    assert r.status_code == 302
    sent = fake.sent[("POST", "/systems")]
    assert sent["kind"] == "http"
    assert sent["heartbeat_url"] == "http://x"
    # i campi TCP non vengono propagati per il tipo http
    assert sent["tcp_host"] is None and sent["tcp_port"] is None


def test_systems_create_tcp_payload(client, login, fake):
    login(["systems.create"])
    fake.set("POST", "/systems", {"id": "1"})
    r = client.post("/systems/new", data={
        "system_id": "s1", "system_name": "S", "kind": "tcp",
        "heartbeat_url": "http://ignored", "tcp_host": "db.local",
        "tcp_port": "5432", "probe_id": "p1", "poll_interval_seconds": "30",
        "enabled": "on"})
    assert r.status_code == 302
    sent = fake.sent[("POST", "/systems")]
    assert sent["kind"] == "tcp"
    assert sent["tcp_host"] == "db.local" and sent["tcp_port"] == 5432
    # l'URL heartbeat non viene propagato per il tipo tcp
    assert sent["heartbeat_url"] is None


def test_systems_update_tcp_payload(client, login, fake):
    login(["systems.update"])
    fake.set("PUT", "/systems/1", {"id": "1"})
    r = client.post("/systems/1/edit", data={
        "system_id": "s1", "system_name": "S2", "kind": "tcp",
        "tcp_host": "10.0.0.1", "tcp_port": "6379", "probe_id": "p1",
        "poll_interval_seconds": "60", "timeout_seconds": "5"})
    assert r.status_code == 302
    sent = fake.sent[("PUT", "/systems/1")]
    assert sent["kind"] == "tcp" and sent["tcp_host"] == "10.0.0.1"
    assert sent["tcp_port"] == 6379


def test_systems_create_invalid_kind_defaults_http(client, login, fake):
    login(["systems.create"])
    fake.set("POST", "/systems", {"id": "1"})
    r = client.post("/systems/new", data={
        "system_id": "s1", "system_name": "S", "kind": "weird",
        "heartbeat_url": "http://x", "probe_id": "p1"})
    assert r.status_code == 302
    assert fake.sent[("POST", "/systems")]["kind"] == "http"


# -- P-10 Test endpoint heartbeat (pre-salvataggio) ---------------------------
def test_systems_new_form_has_test_button(client, login, fake):
    login(["systems.create"])
    fake.set("GET", "/probes", {"items": []})
    r = client.get("/systems/new")
    assert r.status_code == 200
    assert b"test-heartbeat-btn" in r.data
    assert b"Testa endpoint" in r.data
    assert b"/systems/test-heartbeat" in r.data


def test_systems_edit_form_has_test_button(client, login, fake):
    login(["systems.update"])
    fake.set("GET", "/systems/1", {"id": "1", "system_name": "S",
                                   "thresholds": {}})
    fake.set("GET", "/probes", {"items": []})
    r = client.get("/systems/1/edit")
    assert r.status_code == 200
    assert b"test-heartbeat-btn" in r.data


def test_test_heartbeat_reachable_valid(client, login, fake):
    login(["systems.create"])
    fake.set("POST", "/systems/test", {
        "reachable": True, "http_status": 200, "response_ms": 42,
        "valid_schema": True, "checks_count": 1, "error": None,
        "documents": [{"system_id": "s1", "system_name": "S", "check_id": "c1",
                       "check_name": "C", "status": "ok", "response_ms": 42,
                       "message": None}]})
    r = client.post("/systems/test-heartbeat",
                    json={"heartbeat_url": "http://x", "timeout_seconds": 3})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["result"]["reachable"] is True
    assert ("POST", "/systems/test") in fake.calls


def test_test_heartbeat_unreachable(client, login, fake):
    login(["systems.update"])
    fake.set("POST", "/systems/test", {
        "reachable": False, "http_status": None, "response_ms": 0,
        "valid_schema": False, "checks_count": 0, "documents": [],
        "error": "Connection refused"})
    # timeout assente -> ramo senza timeout nel payload; invio via form.
    r = client.post("/systems/test-heartbeat", data={"heartbeat_url": "http://x"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["result"]["reachable"] is False


def test_test_heartbeat_missing_url(client, login, fake):
    login(["systems.create"])
    r = client.post("/systems/test-heartbeat", json={"heartbeat_url": "  "})
    assert r.status_code == 422
    assert r.get_json()["ok"] is False


def test_test_tcp_reachable(client, login, fake):
    login(["systems.create"])
    fake.set("POST", "/systems/test", {"reachable": True, "response_ms": 12,
                                       "error": None})
    r = client.post("/systems/test-heartbeat",
                    json={"kind": "tcp", "tcp_host": "db", "tcp_port": 5432,
                          "timeout_seconds": 3})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["result"]["reachable"] is True
    sent = fake.sent[("POST", "/systems/test")]
    assert sent == {"kind": "tcp", "tcp_host": "db", "tcp_port": 5432,
                    "timeout_seconds": 3}


def test_test_tcp_missing_host_or_port(client, login, fake):
    login(["systems.update"])
    r = client.post("/systems/test-heartbeat",
                    json={"kind": "tcp", "tcp_host": "db"})
    assert r.status_code == 422
    assert "host e porta" in r.get_json()["error"]


def test_test_http_sends_kind(client, login, fake):
    login(["systems.create"])
    fake.set("POST", "/systems/test", {"reachable": True, "valid_schema": True,
                                       "response_ms": 5, "checks_count": 0,
                                       "documents": []})
    r = client.post("/systems/test-heartbeat",
                    json={"kind": "http", "heartbeat_url": "http://x"})
    assert r.status_code == 200
    assert fake.sent[("POST", "/systems/test")]["kind"] == "http"


def test_test_heartbeat_backend_error(client, login, fake):
    from conftest import ApiError
    login(["systems.create"])
    fake.set("POST", "/systems/test",
             ApiError(422, "VALIDATION", "URL non valido"))
    r = client.post("/systems/test-heartbeat", json={"heartbeat_url": "http://x"})
    assert r.status_code == 422
    assert r.get_json()["error"] == "URL non valido"


def test_test_heartbeat_auth_error(client, login, fake):
    from conftest import ApiAuthError
    login(["systems.create"])
    fake.set("POST", "/systems/test", ApiAuthError(401, "AUTH", "scaduto"))
    r = client.post("/systems/test-heartbeat", json={"heartbeat_url": "http://x"})
    assert r.status_code == 401
    assert r.get_json()["ok"] is False


def test_test_heartbeat_backend_unavailable(client, login, fake):
    from conftest import ApiUnavailableError
    login(["systems.update"])
    fake.set("POST", "/systems/test", ApiUnavailableError("timeout"))
    r = client.post("/systems/test-heartbeat", json={"heartbeat_url": "http://x"})
    assert r.status_code == 503
    assert "non raggiungibile" in r.get_json()["error"]


def test_test_heartbeat_forbidden(client, login, fake):
    login(["systems.read"])  # né create né update
    r = client.post("/systems/test-heartbeat", json={"heartbeat_url": "http://x"})
    assert r.status_code == 403
