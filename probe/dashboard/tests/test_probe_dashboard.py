"""Test della dashboard PROBE: app, login locale, viste PP-01..PP-05."""
from pulse_fe_common.http_client import (ApiAuthError, ApiError,
                                         ApiUnavailableError)


# -- App / infrastruttura -----------------------------------------------------
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_session_cookie_config(app):
    # Nome cookie distinto da quello del Server + attributi di sessione sicuri.
    assert app.config["SESSION_COOKIE_NAME"] == "pulse_probe_session"
    assert app.config["SESSION_COOKIE_NAME"] != "pulse_server_session"
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_root_anonymous_redirects_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_root_authenticated_redirects_dashboard(client, login):
    login()
    assert "/dashboard" in client.get("/").headers["Location"]


def test_404_handler(client, login):
    login()
    assert client.get("/inesistente").status_code == 404


def test_login_required_redirect(client):
    r = client.get("/dashboard")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


# -- PP-01 Login locale -------------------------------------------------------
def test_login_get(client):
    assert client.get("/login").status_code == 200


def test_login_get_authenticated_redirects(client, login):
    login()
    assert client.get("/login").status_code == 302


def test_login_success(client):
    r = client.post("/login", data={"username": "probe", "password": "secret"})
    assert r.status_code == 302
    assert "/dashboard" in r.headers["Location"]


def test_login_success_with_next(client):
    r = client.post("/login?next=/status",
                    data={"username": "probe", "password": "secret"})
    assert r.headers["Location"].endswith("/status")


def test_login_failure(client):
    r = client.post("/login", data={"username": "probe", "password": "wrong"})
    assert r.status_code == 401
    with client.session_transaction() as s:
        assert "probe_user" not in s


def test_login_page_preserves_flash_error(client):
    with client.session_transaction() as s:
        s["_flashes"] = [("danger", "Credenziali locali non valide.")]
    r = client.get("/login")
    assert r.status_code == 200
    assert b"Credenziali locali non valide." in r.data
    assert b'class="alert alert-danger' in r.data


def test_login_page_hides_success_and_info_flash(client):
    with client.session_transaction() as s:
        s["_flashes"] = [("success", "Disconnesso."),
                         ("info", "Nota informativa.")]
    r = client.get("/login")
    assert r.status_code == 200
    assert b"Disconnesso." not in r.data
    assert b"Nota informativa." not in r.data
    assert b'class="alert alert-success' not in r.data
    with client.session_transaction() as s:
        assert not s.get("_flashes")


def test_logout_then_login_has_no_success_banner(client, login):
    login()
    client.post("/logout")  # flasha "Disconnesso." (success)
    r = client.get("/login")
    assert r.status_code == 200
    assert b"Disconnesso." not in r.data
    assert b'class="alert alert-success' not in r.data


def test_internal_pages_have_no_flash_banner(client, login, fake):
    login()
    fake.set("GET", "/status", {"opensearch_healthy": True, "version": "1.0"})
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", {"items": []})
    with client.session_transaction() as s:
        s["_flashes"] = [("success", "Operazione completata.")]
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert b"Operazione completata." not in r.data
    assert b'class="alert alert-' not in r.data
    with client.session_transaction() as s:
        assert not s.get("_flashes")


def test_logout(client, login):
    login()
    r = client.post("/logout")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


# -- PP-02 Dashboard / PP-03 dettaglio ---------------------------------------
def test_dashboard_index(client, login, fake):
    login()
    fake.set("GET", "/status", {"opensearch_healthy": True, "version": "1.0",
                                "systems_polled": 2})
    fake.set("GET", "/systems", {"items": [{"system_id": "s1", "system_name": "S",
                                            "enabled": True}]})
    fake.set("GET", "/query/heartbeats", {"items": []})
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert b"Dashboard Probe" in r.data


def test_dashboard_localizes_heartbeat_timestamp(client, login, fake):
    # Il fuso della Sonda arriva da env (default Europe/Rome nel cfg di test):
    # 12:00 UTC estate -> 14:00 locali. La tabella heartbeat e' ora DataTables
    # server-side: la data localizzata compare nel JSON dell'adattatore /dt.
    login()
    fake.set("GET", "/query/heartbeats",
             {"items": [{"@timestamp": "2026-07-16T12:00:00Z", "system_name": "s",
                         "check_name": "c", "status": "ok", "response_ms": 5}],
              "total": 1})
    r = client.get("/dt/heartbeats?draw=1&start=0&length=50")
    assert r.status_code == 200
    body = r.get_json()
    assert body["data"][0]["@timestamp"] == "16/07/2026 14:00:00"


def test_dashboard_timezone_from_env(monkeypatch):
    # Con PULSE_PROBE_TIMEZONE=UTC il filtro non converte (12:00 resta 12:00).
    monkeypatch.setenv("PULSE_PROBE_TIMEZONE", "UTC")
    import app as app_module
    from pulse_fe_common.config import ProbeDashboardConfig
    from tests.conftest import FakeApiClient

    application = app_module.create_app(ProbeDashboardConfig.from_env())
    application.config["TESTING"] = True
    fake = FakeApiClient()
    fake.set("GET", "/query/heartbeats",
             {"items": [{"@timestamp": "2026-07-16T12:00:00Z", "system_name": "s",
                         "check_name": "c", "status": "ok", "response_ms": 5}],
              "total": 1})
    application.config["API_CLIENT"] = fake
    c = application.test_client()
    with c.session_transaction() as s:
        s["probe_user"] = "probe"
    r = c.get("/dt/heartbeats?draw=1&start=0&length=50")
    body = r.get_json()
    assert body["data"][0]["@timestamp"] == "16/07/2026 12:00:00"


def test_dashboard_index_with_query_params(client, login, fake):
    login()
    fake.set("GET", "/status", {"opensearch_healthy": True, "version": "1.0"})
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", {"items": []})
    r = client.get("/dashboard?system_id=s1&status=ok&page=1&page_size=5")
    assert r.status_code == 200


def test_system_detail(client, login, fake):
    login()
    fake.set("GET", "/query/heartbeats", {"items": []})
    fake.set("POST", "/query", {"items": [], "aggregations": {"uptime": 99}})
    r = client.get("/systems/s1?from=a&to=b")
    assert r.status_code == 200


# -- PP-04 Query diretta ------------------------------------------------------
def test_query_builder_get(client, login):
    login()
    assert client.get("/query").status_code == 200


def test_query_run_success(client, login, fake):
    login()
    fake.set("POST", "/query", {"items": [], "aggregations": {}, "total": 0})
    r = client.post("/query", data={"filters": "[]", "aggregations": "[]",
                                    "from": "", "to": ""})
    assert r.status_code == 200


def test_query_run_empty_json_defaults(client, login, fake):
    login()
    fake.set("POST", "/query", {"items": [], "aggregations": {}, "total": 0})
    r = client.post("/query", data={"filters": "", "aggregations": "",
                                    "from": "", "to": ""})
    assert r.status_code == 200


def test_query_run_invalid_json(client, login):
    login()
    r = client.post("/query", data={"filters": "{bad"})
    assert r.status_code == 302


# -- PP-05 Stato / salute -----------------------------------------------------
def test_status_ready_ok(client, login, fake):
    login()
    fake.set("GET", "/status", {"version": "1.0"})
    fake.set("GET", "/health/ready", {"status": "ready"})
    r = client.get("/status")
    assert r.status_code == 200
    assert b"ready" in r.data


def test_status_ready_unavailable_fallback(client, login, fake):
    login()
    fake.set("GET", "/status", {"version": "1.0"})
    fake.set("GET", "/health/ready", ApiUnavailableError("os giù"))
    r = client.get("/status")
    assert r.status_code == 200
    assert b"not-ready" in r.data


def test_status_ready_apierror_fallback(client, login, fake):
    login()
    fake.set("GET", "/status", {"version": "1.0"})
    fake.set("GET", "/health/ready", ApiError(503, "X", "non pronto"))
    r = client.get("/status")
    assert r.status_code == 200
    assert b"not-ready" in r.data


# -- Error handler probe-agent ------------------------------------------------
def test_error_handler_apierror(client, login, fake):
    login()
    fake.set("GET", "/status", ApiError(500, "BOOM", "errore agent"))
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", {"items": []})
    r = client.get("/dashboard")
    assert r.status_code == 500
    assert b"errore agent" in r.data


def test_error_handler_auth_error(client, login, fake):
    login()
    fake.set("GET", "/status", ApiAuthError(401, "EXP", "token errato"))
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", {"items": []})
    r = client.get("/dashboard")
    assert r.status_code == 401


def test_error_handler_unavailable(client, login, fake):
    login()
    fake.set("GET", "/status", ApiUnavailableError("agent giù"))
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", {"items": []})
    r = client.get("/dashboard")
    assert r.status_code == 503
