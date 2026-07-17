"""Test dell'ordinamento server-side (parametro `sort`) per DataTables.

Contratto: `sort=campo` (asc), `sort=-campo` (desc); campo non consentito ->
ordinamento di default (nessun errore). Combinabile con q/page.
"""

from __future__ import annotations

OPERATOR_ROLE = "00000000-0000-0000-0000-000000000003"


def _mk_user(client, headers, username: str) -> None:
    r = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": username, "email": f"{username}@example.com", "full_name": username,
            "password": "Password123!", "role_ids": [OPERATOR_ROLE], "status": "active",
        },
    )
    assert r.status_code == 201, r.text


def _mk_probe(client, headers, name: str) -> None:
    r = client.post(
        "/api/v1/probes",
        headers=headers,
        json={"name": name, "description": "", "query_endpoint": "https://p.local:8444", "tags": [], "enabled": True},
    )
    assert r.status_code == 201, r.text


# ------------------------------- users -------------------------------------


def test_users_sort_asc_desc_and_query(client, auth_headers) -> None:
    for u in ("sortu-charlie", "sortu-alpha", "sortu-bravo"):
        _mk_user(client, auth_headers, u)
    asc = client.get("/api/v1/users?q=sortu&sort=username", headers=auth_headers)
    assert asc.status_code == 200
    names_asc = [i["username"] for i in asc.json()["items"]]
    assert names_asc == ["sortu-alpha", "sortu-bravo", "sortu-charlie"]

    desc = client.get("/api/v1/users?q=sortu&sort=-username", headers=auth_headers)
    names_desc = [i["username"] for i in desc.json()["items"]]
    assert names_desc == ["sortu-charlie", "sortu-bravo", "sortu-alpha"]


def test_users_sort_invalid_field_falls_back_to_default(client, auth_headers) -> None:
    for u in ("sortx-2", "sortx-1"):
        _mk_user(client, auth_headers, u)
    # campo non in whitelist -> default (created_at asc): rispetta ordine di creazione
    r = client.get("/api/v1/users?q=sortx&sort=not_a_column", headers=auth_headers)
    assert r.status_code == 200
    names = [i["username"] for i in r.json()["items"]]
    assert names == ["sortx-2", "sortx-1"]


# ------------------------------- probes ------------------------------------


def test_probes_sort_asc_desc(client, auth_headers) -> None:
    for n in ("sortp-charlie", "sortp-alpha", "sortp-bravo"):
        _mk_probe(client, auth_headers, n)
    asc = client.get("/api/v1/probes?q=sortp&sort=name", headers=auth_headers)
    assert asc.status_code == 200
    names_asc = [i["name"] for i in asc.json()["items"]]
    assert names_asc == ["sortp-alpha", "sortp-bravo", "sortp-charlie"]

    desc = client.get("/api/v1/probes?q=sortp&sort=-name", headers=auth_headers)
    names_desc = [i["name"] for i in desc.json()["items"]]
    assert names_desc == ["sortp-charlie", "sortp-bravo", "sortp-alpha"]


def test_probes_sort_invalid_field_default(client, auth_headers) -> None:
    r = client.get("/api/v1/probes?sort=bogus", headers=auth_headers)
    assert r.status_code == 200  # nessun errore: usa default


# ------------------------------- audit -------------------------------------


def test_audit_sort_timestamp_asc_desc(client, auth_headers) -> None:
    # genera alcune voci di audit con azioni distinte
    for u in ("sorta-1", "sorta-2", "sorta-3"):
        _mk_user(client, auth_headers, u)
    asc = client.get("/api/v1/audit?sort=timestamp", headers=auth_headers)
    assert asc.status_code == 200
    ts_asc = [i["timestamp"] for i in asc.json()["items"]]
    assert ts_asc == sorted(ts_asc)

    desc = client.get("/api/v1/audit?sort=-timestamp", headers=auth_headers)
    ts_desc = [i["timestamp"] for i in desc.json()["items"]]
    assert ts_desc == sorted(ts_desc, reverse=True)


def test_audit_sort_invalid_field_equals_default(client, auth_headers) -> None:
    _mk_user(client, auth_headers, "sorta-inv")
    default = client.get("/api/v1/audit", headers=auth_headers).json()["items"]
    bogus = client.get("/api/v1/audit?sort=nope", headers=auth_headers).json()["items"]
    assert [i["id"] for i in default] == [i["id"] for i in bogus]


def test_audit_sort_by_action_field(client, auth_headers) -> None:
    r = client.get("/api/v1/audit?sort=action&page=1&page_size=50", headers=auth_headers)
    assert r.status_code == 200
    actions = [i["action"] for i in r.json()["items"]]
    assert actions == sorted(actions)
