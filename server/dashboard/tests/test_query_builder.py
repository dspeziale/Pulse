"""Test della ricerca guidata P-04 (Interrogazione dati piu' friendly).

Copre: helper dei preset di periodo, rendering dei filtri guidati + init
DataTables server-side dei risultati, proxy /checks-by-system per il <select>
Check, e la colonna Messaggio negli heartbeat. Backend simulato (conftest).
"""
from __future__ import annotations

from datetime import datetime, timezone


# -- Helper preset di periodo -------------------------------------------------
def test_time_presets_keys_and_today_midnight():
    from views.query import time_presets
    # 2026-07-16 15:30Z -> Europe/Rome (estate, +02:00) = 17:30 locali.
    now = datetime(2026, 7, 16, 15, 30, 0, tzinfo=timezone.utc)
    presets, offset = time_presets("Europe/Rome", now=now)
    assert set(presets) == {"last_hour", "today", "last_24h", "last_7d",
                            "last_30d"}
    for p in presets.values():
        assert p["from"].endswith("Z") and p["to"].endswith("Z")
    # "Oggi" parte dalla mezzanotte locale: 2026-07-16 00:00+02:00 = 15/07 22:00Z
    assert presets["today"]["from"] == "2026-07-15T22:00:00Z"
    assert presets["today"]["to"] == "2026-07-16T15:30:00Z"
    assert presets["last_hour"]["from"] == "2026-07-16T14:30:00Z"
    assert offset == 120


def test_time_presets_invalid_tz_falls_back():
    from views.query import time_presets
    now = datetime(2026, 1, 16, 12, 0, 0, tzinfo=timezone.utc)  # inverno
    presets, offset = time_presets("Pinco/Pallino", now=now)  # -> Europe/Rome
    assert offset == 60  # Europe/Rome inverno +01:00
    assert presets["today"]["from"] == "2026-01-15T23:00:00Z"


# -- Pagina: filtri guidati + init DataTables risultati -----------------------
def _prep_builder(fake):
    fake.set("GET", "/probes", {"items": [{"id": "p1", "name": "Sonda 1"}]})


def test_builder_renders_guided_filters(client, login, fake):
    login(["heartbeats.query"])
    _prep_builder(fake)
    html = client.get("/query").get_data(as_text=True)
    # contenitore app + proxy/URL
    assert "data-query-app" in html
    assert "/systems-by-probe" in html
    assert "/checks-by-system" in html
    assert "/dt/heartbeats/__PID__" in html
    assert 'data-tz-offset=' in html
    # controlli guidati
    for cid in ("q-probe", "q-system", "q-check", "q-status", "q-preset",
                "q-only-problems", "q-results"):
        assert 'id="%s"' % cid in html
    # preset di default = Oggi
    assert '<option value="today" selected>Oggi</option>' in html
    # preset e colonne serializzati per il JS
    assert 'id="q-presets"' in html and 'id="q-columns"' in html
    # tabella risultati DataTables + script guidato
    assert "PulseDT.init" not in html  # l'init dei risultati e' in pulse-query.js
    assert "js/pulse-query.js" in html
    # colonna Messaggio negli heartbeat
    assert ">Messaggio<" in html


def test_builder_keeps_advanced_form(client, login, fake):
    """La query strutturata (JSON) resta disponibile nella sezione Avanzato."""
    login(["heartbeats.query"])
    _prep_builder(fake)
    html = client.get("/query").get_data(as_text=True)
    assert "advanced-query" in html and "data-bs-toggle=\"collapse\"" in html
    assert 'name="filters"' in html and 'name="aggregations"' in html
    assert 'data-probe-source' in html
    assert 'id="probe-systems-list"' in html
    assert "js/pulse-systems.js" in html


def test_builder_preselected_probe_loads_systems(client, login, fake):
    login(["heartbeats.query"])
    _prep_builder(fake)
    fake.set("GET", "/systems", {"items": [{"id": "s", "system_id": "sys-1",
                                            "system_name": "CRM"}]})
    fake.set("GET", "/systems/sys-1/checks", {"items": []})
    r = client.get("/query?probe_id=p1&system_id=sys-1")
    assert r.status_code == 200


# -- Proxy /checks-by-system --------------------------------------------------
def test_checks_by_system_returns_items(client, login, fake):
    login(["heartbeats.query"])
    fake.set("GET", "/checks", {"items": [
        {"check_id": "db", "check_name": "Database", "extra": "ignored"},
        {"check_id": "api", "check_name": "API"},
    ]})
    r = client.get("/checks-by-system?system_id=sys-1&probe_id=p1")
    assert r.status_code == 200
    assert r.get_json()["items"] == [
        {"check_id": "db", "check_name": "Database"},
        {"check_id": "api", "check_name": "API"},
    ]
    # system_id (+ probe_id) inoltrati al backend
    params = fake.params[("GET", "/checks")]
    assert params["system_id"] == "sys-1" and params["probe_id"] == "p1"


def test_checks_by_system_without_probe(client, login, fake):
    login(["heartbeats.query"])
    fake.set("GET", "/checks", {"items": []})
    r = client.get("/checks-by-system?system_id=sys-1")
    assert r.status_code == 200
    assert "probe_id" not in fake.params[("GET", "/checks")]


def test_checks_by_system_empty_without_system(client, login, fake):
    login(["heartbeats.query"])
    r = client.get("/checks-by-system")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}
    assert ("GET", "/checks") not in fake.calls


def test_checks_by_system_backend_error_is_silent(client, login, fake):
    from conftest import ApiError
    login(["heartbeats.query"])
    fake.set("GET", "/checks", ApiError(403, "FORBIDDEN", "no checks.read"))
    r = client.get("/checks-by-system?system_id=sys-1")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}


def test_checks_by_system_non_dict_backend(client, login, fake):
    login(["heartbeats.query"])
    fake.set("GET", "/checks", ["unexpected"])
    r = client.get("/checks-by-system?system_id=sys-1")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}


def test_checks_by_system_forbidden(client, login):
    login(["dashboard.read"])
    assert client.get("/checks-by-system?system_id=sys-1").status_code == 403


# -- Heartbeat: colonna Messaggio nell'adattatore -----------------------------
def test_heartbeats_adapter_includes_message(client, login, fake):
    login(["heartbeats.read"])
    fake.set("GET", "/probes/1/heartbeats", {"items": [
        {"@timestamp": "2026-07-16T12:00:00Z", "system_name": "S",
         "check_name": "C", "status": "error", "response_ms": 9,
         "message": "timeout"},
        {"@timestamp": "2026-07-16T12:01:00Z", "system_name": "S",
         "check_name": "C", "status": "ok", "response_ms": 3},
    ], "total": 2})
    rows = client.get("/dt/heartbeats/1?draw=1&start=0&length=50").get_json()["data"]
    assert rows[0]["message"] == "timeout"
    assert rows[1]["message"] == ""   # messaggio assente -> stringa vuota
