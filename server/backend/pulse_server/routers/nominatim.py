"""Gateway/tunnel verso Nominatim (aggiunta su richiesta utente).

Espone un proxy HTTP GET verso Nominatim con base URL FISSA da configurazione,
cosi' che Sonde e ALTRI SERVIZI (che NON raggiungono Nominatim) possano
geocodificare passando dal Server.

AUTENTICAZIONE DUALE (una delle due):
  (a) JWT Pulse valido (qualsiasi utente autenticato attivo) — riusa la logica di
      `deps.get_current_user`; OPPURE
  (b) header `X-API-Key` (o query param `api_key`) == `PULSE_NOMINATIM_API_KEY`,
      SE questa e' configurata (non vuota).
Se nessuna delle due -> 401. Cosi' Pulse UI/Sonde usano JWT o API key; gli altri
servizi (senza JWT Pulse) usano l'API key.

SICUREZZA:
  - la base URL e' FISSA (config `nominatim_url`): il chiamante controlla SOLO
    l'endpoint (allowlist) e i query params; host/schema NON sono modificabili;
  - endpoint non in allowlist -> 404;
  - l'eventuale `api_key` di autenticazione NON viene inoltrato a Nominatim.

RATE LIMIT / CACHE: gestiti dal `NominatimGateway` (throttle upstream ~1 req/s +
cache TTL in-process). Vedi `pulse_server/nominatim.py`.
"""

from __future__ import annotations

import hmac

import jwt
from fastapi import Request, Response
from fastapi.routing import APIRouter

from .. import errors
from ..context import NominatimGatewayDep
from ..deps import SessionDep, SettingsDep, get_current_user

router = APIRouter(prefix="/api/v1/nominatim", tags=["nominatim"])

# Allowlist degli endpoint Nominatim inoltrabili (host/schema restano fissi).
_ALLOWED_ENDPOINTS = frozenset({"search", "reverse", "lookup", "status", "details"})

# Nome del query param usato come API key (da NON inoltrare a Nominatim).
_API_KEY_PARAM = "api_key"


def _api_key_valid(request: Request, settings: SettingsDep) -> bool:
    """True se e' presente un'API key valida (header X-API-Key o query api_key).

    Ritorna False se la chiave non e' configurata (feature disabilitata) o se non
    corrisponde. Il confronto e' a tempo costante (anti timing attack).
    """
    configured = settings.nominatim_api_key
    if not configured:
        return False
    provided = request.headers.get("X-API-Key") or request.query_params.get(_API_KEY_PARAM)
    if not provided:
        return False
    return hmac.compare_digest(provided, configured)


def _jwt_valid(request: Request, session: SessionDep, settings: SettingsDep) -> bool:
    """True se la richiesta porta un JWT Pulse valido di utente attivo."""
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return False
    try:
        get_current_user(request, session, settings)
    except (errors.ApiError, jwt.PyJWTError):
        return False
    return True


def _authorize(request: Request, session: SessionDep, settings: SettingsDep) -> None:
    """Autorizza la richiesta via API key OPPURE JWT Pulse; altrimenti 401."""
    if _api_key_valid(request, settings):
        return
    if _jwt_valid(request, session, settings):
        return
    raise errors.unauthorized(
        "Credenziali mancanti o non valide: fornire un JWT Pulse o l'header X-API-Key."
    )


@router.get("/{endpoint}")
def nominatim_gateway(
    endpoint: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    gateway: NominatimGatewayDep,
) -> Response:
    """Inoltra una GET a `{nominatim_url}/{endpoint}` preservando la query string."""
    if endpoint not in _ALLOWED_ENDPOINTS:
        raise errors.not_found("Endpoint Nominatim non consentito.")
    _authorize(request, session, settings)
    # Preserva la query string del chiamante, rimuovendo SOLO l'eventuale api_key
    # (usata per l'auth del gateway, non un parametro Nominatim).
    query_items = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != _API_KEY_PARAM
    ]
    result = gateway.fetch(endpoint, query_items)
    return Response(
        content=result.content,
        status_code=result.status_code,
        media_type=result.content_type,
    )
