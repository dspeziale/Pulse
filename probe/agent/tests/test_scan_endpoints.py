"""Test degli endpoint di scansione e dello storage scansioni (in-memory).

nmap e' MOCKATO (state.scan_runner): nessuna esecuzione reale di nmap.
"""

from __future__ import annotations

from pulse_probe.store import InMemoryStore

_VALID_XML = """<nmaprun>
  <host><status state="up"/><address addr="10.0.0.5" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port></ports>
  </host>
  <runstats><hosts up="1" down="0" total="1"/></runstats>
</nmaprun>"""


def _ok_runner(argv, timeout):  # type: ignore[no-untyped-def]
    return (0, _VALID_XML, "")


# ------------------------------- POST /scan --------------------------------


def test_post_scan_runs_and_detail(client, state, auth) -> None:
    state.scan_runner = _ok_runner
    r = client.post(
        "/api/v1/scan",
        headers=auth,
        json={"target": "10.0.0.5", "technique": "connect", "top_ports": 10},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running" and body["target"] == "10.0.0.5"
    scan_id = body["scan_id"]

    # il BackgroundTask e' gia' stato eseguito dal TestClient -> scansione completata
    detail = client.get(f"/api/v1/scan/{scan_id}", headers=auth)
    assert detail.status_code == 200
    d = detail.json()
    assert d["status"] == "done"
    assert d["summary"]["ports_open"] == 1
    assert d["hosts"][0]["ip"] == "10.0.0.5"


def test_post_scan_failure_status(client, state, auth) -> None:
    state.scan_runner = lambda argv, timeout: (1, "", "requires root privileges")
    r = client.post("/api/v1/scan", headers=auth, json={"target": "10.0.0.5", "technique": "syn"})
    scan_id = r.json()["scan_id"]
    d = client.get(f"/api/v1/scan/{scan_id}", headers=auth).json()
    assert d["status"] == "failed" and "CAP_NET_RAW" in d["error"]


def test_post_scan_invalid_target_422(client, auth) -> None:
    r = client.post("/api/v1/scan", headers=auth, json={"target": "-oX"})
    assert r.status_code == 422


def test_post_scan_invalid_extra_422(client, auth) -> None:
    r = client.post("/api/v1/scan", headers=auth, json={"target": "10.0.0.5", "extra": "-oN out.txt"})
    assert r.status_code == 422


def test_post_scan_requires_token(client) -> None:
    assert client.post("/api/v1/scan", json={"target": "10.0.0.5"}).status_code == 401


# ------------------------------- GET /scans --------------------------------


def test_list_scans_pagination(client, state, auth) -> None:
    state.scan_runner = _ok_runner
    for _ in range(3):
        client.post("/api/v1/scan", headers=auth, json={"target": "10.0.0.5"})
    listed = client.get("/api/v1/scans?page=1&page_size=2", headers=auth)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert {"scan_id", "target", "status", "started_at", "finished_at", "summary"} <= set(
        body["items"][0].keys()
    )


def test_list_scans_requires_token(client) -> None:
    assert client.get("/api/v1/scans").status_code == 401


# ------------------------------- GET /scan/{id} ----------------------------


def test_get_scan_not_found(client, auth) -> None:
    r = client.get("/api/v1/scan/does-not-exist", headers=auth)
    assert r.status_code == 404


# ------------------------------- /status nmap ------------------------------


def test_status_includes_nmap_fields(client, auth) -> None:
    r = client.get("/api/v1/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "nmap_available" in body and "nmap_version" in body


# ------------------------------- storage in-memory -------------------------


def test_inmemory_scan_store_crud_and_order() -> None:
    store = InMemoryStore()
    store.index_scan({"scan_id": "a", "started_at": "2026-07-17T00:00:00", "status": "done"})
    store.index_scan({"scan_id": "b", "started_at": "2026-07-17T01:00:00", "status": "running"})
    # get
    assert store.get_scan("a")["status"] == "done"  # type: ignore[index]
    assert store.get_scan("missing") is None
    # upsert
    store.index_scan({"scan_id": "a", "started_at": "2026-07-17T00:00:00", "status": "failed"})
    assert store.get_scan("a")["status"] == "failed"  # type: ignore[index]
    # search ordinato per started_at desc + paginazione
    items, total = store.search_scans(page=1, page_size=1)
    assert total == 2 and items[0]["scan_id"] == "b"
    items2, _ = store.search_scans(page=2, page_size=1)
    assert items2[0]["scan_id"] == "a"
