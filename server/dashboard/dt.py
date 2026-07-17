"""Adattatore DataTables server-side per la dashboard SERVER.

Espone ``GET /dt/<resource>`` (liste) e ``GET /dt/heartbeats/<probe_id>``
(heartbeat) che traducono i parametri DataTables nei parametri delle API REST del
backend e ricompongono la risposta nel formato ``{draw, recordsTotal,
recordsFiltered, data}`` (vedi ``pulse_fe_common.datatables``).

Le celle sono renderizzate lato server con lo STESSO markup dei template Jinja
(badge ``b-*``, pulsanti azione con permessi RBAC, date via il filtro ``localdt``)
cosi' che la conversione a DataTables non alteri l'aspetto delle tabelle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from flask import Blueprint, abort, current_app, jsonify, request
from markupsafe import Markup

from pulse_fe_common.auth import can, is_authenticated, user_permissions
from pulse_fe_common.datatables import (DTColumn, DTTable, badge, bool_badge,
                                        serve, status_badge)
from pulse_fe_common.rbac import has_any

from sdk import api_get

bp = Blueprint("dt", __name__)


# --------------------------------------------------------------------------- #
# Helper di rendering (usano il contesto di richiesta: url_for, can, localdt)
# --------------------------------------------------------------------------- #
def _localdt(value: Any) -> str:
    """Formatta un timestamp col filtro ``localdt`` (fuso da /config, con cache)."""
    return current_app.jinja_env.filters["localdt"](value)


def _probe_name(value: Any) -> str:
    """Risolve un probe_id nel nome Sonda col filtro ``probe_name`` (con cache)."""
    return current_app.jinja_env.filters["probe_name"](value)


def _link(endpoint: str, text: Any, *, bold: bool = True, **params) -> Markup:
    from flask import url_for

    cls = "fw-semibold text-decoration-none" if bold else "text-decoration-none"
    return Markup('<a class="{}" href="{}">{}</a>').format(
        cls, url_for(endpoint, **params), "" if text is None else text
    )


def _icon_btn(endpoint: str, icon: str, title: str, **params) -> Markup:
    from flask import url_for

    return Markup(
        '<a class="btn btn-sm btn-outline-secondary" href="{}" title="{}">'
        '<i class="bi {}"></i></a>'
    ).format(url_for(endpoint, **params), title, icon)


def _muted(text: Any) -> Any:
    """Le classi ``text-body-secondary`` delle vecchie celle sono ora applicate
    via ``className`` nella config colonna: qui si restituisce solo il valore."""
    return "" if text is None else text


# --------------------------------------------------------------------------- #
# Render per risorsa
# --------------------------------------------------------------------------- #
_ACCT = {"active": "b-ok", "disabled": "b-off", "locked": "b-warn"}
_LOG_LVL = {
    "debug": "text-bg-secondary", "info": "text-bg-info",
    "warning": "text-bg-warning", "error": "text-bg-danger",
    "critical": "text-bg-dark",
}
_CH_ICON = {"email": "bi-envelope", "telegram": "bi-telegram",
            "whatsapp": "bi-whatsapp"}


# -- users --------------------------------------------------------------------
def _users_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("username", lambda u: _link("users.detail", u.get("username"),
                                                 user_id=u.get("id")),
                     sort="username", title="Username"),
            DTColumn("full_name", lambda u: _muted(u.get("full_name")),
                     sort="full_name", title="Nome"),
            DTColumn("email", lambda u: _muted(u.get("email")), sort="email",
                     title="Email"),
            DTColumn("status", lambda u: badge(u.get("status"),
                                               _ACCT.get(u.get("status"), "b-unknown")),
                     sort="status", title="Stato"),
            DTColumn("roles", lambda u: ", ".join(u.get("roles", []) or []),
                     title="Ruoli", class_="text-body-secondary"),
            DTColumn("actions", _users_actions, title="Azioni",
                     th_class="text-end", class_="text-end"),
        ],
        order=(0, "asc"), default_length=25,
    )


def _users_actions(u: Mapping) -> Markup:
    out = _icon_btn("users.detail", "bi-eye", "Dettaglio", user_id=u.get("id"))
    if can("users.update"):
        out += _icon_btn("users.edit_user", "bi-pencil", "Modifica",
                         user_id=u.get("id"))
    return out


# -- roles --------------------------------------------------------------------
def _roles_actions(r: Mapping) -> Markup:
    out = _icon_btn("roles.detail", "bi-eye", "Dettaglio", role_id=r.get("id"))
    if can("roles.update") and not r.get("is_builtin"):
        out += _icon_btn("roles.edit_role", "bi-pencil", "Modifica",
                         role_id=r.get("id"))
    return out


def _roles_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("name", lambda r: _link("roles.detail", r.get("name"),
                                             role_id=r.get("id")),
                     sort="name", title="Nome"),
            DTColumn("description", lambda r: _muted(r.get("description")),
                     title="Descrizione", class_="text-body-secondary"),
            DTColumn("is_builtin", lambda r: bool_badge(r.get("is_builtin")),
                     title="Predefinito"),
            DTColumn("permissions", lambda r: len(r.get("permissions", []) or []),
                     title="N. permessi", th_class="text-end", class_="text-end"),
            DTColumn("actions", _roles_actions, title="Azioni",
                     th_class="text-end", class_="text-end"),
        ],
        order=(0, "asc"), default_length=25,
    )


# -- probes -------------------------------------------------------------------
def _probes_actions(p: Mapping) -> Markup:
    out = _icon_btn("probes.detail", "bi-eye", "Dettaglio", probe_id=p.get("id"))
    if can("probes.update"):
        out += _icon_btn("probes.edit_probe", "bi-pencil", "Modifica",
                         probe_id=p.get("id"))
    return out


def _probes_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("name", lambda p: _link("probes.detail", p.get("name"),
                                             probe_id=p.get("id")),
                     sort="name", title="Nome"),
            DTColumn("location", lambda p: p.get("location") or "—",
                     sort="location", title="Posizione",
                     class_="text-body-secondary"),
            DTColumn("contact_name", lambda p: p.get("contact_name") or "—",
                     sort="contact_name", title="Referente",
                     class_="text-body-secondary"),
            DTColumn("status", lambda p: status_badge(p.get("status")),
                     sort="status", title="Stato"),
            DTColumn("systems_count", lambda p: p.get("systems_count"),
                     title="Sistemi", th_class="text-end", class_="text-end"),
            DTColumn("last_seen_at", lambda p: _localdt(p.get("last_seen_at")),
                     sort="last_seen_at", title="Ultimo contatto",
                     class_="text-body-secondary"),
            DTColumn("actions", _probes_actions, title="Azioni",
                     th_class="text-end", class_="text-end"),
        ],
        order=(0, "asc"), default_length=25,
    )


# -- systems ------------------------------------------------------------------
def _systems_target(s: Mapping) -> Markup:
    skind = s.get("kind") or "http"
    if skind == "tcp":
        body = f"{s.get('tcp_host', '')}:{s.get('tcp_port', '')}"
    else:
        body = s.get("heartbeat_url") or ""
    return Markup('<span class="d-inline-block text-truncate" '
                  'style="max-width:22rem">{}</span>').format(body)


def _systems_kind(s: Mapping) -> Markup:
    skind = s.get("kind") or "http"
    cls = "b-unknown" if skind == "tcp" else "b-ok"
    label = "TCP" if skind == "tcp" else "HTTP"
    return badge(label, cls)


def _systems_actions(s: Mapping) -> Markup:
    out = _icon_btn("systems.detail", "bi-eye", "Dettaglio", system_id=s.get("id"))
    if can("systems.update"):
        out += _icon_btn("systems.edit_system", "bi-pencil", "Modifica",
                         system_id=s.get("id"))
    return out


def _systems_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("system_id", lambda s: _link("systems.detail",
                                                  s.get("system_id"),
                                                  system_id=s.get("id")),
                     sort="system_id", title="System ID"),
            DTColumn("system_name", lambda s: _muted(s.get("system_name")),
                     sort="system_name", title="Nome"),
            DTColumn("kind", _systems_kind, sort="kind", title="Tipo"),
            DTColumn("target", _systems_target, title="Endpoint / Target",
                     class_="text-body-secondary"),
            DTColumn("probe_id", lambda s: _probe_name(s.get("probe_id")),
                     title="Sonda"),
            DTColumn("enabled", lambda s: bool_badge(s.get("enabled")),
                     sort="enabled", title="Abilitato"),
            DTColumn("actions", _systems_actions, title="Azioni",
                     th_class="text-end", class_="text-end"),
        ],
        order=(0, "asc"), default_length=25,
    )


# -- workflows ----------------------------------------------------------------
def _workflows_actions(w: Mapping) -> Markup:
    out = _icon_btn("workflows.detail", "bi-eye", "Dettaglio",
                    workflow_id=w.get("id"))
    if can("workflows.update"):
        out += _icon_btn("workflows.edit_workflow", "bi-pencil", "Modifica",
                         workflow_id=w.get("id"))
    return out


def _workflows_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("name", lambda w: _link("workflows.detail", w.get("name"),
                                             workflow_id=w.get("id")),
                     sort="name", title="Nome"),
            DTColumn("trigger", lambda w: Markup("<code>{}</code>").format(
                w.get("trigger", "")), title="Trigger"),
            DTColumn("enabled", lambda w: bool_badge(w.get("enabled")),
                     sort="enabled", title="Abilitato"),
            DTColumn("actions", _workflows_actions, title="Azioni",
                     th_class="text-end", class_="text-end"),
        ],
        order=(0, "asc"), default_length=25,
    )


# -- notification channels ----------------------------------------------------
def _channels_type(c: Mapping) -> Markup:
    icon = _CH_ICON.get(c.get("type"), "bi-broadcast")
    return Markup('<i class="bi {} me-1"></i>{}').format(icon, c.get("type", ""))


def _channels_actions(c: Mapping) -> Markup:
    out = _icon_btn("notifications.detail", "bi-eye", "Dettaglio",
                    channel_id=c.get("id"))
    if can("notifications.update"):
        out += _icon_btn("notifications.edit_channel", "bi-pencil", "Modifica",
                         channel_id=c.get("id"))
    return out


def _channels_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("name", lambda c: _link("notifications.detail", c.get("name"),
                                             channel_id=c.get("id")),
                     sort="name", title="Nome"),
            DTColumn("type", _channels_type, sort="type", title="Tipo"),
            DTColumn("enabled", lambda c: bool_badge(c.get("enabled")),
                     sort="enabled", title="Abilitato"),
            DTColumn("inbound_enabled",
                     lambda c: bool_badge(c.get("inbound_enabled")),
                     title="Inbound"),
            DTColumn("actions", _channels_actions, title="Azioni",
                     th_class="text-end", class_="text-end"),
        ],
        order=(0, "asc"), default_length=25,
    )


# -- notification deliveries (storico invii) ----------------------------------
def _deliveries_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("created_at", lambda h: _localdt(h.get("created_at")),
                     sort="created_at", title="Data", class_="text-body-secondary"),
            DTColumn("channel_id", lambda h: _muted(h.get("channel_id")),
                     sort="channel_id", title="Canale"),
            DTColumn("recipient", lambda h: _muted(h.get("recipient")),
                     title="Destinatario"),
            DTColumn("status", lambda h: status_badge(h.get("status")),
                     sort="status", title="Esito"),
            DTColumn("error", lambda h: h.get("error") or "", title="Errore",
                     class_="text-body-secondary"),
        ],
        order=(0, "desc"), default_length=25, searching=False,
    )


# -- audit --------------------------------------------------------------------
def _audit_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("timestamp", lambda e: _link("audit.detail",
                                                  _localdt(e.get("timestamp")),
                                                  bold=False, entry_id=e.get("id")),
                     sort="timestamp", title="Data"),
            DTColumn("actor", lambda e: "{}:{}".format(e.get("actor_type", ""),
                                                       e.get("actor_id", "")),
                     sort="actor_type", title="Attore",
                     class_="text-body-secondary"),
            DTColumn("action", lambda e: Markup("<code>{}</code>").format(
                e.get("action", "")), sort="action", title="Azione"),
            DTColumn("entity_type", lambda e: _muted(e.get("entity_type")),
                     sort="entity_type", title="Entità"),
            DTColumn("outcome", lambda e: status_badge(e.get("outcome")),
                     sort="outcome", title="Esito"),
        ],
        order=(0, "desc"), default_length=25, searching=False,
    )


# -- logs ---------------------------------------------------------------------
def _logs_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("timestamp", lambda e: _localdt(e.get("timestamp")),
                     sort="timestamp", title="Data",
                     class_="text-body-secondary text-nowrap"),
            DTColumn("component", lambda e: _muted(e.get("component")),
                     sort="component", title="Componente"),
            DTColumn("level", lambda e: badge(e.get("level"),
                                              _LOG_LVL.get(e.get("level"),
                                                           "text-bg-secondary")),
                     sort="level", title="Livello"),
            DTColumn("logger", lambda e: _muted(e.get("logger")), title="Logger",
                     class_="text-body-secondary"),
            DTColumn("message", lambda e: _muted(e.get("message")),
                     title="Messaggio"),
        ],
        order=(0, "desc"), default_length=25,
    )


# -- alarms -------------------------------------------------------------------
def _alarms_actions(a: Mapping) -> Markup:
    from flask import url_for

    if can("commands.execute") and a.get("status") == "active":
        return Markup(
            '<form method="post" action="{}" class="d-inline-flex gap-1">'
            '<input name="note" class="form-control form-control-sm" '
            'style="width:12rem" placeholder="Nota (opzionale)">'
            '<button class="btn btn-sm btn-outline-primary" title="Riconosci allarme">'
            '<i class="bi bi-check2-square me-1"></i>Ack</button></form>'
        ).format(url_for("alarms.ack_alarm", alarm_id=a.get("id")))
    return Markup('<span class="text-body-secondary small">—</span>')


def _alarms_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("system_id", lambda a: _muted(a.get("system_id")),
                     title="Sistema"),
            DTColumn("probe_id", lambda a: _probe_name(a.get("probe_id")),
                     title="Sonda"),
            DTColumn("status", lambda a: status_badge(a.get("status")),
                     sort="status", title="Stato"),
            DTColumn("opened_at", lambda a: _localdt(a.get("opened_at")),
                     sort="opened_at", title="Aperto",
                     class_="text-body-secondary"),
            DTColumn("actions", _alarms_actions, title="Azioni",
                     th_class="text-end", class_="text-end"),
        ],
        order=(3, "desc"), default_length=25, searching=False,
    )


# -- heartbeats (dettaglio Sonda: /probes/{id}/heartbeats) --------------------
def _heartbeats_table() -> DTTable:
    return DTTable(
        columns=[
            DTColumn("@timestamp", lambda h: _localdt(h.get("@timestamp")),
                     sort="@timestamp", title="Timestamp",
                     class_="text-body-secondary"),
            DTColumn("system_name", lambda h: _muted(h.get("system_name")),
                     sort="system_name", title="Sistema"),
            DTColumn("check_name", lambda h: _muted(h.get("check_name")),
                     sort="check_name", title="Check"),
            DTColumn("status", lambda h: status_badge(h.get("status")),
                     sort="status", title="Stato"),
            DTColumn("response_ms", lambda h: h.get("response_ms"),
                     sort="response_ms", title="ms", th_class="text-end",
                     class_="text-end"),
            DTColumn("message", lambda h: h.get("message") or "",
                     title="Messaggio", class_="text-body-secondary"),
        ],
        order=(0, "desc"), default_length=50, searching=False,
    )


# --------------------------------------------------------------------------- #
# Registro risorse per la rotta generica /dt/<resource>
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Resource:
    path: str                     # endpoint di lista del backend
    permission: str               # permesso di lettura richiesto
    table: DTTable                # colonne + presentazione
    filters: Sequence[str] = ()   # chiavi filtro accettate da ajax.data


_RESOURCES: dict[str, _Resource] = {
    "users": _Resource("/users", "users.read", _users_table(),
                       ("status", "role")),
    "roles": _Resource("/roles", "roles.read", _roles_table()),
    "probes": _Resource("/probes", "probes.read", _probes_table(), ("status",)),
    "systems": _Resource("/systems", "systems.read", _systems_table(),
                         ("probe_id", "enabled", "kind")),
    "workflows": _Resource("/notification-workflows", "workflows.read",
                           _workflows_table(), ("enabled",)),
    "channels": _Resource("/notification-channels", "notifications.read",
                          _channels_table(), ("type", "enabled")),
    "deliveries": _Resource("/notifications/history", "notifications.read",
                            _deliveries_table(),
                            ("channel_id", "workflow_id", "status", "from", "to")),
    "audit": _Resource("/audit", "audit.read", _audit_table(),
                       ("actor", "action", "entity_type", "entity_id",
                        "outcome", "from", "to")),
    "logs": _Resource("/logs", "syslog.read", _logs_table(),
                      ("component", "probe_id", "level", "from", "to")),
    "alarms": _Resource("/alarms", "workflows.read", _alarms_table(),
                        ("status", "system_id", "probe_id", "from", "to")),
}

#: Tabelle esposte ai template per costruire thead + init JS (include heartbeats).
_TABLES: dict[str, DTTable] = {name: r.table for name, r in _RESOURCES.items()}
_TABLES["heartbeats"] = _heartbeats_table()


def table_meta(resource: str) -> dict:
    """Meta della tabella (thead + config JS) per l'uso nei template."""
    table = _TABLES.get(resource)
    if table is None:
        raise KeyError(resource)
    return table.meta()


def _collect_filters(names: Sequence[str]) -> dict:
    return {n: request.args.get(n) for n in names
            if request.args.get(n) not in (None, "")}


# --------------------------------------------------------------------------- #
# Rotte
# --------------------------------------------------------------------------- #
@bp.route("/dt/<resource>")
def dt_resource(resource: str):
    """Adattatore generico DataTables per le liste con endpoint paginato."""
    spec = _RESOURCES.get(resource)
    if spec is None:
        abort(404)
    if not is_authenticated():
        abort(401)
    if not has_any(user_permissions(), (spec.permission,)):
        abort(403)
    filters = _collect_filters(spec.filters)
    payload = serve(
        request.args, spec.table.columns,
        fetch=lambda params: api_get(spec.path, params=params),
        extra_filters=filters,
    )
    return jsonify(payload)


@bp.route("/dt/heartbeats/<probe_id>")
def dt_heartbeats(probe_id: str):
    """Adattatore heartbeat per il dettaglio Sonda (/probes/{id}/heartbeats)."""
    if not is_authenticated():
        abort(401)
    if not has_any(user_permissions(), ("heartbeats.read",)):
        abort(403)
    filters = _collect_filters(
        ("system_id", "check_id", "status", "from", "to"))
    table = _TABLES["heartbeats"]
    payload = serve(
        request.args, table.columns,
        fetch=lambda params: api_get(f"/probes/{probe_id}/heartbeats",
                                     params=params),
        extra_filters=filters,
    )
    return jsonify(payload)


def register_template_globals(app) -> None:
    """Espone ``dt_meta(resource)`` ai template Jinja."""
    app.jinja_env.globals["dt_meta"] = table_meta
