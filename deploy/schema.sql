-- =============================================================================
-- Pulse — Schema fisico DB Server (PostgreSQL 16)
-- File: deploy/schema.sql
-- Autore: AGENTE 2 — DBA
-- Data: 2026-07-15
--
-- DDL completo ed eseguibile. Idempotente dove ragionevole:
--   - CREATE TABLE IF NOT EXISTS
--   - CREATE INDEX IF NOT EXISTS
--   - CREATE OR REPLACE FUNCTION / VIEW
--   - DROP TRIGGER IF EXISTS + CREATE TRIGGER
--
-- Contiene SOLO le entita' del DB Server (modello logico §3 di
-- DOCUMENTO_DATABASE.md). Le serie temporali (heartbeat/eventi) risiedono su
-- OpenSearch locale alle Probe e NON sono presenti qui (RF-051).
--
-- Convenzioni tipi (mapping da tipi logici §2 del modello):
--   UUID       -> uuid            (default gen_random_uuid(), core PG >= 13)
--   STRING(n)  -> varchar(n)
--   TEXT       -> text
--   INT        -> integer
--   BIGINT     -> bigint
--   DECIMAL    -> numeric
--   BOOLEAN    -> boolean
--   TIMESTAMP  -> timestamptz     (sempre UTC)
--   ENUM(...)  -> varchar + CHECK (portabile, evolvibile senza ALTER TYPE)
--   JSON       -> jsonb           (indicizzabile, query-abile)
--   ARRAY<STRING> -> jsonb        (per probes.tags, coerente con array JSON API)
--
-- Identificatori che coincidono con parole riservate PostgreSQL sono quotati:
--   "trigger" (notification_workflows), "timestamp" (audit_log/system_logs),
--   "window" (probe_rollups), "repeat" (workflow_actions).
-- =============================================================================

-- gen_random_uuid() e' in core da PostgreSQL 13; pgcrypto reso disponibile per
-- ambienti/estensioni future (idempotente).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- FUNZIONI DI SUPPORTO (trigger)
-- =============================================================================

-- Aggiorna automaticamente updated_at ad ogni UPDATE.
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- Rende audit_log immutabile (append-only): blocca UPDATE e DELETE a livello DB
-- (RNF-006). Nessuna API applicativa puo' alterare l'audit.
CREATE OR REPLACE FUNCTION fn_audit_log_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_log e'' immutabile (append-only): operazione % vietata', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

-- Protegge i ruoli predefiniti (is_builtin = true) da eliminazione e da modifica
-- strutturale (name / is_builtin), coerente con RF-012 e RB-02.
CREATE OR REPLACE FUNCTION fn_protect_builtin_roles()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.is_builtin THEN
            RAISE EXCEPTION 'Il ruolo predefinito "%" non e'' eliminabile', OLD.name
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN OLD;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.is_builtin AND (NEW.name <> OLD.name OR NEW.is_builtin <> OLD.is_builtin) THEN
            RAISE EXCEPTION 'Struttura del ruolo predefinito "%" non modificabile', OLD.name
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    RETURN NEW;
END;
$$;

-- =============================================================================
-- RBAC: users, roles, permissions, user_roles, role_permissions
-- =============================================================================

-- 3.1 users
CREATE TABLE IF NOT EXISTS users (
    id                 uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    username           varchar(100) NOT NULL UNIQUE,
    email              varchar(255) NOT NULL UNIQUE,
    full_name          varchar(255),
    password_hash      varchar(255) NOT NULL,
    status             varchar(20)  NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','disabled','locked')),
    failed_login_count integer      NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    last_login_at      timestamptz,
    created_at         timestamptz  NOT NULL DEFAULT now(),
    updated_at         timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);

-- 3.2 roles
CREATE TABLE IF NOT EXISTS roles (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(100) NOT NULL UNIQUE,
    description varchar(255),
    is_builtin  boolean      NOT NULL DEFAULT false,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now()
);

-- 3.3 permissions (catalogo fisso, popolato dal seed)
CREATE TABLE IF NOT EXISTS permissions (
    code        varchar(64)  PRIMARY KEY,
    area        varchar(40)  NOT NULL,
    description varchar(255) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_permissions_area ON permissions (area);

-- 3.4 user_roles (N:N utenti<->ruoli)
CREATE TABLE IF NOT EXISTS user_roles (
    user_id     uuid        NOT NULL REFERENCES users (id) ON UPDATE CASCADE ON DELETE CASCADE,
    role_id     uuid        NOT NULL REFERENCES roles (id) ON UPDATE CASCADE ON DELETE CASCADE,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);
-- Ricerca inversa "utenti per ruolo" (GET /users?role=...).
CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles (role_id);

-- 3.5 role_permissions (N:N ruoli<->permessi)
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id         uuid        NOT NULL REFERENCES roles (id) ON UPDATE CASCADE ON DELETE CASCADE,
    permission_code varchar(64) NOT NULL REFERENCES permissions (code) ON UPDATE CASCADE ON DELETE RESTRICT,
    PRIMARY KEY (role_id, permission_code)
);
-- Ricerca inversa "ruoli per permesso".
CREATE INDEX IF NOT EXISTS idx_role_permissions_code ON role_permissions (permission_code);

-- =============================================================================
-- PROBE ed enrollment
-- =============================================================================

-- 3.6 probes
CREATE TABLE IF NOT EXISTS probes (
    id                      uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    varchar(100) NOT NULL UNIQUE,
    description             varchar(255),
    query_endpoint          varchar(255),
    tags                    jsonb        NOT NULL DEFAULT '[]'::jsonb,
    enabled                 boolean      NOT NULL DEFAULT true,
    status                  varchar(20)  NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','online','offline')),
    token_hash              varchar(255),
    certificate_fingerprint varchar(255),
    version                 varchar(40),
    last_seen_at            timestamptz,
    last_sync_at            timestamptz,
    last_error              text,
    config_version          varchar(40),
    -- Dati anagrafici della Sonda (tutti opzionali).
    location                varchar(255),
    contact_name            varchar(255),
    contact_email           varchar(255),
    contact_phone           varchar(50),
    created_at              timestamptz  NOT NULL DEFAULT now(),
    updated_at              timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT chk_probes_tags_is_array CHECK (jsonb_typeof(tags) = 'array')
);
CREATE INDEX IF NOT EXISTS idx_probes_status  ON probes (status);
CREATE INDEX IF NOT EXISTS idx_probes_enabled ON probes (enabled);

-- 3.7 enrollment_tokens (monouso, a scadenza — RNF-007)
CREATE TABLE IF NOT EXISTS enrollment_tokens (
    id         uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    probe_id   uuid         NOT NULL REFERENCES probes (id) ON UPDATE CASCADE ON DELETE CASCADE,
    token_hash varchar(255) NOT NULL,
    expires_at timestamptz  NOT NULL,
    used_at    timestamptz,
    created_at timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_enrollment_tokens_probe   ON enrollment_tokens (probe_id);
-- Lookup del token in fase di /probe/register.
CREATE INDEX IF NOT EXISTS idx_enrollment_tokens_hash    ON enrollment_tokens (token_hash);
-- Purge dei token scaduti (retention).
CREATE INDEX IF NOT EXISTS idx_enrollment_tokens_expires ON enrollment_tokens (expires_at);

-- =============================================================================
-- SISTEMI monitorati, finestre manutenzione, check scoperti
-- =============================================================================

-- 3.8 monitored_systems
-- Supporta due tipi di controllo (kind):
--   'http' -> heartbeat HTTP/HTTPS su heartbeat_url (obbligatorio)
--   'tcp'  -> connettivita' TCP su tcp_host:tcp_port (entrambi obbligatori)
CREATE TABLE IF NOT EXISTS monitored_systems (
    id                    uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id             varchar(100) NOT NULL UNIQUE,
    system_name           varchar(255) NOT NULL,
    kind                  varchar(10)  NOT NULL DEFAULT 'http'
                          CHECK (kind IN ('http','tcp')),
    -- NULLABLE: obbligatorio solo per kind='http' (vincolo chk_monitored_systems_kind).
    heartbeat_url         varchar(500),
    tcp_host              varchar(255),
    tcp_port              integer      CHECK (tcp_port IS NULL OR (tcp_port BETWEEN 1 AND 65535)),
    -- 1 sistema -> 1 probe; RESTRICT: DELETE probe -> 409 se ha sistemi assegnati.
    probe_id              uuid         NOT NULL REFERENCES probes (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    poll_interval_seconds integer      NOT NULL CHECK (poll_interval_seconds > 0),
    timeout_seconds       integer      NOT NULL CHECK (timeout_seconds > 0),
    enabled               boolean      NOT NULL DEFAULT true,
    response_ms_warn      integer      CHECK (response_ms_warn  >= 0),
    response_ms_error     integer      CHECK (response_ms_error >= 0),
    created_at            timestamptz  NOT NULL DEFAULT now(),
    updated_at            timestamptz  NOT NULL DEFAULT now(),
    -- Coerenza dei campi in base al tipo di controllo.
    CONSTRAINT chk_monitored_systems_kind CHECK (
        (kind = 'http' AND heartbeat_url IS NOT NULL)
        OR
        (kind = 'tcp'  AND tcp_host IS NOT NULL AND tcp_port IS NOT NULL)
    )
);
-- 1 probe -> N sistemi: filtro GET /systems?probe_id e pull config Probe.
CREATE INDEX IF NOT EXISTS idx_monitored_systems_probe   ON monitored_systems (probe_id);
CREATE INDEX IF NOT EXISTS idx_monitored_systems_enabled ON monitored_systems (enabled);

-- 3.9 maintenance_windows
CREATE TABLE IF NOT EXISTS maintenance_windows (
    id         uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id  uuid         REFERENCES monitored_systems (id) ON UPDATE CASCADE ON DELETE CASCADE,
    probe_id   uuid         REFERENCES probes (id)            ON UPDATE CASCADE ON DELETE CASCADE,
    start_at   timestamptz  NOT NULL,
    end_at     timestamptz  NOT NULL,
    note       varchar(255),
    created_by uuid         REFERENCES users (id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT chk_maintenance_window_range CHECK (end_at > start_at),
    -- almeno uno tra system_id/probe_id o entrambi NULL (finestra globale)
    CONSTRAINT chk_maintenance_scope CHECK (true)
);
CREATE INDEX IF NOT EXISTS idx_maintenance_windows_system ON maintenance_windows (system_id);
CREATE INDEX IF NOT EXISTS idx_maintenance_windows_probe  ON maintenance_windows (probe_id);
-- Verifica "sistema/probe in manutenzione ora" nella valutazione soppressione.
CREATE INDEX IF NOT EXISTS idx_maintenance_windows_range  ON maintenance_windows (start_at, end_at);

-- 3.10 discovered_checks (registro sintetico; dati puntuali su OpenSearch)
CREATE TABLE IF NOT EXISTS discovered_checks (
    id           uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id    uuid         NOT NULL REFERENCES monitored_systems (id) ON UPDATE CASCADE ON DELETE CASCADE,
    check_id     varchar(100) NOT NULL,
    check_name   varchar(255),
    probe_id     uuid         REFERENCES probes (id) ON UPDATE CASCADE ON DELETE CASCADE,
    last_status  varchar(40),
    last_seen_at timestamptz,
    CONSTRAINT uq_discovered_checks UNIQUE (system_id, check_id)
);
CREATE INDEX IF NOT EXISTS idx_discovered_checks_probe ON discovered_checks (probe_id);

-- =============================================================================
-- NOTIFICHE: canali, workflow, condizioni, azioni
-- =============================================================================

-- 3.11 notification_channels
CREATE TABLE IF NOT EXISTS notification_channels (
    id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name            varchar(100) NOT NULL UNIQUE,
    type            varchar(20)  NOT NULL CHECK (type IN ('email','telegram','whatsapp')),
    enabled         boolean      NOT NULL DEFAULT true,
    inbound_enabled boolean      NOT NULL DEFAULT false,
    -- config contiene segreti CIFRATI A RIPOSO a livello applicativo (RNF-004).
    config          jsonb        NOT NULL,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notification_channels_type ON notification_channels (type);

-- 3.12 notification_workflows
CREATE TABLE IF NOT EXISTS notification_workflows (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(100) NOT NULL UNIQUE,
    description varchar(255),
    enabled     boolean      NOT NULL DEFAULT true,
    "trigger"   varchar(40)  NOT NULL CHECK ("trigger" IN (
                    'status_changed','status_is','system_unreachable','system_recovered',
                    'response_time_exceeded','sustained_state','probe_offline','probe_online')),
    scope       jsonb,
    suppression jsonb,
    created_by  uuid         REFERENCES users (id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_workflows_enabled ON notification_workflows (enabled);
-- Selezione dei workflow candidati per tipo di evento in ingresso.
CREATE INDEX IF NOT EXISTS idx_workflows_trigger ON notification_workflows ("trigger");

-- 3.13 workflow_conditions
CREATE TABLE IF NOT EXISTS workflow_conditions (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id uuid         NOT NULL REFERENCES notification_workflows (id) ON UPDATE CASCADE ON DELETE CASCADE,
    field       varchar(100) NOT NULL,
    op          varchar(20)  NOT NULL CHECK (op IN (
                    'eq','neq','gt','gte','lt','lte','in','not_in','contains','matches')),
    value       jsonb,
    logic_group varchar(20),
    order_index integer
);
CREATE INDEX IF NOT EXISTS idx_workflow_conditions_workflow ON workflow_conditions (workflow_id);

-- 3.14 workflow_actions (step di escalation)
CREATE TABLE IF NOT EXISTS workflow_actions (
    id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id          uuid        NOT NULL REFERENCES notification_workflows (id) ON UPDATE CASCADE ON DELETE CASCADE,
    step_order           integer     NOT NULL CHECK (step_order >= 0),
    -- RESTRICT: DELETE canale -> 409 se usato da un workflow (azione).
    channel_id           uuid        NOT NULL REFERENCES notification_channels (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    recipients           jsonb       NOT NULL,
    template             text        NOT NULL,
    delay_seconds        integer     NOT NULL DEFAULT 0 CHECK (delay_seconds >= 0),
    escalation_condition jsonb,
    "repeat"             jsonb,
    CONSTRAINT uq_workflow_actions_step UNIQUE (workflow_id, step_order)
);
CREATE INDEX IF NOT EXISTS idx_workflow_actions_channel ON workflow_actions (channel_id);

-- =============================================================================
-- ALLARMI, invii, identita' canale, comandi inbound
-- =============================================================================

-- 3.15 alarms
CREATE TABLE IF NOT EXISTS alarms (
    id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     uuid         REFERENCES notification_workflows (id) ON UPDATE CASCADE ON DELETE SET NULL,
    probe_id        uuid         REFERENCES probes (id)                 ON UPDATE CASCADE ON DELETE SET NULL,
    system_id       uuid         REFERENCES monitored_systems (id)      ON UPDATE CASCADE ON DELETE SET NULL,
    check_id        varchar(100),
    dedup_key       varchar(255),
    status          varchar(20)  NOT NULL CHECK (status IN ('active','acknowledged','resolved')),
    current_step    integer,
    opened_at       timestamptz  NOT NULL DEFAULT now(),
    acknowledged_at timestamptz,
    acknowledged_by uuid         REFERENCES users (id) ON UPDATE CASCADE ON DELETE SET NULL,
    resolved_at     timestamptz
);
-- Throttling/dedup: ricerca allarme aperto per chiave.
CREATE INDEX IF NOT EXISTS idx_alarms_dedup_status ON alarms (dedup_key, status);
CREATE INDEX IF NOT EXISTS idx_alarms_status       ON alarms (status);
CREATE INDEX IF NOT EXISTS idx_alarms_system       ON alarms (system_id);
CREATE INDEX IF NOT EXISTS idx_alarms_probe        ON alarms (probe_id);
-- Filtri temporali GET /alarms.
CREATE INDEX IF NOT EXISTS idx_alarms_opened_at    ON alarms (opened_at);

-- 3.16 notification_deliveries (storico invii; retention configurabile — DB-06)
CREATE TABLE IF NOT EXISTS notification_deliveries (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id uuid         REFERENCES notification_workflows (id) ON UPDATE CASCADE ON DELETE SET NULL,
    action_id   uuid         REFERENCES workflow_actions (id)       ON UPDATE CASCADE ON DELETE SET NULL,
    alarm_id    uuid         REFERENCES alarms (id)                 ON UPDATE CASCADE ON DELETE SET NULL,
    -- channel_id NOT NULL (modello §3.16); RESTRICT preserva la storia: la
    -- cancellazione del canale richiede prima il purge per retention.
    channel_id  uuid         NOT NULL REFERENCES notification_channels (id) ON UPDATE CASCADE ON DELETE RESTRICT,
    recipient   varchar(255) NOT NULL,
    status      varchar(20)  NOT NULL CHECK (status IN ('sent','failed','retrying')),
    error       text,
    retry_count integer      NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    created_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_deliveries_channel    ON notification_deliveries (channel_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_workflow   ON notification_deliveries (workflow_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_alarm      ON notification_deliveries (alarm_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_status     ON notification_deliveries (status);
-- Storico filtrabile per data + purge retention.
CREATE INDEX IF NOT EXISTS idx_deliveries_created_at ON notification_deliveries (created_at);

-- 3.17 channel_identities
CREATE TABLE IF NOT EXISTS channel_identities (
    id                uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid         NOT NULL REFERENCES users (id) ON UPDATE CASCADE ON DELETE CASCADE,
    channel_type      varchar(20)  NOT NULL CHECK (channel_type IN ('email','telegram','whatsapp')),
    external_id       varchar(255) NOT NULL,
    verified          boolean      NOT NULL DEFAULT false,
    verification_code varchar(64),
    created_at        timestamptz  NOT NULL DEFAULT now(),
    -- una identita' di canale -> un solo utente.
    CONSTRAINT uq_channel_identity UNIQUE (channel_type, external_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_identities_user ON channel_identities (user_id);

-- 3.18 inbound_commands (log comandi ricevuti dai canali)
CREATE TABLE IF NOT EXISTS inbound_commands (
    id           uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_type varchar(20)  NOT NULL CHECK (channel_type IN ('email','telegram','whatsapp')),
    external_id  varchar(255) NOT NULL,
    user_id      uuid         REFERENCES users (id) ON UPDATE CASCADE ON DELETE SET NULL,
    command      varchar(100) NOT NULL,
    args         jsonb,
    outcome      varchar(20)  NOT NULL CHECK (outcome IN ('executed','denied','error')),
    response     text,
    received_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_inbound_identity    ON inbound_commands (channel_type, external_id);
CREATE INDEX IF NOT EXISTS idx_inbound_user        ON inbound_commands (user_id);
-- Purge retention + ordinamento cronologico.
CREATE INDEX IF NOT EXISTS idx_inbound_received_at ON inbound_commands (received_at);

-- =============================================================================
-- AUDIT (immutabile) e LOG di sistema
-- =============================================================================

-- 3.19 audit_log (append-only, RNF-006)
CREATE TABLE IF NOT EXISTS audit_log (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    "timestamp" timestamptz  NOT NULL DEFAULT now(),
    actor_type  varchar(20)  NOT NULL CHECK (actor_type IN ('user','probe','system')),
    actor_id    varchar(100),
    action      varchar(100) NOT NULL,
    entity_type varchar(100),
    entity_id   varchar(100),
    outcome     varchar(20)  NOT NULL CHECK (outcome IN ('success','failure')),
    ip          varchar(64),
    details     jsonb
);
-- Filtri GET /audit: attore, azione, entita', esito, intervallo.
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log ("timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor     ON audit_log (actor_type, actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_action    ON audit_log (action);
CREATE INDEX IF NOT EXISTS idx_audit_entity    ON audit_log (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_outcome   ON audit_log (outcome);

-- 3.20 system_logs (aggregati Server + Probe; retention configurabile — DB-06)
CREATE TABLE IF NOT EXISTS system_logs (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    "timestamp" timestamptz  NOT NULL DEFAULT now(),
    component   varchar(20)  NOT NULL CHECK (component IN ('server','probe')),
    probe_id    uuid         REFERENCES probes (id) ON UPDATE CASCADE ON DELETE SET NULL,
    level       varchar(20)  NOT NULL CHECK (level IN ('debug','info','warning','error','critical')),
    logger      varchar(255),
    message     text         NOT NULL,
    context     jsonb
);
-- Filtri GET /logs: componente, livello, intervallo.
CREATE INDEX IF NOT EXISTS idx_system_logs_main  ON system_logs ("timestamp", component, level);
CREATE INDEX IF NOT EXISTS idx_system_logs_probe ON system_logs (probe_id);

-- =============================================================================
-- CONFIGURAZIONE, SESSIONI, ROLLUP
-- =============================================================================

-- 3.21 configuration
CREATE TABLE IF NOT EXISTS configuration (
    key              varchar(100) PRIMARY KEY,
    value            jsonb,
    type             varchar(40),
    sensitive        boolean      NOT NULL DEFAULT false,
    requires_restart boolean      NOT NULL DEFAULT false,
    description      varchar(255),
    updated_by       uuid         REFERENCES users (id) ON UPDATE CASCADE ON DELETE SET NULL,
    updated_at       timestamptz  NOT NULL DEFAULT now()
);

-- 3.22 sessions / refresh_tokens
CREATE TABLE IF NOT EXISTS sessions (
    id                 uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid         NOT NULL REFERENCES users (id) ON UPDATE CASCADE ON DELETE CASCADE,
    refresh_token_hash varchar(255) NOT NULL,
    issued_at          timestamptz  NOT NULL DEFAULT now(),
    expires_at         timestamptz  NOT NULL,
    revoked_at         timestamptz,
    user_agent         varchar(255),
    ip                 varchar(64)
);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions (user_id);
-- Lookup su /auth/refresh e revoca su /auth/logout.
CREATE INDEX IF NOT EXISTS idx_sessions_token   ON sessions (refresh_token_hash);
-- Purge sessioni scadute/revocate.
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at);

-- 3.23 probe_rollups (snapshot dashboard aggregata; NON serie temporale grezza)
CREATE TABLE IF NOT EXISTS probe_rollups (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    probe_id     uuid        NOT NULL REFERENCES probes (id) ON UPDATE CASCADE ON DELETE CASCADE,
    "window"     varchar(20),
    payload      jsonb       NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now()
);
-- Ultimo rollup per probe (per finestra) + purge retention breve.
CREATE INDEX IF NOT EXISTS idx_probe_rollups_probe ON probe_rollups (probe_id, generated_at DESC);

-- =============================================================================
-- TRIGGER
-- =============================================================================

-- updated_at automatico
DROP TRIGGER IF EXISTS trg_users_updated_at              ON users;
CREATE TRIGGER trg_users_updated_at              BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

DROP TRIGGER IF EXISTS trg_roles_updated_at              ON roles;
CREATE TRIGGER trg_roles_updated_at              BEFORE UPDATE ON roles
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

DROP TRIGGER IF EXISTS trg_probes_updated_at             ON probes;
CREATE TRIGGER trg_probes_updated_at             BEFORE UPDATE ON probes
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

DROP TRIGGER IF EXISTS trg_monitored_systems_updated_at  ON monitored_systems;
CREATE TRIGGER trg_monitored_systems_updated_at  BEFORE UPDATE ON monitored_systems
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

DROP TRIGGER IF EXISTS trg_channels_updated_at           ON notification_channels;
CREATE TRIGGER trg_channels_updated_at           BEFORE UPDATE ON notification_channels
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

DROP TRIGGER IF EXISTS trg_workflows_updated_at          ON notification_workflows;
CREATE TRIGGER trg_workflows_updated_at          BEFORE UPDATE ON notification_workflows
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

DROP TRIGGER IF EXISTS trg_configuration_updated_at      ON configuration;
CREATE TRIGGER trg_configuration_updated_at      BEFORE UPDATE ON configuration
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- audit_log immutabile
DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log;
CREATE TRIGGER trg_audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log_immutable();

-- protezione ruoli predefiniti
DROP TRIGGER IF EXISTS trg_protect_builtin_roles ON roles;
CREATE TRIGGER trg_protect_builtin_roles BEFORE UPDATE OR DELETE ON roles
    FOR EACH ROW EXECUTE FUNCTION fn_protect_builtin_roles();

-- =============================================================================
-- VISTE
-- =============================================================================

-- Permessi effettivi per utente = unione dei permessi dei suoi ruoli.
-- Supporta la costruzione di user.permissions in /auth/login e /auth/me.
CREATE OR REPLACE VIEW v_user_effective_permissions AS
SELECT DISTINCT ur.user_id, rp.permission_code
FROM user_roles ur
JOIN role_permissions rp ON rp.role_id = ur.role_id;

-- Conteggio sistemi per Probe (campo systems_count della risposta Probe).
CREATE OR REPLACE VIEW v_probe_system_counts AS
SELECT p.id AS probe_id, count(ms.id) AS systems_count
FROM probes p
LEFT JOIN monitored_systems ms ON ms.probe_id = p.id
GROUP BY p.id;

-- Allarmi attualmente non risolti (dashboard "active_alarms", GET /alarms?status=active).
CREATE OR REPLACE VIEW v_active_alarms AS
SELECT *
FROM alarms
WHERE status IN ('active','acknowledged');

-- =============================================================================
-- FUNZIONE DI RETENTION (DB-06 / RQ-02)
-- Elimina dati storici oltre le soglie indicate (giorni). Invocabile da uno
-- scheduler esterno (cron di sistema / job applicativo) o da pg_cron se
-- installato. Ritorna il numero totale di righe eliminate.
-- =============================================================================
CREATE OR REPLACE FUNCTION fn_purge_retention(
    p_system_logs_days integer DEFAULT 90,
    p_deliveries_days  integer DEFAULT 180,
    p_inbound_days     integer DEFAULT 90,
    p_rollups_days     integer DEFAULT 7
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted bigint := 0;
    v_tmp     bigint;
BEGIN
    DELETE FROM system_logs
      WHERE "timestamp" < now() - make_interval(days => p_system_logs_days);
    GET DIAGNOSTICS v_tmp = ROW_COUNT; v_deleted := v_deleted + v_tmp;

    DELETE FROM notification_deliveries
      WHERE created_at < now() - make_interval(days => p_deliveries_days);
    GET DIAGNOSTICS v_tmp = ROW_COUNT; v_deleted := v_deleted + v_tmp;

    DELETE FROM inbound_commands
      WHERE received_at < now() - make_interval(days => p_inbound_days);
    GET DIAGNOSTICS v_tmp = ROW_COUNT; v_deleted := v_deleted + v_tmp;

    DELETE FROM probe_rollups
      WHERE generated_at < now() - make_interval(days => p_rollups_days);
    GET DIAGNOSTICS v_tmp = ROW_COUNT; v_deleted := v_deleted + v_tmp;

    -- Igiene: token di enrollment scaduti e sessioni scadute/revocate da tempo.
    DELETE FROM enrollment_tokens WHERE expires_at < now() - make_interval(days => 1);
    GET DIAGNOSTICS v_tmp = ROW_COUNT; v_deleted := v_deleted + v_tmp;

    DELETE FROM sessions
      WHERE expires_at < now() - make_interval(days => 7)
         OR (revoked_at IS NOT NULL AND revoked_at < now() - make_interval(days => 7));
    GET DIAGNOSTICS v_tmp = ROW_COUNT; v_deleted := v_deleted + v_tmp;

    -- NB: audit_log NON viene mai purgato qui (immutabile, retention legale).
    RETURN v_deleted;
END;
$$;

-- =============================================================================
-- FINE schema.sql
-- =============================================================================
