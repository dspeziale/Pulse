"""Test del dispatcher comandi in ingresso (commands.py)."""

from __future__ import annotations

import datetime as dt
import uuid

from pulse_server.commands import execute_command
from pulse_server.models import (
    Alarm,
    ChannelIdentity,
    MonitoredSystem,
    Probe,
    Role,
    User,
    UserRole,
)
from pulse_server.security import hash_password

SUPERADMIN_ROLE = uuid.UUID("00000000-0000-0000-0000-000000000001")
VIEWER_ROLE = uuid.UUID("00000000-0000-0000-0000-000000000004")


def _user(session, username, role_id=SUPERADMIN_ROLE, status="active"):
    u = User(
        username=username, email=f"{username}@x.local", full_name="",
        password_hash=hash_password("Password123!"), status=status,
    )
    session.add(u)
    session.flush()
    session.add(UserRole(user_id=u.id, role_id=role_id))
    session.flush()
    return u


def _identity(session, user, ext, ctype="telegram"):
    session.add(ChannelIdentity(user_id=user.id, channel_type=ctype, external_id=ext, verified=True))
    session.flush()


def test_unassociated_identity_denied(db_session) -> None:
    res = execute_command(db_session, channel_type="telegram", external_id="ghost", text="/help")
    assert res.outcome == "denied"


def test_inactive_user_denied(db_session) -> None:
    u = _user(db_session, "inactive", status="disabled")
    _identity(db_session, u, "ext-inactive")
    res = execute_command(db_session, channel_type="telegram", external_id="ext-inactive", text="/help")
    assert res.outcome == "denied"


def test_missing_commands_execute_denied(db_session) -> None:
    # Viewer non ha commands.execute
    u = _user(db_session, "viewercmd", role_id=VIEWER_ROLE)
    _identity(db_session, u, "ext-viewer")
    res = execute_command(db_session, channel_type="telegram", external_id="ext-viewer", text="/help")
    assert res.outcome == "denied"


def test_unknown_command(db_session) -> None:
    u = _user(db_session, "sa1")
    _identity(db_session, u, "ext-sa1")
    res = execute_command(db_session, channel_type="telegram", external_id="ext-sa1", text="/bogus")
    assert res.outcome == "error"


def test_help_ok(db_session) -> None:
    u = _user(db_session, "sa2")
    _identity(db_session, u, "ext-sa2")
    res = execute_command(db_session, channel_type="telegram", external_id="ext-sa2", text="/help")
    assert res.outcome == "executed" and "/status" in res.response


def test_empty_text(db_session) -> None:
    u = _user(db_session, "sa-empty")
    _identity(db_session, u, "ext-empty")
    res = execute_command(db_session, channel_type="telegram", external_id="ext-empty", text="   ")
    assert res.outcome == "error"


def test_status_and_probes(db_session) -> None:
    u = _user(db_session, "sa3")
    _identity(db_session, u, "ext-sa3")
    probe = Probe(name="cmd-probe", status="online", tags=[])
    db_session.add(probe)
    db_session.flush()
    system = MonitoredSystem(
        system_id="cmd-sys", system_name="Sys", heartbeat_url="https://s/api/heartbeat",
        probe_id=probe.id, poll_interval_seconds=30, timeout_seconds=5, enabled=True,
    )
    db_session.add(system)
    db_session.flush()

    all_status = execute_command(db_session, channel_type="telegram", external_id="ext-sa3", text="/status")
    assert all_status.outcome == "executed"
    one = execute_command(db_session, channel_type="telegram", external_id="ext-sa3", text="/status cmd-sys")
    assert one.outcome == "executed" and "nessun allarme" in one.response
    missing = execute_command(db_session, channel_type="telegram", external_id="ext-sa3", text="/status ghost")
    assert missing.outcome == "error"
    probes = execute_command(db_session, channel_type="telegram", external_id="ext-sa3", text="/probes")
    assert probes.outcome == "executed" and "cmd-probe" in probes.response


def test_ack_command(db_session) -> None:
    u = _user(db_session, "sa4")
    _identity(db_session, u, "ext-sa4")
    alarm = Alarm(status="active", dedup_key="cmd", opened_at=dt.datetime.now(dt.timezone.utc))
    db_session.add(alarm)
    db_session.flush()

    assert execute_command(db_session, channel_type="telegram", external_id="ext-sa4", text="/ack").outcome == "error"
    assert execute_command(db_session, channel_type="telegram", external_id="ext-sa4", text="/ack not-uuid").outcome == "error"
    ghost = execute_command(db_session, channel_type="telegram", external_id="ext-sa4", text=f"/ack {uuid.uuid4()}")
    assert ghost.outcome == "error"
    ok = execute_command(db_session, channel_type="telegram", external_id="ext-sa4", text=f"/ack {alarm.id}")
    assert ok.outcome == "executed"
    db_session.flush()
    assert alarm.status == "acknowledged"
    # allarme risolto -> nuovo ack rifiutato
    alarm.status = "resolved"
    db_session.flush()
    resolved = execute_command(db_session, channel_type="telegram", external_id="ext-sa4", text=f"/ack {alarm.id}")
    assert resolved.outcome == "error"


def test_silence_unsilence(db_session) -> None:
    u = _user(db_session, "sa5")
    _identity(db_session, u, "ext-sa5")
    probe = Probe(name="sil-probe", status="online", tags=[])
    db_session.add(probe)
    db_session.flush()
    system = MonitoredSystem(
        system_id="sil-sys", system_name="Sys", heartbeat_url="https://s/api/heartbeat",
        probe_id=probe.id, poll_interval_seconds=30, timeout_seconds=5, enabled=True,
    )
    db_session.add(system)
    db_session.flush()

    assert execute_command(db_session, channel_type="telegram", external_id="ext-sa5", text="/silence sil-sys").outcome == "error"
    assert execute_command(db_session, channel_type="telegram", external_id="ext-sa5", text="/silence ghost 10").outcome == "error"
    assert execute_command(db_session, channel_type="telegram", external_id="ext-sa5", text="/silence sil-sys abc").outcome == "error"
    assert execute_command(db_session, channel_type="telegram", external_id="ext-sa5", text="/silence sil-sys -5").outcome == "error"
    ok = execute_command(db_session, channel_type="telegram", external_id="ext-sa5", text="/silence sil-sys 30")
    assert ok.outcome == "executed"

    assert execute_command(db_session, channel_type="telegram", external_id="ext-sa5", text="/unsilence").outcome == "error"
    assert execute_command(db_session, channel_type="telegram", external_id="ext-sa5", text="/unsilence ghost").outcome == "error"
    uns = execute_command(db_session, channel_type="telegram", external_id="ext-sa5", text="/unsilence sil-sys")
    assert uns.outcome == "executed"


def test_status_requires_heartbeats_read(db_session) -> None:
    # Operator ha heartbeats.read; creiamo un ruolo con solo commands.execute
    role = Role(name="cmd-only", description="", is_builtin=False)
    db_session.add(role)
    db_session.flush()
    from pulse_server.models import RolePermission

    db_session.add(RolePermission(role_id=role.id, permission_code="commands.execute"))
    db_session.flush()
    u = _user(db_session, "cmdonly", role_id=role.id)
    _identity(db_session, u, "ext-cmdonly")
    res = execute_command(db_session, channel_type="telegram", external_id="ext-cmdonly", text="/status")
    assert res.outcome == "denied"
