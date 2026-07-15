"""Connessione PostgreSQL (SQLAlchemy 2.0, sync + psycopg)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Restituisce (creandolo una volta) l'engine SQLAlchemy."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionFactory


def set_engine(engine: Engine) -> None:
    """Override dell'engine (usato dai test per puntare a un DB dedicato)."""
    global _engine, _SessionFactory
    _engine = engine
    _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """Dependency FastAPI: apre una sessione per richiesta e la chiude."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
