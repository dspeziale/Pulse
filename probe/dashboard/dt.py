"""Adattatore DataTables server-side per la dashboard PROBE.

Espone gli endpoint heartbeat consumati dalle tabelle DataTables della Sonda:
  - ``GET /dt/heartbeats``                 -> dashboard Sonda (tutti i sistemi)
  - ``GET /dt/heartbeats/system/<sid>``    -> dettaglio sistema (filtrato)

Traducono i parametri DataTables nei parametri di ``/query/heartbeats`` (proxy
locale del probe-agent: page/page_size/sort/filtri) e ricompongono la risposta
nel formato ``{draw, recordsTotal, recordsFiltered, data}``. Le celle usano lo
stesso markup dei template (badge di stato, date via il filtro ``localdt``).
"""
from __future__ import annotations

from typing import Any, Sequence

from flask import Blueprint, abort, current_app, jsonify, request

from pulse_fe_common.datatables import DTColumn, DTTable, serve, status_badge

from probe_auth import is_authenticated
from sdk import api_get

bp = Blueprint("dt", __name__)


def _localdt(value: Any) -> str:
    return current_app.jinja_env.filters["localdt"](value)


def _muted(text: Any) -> Any:
    return "" if text is None else text


def _ts_col() -> DTColumn:
    return DTColumn("@timestamp", lambda h: _localdt(h.get("@timestamp")),
                    sort="@timestamp", title="Timestamp",
                    class_="text-body-secondary")


def _status_col() -> DTColumn:
    return DTColumn("status", lambda h: status_badge(h.get("status")),
                    sort="status", title="Stato")


def _ms_col() -> DTColumn:
    return DTColumn("response_ms", lambda h: h.get("response_ms"),
                    sort="response_ms", title="ms", th_class="text-end",
                    class_="text-end")


def _msg_col() -> DTColumn:
    return DTColumn("message", lambda h: h.get("message") or "",
                    title="Messaggio", class_="text-body-secondary")


def _index_table() -> DTTable:
    """Heartbeat della dashboard Sonda (colonna Sistema inclusa)."""
    return DTTable(
        columns=[
            _ts_col(),
            DTColumn("system_name", lambda h: _muted(h.get("system_name")),
                     sort="system_name", title="Sistema"),
            DTColumn("check_name", lambda h: _muted(h.get("check_name")),
                     sort="check_name", title="Check"),
            _status_col(),
            _ms_col(),
            _msg_col(),
        ],
        order=(0, "desc"), default_length=50, searching=False,
    )


def _system_table() -> DTTable:
    """Heartbeat del dettaglio sistema (senza colonna Sistema)."""
    return DTTable(
        columns=[
            _ts_col(),
            DTColumn("check_name", lambda h: _muted(h.get("check_name")),
                     sort="check_name", title="Check"),
            _status_col(),
            _ms_col(),
            _msg_col(),
        ],
        order=(0, "desc"), default_length=50, searching=False,
    )


_TABLES = {"heartbeats": _index_table(), "heartbeats_system": _system_table()}


def table_meta(resource: str) -> dict:
    table = _TABLES.get(resource)
    if table is None:
        raise KeyError(resource)
    return table.meta()


def _collect_filters(names: Sequence[str]) -> dict:
    return {n: request.args.get(n) for n in names
            if request.args.get(n) not in (None, "")}


@bp.route("/dt/heartbeats")
def dt_heartbeats():
    """Heartbeat della dashboard Sonda (tutti i sistemi)."""
    if not is_authenticated():
        abort(401)
    filters = _collect_filters(("system_id", "check_id", "status", "from", "to"))
    payload = serve(
        request.args, _TABLES["heartbeats"].columns,
        fetch=lambda params: api_get("/query/heartbeats", params=params),
        extra_filters=filters,
    )
    return jsonify(payload)


@bp.route("/dt/heartbeats/system/<system_id>")
def dt_heartbeats_system(system_id: str):
    """Heartbeat del dettaglio sistema (system_id dal path, resto da ajax.data)."""
    if not is_authenticated():
        abort(401)
    filters = _collect_filters(("check_id", "status", "from", "to"))
    filters["system_id"] = system_id
    payload = serve(
        request.args, _TABLES["heartbeats_system"].columns,
        fetch=lambda params: api_get("/query/heartbeats", params=params),
        extra_filters=filters,
    )
    return jsonify(payload)


def register_template_globals(app) -> None:
    app.jinja_env.globals["dt_meta"] = table_meta
