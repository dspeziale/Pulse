"""Fixture di test: Postgres effimero via Docker + isolamento per-test.

Strategia:
 - una sola istanza Postgres (session scope) su porta dedicata; schema.sql e
   seed.sql applicati una volta e committati (seed sempre presente nei test);
 - ogni test gira dentro una transazione esterna con savepoint
   (join_transaction_mode="create_savepoint"): i commit del codice sotto test
   rilasciano solo i savepoint, mentre il rollback finale ripulisce tutto,
   garantendo isolamento senza perdere il seed.

Se Docker non e' disponibile o `PULSE_TEST_DATABASE_URL` non e' impostata, la
suite viene saltata (skip) con messaggio esplicativo.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import time
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SCHEMA = _REPO_ROOT / "deploy" / "schema.sql"
_SEED = _REPO_ROOT / "deploy" / "seed.sql"

_CONTAINER = f"pulse-test-pg-{uuid.uuid4().hex[:8]}"
_PORT = int(os.environ.get("PULSE_TEST_PG_PORT", "5433"))
_DB_URL_ENV = "PULSE_TEST_DATABASE_URL"


def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"], check=True, capture_output=True, timeout=30
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _apply_sql_via_psql(container: str, path: pathlib.Path) -> None:
    """Applica un file SQL eseguendo psql DENTRO il container.

    Evita l'interpretazione dei '%' (usati in RAISE EXCEPTION) come placeholder
    da parte del driver psycopg lato client.
    """
    with open(path, "rb") as fh:
        subprocess.run(
            [
                "docker", "exec", "-i", container,
                "psql", "-U", "pulse", "-d", "pulse", "-v", "ON_ERROR_STOP=1", "-q",
            ],
            stdin=fh,
            check=True,
            capture_output=True,
        )


def _apply_sql_via_engine(engine: Engine, path: pathlib.Path) -> None:
    """Fallback per DB esterno: esegue lo script grezzo via driver DBAPI.

    Usa una connessione DBAPI in autocommit e cursor.execute() sul testo intero
    (psycopg accetta piu' statement in un'unica execute senza parametri).
    """
    sql = path.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        raw.autocommit = True  # type: ignore[attr-defined]
        with raw.cursor() as cur:
            cur.execute(sql)  # type: ignore[arg-type]
    finally:
        raw.close()


def _wait_ready(url: str, attempts: int = 60) -> Engine:
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            engine = create_engine(url, future=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return engine
        except Exception as exc:  # noqa: BLE001 - retry finche' il DB e' pronto
            last_exc = exc
            time.sleep(1.0)
    raise RuntimeError(f"Postgres non pronto: {last_exc}")


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    external = os.environ.get(_DB_URL_ENV)
    started_container = False
    if external:
        url = external
    else:
        if not _docker_available():
            pytest.skip("Docker non disponibile e PULSE_TEST_DATABASE_URL non impostata.")
        subprocess.run(
            [
                "docker", "run", "-d", "--name", _CONTAINER,
                "-e", "POSTGRES_USER=pulse",
                "-e", "POSTGRES_PASSWORD=pulse",
                "-e", "POSTGRES_DB=pulse",
                "-p", f"{_PORT}:5432",
                "postgres:16",
            ],
            check=True,
            capture_output=True,
        )
        started_container = True
        url = f"postgresql+psycopg://pulse:pulse@localhost:{_PORT}/pulse"

    try:
        engine = _wait_ready(url)
        if started_container:
            _apply_sql_via_psql(_CONTAINER, _SCHEMA)
            _apply_sql_via_psql(_CONTAINER, _SEED)
        else:
            _apply_sql_via_engine(engine, _SCHEMA)
            _apply_sql_via_engine(engine, _SEED)
        yield engine
        engine.dispose()
    finally:
        if started_container:
            subprocess.run(["docker", "rm", "-f", _CONTAINER], capture_output=True)


@pytest.fixture()
def db_session(db_engine: Engine) -> Iterator[Session]:
    connection = db_engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture()
def client(db_session: Session):
    """TestClient FastAPI con get_session sovrascritta dalla sessione di test."""
    from fastapi.testclient import TestClient

    from pulse_server.db import get_session
    from pulse_server.main import create_app

    app = create_app()

    def _override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_token(client) -> str:
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "ChangeMe123!"}
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


@pytest.fixture()
def auth_headers(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}
