"""Esecuzione dei comandi in ingresso dai canali (07_workflow_notifiche.md §7).

Flusso: risoluzione identita' canale -> utente Pulse -> verifica permessi RBAC
-> esecuzione -> risposta testuale + log in inbound_commands.

Comandi supportati (§7.1): /help, /status, /silence, /unsilence, /ack, /probes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .deps import load_user_permissions
from .models import (
    Alarm,
    ChannelIdentity,
    InboundCommand,
    MaintenanceWindow,
    MonitoredSystem,
    Probe,
    User,
)

# Comando -> permessi richiesti (oltre a commands.execute implicito).
_COMMAND_PERMISSIONS: dict[str, set[str]] = {
    "/help": set(),
    "/status": {"heartbeats.read"},
    "/silence": {"workflows.update"},
    "/unsilence": {"workflows.update"},
    "/ack": set(),
    "/probes": {"probes.read"},
}

_HELP_TEXT = (
    "Comandi disponibili: /help, /status [system_id], /silence <system_id> <minuti>, "
    "/unsilence <system_id>, /ack <alarm_id>, /probes"
)


@dataclass
class CommandResult:
    outcome: str  # executed | denied | error
    response: str


def _parse(text: str) -> tuple[str, list[str]]:
    parts = text.strip().split()
    if not parts:
        return "", []
    cmd = parts[0].lower()
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    return cmd, parts[1:]


def resolve_user(session: Session, channel_type: str, external_id: str) -> User | None:
    identity = session.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.channel_type == channel_type,
            ChannelIdentity.external_id == external_id,
            ChannelIdentity.verified.is_(True),
        )
    ).scalar_one_or_none()
    if identity is None:
        return None
    return session.get(User, identity.user_id)


def execute_command(
    session: Session,
    *,
    channel_type: str,
    external_id: str,
    text: str,
) -> CommandResult:
    """Risolve identita', verifica permessi ed esegue il comando. Logga sempre."""
    cmd, args = _parse(text)
    now = dt.datetime.now(dt.timezone.utc)
    user = resolve_user(session, channel_type, external_id)

    if user is None:
        result = CommandResult("denied", "Identita' non associata a un utente Pulse.")
        _log(session, channel_type, external_id, None, cmd, args, result)
        return result
    if user.status != "active":
        result = CommandResult("denied", "Utente non attivo.")
        _log(session, channel_type, external_id, user.id, cmd, args, result)
        return result

    perms = load_user_permissions(session, user.id)
    if "commands.execute" not in perms:
        result = CommandResult("denied", "Permesso commands.execute mancante.")
        _log(session, channel_type, external_id, user.id, cmd, args, result)
        return result

    required = _COMMAND_PERMISSIONS.get(cmd)
    if required is None:
        result = CommandResult("error", f"Comando sconosciuto: {cmd}. {_HELP_TEXT}")
        _log(session, channel_type, external_id, user.id, cmd, args, result)
        return result
    if not required.issubset(perms):
        result = CommandResult("denied", f"Permessi insufficienti per {cmd}.")
        _log(session, channel_type, external_id, user.id, cmd, args, result)
        return result

    result = _dispatch(session, cmd, args, user, now)
    _log(session, channel_type, external_id, user.id, cmd, args, result)
    return result


def _dispatch(
    session: Session, cmd: str, args: list[str], user: User, now: dt.datetime
) -> CommandResult:
    if cmd == "/help":
        return CommandResult("executed", _HELP_TEXT)
    if cmd == "/status":
        return _cmd_status(session, args)
    if cmd == "/probes":
        return _cmd_probes(session)
    if cmd == "/ack":
        return _cmd_ack(session, args, user, now)
    if cmd == "/silence":
        return _cmd_silence(session, args, user, now)
    if cmd == "/unsilence":
        return _cmd_unsilence(session, args, now)
    return CommandResult("error", f"Comando non gestito: {cmd}")  # pragma: no cover


def _cmd_status(session: Session, args: list[str]) -> CommandResult:
    if not args:
        total = session.execute(select(MonitoredSystem)).scalars().all()
        return CommandResult("executed", f"Sistemi monitorati: {len(total)}")
    system = session.execute(
        select(MonitoredSystem).where(MonitoredSystem.system_id == args[0])
    ).scalar_one_or_none()
    if system is None:
        return CommandResult("error", f"Sistema non trovato: {args[0]}")
    active = session.execute(
        select(Alarm).where(Alarm.system_id == system.id, Alarm.status.in_(["active", "acknowledged"]))
    ).scalars().all()
    state = "in allarme" if active else "nessun allarme attivo"
    return CommandResult("executed", f"{system.system_name} ({system.system_id}): {state}")


def _cmd_probes(session: Session) -> CommandResult:
    probes = session.execute(select(Probe)).scalars().all()
    lines = [f"{p.name}: {p.status}" for p in probes]
    return CommandResult("executed", "\n".join(lines) if lines else "Nessuna Probe registrata.")


def _cmd_ack(session: Session, args: list[str], user: User, now: dt.datetime) -> CommandResult:
    if not args:
        return CommandResult("error", "Uso: /ack <alarm_id>")
    try:
        alarm_id = uuid.UUID(args[0])
    except ValueError:
        return CommandResult("error", "alarm_id non valido.")
    alarm = session.get(Alarm, alarm_id)
    if alarm is None:
        return CommandResult("error", "Allarme inesistente.")
    if alarm.status == "resolved":
        return CommandResult("error", "Allarme gia' risolto.")
    alarm.status = "acknowledged"
    alarm.acknowledged_at = now
    alarm.acknowledged_by = user.id
    return CommandResult("executed", f"Allarme {alarm_id} riconosciuto.")


def _cmd_silence(session: Session, args: list[str], user: User, now: dt.datetime) -> CommandResult:
    if len(args) < 2:
        return CommandResult("error", "Uso: /silence <system_id> <minuti>")
    system = session.execute(
        select(MonitoredSystem).where(MonitoredSystem.system_id == args[0])
    ).scalar_one_or_none()
    if system is None:
        return CommandResult("error", f"Sistema non trovato: {args[0]}")
    try:
        minutes = int(args[1])
    except ValueError:
        return CommandResult("error", "Durata (minuti) non valida.")
    if minutes <= 0:
        return CommandResult("error", "La durata deve essere positiva.")
    session.add(
        MaintenanceWindow(
            system_id=system.id,
            probe_id=system.probe_id,
            start_at=now,
            end_at=now + dt.timedelta(minutes=minutes),
            note=f"Silence via comando (utente {user.username})",
            created_by=user.id,
        )
    )
    return CommandResult("executed", f"Sistema {args[0]} silenziato per {minutes} minuti.")


def _cmd_unsilence(session: Session, args: list[str], now: dt.datetime) -> CommandResult:
    if not args:
        return CommandResult("error", "Uso: /unsilence <system_id>")
    system = session.execute(
        select(MonitoredSystem).where(MonitoredSystem.system_id == args[0])
    ).scalar_one_or_none()
    if system is None:
        return CommandResult("error", f"Sistema non trovato: {args[0]}")
    windows = session.execute(
        select(MaintenanceWindow).where(
            MaintenanceWindow.system_id == system.id, MaintenanceWindow.end_at > now
        )
    ).scalars().all()
    for win in windows:
        win.end_at = now
    return CommandResult("executed", f"Silenziamenti attivi rimossi per {args[0]}.")


def _log(
    session: Session,
    channel_type: str,
    external_id: str,
    user_id: uuid.UUID | None,
    cmd: str,
    args: list[str],
    result: CommandResult,
) -> None:
    session.add(
        InboundCommand(
            channel_type=channel_type,
            external_id=external_id,
            user_id=user_id,
            command=cmd or "(vuoto)",
            args={"args": args},
            outcome=result.outcome,
            response=result.response,
        )
    )
