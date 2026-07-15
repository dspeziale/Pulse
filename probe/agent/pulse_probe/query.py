"""Motore di query strutturata Pulse (non DSL raw) sui documenti heartbeat.

Funzioni pure riusate sia dallo storage in-memory sia (post-fetch) da OpenSearch,
per garantire semantica identica e testabilita'.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any


def _parse_iso(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def eval_op(op: str, left: Any, right: Any) -> bool:
    """Valuta un operatore di filtro. Operatore sconosciuto -> False."""
    if op == "eq":
        return bool(left == right)
    if op == "neq":
        return bool(left != right)
    if op in ("gt", "gte", "lt", "lte"):
        if left is None or right is None:
            return False
        try:
            lf, rf = float(left), float(right)
        except (ValueError, TypeError):
            return False
        return {"gt": lf > rf, "gte": lf >= rf, "lt": lf < rf, "lte": lf <= rf}[op]
    if op == "in":
        return isinstance(right, (list, tuple)) and left in right
    if op == "not_in":
        return isinstance(right, (list, tuple)) and left not in right
    if op == "contains":
        return left is not None and right is not None and str(right) in str(left)
    if op == "matches":
        if left is None or right is None:
            return False
        try:
            return re.search(str(right), str(left)) is not None
        except re.error:
            return False
    return False


def match_filters(doc: dict[str, Any], filters: list[dict[str, Any]]) -> bool:
    """AND di tutti i filtri (semantica del query builder Pulse)."""
    for f in filters:
        if not eval_op(f["op"], doc.get(f["field"]), f.get("value")):
            return False
    return True


def within_time(doc: dict[str, Any], frm: str | None, to: str | None) -> bool:
    if frm is None and to is None:
        return True
    ts = _parse_iso(doc.get("@timestamp"))
    if ts is None:
        return False
    if frm is not None:
        start = _parse_iso(frm)
        if start is not None and ts < start:
            return False
    if to is not None:
        end = _parse_iso(to)
        if end is not None and ts > end:
            return False
    return True


def compute_aggregations(
    docs: list[dict[str, Any]], aggregations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Calcola aggregazioni avg/min/max/count/uptime sui documenti filtrati."""
    result: dict[str, Any] = {}
    for agg in aggregations:
        atype = agg["type"]
        field = agg.get("field")
        if atype == "count":
            result["count"] = len(docs)
        elif atype == "uptime":
            total = len(docs)
            up = sum(1 for d in docs if d.get("status") == "ok")
            result["uptime"] = round(100.0 * up / total, 2) if total else 0.0
        elif atype in ("avg", "min", "max") and field:
            values = [
                float(d[field])
                for d in docs
                if d.get(field) is not None and _is_number(d.get(field))
            ]
            key = f"{atype}_{field}"
            if not values:
                result[key] = None
            elif atype == "avg":
                result[key] = round(sum(values) / len(values), 3)
            elif atype == "min":
                result[key] = min(values)
            else:
                result[key] = max(values)
    return result


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def apply_query(
    docs: list[dict[str, Any]],
    *,
    filters: list[dict[str, Any]] | None = None,
    frm: str | None = None,
    to: str | None = None,
    aggregations: list[dict[str, Any]] | None = None,
    sort: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Applica filtri, intervallo, ordinamento, paginazione e aggregazioni.

    Ritorna (items_pagina, total_filtrati, aggregazioni).
    """
    filters = filters or []
    selected = [
        d for d in docs if match_filters(d, filters) and within_time(d, frm, to)
    ]
    total = len(selected)

    aggs = compute_aggregations(selected, aggregations or []) if aggregations else {}

    reverse = False
    sort_field = "@timestamp"
    if sort:
        if sort.startswith("-"):
            reverse = True
            sort_field = sort[1:]
        else:
            sort_field = sort
    selected.sort(key=lambda d: (d.get(sort_field) is None, d.get(sort_field)), reverse=reverse)

    if page is not None and page_size is not None:
        start = (max(1, page) - 1) * page_size
        items = selected[start : start + page_size]
    else:
        items = selected
    return items, total, aggs
