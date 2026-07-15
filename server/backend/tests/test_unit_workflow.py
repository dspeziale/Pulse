"""Unit test del motore workflow (funzioni pure, nessun DB)."""

from __future__ import annotations

import datetime as dt

import pytest

from pulse_server.workflow import (
    conditions_match,
    eval_condition,
    evaluate,
    scope_match,
    _event_field,
    _within_active_hours,
)


@pytest.mark.parametrize(
    "op,left,right,expected",
    [
        ("eq", 1, 1, True),
        ("eq", 1, 2, False),
        ("neq", 1, 2, True),
        ("gt", 5, 3, True),
        ("gte", 3, 3, True),
        ("lt", 2, 3, True),
        ("lte", 3, 3, True),
        ("gt", None, 3, False),
        ("gt", "x", "y", False),
        ("in", 2, [1, 2, 3], True),
        ("in", 9, [1, 2], False),
        ("not_in", 9, [1, 2], True),
        ("contains", "hello world", "world", True),
        ("contains", None, "x", False),
        ("matches", "abc123", r"\d+", True),
        ("matches", "abc", r"\d+", False),
        ("matches", None, "x", False),
        ("matches", "x", "[", False),
        ("unknown_op", 1, 1, False),
    ],
)
def test_eval_condition(op, left, right, expected) -> None:
    assert eval_condition(op, left, right) is expected


def test_conditions_match_and_or() -> None:
    event = {"status": "error", "response_ms": 900}
    # AND nel gruppo g1
    conds = [
        {"field": "status", "op": "eq", "value": "error", "group": "g1"},
        {"field": "response_ms", "op": "gt", "value": 500, "group": "g1"},
    ]
    assert conditions_match(event, conds) is True
    # gruppo che fallisce ma OR con gruppo che passa
    conds2 = [
        {"field": "status", "op": "eq", "value": "ok", "group": "a"},
        {"field": "response_ms", "op": "gt", "value": 500, "group": "b"},
    ]
    assert conditions_match(event, conds2) is True
    assert conditions_match(event, []) is True
    assert conditions_match({"status": "ok"}, [{"field": "status", "op": "eq", "value": "error"}]) is False


def test_event_field_metrics() -> None:
    event = {"details": '{"metrics": {"cpu": 91}}'}
    assert _event_field(event, "details.metrics.cpu") == 91
    assert _event_field({"details": "not-json"}, "details.metrics.cpu") is None
    assert _event_field({"details": {"metrics": {"x": 1}}}, "details.metrics.x") == 1
    assert _event_field({"details": 5}, "details.metrics.x") is None
    assert _event_field({"a": 2}, "a") == 2
    assert _event_field({}, "missing") is None


def test_scope_match() -> None:
    assert scope_match({"system_id": "s1"}, None) is True
    assert scope_match({"system_id": "s1"}, {"system_ids": ["s1"]}) is True
    assert scope_match({"system_id": "s2"}, {"system_ids": ["s1"]}) is False
    assert scope_match({}, {"probe_ids": ["p1"]}) is False
    assert scope_match({"probe_id": "p1", "system_id": "s1", "check_id": "c1"},
                       {"probe_ids": ["p1"], "system_ids": ["s1"], "check_ids": ["c1"]}) is True


def test_within_active_hours() -> None:
    monday_10 = dt.datetime(2026, 7, 13, 10, 0, tzinfo=dt.timezone.utc)  # lunedi'
    assert _within_active_hours(None, monday_10) is True
    assert _within_active_hours({"days": [0]}, monday_10) is True
    assert _within_active_hours({"days": [1, 2]}, monday_10) is False
    assert _within_active_hours({"start": "09:00", "end": "18:00"}, monday_10) is True
    assert _within_active_hours({"start": "11:00", "end": "18:00"}, monday_10) is False


def test_evaluate_full_matrix() -> None:
    now = dt.datetime(2026, 7, 13, 10, 0, tzinfo=dt.timezone.utc)
    wf = {
        "trigger": "status_changed",
        "scope": {},
        "conditions": [{"field": "status", "op": "eq", "value": "error", "group": "g"}],
        "suppression": {"respect_maintenance": True},
        "actions": [{"step_order": 0}],
    }
    ev_ok = {"type": "status_changed", "status": "error"}
    res = evaluate(ev_ok, wf, now=now)
    assert res.matched and res.planned_actions and res.suppressed_by is None

    # trigger diverso
    assert evaluate({"type": "system_recovered"}, wf, now=now).matched is False
    # condizione non soddisfatta
    assert evaluate({"type": "status_changed", "status": "ok"}, wf, now=now).matched is False
    # manutenzione attiva -> soppresso
    supp = evaluate(ev_ok, wf, now=now, maintenance_active=True)
    assert supp.matched and supp.suppressed_by == "maintenance_window"
    # fuori orario attivo -> soppresso
    wf2 = dict(wf, suppression={"active_hours": {"start": "11:00", "end": "18:00"}})
    off = evaluate(ev_ok, wf2, now=now)
    assert off.suppressed_by == "active_hours"


def test_evaluate_scope_reject() -> None:
    now = dt.datetime(2026, 7, 13, 10, 0, tzinfo=dt.timezone.utc)
    wf = {"trigger": "status_changed", "scope": {"system_ids": ["only"]}, "conditions": [], "suppression": {}, "actions": []}
    assert evaluate({"type": "status_changed", "system_id": "other"}, wf, now=now).matched is False
