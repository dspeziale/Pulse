"""Test aree Ruoli (§1.3) e Permessi (§1.4)."""

from __future__ import annotations

SUPERADMIN_ROLE = "00000000-0000-0000-0000-000000000001"


def test_permissions_catalog_has_42(client, auth_headers) -> None:
    r = client.get("/api/v1/permissions", headers=auth_headers)
    assert r.status_code == 200
    # 42 permessi dopo l'aggiunta di scans.run/scans.read (seed iterazione 51).
    assert len(r.json()["items"]) == 42


def test_role_crud_flow(client, auth_headers) -> None:
    created = client.post(
        "/api/v1/roles",
        headers=auth_headers,
        json={"name": "custom", "description": "Custom", "permission_codes": ["users.read"]},
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert created.json()["permissions"] == ["users.read"]
    assert created.json()["is_builtin"] is False

    got = client.get(f"/api/v1/roles/{rid}", headers=auth_headers)
    assert got.status_code == 200

    upd = client.put(f"/api/v1/roles/{rid}", headers=auth_headers, json={"description": "Changed"})
    assert upd.status_code == 200 and upd.json()["description"] == "Changed"

    setperm = client.put(
        f"/api/v1/roles/{rid}/permissions",
        headers=auth_headers,
        json={"permission_codes": ["users.read", "roles.read"]},
    )
    assert setperm.status_code == 200
    assert set(setperm.json()["permissions"]) == {"users.read", "roles.read"}

    listed = client.get("/api/v1/roles?q=custom", headers=auth_headers)
    assert listed.json()["total"] >= 1

    deleted = client.delete(f"/api/v1/roles/{rid}", headers=auth_headers)
    assert deleted.status_code == 204


def test_role_duplicate_name_conflict(client, auth_headers) -> None:
    client.post("/api/v1/roles", headers=auth_headers, json={"name": "dupr", "description": "", "permission_codes": []})
    r = client.post("/api/v1/roles", headers=auth_headers, json={"name": "dupr", "description": "", "permission_codes": []})
    assert r.status_code == 409


def test_role_invalid_permission_code_422(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/roles",
        headers=auth_headers,
        json={"name": "badperm", "description": "", "permission_codes": ["does.not.exist"]},
    )
    assert r.status_code == 422


def test_builtin_role_cannot_rename(client, auth_headers) -> None:
    r = client.put(f"/api/v1/roles/{SUPERADMIN_ROLE}", headers=auth_headers, json={"name": "Renamed"})
    assert r.status_code == 409


def test_builtin_role_description_update_409(client, auth_headers) -> None:
    """BUG-02: PUT su ruolo predefinito -> 409 anche per la sola description."""
    r = client.put(
        f"/api/v1/roles/{SUPERADMIN_ROLE}", headers=auth_headers, json={"description": "HACKED-DESC"}
    )
    assert r.status_code == 409
    # la description NON deve essere cambiata
    got = client.get(f"/api/v1/roles/{SUPERADMIN_ROLE}", headers=auth_headers)
    assert got.json()["description"] != "HACKED-DESC"


def test_builtin_role_cannot_delete(client, auth_headers) -> None:
    r = client.delete(f"/api/v1/roles/{SUPERADMIN_ROLE}", headers=auth_headers)
    assert r.status_code == 409


def test_builtin_role_permissions_immutable(client, auth_headers) -> None:
    r = client.put(
        f"/api/v1/roles/{SUPERADMIN_ROLE}/permissions",
        headers=auth_headers,
        json={"permission_codes": ["users.read"]},
    )
    assert r.status_code == 409


def test_delete_role_in_use_conflict(client, auth_headers) -> None:
    rid = client.post(
        "/api/v1/roles", headers=auth_headers, json={"name": "inuse", "description": "", "permission_codes": []}
    ).json()["id"]
    client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "username": "hasrole", "email": "hasrole@example.com", "full_name": "",
            "password": "Password123!", "role_ids": [rid], "status": "active",
        },
    )
    r = client.delete(f"/api/v1/roles/{rid}", headers=auth_headers)
    assert r.status_code == 409


def test_role_not_found(client, auth_headers) -> None:
    ghost = "00000000-0000-0000-0000-0000000000ee"
    assert client.get(f"/api/v1/roles/{ghost}", headers=auth_headers).status_code == 404
    assert client.put(f"/api/v1/roles/{ghost}", headers=auth_headers, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/roles/{ghost}", headers=auth_headers).status_code == 404
    assert client.put(f"/api/v1/roles/{ghost}/permissions", headers=auth_headers, json={"permission_codes": []}).status_code == 404
