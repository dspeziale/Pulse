"""Test area Auth (§1.1) e dependency RBAC."""

from __future__ import annotations


def test_login_success(client) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "ChangeMe123!"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["username"] == "admin"
    assert "SuperAdmin" in data["user"]["roles"]
    assert "users.read" in data["user"]["permissions"]


def test_login_wrong_password(client) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_login_unknown_user(client) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401


def test_login_lockout_after_threshold(client) -> None:
    # crea un utente dedicato e lo blocca superando la soglia
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "ChangeMe123!"}
    ).json()
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "lockme",
            "email": "lockme@example.com",
            "full_name": "Lock Me",
            "password": "Password123!",
            "role_ids": [],
            "status": "active",
        },
    )
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "lockme", "password": "bad"})
    # ora l'account e' locked -> 401 anche con password giusta? no: status locked => forbidden path
    resp = client.post("/api/v1/auth/login", json={"username": "lockme", "password": "Password123!"})
    assert resp.status_code == 403


def test_me_and_change_password(client, auth_headers) -> None:
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"

    # cambio password sbagliata
    bad = client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers,
        json={"current_password": "wrong", "new_password": "NewPassw0rd!"},
    )
    assert bad.status_code == 400

    ok = client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers,
        json={"current_password": "ChangeMe123!", "new_password": "NewPassw0rd!"},
    )
    assert ok.status_code == 204


def test_refresh_and_logout(client) -> None:
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "ChangeMe123!"}
    ).json()
    refresh = login["refresh_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200
    assert r.json()["access_token"]

    headers = {"Authorization": f"Bearer {login['access_token']}"}
    logout = client.post("/api/v1/auth/logout", headers=headers, json={"refresh_token": refresh})
    assert logout.status_code == 204

    # dopo il logout il refresh e' revocato
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


def test_refresh_invalid_token(client) -> None:
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-token"})
    assert r.status_code == 401


def test_missing_bearer_is_401(client) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_malformed_bearer_is_401(client) -> None:
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_non_access_token_rejected(client) -> None:
    from pulse_server.config import get_settings
    from pulse_server.security import create_access_token

    settings = get_settings()
    tok = create_access_token(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        subject="00000000-0000-0000-0000-0000000000a1",
        ttl_seconds=60,
        roles=[],
        permissions=[],
        extra={"type": "refresh"},
    )
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_forbidden_without_permission(client) -> None:
    # crea utente viewer, il quale non ha users.read
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "ChangeMe123!"}
    ).json()
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    viewer_role = "00000000-0000-0000-0000-000000000004"
    client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "viewer1",
            "email": "viewer1@example.com",
            "full_name": "Viewer",
            "password": "Password123!",
            "role_ids": [viewer_role],
            "status": "active",
        },
    )
    vtok = client.post(
        "/api/v1/auth/login", json={"username": "viewer1", "password": "Password123!"}
    ).json()["access_token"]
    r = client.get("/api/v1/users", headers={"Authorization": f"Bearer {vtok}"})
    assert r.status_code == 403
