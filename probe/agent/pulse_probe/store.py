"""Storage delle serie temporali heartbeat/eventi sulla Probe.

Due backend con la stessa interfaccia:
 - `InMemoryStore`: fallback locale (usato quando OpenSearch non e' configurato o
   non raggiungibile) e nei test;
 - `OpenSearchStore`: indicizza su OpenSearch locale (indici + mapping §5 del
   DOCUMENTO_DATABASE.md) e recupera i documenti filtrati, riusando il motore di
   query strutturata per aggregazioni/paginazione (semantica identica).

`build_store()` sceglie il backend: OpenSearch se raggiungibile, altrimenti
InMemory (comportamento degradato, documentato).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from . import query as q
from .config import Settings

logger = logging.getLogger("pulse_probe.store")

# Mapping degli indici OpenSearch (§5.1 heartbeat, §5.2 eventi).
HEARTBEAT_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "@timestamp": {"type": "date"},
            "system_id": {"type": "keyword"},
            "system_name": {"type": "keyword"},
            "check_id": {"type": "keyword"},
            "check_name": {"type": "keyword"},
            "status": {"type": "keyword"},
            "status_raw": {"type": "keyword"},
            "response_ms": {"type": "integer"},
            "message": {"type": "text"},
            "details": {"type": "text"},
            "probe_id": {"type": "keyword"},
            "reachable": {"type": "boolean"},
            "http_status": {"type": "integer"},
            "latency_ms": {"type": "integer"},
            "ingested_at": {"type": "date"},
        }
    }
}

EVENTS_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "@timestamp": {"type": "date"},
            "type": {"type": "keyword"},
            "system_id": {"type": "keyword"},
            "check_id": {"type": "keyword"},
            "status": {"type": "keyword"},
            "previous_status": {"type": "keyword"},
            "reachable": {"type": "boolean"},
            "probe_id": {"type": "keyword"},
        }
    }
}


class Store(Protocol):
    def index_heartbeats(self, docs: list[dict[str, Any]]) -> None: ...

    def index_events(self, events: list[dict[str, Any]]) -> None: ...

    def search_heartbeats(
        self,
        *,
        filters: list[dict[str, Any]] | None = None,
        frm: str | None = None,
        to: str | None = None,
        aggregations: list[dict[str, Any]] | None = None,
        sort: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]: ...

    def healthy(self) -> bool: ...


class InMemoryStore:
    """Backend in-memory: semplice, deterministico, usato come fallback/test."""

    def __init__(self) -> None:
        self._heartbeats: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []

    def index_heartbeats(self, docs: list[dict[str, Any]]) -> None:
        self._heartbeats.extend(docs)

    def index_events(self, events: list[dict[str, Any]]) -> None:
        self._events.extend(events)

    def search_heartbeats(
        self,
        *,
        filters: list[dict[str, Any]] | None = None,
        frm: str | None = None,
        to: str | None = None,
        aggregations: list[dict[str, Any]] | None = None,
        sort: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        return q.apply_query(
            self._heartbeats,
            filters=filters,
            frm=frm,
            to=to,
            aggregations=aggregations,
            sort=sort,
            page=page,
            page_size=page_size,
        )

    def healthy(self) -> bool:
        return True


class OpenSearchStore:  # pragma: no cover - richiede un cluster OpenSearch reale
    """Backend OpenSearch (opensearch-py). Indicizza e recupera i documenti.

    Le aggregazioni/paginazione sono calcolate dal motore di query strutturata
    sui documenti filtrati recuperati (cap `MAX_FETCH`), per semantica identica
    al backend in-memory.
    """

    MAX_FETCH = 10000

    def __init__(self, settings: Settings, client: Any) -> None:
        self._settings = settings
        self._client = client
        self._hb = settings.heartbeat_index
        self._ev = settings.events_index
        self._ensure_indices()

    def _ensure_indices(self) -> None:
        for name, mapping in ((self._hb, HEARTBEAT_MAPPING), (self._ev, EVENTS_MAPPING)):
            if not self._client.indices.exists(index=name):
                self._client.indices.create(index=name, body=mapping)

    def index_heartbeats(self, docs: list[dict[str, Any]]) -> None:
        for doc in docs:
            self._client.index(index=self._hb, body=doc)
        if docs:
            self._client.indices.refresh(index=self._hb)

    def index_events(self, events: list[dict[str, Any]]) -> None:
        for ev in events:
            self._client.index(index=self._ev, body=ev)
        if events:
            self._client.indices.refresh(index=self._ev)

    def search_heartbeats(
        self,
        *,
        filters: list[dict[str, Any]] | None = None,
        frm: str | None = None,
        to: str | None = None,
        aggregations: list[dict[str, Any]] | None = None,
        sort: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        body = {"size": self.MAX_FETCH, "query": {"match_all": {}}}
        resp = self._client.search(index=self._hb, body=body)
        docs = [hit["_source"] for hit in resp.get("hits", {}).get("hits", [])]
        return q.apply_query(
            docs,
            filters=filters,
            frm=frm,
            to=to,
            aggregations=aggregations,
            sort=sort,
            page=page,
            page_size=page_size,
        )

    def healthy(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:  # noqa: BLE001
            return False


def build_store(settings: Settings) -> Store:
    """Sceglie il backend: OpenSearch se raggiungibile, altrimenti in-memory."""
    if not settings.opensearch_url:
        logger.info("OpenSearch non configurato: uso storage in-memory (degradato).")
        return InMemoryStore()
    try:  # pragma: no cover - dipende da un cluster reale
        from opensearchpy import OpenSearch

        auth = None
        if settings.opensearch_user and settings.opensearch_password:
            auth = (settings.opensearch_user, settings.opensearch_password)
        client = OpenSearch(
            hosts=[settings.opensearch_url],
            http_auth=auth,
            verify_certs=settings.opensearch_verify_certs,
            ssl_show_warn=False,
        )
        if not client.ping():
            raise RuntimeError("ping fallito")
        return OpenSearchStore(settings, client)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        logger.warning("OpenSearch non raggiungibile (%s): fallback in-memory.", exc)
        return InMemoryStore()
