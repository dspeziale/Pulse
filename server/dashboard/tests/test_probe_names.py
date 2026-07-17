"""Test del resolver probe_id -> nome (probesource) e della resa del NOME Sonda.

Ovunque si referenzia una Sonda si mostra il nome, non il codice; gli URL
continuano a usare il probe_id. Backend simulato (conftest).
"""
from __future__ import annotations

import probesource


# -- Unita': resolver ---------------------------------------------------------
class _FakeClient:
    def __init__(self, items, exc=None):
        self._items = items
        self._exc = exc
        self.params = None

    def get(self, path, token=None, params=None):
        self.params = params
        if self._exc:
            raise self._exc
        return {"items": self._items}


def test_fetch_probe_names_builds_map():
    c = _FakeClient([{"id": "a", "name": "probe-locale-01"},
                     {"id": "b", "name": "probe-milano"}])
    names = probesource.fetch_probe_names(c, "tok")
    assert names == {"a": "probe-locale-01", "b": "probe-milano"}
    # la lista e' richiesta con page_size ampio per risolvere tutte le Sonde
    assert c.params == {"page_size": probesource.MAX_PROBES}


def test_fetch_probe_names_skips_missing_id_and_defaults_name():
    c = _FakeClient([{"id": None, "name": "x"}, {"id": "b"}])
    names = probesource.fetch_probe_names(c, "tok")
    assert names == {"b": "b"}   # id senza name -> name = id


def test_resolve_probe_names_cache_hit():
    cache = {"value": {"a": "cached"}, "exp": 100.0}
    calls = []

    def fetch():
        calls.append(1)
        return {"a": "fresh"}

    out = probesource.resolve_probe_names(cache, fetch, ttl=60, now=50.0)
    assert out == {"a": "cached"} and calls == []   # non scaduta -> nessun fetch


def test_resolve_probe_names_fetches_and_caches():
    cache = {"value": {}, "exp": 0.0}
    out = probesource.resolve_probe_names(cache, lambda: {"a": "n"}, ttl=60,
                                          now=10.0)
    assert out == {"a": "n"}
    assert cache["value"] == {"a": "n"} and cache["exp"] == 70.0


def test_resolve_probe_names_error_falls_back_empty():
    cache = {"value": {}, "exp": 0.0}

    def boom():
        raise RuntimeError("backend giu'")

    assert probesource.resolve_probe_names(cache, boom, now=1.0) == {}


def test_probe_name_lookup_and_fallback():
    names = {"a": "probe-locale-01"}
    assert probesource.probe_name(names, "a") == "probe-locale-01"
    assert probesource.probe_name(names, "sconosciuto") == "sconosciuto"
    assert probesource.probe_name(names, None) == "—"
    assert probesource.probe_name(names, "") == "—"


# -- Filtro Jinja probe_name integrato ----------------------------------------
def test_probe_name_filter_resolves(app):
    with app.test_request_context("/"):
        app.config["PROBE_CACHE"] = {"value": {"a": "probe-locale-01"},
                                     "exp": 9e18}
        out = app.jinja_env.filters["probe_name"]("a")
    assert out == "probe-locale-01"


# -- DataTables: colonna Sonda mostra il NOME (sistemi/allarmi) ----------------
def test_dt_systems_probe_column_shows_name(client, login, fake):
    login(["systems.read"])
    fake.set("GET", "/probes", {"items": [{"id": "p1", "name": "probe-milano"}]})
    fake.set("GET", "/systems", {"items": [
        {"id": "1", "system_id": "s1", "system_name": "S", "kind": "http",
         "heartbeat_url": "http://x", "probe_id": "p1", "enabled": True}],
        "total": 1})
    row = client.get("/dt/systems?draw=1&start=0&length=25").get_json()["data"][0]
    assert row["probe_id"] == "probe-milano"   # NOME, non il codice p1


def test_dt_systems_probe_column_fallback_to_id(client, login, fake):
    login(["systems.read"])
    fake.set("GET", "/probes", {"items": []})   # mappa vuota -> fallback all'id
    fake.set("GET", "/systems", {"items": [
        {"id": "1", "system_id": "s1", "system_name": "S", "kind": "http",
         "heartbeat_url": "http://x", "probe_id": "p1", "enabled": True}],
        "total": 1})
    row = client.get("/dt/systems?draw=1&start=0&length=25").get_json()["data"][0]
    assert row["probe_id"] == "p1"


def test_dt_alarms_probe_column_shows_name(client, login, fake):
    login(["workflows.read"])
    fake.set("GET", "/probes", {"items": [{"id": "p1", "name": "probe-milano"}]})
    fake.set("GET", "/alarms", {"items": [
        {"id": "1", "system_id": "s1", "probe_id": "p1", "status": "active",
         "opened_at": "2026-07-16T12:00:00Z"}], "total": 1})
    row = client.get("/dt/alarms?draw=1&start=0&length=25").get_json()["data"][0]
    assert row["probe_id"] == "probe-milano"


# -- Template: nome come testo, probe_id nell'URL -----------------------------
def test_systems_detail_shows_name_keeps_id_in_url(client, login, fake):
    login(["systems.read", "probes.read"])
    fake.set("GET", "/probes", {"items": [{"id": "p1", "name": "probe-milano"}]})
    fake.set("GET", "/systems/1", {"id": "1", "system_name": "S", "kind": "http",
                                   "probe_id": "p1", "thresholds": {}})
    fake.set("GET", "/systems/1/checks", {"items": []})
    html = client.get("/systems/1").get_data(as_text=True)
    assert ">probe-milano</a>" in html            # testo = nome
    assert 'href="/probes/p1"' in html            # URL = probe_id


def test_dashboard_probe_rows_show_name(client, login, fake):
    login(["dashboard.read"])
    fake.set("GET", "/dashboard/aggregate", {
        "systems_summary": {"ok": 1, "warn": 0, "error": 0, "down": 0,
                            "unknown": 0},
        "active_alarms": 0,
        "probes": [{"probe_id": "p1", "status": "online", "systems_total": 3,
                    "systems_down": 0}]})
    fake.set("GET", "/probes", {"items": [{"id": "p1", "name": "probe-milano"}]})
    fake.set("GET", "/alarms", {"items": []})
    html = client.get("/dashboard").get_data(as_text=True)
    assert "probe-milano" in html                 # nome mostrato
    assert 'href="/probes/p1' in html             # URL con probe_id
