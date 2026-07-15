"""Utilità RBAC lato UI.

Il catalogo autorevole dei permessi è ``deploy/seed.sql`` (40 codici). Qui non
si duplica il catalogo: si verifica soltanto se l'insieme di permessi restituito
dal backend (via ``GET /api/v1/auth/me`` / login) contiene un dato codice.
"""
from __future__ import annotations

from typing import Iterable, Sequence


def has_permission(permissions: Iterable[str] | None, code: str) -> bool:
    """True se ``code`` è presente nell'insieme di permessi dell'utente."""
    if not permissions:
        return False
    return code in set(permissions)


def has_any(permissions: Iterable[str] | None, codes: Sequence[str]) -> bool:
    """True se l'utente possiede almeno uno dei ``codes`` indicati."""
    if not permissions:
        return False
    owned = set(permissions)
    return any(c in owned for c in codes)
