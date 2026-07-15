"""Scrittura audit log (immutabile, append-only — RNF-006) e log di sistema."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog, SystemLog


def write_audit(
    session: Session,
    *,
    actor_type: str,
    actor_id: str | None,
    action: str,
    outcome: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Inserisce una voce di audit. Non fa commit (lo fa il chiamante)."""
    entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        outcome=outcome,
        entity_type=entity_type,
        entity_id=entity_id,
        ip=ip,
        details=details,
    )
    session.add(entry)
    return entry


def write_system_log(
    session: Session,
    *,
    component: str,
    level: str,
    message: str,
    logger: str | None = None,
    probe_id: Any | None = None,
    context: dict[str, Any] | None = None,
) -> SystemLog:
    """Inserisce una voce di log di sistema (Server o Probe). Non fa commit."""
    entry = SystemLog(
        component=component,
        level=level,
        message=message,
        logger=logger,
        probe_id=probe_id,
        context=context,
    )
    session.add(entry)
    return entry
