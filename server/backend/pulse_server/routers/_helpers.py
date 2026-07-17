"""Utility comuni ai router: paginazione, parsing UUID, gestione conflitti."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session

from .. import errors


def sort_clause(
    sort: str | None,
    allowed: Mapping[str, InstrumentedAttribute[Any]],
    default: ColumnElement[Any],
) -> ColumnElement[Any]:
    """Traduce un parametro `sort` in una clausola ORDER BY (esteso: DataTables).

    Formato di `sort`: `campo` (ascendente) oppure `-campo` (discendente). Se il
    campo (dopo l'eventuale prefisso '-') non e' nella whitelist `allowed`, o se
    `sort` e' assente/vuoto, ritorna `default` (nessun errore: robustezza).
    """
    if not sort:
        return default
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    column = allowed.get(field)
    if column is None:
        return default
    return column.desc() if descending else column.asc()


def clamp_pagination(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    return page, page_size


def offset(page: int, page_size: int) -> int:
    return (page - 1) * page_size


def parse_uuid(value: str, *, what: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise errors.not_found(f"{what} non valido o inesistente.")


def commit_or_conflict(session: Session, *, message: str, details: dict[str, Any] | None = None) -> None:
    """Esegue il commit convertendo le violazioni di integrita' in 409."""
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise errors.conflict(message, details or {"db": str(exc.orig)})


def flush_or_conflict(session: Session, *, message: str, details: dict[str, Any] | None = None) -> None:
    """Esegue il flush convertendo le violazioni di integrita' (es. UNIQUE) in 409.

    Necessario nei create che devono ottenere l'id generato (per righe figlie)
    prima del commit finale: la violazione emergerebbe al flush, non al commit.
    """
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise errors.conflict(message, details or {"db": str(exc.orig)})
