"""Accesso al probe-agent (API di query locale) dalla dashboard Probe.

Le chiamate usano il token del probe-agent configurato via env (decisione FE-03):
la dashboard Probe è un client locale che interroga gli endpoint della PROBE
(`/api/v1/*`, sezione BACKEND del DOCUMENTO_API — "Endpoint sulla PROBE").
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from flask import current_app, request

from pulse_fe_common.http_client import ApiClient


def client() -> ApiClient:
    return current_app.config["API_CLIENT"]


def _token() -> str:
    return current_app.config["PULSE_CFG"].agent_token


def api_get(path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
    return client().get(path, token=_token(), params=params)


def api_post(path: str, json: Any = None) -> Any:
    return client().post(path, token=_token(), json=json)


def query_args(*names: str) -> dict:
    out: dict = {}
    for name in names:
        value = request.args.get(name)
        if value is not None and value != "":
            out[name] = value
    return out


def page_args() -> dict:
    out: dict = {}
    for name in ("page", "page_size"):
        value = request.args.get(name)
        if value:
            out[name] = value
    return out
