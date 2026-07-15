"""Test factory app, healthz, root, error handler e login/logout (P-01)."""
from pulse_fe_common.http_client import (ApiAuthError, ApiError,
                                         ApiUnavailableError)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok"}


def test_root_anonymous_redirects_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_root_authenticated_redirects_dashboard(client, login):
    login(["dashboard.read"])
    r = client.get("/")
    assert "/dashboard" in r.headers["Location"]


def test_login_get(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert b"Accedi" in r.data


def test_login_get_when_authenticated_redirects(client, login):
    login(["dashboard.read"])
    r = client.get("/login")
    assert r.status_code == 302


def test_login_post_success(client, fake):
    fake.set("POST", "/auth/login",
             {"access_token": "a", "refresh_token": "r"})
    fake.set("GET", "/auth/me",
             {"username": "u", "permissions": ["dashboard.read"]})
    r = client.post("/login", data={"username": "u", "password": "p"})
    assert r.status_code == 302
    assert "/dashboard" in r.headers["Location"]


def test_login_post_success_with_next(client, fake):
    fake.set("POST", "/auth/login", {"access_token": "a", "refresh_token": "r"})
    fake.set("GET", "/auth/me", {"username": "u", "permissions": []})
    r = client.post("/login?next=/audit", data={"username": "u", "password": "p"})
    assert r.headers["Location"].endswith("/audit")


def test_login_post_failure(client, fake):
    fake.set("POST", "/auth/login", ApiError(401, "BAD", "credenziali"))
    r = client.post("/login", data={"username": "u", "password": "x"})
    assert r.status_code == 401
    assert b"non valide" in r.data


def test_logout(client, login, fake):
    login(["dashboard.read"])
    fake.set("POST", "/auth/logout", None)
    r = client.post("/logout")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_logout_swallows_backend_error(client, login, fake):
    login([])
    fake.set("POST", "/auth/logout", ApiUnavailableError("down"))
    r = client.post("/logout")
    assert r.status_code == 302


def test_error_handler_apierror(client, login, fake):
    login(["users.read"])
    fake.set("GET", "/users", ApiError(500, "BOOM", "errore interno"))
    r = client.get("/users")
    assert r.status_code == 500
    assert b"errore interno" in r.data


def test_error_handler_auth_error_redirects_login(client, login, fake):
    login(["users.read"])
    fake.set("GET", "/users", ApiAuthError(401, "EXP", "scaduto"))
    r = client.get("/users")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_error_handler_unavailable(client, login, fake):
    login(["users.read"])
    fake.set("GET", "/users", ApiUnavailableError("backend giù"))
    r = client.get("/users")
    assert r.status_code == 503


def test_403_handler(client, login):
    login([])  # nessun permesso
    r = client.get("/users")
    assert r.status_code == 403


def test_404_handler(client, login):
    login([])
    r = client.get("/rotta-inesistente")
    assert r.status_code == 404


def test_login_required_redirect(client):
    r = client.get("/dashboard")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]
