"""Accesso al client HTTP del backend dalla richiesta Flask corrente.

Ogni chiamata usa l'access token JWT salvato in sessione. Funzioni sottili:
la logica di errore/redirect è centralizzata negli error handler dell'app.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from flask import current_app

from pulse_fe_common.auth import access_token
from pulse_fe_common.http_client import ApiClient


def client() -> ApiClient:
    return current_app.config["API_CLIENT"]


def api_get(path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
    return client().get(path, token=access_token(), params=params)


def api_post(path: str, json: Any = None) -> Any:
    return client().post(path, token=access_token(), json=json)


def api_put(path: str, json: Any = None) -> Any:
    return client().put(path, token=access_token(), json=json)


def api_delete(path: str, json: Any = None) -> Any:
    return client().delete(path, token=access_token(), json=json)


def query_args(*names: str) -> dict:
    """Estrae dalla query string i parametri indicati, scartando i vuoti."""
    from flask import request

    out: dict = {}
    for name in names:
        value = request.args.get(name)
        if value is not None and value != "":
            out[name] = value
    return out


def page_args() -> dict:
    """Parametri di paginazione standard (page, page_size)."""
    from flask import request

    out: dict = {}
    page = request.args.get("page")
    page_size = request.args.get("page_size")
    if page:
        out["page"] = page
    if page_size:
        out["page_size"] = page_size
    return out
