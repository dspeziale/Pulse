"""Provider di dipendenze condivise (SecretBox, ProbeQueryClient)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from .config import Settings, get_settings
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


SecretBoxDep = Annotated[SecretBox, Depends(get_secret_box)]
ProbeClientDep = Annotated[ProbeQueryClient, Depends(get_probe_client)]
