"""Test dell'adattatore DataTables server-side della dashboard PROBE (dt.py).

Backend probe-agent simulato da FakeApiClient (vedi conftest). Verifica il
formato DataTables, le mappature start/length->page/page_size, order->sort, i
filtri via ajax.data e la resa delle pagine con asset locali (nessun CDN).
"""
from __future__ import annotations

import pytest

_HB = {"@timestamp": "2026-07-16T12:00:00Z", "system_name": "S",
       "check_name": "C", "status": "ok", "response_ms": 5}


# -- /dt/heartbeats (dashboard Sonda) -----------------------------------------
def test_dt_heartbeats_json_shape(client, login, fake):
    login()
    fake.set("GET", "/query/heartbeats", {"items": [_HB], "total": 12})
    r = client.get("/dt/heartbeats?draw=5&start=50&length=50")
    assert r.status_code == 200
    body = r.get_json()
    assert body["draw"] == 5
    assert body["recordsTotal"] == 12 and body["recordsFiltered"] == 12
    row = body["data"][0]
    assert "16/07/2026 14:00:00" == row["@timestamp"]   # localizzato (Europe/Rome)
    assert "badge b-ok" in row["status"]
    assert row["system_name"] == "S" and row["check_name"] == "C"
    params = fake.params[("GET", "/query/heartbeats")]
    assert params["page"] == 2 and params["page_size"] == 50


def test_dt_heartbeats_sort_and_filters(client, login, fake):
    login()
    fake.set("GET", "/query/heartbeats", {"items": [], "total": 0})
    client.get("/dt/heartbeats?draw=1&start=0&length=50"
               "&order[0][column]=4&order[0][dir]=desc"
               "&columns[4][data]=response_ms&status=warn&system_id=s1")
    params = fake.params[("GET", "/query/heartbeats")]
    assert params["sort"] == "-response_ms"
    assert params["status"] == "warn" and params["system_id"] == "s1"


def test_dt_heartbeats_unauthenticated_401(client):
    assert client.get("/dt/heartbeats").status_code == 401


# -- /dt/heartbeats/system/<id> (dettaglio sistema) ---------------------------
def test_dt_heartbeats_system_forwards_system_id(client, login, fake):
    login()
    fake.set("GET", "/query/heartbeats", {"items": [_HB], "total": 1})
    r = client.get("/dt/heartbeats/system/s1?draw=1&start=0&length=50"
                   "&from=a&to=b")
    assert r.status_code == 200
    # la colonna Sistema non e' presente nel dettaglio sistema
    assert "system_name" not in r.get_json()["data"][0]
    params = fake.params[("GET", "/query/heartbeats")]
    assert params["system_id"] == "s1"
    assert params["from"] == "a" and params["to"] == "b"


def test_dt_heartbeats_system_unauthenticated_401(client):
    assert client.get("/dt/heartbeats/system/s1").status_code == 401


def test_table_meta_unknown_raises():
    import dt as dt_adapter
    with pytest.raises(KeyError):
        dt_adapter.table_meta("nope")


def test_paging_fallback_on_invalid_params(client, login, fake):
    """?page/?page_size non numerici: la view non va in errore (ripiego)."""
    login()
    fake.set("GET", "/status", {"opensearch_healthy": True, "version": "1.0"})
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", {"items": [], "total": 0})
    assert client.get("/dashboard?page=abc&page_size=xyz").status_code == 200


# -- Pagine: init DataTables + asset locali (no CDN) --------------------------
def test_dashboard_page_has_datatable_and_local_assets(client, login, fake):
    login()
    fake.set("GET", "/status", {"opensearch_healthy": True, "version": "1.0"})
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", {"items": [], "total": 0})
    html = client.get("/dashboard").get_data(as_text=True)
    assert "PulseDT.init" in html
    assert "/dt/heartbeats" in html
    assert "vendor/jquery/jquery.min.js" in html
    assert "vendor/datatables/js/dataTables.min.js" in html
    assert "vendor/datatables/css/dataTables.bootstrap5.min.css" in html
    assert "cdn.datatables.net" not in html and "code.jquery.com" not in html


def test_system_detail_page_datatable_with_window(client, login, fake):
    login()
    fake.set("GET", "/query/heartbeats", {"items": [], "total": 0})
    fake.set("POST", "/query", {"items": [], "aggregations": {"uptime": 99}})
    html = client.get("/systems/s1?from=x&to=y").get_data(as_text=True)
    assert "PulseDT.init" in html
    assert "/dt/heartbeats/system/s1" in html
    # la finestra temporale corrente e' passata ad ajax.data
    assert 'd.from = "x"' in html and 'd.to = "y"' in html
