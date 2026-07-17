"""Schemi Pydantic v2 (request/response) aderenti al DOCUMENTO_API.md.

Ogni modello rispecchia campi/tipi definiti nel contratto API. I timestamp sono
serializzati in ISO-8601 (timezone-aware UTC dal DB timestamptz).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError


class _Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ============================ Auth =========================================


class LoginRequest(_Model):
    username: str
    password: str


class LoginUser(_Model):
    id: str
    username: str
    roles: list[str]
    permissions: list[str]


class LoginResponse(_Model):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: LoginUser


class RefreshRequest(_Model):
    refresh_token: str


class RefreshResponse(_Model):
    access_token: str
    expires_in: int


class LogoutRequest(_Model):
    refresh_token: str


class MeResponse(_Model):
    id: str
    username: str
    email: str
    full_name: str | None
    roles: list[str]
    permissions: list[str]
    status: str


class ChangePasswordRequest(_Model):
    current_password: str
    new_password: str = Field(min_length=8)


# ============================ Utenti =======================================


class UserOut(_Model):
    id: str
    username: str
    email: str
    full_name: str | None
    status: str
    roles: list[str]
    created_at: dt.datetime
    updated_at: dt.datetime
    last_login_at: dt.datetime | None


class UserList(_Model):
    items: list[UserOut]
    total: int
    page: int
    page_size: int


class UserCreate(_Model):
    username: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=255)
    full_name: str | None = None
    password: str = Field(min_length=8)
    role_ids: list[str] = Field(default_factory=list)
    status: Literal["active", "disabled"] = "active"


class UserUpdate(_Model):
    email: EmailStr | None = None
    full_name: str | None = None
    status: Literal["active", "disabled", "locked"] | None = None


class UserRolesUpdate(_Model):
    role_ids: list[str]


class ResetPasswordRequest(_Model):
    new_password: str = Field(min_length=8)


# ============================ Ruoli ========================================


class RoleOut(_Model):
    id: str
    name: str
    description: str | None
    is_builtin: bool
    permissions: list[str]
    created_at: dt.datetime


class RoleList(_Model):
    items: list[RoleOut]
    total: int


class RoleCreate(_Model):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(_Model):
    name: str | None = None
    description: str | None = None


class RolePermissionsUpdate(_Model):
    permission_codes: list[str]


# ============================ Permessi =====================================


class PermissionOut(_Model):
    code: str
    area: str
    description: str


class PermissionList(_Model):
    items: list[PermissionOut]


# ============================ Probe ========================================


# Converte una stringa vuota/whitespace in None per contact_email, cosi' un campo
# lasciato vuoto dal FE non genera un 422 su EmailStr (esteso su richiesta utente).
def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class ProbeOut(_Model):
    id: str
    name: str
    description: str | None
    query_endpoint: str | None
    tags: list[Any]
    location: str | None
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    enabled: bool
    status: str
    last_seen_at: dt.datetime | None
    version: str | None
    systems_count: int
    created_at: dt.datetime


class ProbeList(_Model):
    items: list[ProbeOut]
    total: int


class ProbeCreate(_Model):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    query_endpoint: str | None = None
    tags: list[str] = Field(default_factory=list)
    location: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: EmailStr | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)
    enabled: bool = True

    _norm_email = field_validator("contact_email", mode="before")(_blank_to_none)


class ProbeUpdate(_Model):
    name: str | None = None
    description: str | None = None
    query_endpoint: str | None = None
    tags: list[str] | None = None
    location: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: EmailStr | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)
    enabled: bool | None = None

    _norm_email = field_validator("contact_email", mode="before")(_blank_to_none)


class EnrollmentInfo(_Model):
    enrollment_token: str
    enrollment_expires_at: dt.datetime


class ProbeCreateResponse(_Model):
    probe: ProbeOut
    enrollment_token: str
    enrollment_expires_at: dt.datetime


class ProbeStatusOut(_Model):
    id: str
    status: str
    last_seen_at: dt.datetime | None
    version: str | None
    last_sync_at: dt.datetime | None
    last_error: str | None


# ============================ Sistemi ======================================


class Thresholds(_Model):
    response_ms_warn: int | None = None
    response_ms_error: int | None = None


class MaintenanceWindowIn(_Model):
    start: dt.datetime
    end: dt.datetime
    note: str | None = None


class MaintenanceWindowOut(_Model):
    start: dt.datetime
    end: dt.datetime
    note: str | None = None


# Tipo di controllo di un sistema monitorato (esteso su richiesta utente).
SystemKind = Literal["http", "tcp"]


def _require_http_url(value: str) -> None:
    """Valida che `value` sia un URL http/https con host (solleva altrimenti)."""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PydanticCustomError(
            "value_error", "heartbeat_url deve essere un URL http/https valido."
        )


def _validate_system_kind(
    kind: str,
    heartbeat_url: str | None,
    tcp_host: str | None,
    tcp_port: int | None,
) -> None:
    """Valida la coerenza dei campi in base a `kind` (esteso su richiesta utente).

    - `http`: `heartbeat_url` obbligatorio (e valido).
    - `tcp` : `tcp_host` e `tcp_port` (1..65535) obbligatori.
    Solleva PydanticCustomError (mappato a 422 dal handler) in caso di incoerenza.
    """
    if tcp_port is not None and not (1 <= tcp_port <= 65535):
        raise PydanticCustomError(
            "value_error", "tcp_port deve essere compreso tra 1 e 65535."
        )
    if kind == "http":
        if not heartbeat_url:
            raise PydanticCustomError(
                "value_error", "heartbeat_url e' obbligatorio per kind='http'."
            )
        _require_http_url(heartbeat_url)
    else:  # kind == "tcp"
        if not tcp_host:
            raise PydanticCustomError(
                "value_error", "tcp_host e' obbligatorio per kind='tcp'."
            )
        if tcp_port is None:
            raise PydanticCustomError(
                "value_error", "tcp_port e' obbligatorio per kind='tcp'."
            )


class SystemOut(_Model):
    id: str
    system_id: str
    system_name: str
    kind: SystemKind
    heartbeat_url: str | None
    tcp_host: str | None
    tcp_port: int | None
    probe_id: str
    poll_interval_seconds: int
    timeout_seconds: int
    enabled: bool
    thresholds: Thresholds
    maintenance_windows: list[MaintenanceWindowOut]
    created_at: dt.datetime


class SystemList(_Model):
    items: list[SystemOut]
    total: int


class SystemCreate(_Model):
    system_id: str = Field(min_length=1, max_length=100)
    system_name: str = Field(min_length=1, max_length=255)
    kind: SystemKind = "http"
    heartbeat_url: str | None = Field(default=None, max_length=500)
    tcp_host: str | None = Field(default=None, max_length=255)
    tcp_port: int | None = None
    probe_id: str
    poll_interval_seconds: int = Field(gt=0)
    timeout_seconds: int = Field(gt=0)
    enabled: bool = True
    thresholds: Thresholds | None = None
    maintenance_windows: list[MaintenanceWindowIn] | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> "SystemCreate":
        _validate_system_kind(self.kind, self.heartbeat_url, self.tcp_host, self.tcp_port)
        return self


class SystemUpdate(_Model):
    system_name: str | None = None
    kind: SystemKind | None = None
    heartbeat_url: str | None = Field(default=None, max_length=500)
    tcp_host: str | None = Field(default=None, max_length=255)
    tcp_port: int | None = None
    probe_id: str | None = None
    poll_interval_seconds: int | None = Field(default=None, gt=0)
    timeout_seconds: int | None = Field(default=None, gt=0)
    enabled: bool | None = None
    thresholds: Thresholds | None = None
    maintenance_windows: list[MaintenanceWindowIn] | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> "SystemUpdate":
        """Valida la coerenza risultante quando i campi rilevanti sono forniti.

        Update parziale: se `kind` e' fornito, i campi obbligatori del nuovo tipo
        devono essere presenti nella stessa richiesta. `tcp_port` (se fornito) e'
        sempre validato nel range 1..65535.
        """
        if self.tcp_port is not None and not (1 <= self.tcp_port <= 65535):
            raise PydanticCustomError(
                "value_error", "tcp_port deve essere compreso tra 1 e 65535."
            )
        if self.kind is not None:
            _validate_system_kind(
                self.kind, self.heartbeat_url, self.tcp_host, self.tcp_port
            )
        elif self.heartbeat_url is not None:
            _require_http_url(self.heartbeat_url)
        return self


class SystemTestRequest(_Model):
    """Richiesta di test di un sistema (aggiunta/estesa su richiesta utente).

    Non persiste nulla. Per `kind='http'` esegue una GET diagnostica verso
    `heartbeat_url`; per `kind='tcp'` apre una connessione TCP a `tcp_host:tcp_port`.
    """

    kind: SystemKind = "http"
    heartbeat_url: str | None = Field(default=None, max_length=500)
    tcp_host: str | None = Field(default=None, max_length=255)
    tcp_port: int | None = None
    timeout_seconds: int = Field(default=5, ge=1, le=60)

    @model_validator(mode="after")
    def _check_kind(self) -> "SystemTestRequest":
        _validate_system_kind(self.kind, self.heartbeat_url, self.tcp_host, self.tcp_port)
        return self


class SystemTestDocument(_Model):
    """Documento canonico Pulse estratto dalla risposta del target."""

    system_id: str
    system_name: str | None = None
    check_id: str
    check_name: str | None = None
    status: str
    response_ms: float | None = None
    message: str | None = None


class SystemTestResponse(_Model):
    """Esito del test dell'endpoint heartbeat (aggiunta su richiesta utente)."""

    reachable: bool
    http_status: int | None
    response_ms: int
    valid_schema: bool
    checks_count: int
    documents: list[SystemTestDocument]
    error: str | None


class CheckOut(_Model):
    check_id: str
    check_name: str | None
    last_status: str | None
    last_seen_at: dt.datetime | None


class SystemChecksList(_Model):
    items: list[CheckOut]


class GlobalCheckOut(_Model):
    system_id: str
    check_id: str
    check_name: str | None
    probe_id: str | None
    last_status: str | None
    last_seen_at: dt.datetime | None


class GlobalChecksList(_Model):
    items: list[GlobalCheckOut]
    total: int


# ============================ Heartbeat / Query ============================


class Heartbeat(_Model):
    timestamp: str = Field(alias="@timestamp")
    system_id: str
    system_name: str | None = None
    check_id: str
    check_name: str | None = None
    status: str
    response_ms: int | None = None
    message: str | None = None
    details: str | None = None
    probe_id: str
    reachable: bool
    http_status: int | None = None
    latency_ms: int | None = None
    ingested_at: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class HeartbeatList(_Model):
    items: list[dict[str, Any]]
    total: int


class QueryFilter(_Model):
    field: str
    op: str
    value: Any


class QueryAggregation(_Model):
    type: Literal["avg", "min", "max", "count", "uptime"]
    field: str | None = None
    interval: str | None = None


class QueryRequest(_Model):
    filters: list[QueryFilter] = Field(default_factory=list)
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    aggregations: list[QueryAggregation] | None = None
    page: int | None = None
    page_size: int | None = None
    sort: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class QueryResponse(_Model):
    items: list[dict[str, Any]]
    aggregations: dict[str, Any]
    total: int


# ==================== Scansioni NMAP (proxy verso Probe) ===================
# (aggiunta su richiesta utente: NMAP). Le opzioni sono validate in modo
# strutturale qui (tipi/Literal/bound) ma la validazione profonda dei target/
# opzioni nmap resta sulla Probe (whitelist/regex, argv mai su shell).


class ScanRequest(_Model):
    """Opzioni di una scansione NMAP inoltrate alla Probe (pass-through tipizzato)."""

    target: str
    timing: Literal["T0", "T1", "T2", "T3", "T4", "T5"] = "T3"
    technique: Literal["connect", "syn", "udp", "ping"] = "connect"
    ports: str | None = None
    top_ports: int | None = Field(default=None, ge=1, le=65535)
    service_version: bool = False
    version_intensity: int | None = Field(default=None, ge=0, le=9)
    os_detection: bool = False
    no_ping: bool = False
    scripts: list[str] = Field(default_factory=list)
    script_args: str | None = None
    min_rate: int | None = Field(default=None, ge=1)
    max_rate: int | None = Field(default=None, ge=1)
    max_retries: int | None = Field(default=None, ge=0, le=20)
    extra: str | None = None


class ScanStartOut(_Model):
    scan_id: str
    status: str
    started_at: str
    target: str


class ScanListItem(_Model):
    scan_id: str
    target: str
    status: str
    started_at: str
    finished_at: str | None = None
    summary: dict[str, Any] | None = None


class ScanList(_Model):
    items: list[ScanListItem]
    total: int


class ScanDetail(_Model):
    scan_id: str
    target: str
    options: dict[str, Any] = Field(default_factory=dict)
    status: str
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None
    hosts: list[dict[str, Any]] = Field(default_factory=list)


class DashboardProbeSummary(_Model):
    probe_id: str
    status: str
    systems_total: int
    systems_down: int


class SystemsSummary(_Model):
    ok: int
    warn: int
    error: int
    down: int
    unknown: int


class DashboardAggregate(_Model):
    probes: list[DashboardProbeSummary]
    systems_summary: SystemsSummary
    active_alarms: int
    generated_at: str


class DashboardProbeResponse(_Model):
    probe: ProbeOut
    systems: list[dict[str, Any]]
    generated_at: str


# ============================ Comunicazione Probe ==========================


class ProbeRegisterRequest(_Model):
    enrollment_token: str
    hostname: str
    version: str
    csr: str | None = None


class ProbeRegisterResponse(_Model):
    probe_id: str
    probe_token: str
    client_certificate: str | None = None
    ca_certificate: str
    server_probe_endpoint: str


class ProbeConfigSystem(_Model):
    system_id: str
    system_name: str
    kind: SystemKind = "http"
    heartbeat_url: str | None = None
    tcp_host: str | None = None
    tcp_port: int | None = None
    poll_interval_seconds: int
    timeout_seconds: int
    enabled: bool
    thresholds: Thresholds


class ProbeConfigResponse(_Model):
    probe_id: str
    poll_defaults: dict[str, Any]
    systems: list[ProbeConfigSystem]
    config_version: str


class ProbeLivenessRequest(_Model):
    version: str
    uptime_seconds: int
    opensearch_healthy: bool
    systems_polled: int
    last_poll_at: str


class ProbeLivenessResponse(_Model):
    config_version: str


class ProbeEvent(_Model):
    type: Literal[
        "status_changed",
        "system_unreachable",
        "system_recovered",
        "response_time_exceeded",
        "sustained_state",
    ]
    system_id: str
    check_id: str | None = None
    status: str
    previous_status: str | None = None
    response_ms: int | None = None
    reachable: bool
    message: str | None = None
    timestamp: str


class ProbeEventsRequest(_Model):
    events: list[ProbeEvent]


class ProbeEventsResponse(_Model):
    accepted: int


class ProbeRollupSystem(_Model):
    system_id: str
    status: str
    avg_response_ms: float
    uptime_pct: float
    checks: list[dict[str, Any]]


class ProbeRollupRequest(_Model):
    window: str
    generated_at: str
    systems: list[ProbeRollupSystem]


class ProbeRollupResponse(_Model):
    accepted: bool


# ============================ Notifiche ====================================


class ChannelOut(_Model):
    id: str
    name: str
    type: str
    enabled: bool
    inbound_enabled: bool
    config: dict[str, Any]
    created_at: dt.datetime


class ChannelList(_Model):
    items: list[ChannelOut]
    total: int


class ChannelCreate(_Model):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["email", "telegram", "whatsapp"]
    enabled: bool = True
    inbound_enabled: bool = False
    config: dict[str, Any]


class ChannelUpdate(_Model):
    name: str | None = None
    enabled: bool | None = None
    inbound_enabled: bool | None = None
    config: dict[str, Any] | None = None


class ChannelTestRequest(_Model):
    recipient: str
    message: str | None = None


class ChannelTestResponse(_Model):
    delivered: bool
    detail: str


class DeliveryOut(_Model):
    id: str
    channel_id: str
    workflow_id: str | None
    recipient: str
    status: str
    error: str | None
    created_at: dt.datetime


class DeliveryList(_Model):
    items: list[DeliveryOut]
    total: int


# ============================ Workflow =====================================


class WorkflowScope(_Model):
    probe_ids: list[str] = Field(default_factory=list)
    system_ids: list[str] = Field(default_factory=list)
    check_ids: list[str] = Field(default_factory=list)


class WorkflowConditionIO(_Model):
    field: str
    op: str
    value: Any
    group: str | None = None


class WorkflowSuppression(_Model):
    cooldown_seconds: int = 0
    dedup_window_seconds: int = 0
    active_hours: dict[str, Any] | None = None
    respect_maintenance: bool = True


class WorkflowActionIO(_Model):
    step_order: int
    channel_id: str
    recipients: list[str] = Field(default_factory=list)
    template: str
    delay_seconds: int = 0
    escalation_condition: dict[str, Any] | None = None
    repeat: dict[str, Any] | None = None


class WorkflowOut(_Model):
    id: str
    name: str
    description: str | None
    enabled: bool
    trigger: str
    scope: WorkflowScope
    conditions: list[WorkflowConditionIO]
    suppression: WorkflowSuppression
    actions: list[WorkflowActionIO]
    created_at: dt.datetime


class WorkflowList(_Model):
    items: list[WorkflowOut]
    total: int


class WorkflowCreate(_Model):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    enabled: bool = True
    trigger: str
    scope: WorkflowScope = Field(default_factory=WorkflowScope)
    conditions: list[WorkflowConditionIO] = Field(default_factory=list)
    suppression: WorkflowSuppression = Field(default_factory=WorkflowSuppression)
    actions: list[WorkflowActionIO] = Field(default_factory=list)


class WorkflowUpdate(_Model):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    trigger: str | None = None
    scope: WorkflowScope | None = None
    conditions: list[WorkflowConditionIO] | None = None
    suppression: WorkflowSuppression | None = None
    actions: list[WorkflowActionIO] | None = None


class WorkflowEnabledRequest(_Model):
    enabled: bool


class SimulateRequest(_Model):
    event: dict[str, Any]


class SimulateResponse(_Model):
    matched: bool
    planned_actions: list[dict[str, Any]]
    suppressed_by: str | None


# ============================ Allarmi ======================================


class AlarmOut(_Model):
    id: str
    workflow_id: str | None
    probe_id: str | None
    system_id: str | None
    check_id: str | None
    status: str
    opened_at: dt.datetime
    acknowledged_at: dt.datetime | None
    acknowledged_by: str | None
    resolved_at: dt.datetime | None


class AlarmList(_Model):
    items: list[AlarmOut]
    total: int


class AckRequest(_Model):
    note: str | None = None


# ============================ Identita' canale =============================


class ChannelIdentityCreate(_Model):
    channel_type: Literal["telegram", "whatsapp", "email"]
    external_id: str
    verification_code: str


class ChannelIdentityOut(_Model):
    id: str
    channel_type: str
    external_id: str
    user_id: str


class ChannelIdentityList(_Model):
    items: list[ChannelIdentityOut]


class InboundEmailRequest(_Model):
    from_: str = Field(alias="from")
    subject: str
    body: str
    verification_token: str

    model_config = ConfigDict(populate_by_name=True)


# ============================ Audit ========================================


class AuditOut(_Model):
    id: str
    timestamp: dt.datetime
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    outcome: str
    ip: str | None
    details: dict[str, Any]


class AuditList(_Model):
    items: list[AuditOut]
    total: int


# ============================ Log di sistema ===============================


class LogOut(_Model):
    id: str
    timestamp: dt.datetime
    component: str
    probe_id: str | None
    level: str
    logger: str | None
    message: str
    context: dict[str, Any]


class LogList(_Model):
    items: list[LogOut]
    total: int


# ============================ Configurazione ===============================


class ConfigItemOut(_Model):
    key: str
    value: Any
    type: str | None
    sensitive: bool
    requires_restart: bool
    description: str | None


class ConfigList(_Model):
    items: list[ConfigItemOut]


class ConfigUpdateItem(_Model):
    key: str
    value: Any


class ConfigUpdateRequest(_Model):
    items: list[ConfigUpdateItem]


class ConfigUpdateResponse(_Model):
    updated: list[str]
    requires_restart: list[str]


# silenzia riferimenti opzionali non usati direttamente
_ = (uuid, EnrollmentInfo)
