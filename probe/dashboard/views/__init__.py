"""Registrazione dei blueprint della dashboard Probe."""
from __future__ import annotations

from flask import Flask

from . import auth, dashboard, query, status

_BLUEPRINTS = [
    auth.bp,
    dashboard.bp,
    query.bp,
    status.bp,
]


def register_blueprints(app: Flask) -> None:
    for bp in _BLUEPRINTS:
        app.register_blueprint(bp)
