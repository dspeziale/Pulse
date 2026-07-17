"""Registrazione dei blueprint della dashboard Server."""
from __future__ import annotations

from flask import Flask

from . import (alarms, audit, auth, config_bp, dashboard, guida, identities,
               logs, notifications, permissions, probes, profile, query,
               report, roles, scans, systems, users, workflows)

_BLUEPRINTS = [
    auth.bp,
    dashboard.bp,
    probes.bp,
    systems.bp,
    report.bp,
    scans.bp,
    users.bp,
    roles.bp,
    permissions.bp,
    notifications.bp,
    workflows.bp,
    alarms.bp,
    identities.bp,
    audit.bp,
    logs.bp,
    config_bp.bp,
    profile.bp,
    query.bp,
    guida.bp,
]


def register_blueprints(app: Flask) -> None:
    for bp in _BLUEPRINTS:
        app.register_blueprint(bp)
