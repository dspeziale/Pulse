"""Client HTTP tipizzato verso le API REST del backend Pulse.

Usa httpx. Non contiene alcuna logica di business: si limita a effettuare la
chiamata, allegare l'header Authorization e normalizzare gli errori.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx


class ApiError(Exception):
    """Errore restituito dal backend (status >= 400, escluso 401)."""

    def __init__(self, status_code: int, code: str, message: str,
                 details: Optional[dict] = None) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class ApiAuthError(ApiError):
    """Autenticazione assente/scaduta (401): richiede nuovo login."""


class ApiUnavailableError(Exception):
    """Il backend non è raggiungibile (errore di rete/timeout)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ApiClient:
    """Wrapper minimale attorno a httpx per chiamare il backend.

    Ogni metodo accetta un ``token`` opzionale (access token JWT o probe token)
    che viene inviato come ``Authorization: Bearer <token>``.
    """

    def __init__(self, base_url: str, timeout: float = 10.0,
                 verify: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify = verify

    # -- costruzione richiesta -------------------------------------------------
    def _headers(self, token: Optional[str]) -> dict:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _parse(self, response: httpx.Response) -> Any:
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError:  # pragma: no cover - risposta non-JSON inattesa
            return None

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        body = self._parse(response) or {}
        err = body.get("error", {}) if isinstance(body, dict) else {}
        code = err.get("code", "ERROR")
        message = err.get("message", response.reason_phrase or "Errore")
        details = err.get("details", {})
        if response.status_code == 401:
            raise ApiAuthError(401, code, message, details)
        raise ApiError(response.status_code, code, message, details)

    # -- API pubblica ----------------------------------------------------------
    def request(self, method: str, path: str, *, token: Optional[str] = None,
                params: Optional[Mapping[str, Any]] = None,
                json: Any = None) -> Any:
        url = f"{self.base_url}{path}"
        clean_params = None
        if params is not None:
            clean_params = {k: v for k, v in params.items()
                            if v is not None and v != ""}
        try:
            response = httpx.request(
                method, url,
                headers=self._headers(token),
                params=clean_params,
                json=json,
                timeout=self.timeout,
                verify=self.verify,
            )
        except httpx.HTTPError as exc:
            raise ApiUnavailableError(str(exc)) from exc
        self._raise_for_status(response)
        return self._parse(response)

    def get(self, path: str, *, token: Optional[str] = None,
            params: Optional[Mapping[str, Any]] = None) -> Any:
        return self.request("GET", path, token=token, params=params)

    def post(self, path: str, *, token: Optional[str] = None,
             json: Any = None) -> Any:
        return self.request("POST", path, token=token, json=json)

    def put(self, path: str, *, token: Optional[str] = None,
            json: Any = None) -> Any:
        return self.request("PUT", path, token=token, json=json)

    def delete(self, path: str, *, token: Optional[str] = None,
               json: Any = None) -> Any:
        return self.request("DELETE", path, token=token, json=json)
