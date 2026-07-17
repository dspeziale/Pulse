"""Test della normalizzazione fuso orario (dashboard SERVER).

Copre: la sorgente del fuso (tzsource, config + cache TTL), il filtro Jinja
``localdt`` applicato in una pagina reale, e la UI di selezione del fuso.
"""
from tzsource import (DEFAULT_TTL, fetch_config_timezone, resolve_timezone)


# -- tzsource.resolve_timezone (cache TTL) ------------------------------------
def _no_fetch():
    raise AssertionError("fetch non deve essere chiamata su cache valida")


def test_resolve_cache_hit():
    cache = {"value": "UTC", "exp": 100.0}
    assert resolve_timezone(cache, _no_fetch, now=50.0) == "UTC"


def test_resolve_fetch_value_and_sets_expiry():
    cache = {}
    assert resolve_timezone(cache, lambda: "America/New_York", now=0.0) == "America/New_York"
    assert cache["value"] == "America/New_York"
    assert cache["exp"] == DEFAULT_TTL


def test_resolve_fetch_none_falls_back_default():
    cache = {}
    assert resolve_timezone(cache, lambda: None, now=0.0) == "Europe/Rome"


def test_resolve_fetch_raises_falls_back_default():
    def boom():
        raise RuntimeError("backend giù")

    assert resolve_timezone({}, boom, now=0.0) == "Europe/Rome"


# -- tzsource.fetch_config_timezone -------------------------------------------
class _Client:
    def __init__(self, payload):
        self._payload = payload

    def get(self, path, token=None):
        assert path == "/config"
        return self._payload


def test_fetch_config_timezone_found():
    c = _Client({"items": [{"key": "api_port", "value": "8000"},
                           {"key": "timezone", "value": "UTC"}]})
    assert fetch_config_timezone(c, "tok") == "UTC"


def test_fetch_config_timezone_absent():
    c = _Client({"items": [{"key": "api_port", "value": "8000"}]})
    assert fetch_config_timezone(c, "tok") is None


def test_fetch_config_timezone_no_items():
    assert fetch_config_timezone(_Client({}), "tok") is None


# -- Filtro localdt in una pagina reale (dashboard) ---------------------------
def _dash(fake, tz, opened="2026-07-16T12:00:00Z"):
    fake.set("GET", "/dashboard/aggregate",
             {"systems_summary": {"ok": 1, "warn": 0, "error": 0, "down": 0,
                                  "unknown": 0}, "active_alarms": 0, "probes": []})
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/alarms",
             {"items": [{"system_id": "s1", "status": "error", "opened_at": opened}]})
    fake.set("GET", "/config", {"items": [{"key": "timezone", "value": tz}]})


def test_dashboard_timestamp_in_utc(client, login, fake):
    login(["dashboard.read"])
    _dash(fake, "UTC")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert b"16/07/2026 12:00:00" in r.data


def test_dashboard_timestamp_in_rome(client, login, fake):
    login(["dashboard.read"])
    _dash(fake, "Europe/Rome")
    r = client.get("/dashboard")
    # 12:00 UTC estate -> 14:00 Europe/Rome.
    assert b"16/07/2026 14:00:00" in r.data


def test_dashboard_timestamp_in_new_york(client, login, fake):
    login(["dashboard.read"])
    _dash(fake, "America/New_York")
    r = client.get("/dashboard")
    # 12:00 UTC luglio -> 08:00 EDT.
    assert b"16/07/2026 08:00:00" in r.data


def test_dashboard_timestamp_default_when_config_missing(client, login, fake):
    # Nessun /config registrato: ripiego su Europe/Rome senza errori.
    login(["dashboard.read"])
    fake.set("GET", "/dashboard/aggregate",
             {"systems_summary": {"ok": 0, "warn": 0, "error": 0, "down": 0,
                                  "unknown": 0}, "active_alarms": 0, "probes": []})
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/alarms",
             {"items": [{"system_id": "s1", "status": "error",
                         "opened_at": "2026-07-16T12:00:00Z"}]})
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert b"16/07/2026 14:00:00" in r.data  # Europe/Rome di default


# -- UI selezione fuso orario -------------------------------------------------
def test_config_timezone_select(client, login, fake):
    login(["config.read", "config.update"])
    fake.set("GET", "/config", {"items": [
        {"key": "timezone", "value": "Europe/Rome", "type": "str"},
        {"key": "api_port", "value": "8000", "type": "int"},
    ]})
    r = client.get("/config")
    assert r.status_code == 200
    assert b"Localizzazione" in r.data
    assert b'name="value:timezone"' in r.data
    assert b'value="UTC"' in r.data
    assert b'value="Europe/Rome" selected' in r.data


def test_config_timezone_custom_value_included(client, login, fake):
    login(["config.read"])
    fake.set("GET", "/config", {"items": [
        {"key": "timezone", "value": "Asia/Kolkata", "type": "str"},
    ]})
    r = client.get("/config")
    assert b'<option value="Asia/Kolkata" selected>Asia/Kolkata</option>' in r.data
