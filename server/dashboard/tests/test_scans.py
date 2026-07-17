"""Test del menu/pagina Scansioni NMAP (SICUREZZA).

Backend simulato (conftest). Copre: voce di menu condizionata al permesso, form
"Nuova scansione" (solo con scans.run), rotta proxy /scans/run (inoltro opzioni),
elenco (adattatore DataTables /dt/scans), dettaglio + polling, e le due nuove
sezioni della Guida.
"""
from __future__ import annotations


def _probes(fake):
    fake.set("GET", "/probes", {"items": [{"id": "p1", "name": "probe-milano"}]})


# -- Voce di menu (segnale affidabile: link nav href="/scans") ----------------
def test_menu_hidden_without_scan_permissions(client, login):
    login(["dashboard.read"])
    # (la Guida cita "Scansioni NMAP" nel testo: il segnale del menu e' il link)
    assert 'href="/scans"' not in client.get("/guida").get_data(as_text=True)


def test_menu_visible_with_scans_read(client, login):
    login(["scans.read"])
    assert 'href="/scans"' in client.get("/guida").get_data(as_text=True)


def test_menu_visible_with_scans_run_only(client, login):
    login(["scans.run"])
    assert 'href="/scans"' in client.get("/guida").get_data(as_text=True)


# -- Pagina elenco / form -----------------------------------------------------
def test_index_shows_form_with_run(client, login, fake):
    login(["scans.read", "scans.run"])
    _probes(fake)
    html = client.get("/scans").get_data(as_text=True)
    assert "Nuova scansione" in html
    assert 'name="target"' in html
    assert 'id="timing"' in html and 'id="technique"' in html
    assert 'name="scripts"' in html          # NSE categorie
    assert 'name="no_ping" checked' in html  # consigliato ON
    assert 'action="/scans/run"' in html
    # elenco DataTables server-side + asset locale
    assert "/dt/scans/__PID__" in html
    assert "js/pulse-scans.js" in html
    assert "probe-milano" in html            # Sonda selezionabile


def test_index_readonly_without_run(client, login, fake):
    login(["scans.read"])
    _probes(fake)
    html = client.get("/scans").get_data(as_text=True)
    assert "Avvia scansione" not in html     # niente submit del form
    assert 'action="/scans/run"' not in html
    assert 'id="scan-probe"' in html         # ma resta la scelta Sonda (lettura)
    assert "/dt/scans/__PID__" in html


def test_index_forbidden_without_read(client, login):
    login(["dashboard.read"])
    assert client.get("/scans").status_code == 403


# -- Rotta proxy /scans/run ---------------------------------------------------
def test_run_forwards_full_options(client, login, fake):
    login(["scans.run"])
    fake.set("POST", "/probes/p1/scan",
             {"scan_id": "sc1", "status": "running", "target": "10.0.0.0/24"})
    r = client.post("/scans/run", data={
        "probe_id": "p1", "target": "10.0.0.0/24", "timing": "T4",
        "technique": "syn", "ports": "22,80", "top_ports": "100",
        "version_intensity": "7", "min_rate": "50", "max_rate": "500",
        "max_retries": "2", "script_args": "http.useragent=Pulse",
        "extra": "--traceroute", "service_version": "on", "os_detection": "on",
        "no_ping": "on", "scripts": ["default", "vuln"],
        "scripts_extra": "http-title, ssl-cert"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/scans/p1/sc1")   # -> dettaglio
    sent = fake.sent[("POST", "/probes/p1/scan")]
    assert sent["target"] == "10.0.0.0/24"
    assert sent["timing"] == "T4" and sent["technique"] == "syn"
    assert sent["ports"] == "22,80" and sent["top_ports"] == 100
    assert sent["version_intensity"] == 7 and sent["min_rate"] == 50
    assert sent["max_rate"] == 500 and sent["max_retries"] == 2
    assert sent["script_args"] == "http.useragent=Pulse"
    assert sent["extra"] == "--traceroute"
    assert sent["service_version"] is True and sent["os_detection"] is True
    assert sent["no_ping"] is True
    assert sent["scripts"] == ["default", "vuln", "http-title", "ssl-cert"]


def test_run_minimal_options_skips_empty(client, login, fake):
    login(["scans.run"])
    fake.set("POST", "/probes/p1/scan", {"scan_id": "s2"})
    r = client.post("/scans/run", data={"probe_id": "p1", "target": "host",
                                        "top_ports": "notanumber"})
    assert r.status_code == 302
    sent = fake.sent[("POST", "/probes/p1/scan")]
    assert sent["target"] == "host"
    assert "ports" not in sent and "top_ports" not in sent   # invalido -> saltato
    assert sent["service_version"] is False and sent["no_ping"] is False
    assert "scripts" not in sent


def test_run_success_without_scan_id_redirects_index(client, login, fake):
    login(["scans.run"])
    fake.set("POST", "/probes/p1/scan", {"status": "running"})  # niente scan_id
    r = client.post("/scans/run", data={"probe_id": "p1", "target": "x"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/scans?probe_id=p1")


def test_run_without_probe_redirects(client, login, fake):
    login(["scans.run"])
    r = client.post("/scans/run", data={"target": "x"})
    assert r.status_code == 302
    assert ("POST", "/probes//scan") not in fake.calls


def test_run_without_target_redirects(client, login, fake):
    login(["scans.run"])
    r = client.post("/scans/run", data={"probe_id": "p1", "target": "  "})
    assert r.status_code == 302
    assert "/scans?probe_id=p1" in r.headers["Location"]
    assert ("POST", "/probes/p1/scan") not in fake.calls


def test_run_forbidden_without_run_permission(client, login):
    login(["scans.read"])
    assert client.post("/scans/run", data={"probe_id": "p1",
                                           "target": "x"}).status_code == 403


# -- Dettaglio + polling ------------------------------------------------------
def test_detail_renders_hosts_and_ports(client, login, fake):
    login(["scans.read"])
    _probes(fake)
    fake.set("GET", "/probes/p1/scan/sc1", {
        "scan_id": "sc1", "status": "done", "target": "10.0.0.5",
        "started_at": "2026-07-16T12:00:00Z", "finished_at": "2026-07-16T12:01:00Z",
        "options": {"technique": "connect"},
        "hosts": [{"ip": "10.0.0.5", "hostname": "web", "state": "up",
                   "ports": [{"port": 443, "protocol": "tcp", "state": "open",
                              "service": "https", "product": "nginx",
                              "version": "1.25",
                              "scripts": [{"id": "ssl-cert", "output": "CN=web"}]}],
                   "os": [{"name": "Linux 5.x", "accuracy": 95}],
                   "hostscripts": [{"id": "smb-os", "output": "n/a"}]}]})
    html = client.get("/scans/p1/sc1").get_data(as_text=True)
    assert "10.0.0.5" in html and "web" in html
    assert "443" in html and "https" in html and "nginx" in html
    assert "ssl-cert" in html and "CN=web" in html
    assert "Linux 5.x" in html and "95" in html
    assert "probe-milano" in html            # nome Sonda (resolver)
    assert 'data-running="false"' in html    # done -> niente poll


def test_detail_running_enables_poll_and_shows_error(client, login, fake):
    login(["scans.read"])
    _probes(fake)
    fake.set("GET", "/probes/p1/scan/sc2", {
        "scan_id": "sc2", "status": "running", "target": "10.0.0.0/24",
        "error": None, "hosts": []})
    html = client.get("/scans/p1/sc2").get_data(as_text=True)
    assert 'data-scan-poll' in html
    assert 'data-running="true"' in html
    assert "/scans/p1/sc2.json" in html      # URL di polling
    assert "js/pulse-scans.js" in html


def test_detail_shows_error(client, login, fake):
    login(["scans.read"])
    _probes(fake)
    fake.set("GET", "/probes/p1/scan/sc3", {
        "scan_id": "sc3", "status": "failed", "target": "x",
        "error": "privilegi mancanti per SYN scan", "hosts": []})
    html = client.get("/scans/p1/sc3").get_data(as_text=True)
    assert "privilegi mancanti per SYN scan" in html


def test_detail_json_status(client, login, fake):
    login(["scans.read"])
    fake.set("GET", "/probes/p1/scan/sc2", {"status": "running"})
    assert client.get("/scans/p1/sc2.json").get_json() == {"status": "running",
                                                           "running": True}
    fake.set("GET", "/probes/p1/scan/sc1", {"status": "done"})
    assert client.get("/scans/p1/sc1.json").get_json() == {"status": "done",
                                                          "running": False}


def test_detail_forbidden_without_read(client, login):
    login(["dashboard.read"])
    assert client.get("/scans/p1/sc1").status_code == 403


# -- Adattatore DataTables /dt/scans ------------------------------------------
def test_dt_scans_rows(client, login, fake):
    login(["scans.read"])
    fake.set("GET", "/probes/p1/scans", {"items": [
        {"scan_id": "sc1", "target": "10.0.0.0/24", "status": "done",
         "started_at": "2026-07-16T12:00:00Z",
         "finished_at": "2026-07-16T12:05:00Z",
         "summary": {"hosts_up": 3, "open_ports": 12}}], "total": 1})
    row = client.get("/dt/scans/p1?draw=1&start=0&length=25").get_json()["data"][0]
    assert 'badge b-ok' in row["status"]                 # done -> verde
    assert 'href="/scans/p1/sc1"' in row["target"]       # link dettaglio (probe+scan)
    assert "10.0.0.0/24" in row["target"]
    assert "3 host attivi" in row["summary"] and "12 porte aperte" in row["summary"]
    assert "16/07/2026" in row["started_at"]
    assert "bi-eye" in row["actions"]


def test_dt_scans_summary_fallback(client, login, fake):
    login(["scans.read"])
    fake.set("GET", "/probes/p1/scans", {"items": [
        {"scan_id": "s", "target": "t", "status": "running",
         "started_at": None, "finished_at": None, "summary": None}], "total": 1})
    row = client.get("/dt/scans/p1?draw=1&start=0&length=25").get_json()["data"][0]
    assert row["summary"] == "—"
    assert 'badge b-warn' in row["status"]               # running -> giallo


def test_dt_scans_forbidden(client, login):
    login(["dashboard.read"])
    assert client.get("/dt/scans/p1").status_code == 403


def test_dt_scans_unauthenticated(client):
    assert client.get("/dt/scans/p1").status_code == 401


# -- Guida: nuove sezioni -----------------------------------------------------
def test_guida_has_new_sections(client, login):
    login(["dashboard.read"])
    html = client.get("/guida").get_data(as_text=True)
    assert 'id="sec-scansioni"' in html and "Scansioni NMAP" in html
    assert 'id="sec-nominatim"' in html and "Gateway Nominatim" in html
    assert "/api/v1/nominatim/" in html
    assert "X-API-Key" in html
