"""Test residui: init db lazy, comando senza slash, update canale name/inbound."""

from __future__ import annotations


def test_db_lazy_initialization(db_engine) -> None:
    from pulse_server import db

    # forza il ramo di creazione lazy di engine e session factory
    db._engine = None
    db._SessionFactory = None
    engine = db.get_engine()
    assert engine is not None
    factory = db.get_session_factory()
    assert factory is not None
    # ripristina l'engine di test per gli altri test della sessione
    db.set_engine(db_engine)


def test_command_without_leading_slash(db_session) -> None:
    from pulse_server.commands import execute_command
    from pulse_server.models import ChannelIdentity, User, UserRole
    from pulse_server.security import hash_password
    import uuid

    u = User(username="noslash", email="noslash@x", full_name="", password_hash=hash_password("Password123!"), status="active")
    db_session.add(u)
    db_session.flush()
    db_session.add(UserRole(user_id=u.id, role_id=uuid.UUID("00000000-0000-0000-0000-000000000001")))
    db_session.add(ChannelIdentity(user_id=u.id, channel_type="telegram", external_id="ns-1", verified=True))
    db_session.flush()
    # "help" senza slash deve essere normalizzato a "/help"
    res = execute_command(db_session, channel_type="telegram", external_id="ns-1", text="help")
    assert res.outcome == "executed"


def test_channel_update_name_and_inbound(client, auth_headers) -> None:
    cid = client.post(
        "/api/v1/notification-channels",
        headers=auth_headers,
        json={"name": "ch-name", "type": "telegram", "enabled": True, "inbound_enabled": False, "config": {"bot_token": "t", "webhook_secret": "s"}},
    ).json()["id"]
    r = client.put(
        f"/api/v1/notification-channels/{cid}",
        headers=auth_headers,
        json={"name": "ch-renamed", "inbound_enabled": True},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "ch-renamed" and r.json()["inbound_enabled"] is True
