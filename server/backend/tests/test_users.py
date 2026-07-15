"""Test area Utenti (§1.2)."""

from __future__ import annotations

SUPERADMIN_ROLE = "00000000-0000-0000-0000-000000000001"
OPERATOR_ROLE = "00000000-0000-0000-0000-000000000003"
ADMIN_ID = "00000000-0000-0000-0000-0000000000a1"


def _create(client, headers, **over):
    body = {
        "username": over.get("username", "u1"),
        "email": over.get("email", "u1@example.com"),
        "full_name": "User One",
        "password": "Password123!",
        "role_ids": over.get("role_ids", [OPERATOR_ROLE]),
        "status": over.get("status", "active"),
    }
    return client.post("/api/v1/users", headers=headers, json=body)


def test_user_crud_flow(client, auth_headers) -> None:
    created = _create(client, auth_headers)
    assert created.status_code == 201, created.text
    uid = created.json()["id"]
    assert created.json()["roles"] == ["Operator"]

    got = client.get(f"/api/v1/users/{uid}", headers=auth_headers)
    assert got.status_code == 200

    updated = client.put(
        f"/api/v1/users/{uid}", headers=auth_headers, json={"full_name": "Renamed", "email": "new@example.com"}
    )
    assert updated.status_code == 200
    assert updated.json()["email"] == "new@example.com"

    listed = client.get("/api/v1/users?q=Renamed", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    deleted = client.delete(f"/api/v1/users/{uid}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/users/{uid}", headers=auth_headers).status_code == 404


def test_duplicate_username_conflict(client, auth_headers) -> None:
    assert _create(client, auth_headers, username="dup", email="dup1@example.com").status_code == 201
    r = _create(client, auth_headers, username="dup", email="dup2@example.com")
    assert r.status_code == 409


def test_create_with_unknown_role_422(client, auth_headers) -> None:
    r = _create(client, auth_headers, username="x", email="x@example.com", role_ids=["00000000-0000-0000-0000-0000deadbeef"])
    assert r.status_code == 422


def test_list_filters(client, auth_headers) -> None:
    _create(client, auth_headers, username="flt", email="flt@example.com", role_ids=[OPERATOR_ROLE])
    by_role = client.get("/api/v1/users?role=Operator", headers=auth_headers)
    assert by_role.status_code == 200 and by_role.json()["total"] >= 1
    by_status = client.get("/api/v1/users?status=active", headers=auth_headers)
    assert by_status.status_code == 200


def test_self_disable_conflict(client, auth_headers) -> None:
    r = client.put(f"/api/v1/users/{ADMIN_ID}", headers=auth_headers, json={"status": "disabled"})
    assert r.status_code == 409


def test_self_delete_conflict(client, auth_headers) -> None:
    r = client.delete(f"/api/v1/users/{ADMIN_ID}", headers=auth_headers)
    assert r.status_code == 409


def test_last_superadmin_protection_on_role_change(client, auth_headers) -> None:
    # admin e' l'unico SuperAdmin: rimuovergli il ruolo -> 409
    r = client.put(
        f"/api/v1/users/{ADMIN_ID}/roles", headers=auth_headers, json={"role_ids": [OPERATOR_ROLE]}
    )
    assert r.status_code == 409


def test_assign_roles_ok(client, auth_headers) -> None:
    uid = _create(client, auth_headers, username="ar", email="ar@example.com", role_ids=[]).json()["id"]
    r = client.put(
        f"/api/v1/users/{uid}/roles", headers=auth_headers, json={"role_ids": [OPERATOR_ROLE]}
    )
    assert r.status_code == 200
    assert r.json()["roles"] == ["Operator"]


def test_reset_password(client, auth_headers) -> None:
    uid = _create(client, auth_headers, username="rp", email="rp@example.com").json()["id"]
    r = client.post(
        f"/api/v1/users/{uid}/reset-password", headers=auth_headers, json={"new_password": "BrandNew123!"}
    )
    assert r.status_code == 204
    login = client.post("/api/v1/auth/login", json={"username": "rp", "password": "BrandNew123!"})
    assert login.status_code == 200


def test_update_and_delete_not_found(client, auth_headers) -> None:
    ghost = "00000000-0000-0000-0000-0000000000ff"
    assert client.put(f"/api/v1/users/{ghost}", headers=auth_headers, json={"full_name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/users/{ghost}", headers=auth_headers).status_code == 404
    assert client.post(f"/api/v1/users/{ghost}/reset-password", headers=auth_headers, json={"new_password": "Password123!"}).status_code == 404
    assert client.put(f"/api/v1/users/{ghost}/roles", headers=auth_headers, json={"role_ids": []}).status_code == 404


def test_invalid_uuid_path_is_404(client, auth_headers) -> None:
    assert client.get("/api/v1/users/not-a-uuid", headers=auth_headers).status_code == 404


def test_create_user_invalid_email_422(client, auth_headers) -> None:
    """BUG-01: email malformata -> 422 (EmailStr)."""
    r = _create(client, auth_headers, username="bademail", email="clearly-not-an-email")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNPROCESSABLE_ENTITY"


def test_create_user_valid_email_201(client, auth_headers) -> None:
    """BUG-01: email valida -> 201."""
    r = _create(client, auth_headers, username="goodemail", email="ops.team@example.com")
    assert r.status_code == 201
    assert r.json()["email"] == "ops.team@example.com"


def test_update_user_invalid_email_422(client, auth_headers) -> None:
    """BUG-01: anche PUT rifiuta email malformate."""
    uid = _create(client, auth_headers, username="upde", email="upde@example.com").json()["id"]
    r = client.put(f"/api/v1/users/{uid}", headers=auth_headers, json={"email": "not-an-email"})
    assert r.status_code == 422
    ok = client.put(f"/api/v1/users/{uid}", headers=auth_headers, json={"email": "valid@example.com"})
    assert ok.status_code == 200 and ok.json()["email"] == "valid@example.com"
