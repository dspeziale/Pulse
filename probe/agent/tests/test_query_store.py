"""Test del motore di query strutturata e dello store in-memory."""

from __future__ import annotations

import pytest

from pulse_probe import query as q
from pulse_probe.store import InMemoryStore, build_store
from pulse_probe.config import Settings


DOCS = [
    {"@timestamp": "2026-07-15T10:00:00Z", "system_id": "a", "check_id": "db", "status": "ok", "response_ms": 10, "message": "fine"},
    {"@timestamp": "2026-07-15T10:01:00Z", "system_id": "a", "check_id": "db", "status": "error", "response_ms": 900, "message": "boom"},
    {"@timestamp": "2026-07-15T10:02:00Z", "system_id": "b", "check_id": "web", "status": "ok", "response_ms": 50, "message": None},
]


@pytest.mark.parametrize(
    "op,left,right,expected",
    [
        ("eq", "ok", "ok", True), ("neq", "ok", "err", True),
        ("gt", 5, 3, True), ("gte", 3, 3, True), ("lt", 2, 3, True), ("lte", 3, 3, True),
        ("gt", None, 1, False), ("gt", "x", "y", False),
        ("in", "a", ["a", "b"], True), ("not_in", "z", ["a"], True),
        ("contains", "hello", "ell", True), ("contains", None, "x", False),
        ("matches", "abc1", r"\d", True), ("matches", "abc", r"\d", False),
        ("matches", None, "x", False), ("matches", "x", "[", False),
        ("bogus", 1, 1, False),
    ],
)
def test_eval_op(op, left, right, expected) -> None:
    assert q.eval_op(op, left, right) is expected


def test_within_time() -> None:
    doc = {"@timestamp": "2026-07-15T10:00:00Z"}
    assert q.within_time(doc, None, None) is True
    assert q.within_time(doc, "2026-07-15T09:00:00Z", "2026-07-15T11:00:00Z") is True
    assert q.within_time(doc, "2026-07-15T10:30:00Z", None) is False
    assert q.within_time(doc, None, "2026-07-15T09:30:00Z") is False
    assert q.within_time({"@timestamp": "bad"}, "2026-07-15T09:00:00Z", None) is False


def test_apply_query_filters_and_pagination() -> None:
    items, total, aggs = q.apply_query(
        DOCS, filters=[{"field": "system_id", "op": "eq", "value": "a"}], page=1, page_size=1, sort="@timestamp"
    )
    assert total == 2 and len(items) == 1
    assert aggs == {}


def test_apply_query_time_and_sort_desc() -> None:
    items, total, _ = q.apply_query(DOCS, frm="2026-07-15T10:00:30Z", to="2026-07-15T10:10:00Z", sort="-@timestamp")
    assert total == 2
    assert items[0]["@timestamp"] >= items[1]["@timestamp"]


def test_apply_query_aggregations() -> None:
    aggs_spec = [
        {"type": "count"},
        {"type": "uptime"},
        {"type": "avg", "field": "response_ms"},
        {"type": "min", "field": "response_ms"},
        {"type": "max", "field": "response_ms"},
    ]
    _, _, aggs = q.apply_query(DOCS, aggregations=aggs_spec)
    assert aggs["count"] == 3
    assert aggs["avg_response_ms"] == round((10 + 900 + 50) / 3, 3)
    assert aggs["min_response_ms"] == 10 and aggs["max_response_ms"] == 900
    assert 0 <= aggs["uptime"] <= 100


def test_aggregations_empty_field_and_uptime_zero() -> None:
    _, _, aggs = q.apply_query([], aggregations=[{"type": "avg", "field": "response_ms"}, {"type": "uptime"}])
    assert aggs["avg_response_ms"] is None and aggs["uptime"] == 0.0


def test_inmemory_store_roundtrip() -> None:
    store = InMemoryStore()
    store.index_heartbeats(DOCS)
    store.index_events([{"type": "status_changed", "system_id": "a"}])
    items, total, _ = store.search_heartbeats(filters=[{"field": "status", "op": "eq", "value": "ok"}])
    assert total == 2
    assert store.healthy() is True


def test_build_store_defaults_to_inmemory() -> None:
    store = build_store(Settings(opensearch_url=None))
    assert isinstance(store, InMemoryStore)


def test_parse_iso_non_string() -> None:
    """query 16: valore non stringa -> None."""
    assert q._parse_iso(12345) is None
    assert q._parse_iso(None) is None


def test_within_time_non_string_timestamp() -> None:
    doc = {"@timestamp": 999}  # non stringa
    assert q.within_time(doc, "2026-07-15T00:00:00Z", None) is False


def test_within_time_to_only_and_frm_only() -> None:
    doc = {"@timestamp": "2026-07-15T10:00:00Z"}
    # solo `to` (frm None) -> ramo 71->75
    assert q.within_time(doc, None, "2026-07-15T11:00:00Z") is True
    # solo `frm`
    assert q.within_time(doc, "2026-07-15T09:00:00Z", None) is True


def test_aggregation_avg_without_field_ignored() -> None:
    """query 92->83: aggregazione avg senza field non produce output e prosegue."""
    _, _, aggs = q.apply_query(DOCS, aggregations=[{"type": "avg"}, {"type": "count"}])
    assert aggs == {"count": 3}


def test_is_number() -> None:
    """query 114-115/except: _is_number su valore valido e non valido."""
    assert q._is_number(10) is True
    assert q._is_number("3.14") is True
    assert q._is_number("abc") is False
    assert q._is_number(None) is False
