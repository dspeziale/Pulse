"""Test del parsing/normalizzazione dello schema canonico heartbeat."""

from __future__ import annotations

from pulse_probe import canonical


def test_normalize_status() -> None:
    assert canonical.normalize_status("ok") == "ok"
    assert canonical.normalize_status("ERROR") == "error"
    assert canonical.normalize_status("weird") == "unknown"
    assert canonical.normalize_status(None) == "unknown"
    assert canonical.normalize_status(123) == "unknown"


def test_build_documents_single_object() -> None:
    payload = {
        "@timestamp": "2026-07-15T10:00:00Z",
        "system_id": "myapp",
        "system_name": "MyApp",
        "check_id": "db",
        "check_name": "Database",
        "status": "ok",
        "response_ms": 12,
        "message": None,
        "details": '{"metrics":{}}',
    }
    docs = canonical.build_documents(
        payload, system_id="myapp", system_name="MyApp", probe_id="p1",
        reachable=True, http_status=200, latency_ms=8,
    )
    assert len(docs) == 1
    d = docs[0]
    assert d["status"] == "ok" and d["check_id"] == "db"
    assert d["probe_id"] == "p1" and d["reachable"] is True and d["http_status"] == 200
    assert d["ingested_at"]


def test_build_documents_array() -> None:
    payload = [
        {"check_id": "db", "status": "ok", "response_ms": 5},
        {"check_id": "cache", "status": "warn", "response_ms": 20},
        "not-a-dict",
    ]
    docs = canonical.build_documents(
        payload, system_id="s", system_name="S", probe_id=None, reachable=True, http_status=200, latency_ms=1
    )
    assert len(docs) == 2
    assert {d["check_id"] for d in docs} == {"db", "cache"}


def test_build_documents_defaults_and_bad_payload() -> None:
    # payload non dict/list -> nessun documento
    assert canonical.build_documents("x", system_id="s", system_name="S", probe_id=None, reachable=True, http_status=200, latency_ms=1) == []
    # check_id mancante -> "default", timestamp fallback
    docs = canonical.build_documents({"status": "ok"}, system_id="s", system_name="S", probe_id=None, reachable=True, http_status=200, latency_ms=1)
    assert docs[0]["check_id"] == "default" and docs[0]["@timestamp"]


def test_unreachable_document() -> None:
    d = canonical.unreachable_document(
        system_id="s", system_name="S", probe_id="p", http_status=None, latency_ms=5000, message="timeout"
    )
    assert d["status"] == "down" and d["reachable"] is False and d["check_id"] == "connectivity"
