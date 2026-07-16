"""Modelli ORM SQLAlchemy mappati sulle tabelle di deploy/schema.sql.

I nomi tabella/colonna combaciano ESATTAMENTE con lo schema fisico del DBA.
Non ridefiniamo lo schema: questi modelli si limitano a mapparlo. Le colonne
con default lato DB (gen_random_uuid(), now()) usano server_default e vengono
popolate via RETURNING.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


_UUID_DEFAULT = text("gen_random_uuid()")
_NOW = text("now()")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)

    roles: Mapped[list["Role"]] = relationship(
        secondary="user_roles", back_populates="users", lazy="selectin"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)

    users: Mapped[list["User"]] = relationship(
        secondary="user_roles", back_populates="roles", lazy="selectin"
    )
    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", lazy="selectin", cascade="all, delete-orphan"
    )


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    area: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    assigned_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("permissions.code", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped["Role"] = relationship(back_populates="permissions")


class Probe(Base):
    __tablename__ = "probes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))
    query_endpoint: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    token_hash: Mapped[str | None] = mapped_column(String(255))
    certificate_fingerprint: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(40))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    config_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class EnrollmentToken(Base):
    __tablename__ = "enrollment_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    probe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class MonitoredSystem(Base):
    __tablename__ = "monitored_systems"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    system_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    system_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Tipo di controllo: 'http' (heartbeat HTTP su heartbeat_url) o 'tcp'
    # (connettivita' TCP su tcp_host:tcp_port). Vincoli di coerenza lato DB.
    kind: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'http'"))
    # NULLABLE: obbligatorio solo per kind='http' (chk_monitored_systems_kind).
    heartbeat_url: Mapped[str | None] = mapped_column(String(500))
    tcp_host: Mapped[str | None] = mapped_column(String(255))
    tcp_port: Mapped[int | None] = mapped_column(Integer)
    probe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("probes.id", ondelete="RESTRICT"), nullable=False
    )
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    response_ms_warn: Mapped[int | None] = mapped_column(Integer)
    response_ms_error: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitored_systems.id", ondelete="CASCADE")
    )
    probe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("probes.id", ondelete="CASCADE")
    )
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class DiscoveredCheck(Base):
    __tablename__ = "discovered_checks"
    __table_args__ = (UniqueConstraint("system_id", "check_id", name="uq_discovered_checks"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitored_systems.id", ondelete="CASCADE"), nullable=False
    )
    check_id: Mapped[str] = mapped_column(String(100), nullable=False)
    check_name: Mapped[str | None] = mapped_column(String(255))
    probe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("probes.id", ondelete="CASCADE")
    )
    last_status: Mapped[str | None] = mapped_column(String(40))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    inbound_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class NotificationWorkflow(Base):
    __tablename__ = "notification_workflows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    trigger: Mapped[str] = mapped_column("trigger", String(40), nullable=False)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    suppression: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)

    conditions: Mapped[list["WorkflowCondition"]] = relationship(
        back_populates="workflow", lazy="selectin", cascade="all, delete-orphan"
    )
    actions: Mapped[list["WorkflowAction"]] = relationship(
        back_populates="workflow", lazy="selectin", cascade="all, delete-orphan"
    )


class WorkflowCondition(Base):
    __tablename__ = "workflow_conditions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_workflows.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(String(100), nullable=False)
    op: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[Any | None] = mapped_column(JSONB)
    logic_group: Mapped[str | None] = mapped_column(String(20))
    order_index: Mapped[int | None] = mapped_column(Integer)

    workflow: Mapped["NotificationWorkflow"] = relationship(back_populates="conditions")


class WorkflowAction(Base):
    __tablename__ = "workflow_actions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_order", name="uq_workflow_actions_step"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_workflows.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_channels.id", ondelete="RESTRICT"), nullable=False
    )
    recipients: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    escalation_condition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    repeat: Mapped[dict[str, Any] | None] = mapped_column("repeat", JSONB)

    workflow: Mapped["NotificationWorkflow"] = relationship(back_populates="actions")


class Alarm(Base):
    __tablename__ = "alarms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_workflows.id", ondelete="SET NULL")
    )
    probe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("probes.id", ondelete="SET NULL")
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitored_systems.id", ondelete="SET NULL")
    )
    check_id: Mapped[str | None] = mapped_column(String(100))
    dedup_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    current_step: Mapped[int | None] = mapped_column(Integer)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_workflows.id", ondelete="SET NULL")
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_actions.id", ondelete="SET NULL")
    )
    alarm_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alarms.id", ondelete="SET NULL")
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_channels.id", ondelete="RESTRICT"), nullable=False
    )
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ChannelIdentity(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint("channel_type", "external_id", name="uq_channel_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verification_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class InboundCommand(Base):
    __tablename__ = "inbound_commands"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    command: Mapped[str] = mapped_column(String(100), nullable=False)
    args: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    response: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    timestamp: Mapped[dt.datetime] = mapped_column("timestamp", DateTime(timezone=True), server_default=_NOW)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    timestamp: Mapped[dt.datetime] = mapped_column("timestamp", DateTime(timezone=True), server_default=_NOW)
    component: Mapped[str] = mapped_column(String(20), nullable=False)
    probe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("probes.id", ondelete="SET NULL")
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    logger: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Configuration(Base):
    __tablename__ = "configuration"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any | None] = mapped_column(JSONB)
    type: Mapped[str | None] = mapped_column(String(40))
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    requires_restart: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    description: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class DbSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))


class ProbeRollup(Base):
    __tablename__ = "probe_rollups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT)
    probe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False
    )
    window: Mapped[str | None] = mapped_column("window", String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
