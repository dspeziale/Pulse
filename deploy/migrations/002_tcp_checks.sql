-- =============================================================================
-- Pulse — Migrazione 002: controlli di connettivita' TCP
-- File: deploy/migrations/002_tcp_checks.sql
-- Autore: AGENTE 2 — DBA
-- Data: 2026-07-16
--
-- Estende monitored_systems per supportare, oltre ai controlli HTTP heartbeat,
-- controlli di tipo "connettivita' TCP" (host/ip + porta).
--
-- Applicabile a un DB Server GIA' esistente (non ricreabile).
--   docker exec -i pulse-postgres psql -U pulse -d pulse < deploy/migrations/002_tcp_checks.sql
--
-- IDEMPOTENTE / RI-ESEGUIBILE:
--   - ADD COLUMN IF NOT EXISTS (nativo PG)
--   - ALTER COLUMN ... DROP NOT NULL (no-op se gia' nullable)
--   - CHECK aggiunti in blocchi DO che verificano pg_constraint prima di crearli
--
-- COMPATIBILITA' DATI ESISTENTI:
--   I sistemi HTTP gia' presenti restano validi: la colonna kind ha DEFAULT
--   'http', quindi le righe preesistenti ricevono kind='http' e soddisfano il
--   vincolo di coerenza (heartbeat_url NOT NULL era gia' garantito prima).
-- =============================================================================

BEGIN;

-- 1) Nuove colonne ------------------------------------------------------------
ALTER TABLE monitored_systems
    ADD COLUMN IF NOT EXISTS kind     varchar(10) NOT NULL DEFAULT 'http';

ALTER TABLE monitored_systems
    ADD COLUMN IF NOT EXISTS tcp_host varchar(255);

ALTER TABLE monitored_systems
    ADD COLUMN IF NOT EXISTS tcp_port integer;

-- 2) heartbeat_url diventa NULLABLE (obbligatorio solo per kind='http') -------
--    Idempotente: DROP NOT NULL non genera errore se gia' nullable.
ALTER TABLE monitored_systems
    ALTER COLUMN heartbeat_url DROP NOT NULL;

-- 3) Vincoli CHECK (idempotenti tramite verifica su pg_constraint) ------------

-- 3a) kind IN ('http','tcp')
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_monitored_systems_kind_values'
          AND conrelid = 'monitored_systems'::regclass
    ) THEN
        ALTER TABLE monitored_systems
            ADD CONSTRAINT chk_monitored_systems_kind_values
            CHECK (kind IN ('http','tcp'));
    END IF;
END
$$;

-- 3b) tcp_port nel range valido (o NULL)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_monitored_systems_tcp_port'
          AND conrelid = 'monitored_systems'::regclass
    ) THEN
        ALTER TABLE monitored_systems
            ADD CONSTRAINT chk_monitored_systems_tcp_port
            CHECK (tcp_port IS NULL OR (tcp_port BETWEEN 1 AND 65535));
    END IF;
END
$$;

-- 3c) Coerenza campi per tipo di controllo
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_monitored_systems_kind'
          AND conrelid = 'monitored_systems'::regclass
    ) THEN
        ALTER TABLE monitored_systems
            ADD CONSTRAINT chk_monitored_systems_kind
            CHECK (
                (kind = 'http' AND heartbeat_url IS NOT NULL)
                OR
                (kind = 'tcp'  AND tcp_host IS NOT NULL AND tcp_port IS NOT NULL)
            );
    END IF;
END
$$;

COMMIT;

-- =============================================================================
-- FINE 002_tcp_checks.sql
-- =============================================================================
