"""Test della ricerca guidata PP-04 (Interrogazione diretta Sonda friendly).

Copre: rendering dei filtri guidati + init DataTables server-side dei risultati,
proxy /checks-by-system (check distinti ricavati da uno scan documenti, la Sonda
non ha ne' /systems/{id}/checks ne' aggregazione terms), preset di periodo
(default Oggi) e la colonna Messaggio negli heartbeat. Backend simulato.
"""
from __future__ import annotations

from pulse_fe_common.http_client import ApiError


def _prep(fake):
    fake.set("GET", "/systems", {"items": [
        {"system_id": "sys-1", "system_name": "CRM", "enabled": True},
        {"system_id": "sys-2", "system_name": "ERP", "enabled": True},
    ]})


# -- Pagina: filtri guidati + init DataTables risultati -----------------------
def test_builder_renders_guided_filters(client, login, fake):
    login()
    _prep(fake)
    html = client.get("/query").get_data(as_text=True)
    assert "data-query-app" in html
    assert "/checks-by-system" in html
    assert "/dt/heartbeats" in html
    assert "data-tz-offset=" in html
    for cid in ("q-system", "q-check", "q-status", "q-preset",
                "q-only-problems", "q-results"):
        assert 'id="%s"' % cid in html
    # sistemi resi lato server nel <select>
    assert 'value="sys-1"' in html and "CRM" in html
    # check come input+datalist (suggerimenti + testo libero)
    assert 'list="q-check-options"' in html and 'id="q-check-options"' in html
    # preset di default = Oggi
    assert '<option value="today" selected>Oggi</option>' in html
    assert 'id="q-presets"' in html and 'id="q-columns"' in html
    assert "js/pulse-query.js" in html
    assert ">Messaggio<" in html


def test_builder_keeps_advanced_form(client, login, fake):
    login()
    _prep(fake)
    html = client.get("/query").get_data(as_text=True)
    assert "advanced-query" in html and 'data-bs-toggle="collapse"' in html
    assert 'name="filters"' in html and 'name="aggregations"' in html


def test_builder_presets_default_today(client, login, fake):
    import json
    import re
    login()
    _prep(fake)
    html = client.get("/query").get_data(as_text=True)
    m = re.search(r'id="q-presets"[^>]*>(.*?)</script>', html, re.S)
    presets = json.loads(m.group(1))
    assert set(presets) == {"last_hour", "today", "last_24h", "last_7d",
                            "last_30d"}
    for p in presets.values():
        assert p["from"].endswith("Z") and p["to"].endswith("Z")


# -- Proxy /checks-by-system (scan documenti, dedup) --------------------------
def test_checks_by_system_distinct(client, login, fake):
    login()
    fake.set("POST", "/query", {"items": [
        {"check_id": "db", "check_name": "Database"},
        {"check_id": "db", "check_name": "Database"},   # duplicato
        {"check_id": "api", "check_name": "API"},
        {"check_id": None, "check_name": "ignorato"},    # senza check_id
    ], "total": 4})
    r = client.get("/checks-by-system?system_id=sys-1")
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert {"check_id": "db", "check_name": "Database"} in items
    assert {"check_id": "api", "check_name": "API"} in items
    assert len(items) == 2   # distinti, senza il doc privo di check_id
    # lo scan filtra per system_id ed e' limitato (page_size)
    body = fake.sent[("POST", "/query")]
    assert body["filters"] == [{"field": "system_id", "op": "eq",
                                "value": "sys-1"}]
    assert body["from"].endswith("Z") and body["to"].endswith("Z")
    assert body["page_size"] == 1000


def test_checks_by_system_empty_without_system(client, login, fake):
    login()
    r = client.get("/checks-by-system")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}
    assert ("POST", "/query") not in fake.calls


def test_checks_by_system_backend_error_is_silent(client, login, fake):
    login()
    fake.set("POST", "/query", ApiError(500, "BOOM", "store giu'"))
    r = client.get("/checks-by-system?system_id=sys-1")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}


def test_checks_by_system_non_dict_backend(client, login, fake):
    login()
    fake.set("POST", "/query", ["unexpected"])
    r = client.get("/checks-by-system?system_id=sys-1")
    assert r.status_code == 200
    assert r.get_json() == {"items": []}


def test_checks_by_system_requires_login(client):
    r = client.get("/checks-by-system?system_id=sys-1")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


# -- run_query (avanzato) continua a funzionare -------------------------------
def test_run_query_still_renders_guided(client, login, fake):
    login()
    _prep(fake)
    fake.set("POST", "/query", {"items": [], "aggregations": {}, "total": 0})
    r = client.post("/query", data={"filters": "[]", "aggregations": "[]",
                                    "from": "", "to": ""})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "data-query-app" in html and "js/pulse-query.js" in html


# -- Heartbeat: colonna Messaggio nell'adattatore Sonda -----------------------
def test_heartbeats_adapter_includes_message(client, login, fake):
    login()
    fake.set("GET", "/query/heartbeats", {"items": [
        {"@timestamp": "2026-07-16T12:00:00Z", "system_name": "S",
         "check_name": "C", "status": "error", "response_ms": 9,
         "message": "timeout"},
        {"@timestamp": "2026-07-16T12:01:00Z", "system_name": "S",
         "check_name": "C", "status": "ok", "response_ms": 3},
    ], "total": 2})
    rows = client.get("/dt/heartbeats?draw=1&start=0&length=50").get_json()["data"]
    assert rows[0]["message"] == "timeout"
    assert rows[1]["message"] == ""
