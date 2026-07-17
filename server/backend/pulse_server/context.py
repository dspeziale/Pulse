"""Provider di dipendenze condivise (SecretBox, ProbeQueryClient)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from .config import Settings, get_settings
from .nominatim import NominatimGateway
from .proxy import ProbeQueryClient
from .security import SecretBox


@lru_cache(maxsize=1)
def _cached_secret_box(key_material: str) -> SecretBox:
    return SecretBox(key_material)


def get_secret_box(settings: Annotated[Settings, Depends(get_settings)]) -> SecretBox:
    material = settings.secrets_encryption_key or settings.jwt_secret
    return _cached_secret_box(material)


def get_probe_client(settings: Annotated[Settings, Depends(get_settings)]) -> ProbeQueryClient:
    return ProbeQueryClient(settings)


# Il gateway Nominatim e' un SINGLETON di processo: throttle (rate-limit upstream)
# e cache TTL devono persistere fra le richieste.
_nominatim_gateway: NominatimGateway | None = None


def get_nominatim_gateway(
    settings: Annotated[Settings, Depends(get_settings)],
) -> NominatimGateway:
    global _nominatim_gateway
    if _nominatim_gateway is None:
        _nominatim_gateway = NominatimGateway(settings)
    return _nominatim_gateway


SecretBoxDep = Annotated[SecretBox, Depends(get_secret_box)]
ProbeClientDep = Annotated[ProbeQueryClient, Depends(get_probe_client)]
NominatimGatewayDep = Annotated[NominatimGateway, Depends(get_nominatim_gateway)]
