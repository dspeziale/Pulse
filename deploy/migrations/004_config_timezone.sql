-- =============================================================================
-- Pulse — Migrazione 004: parametro di configurazione "timezone"
-- File: deploy/migrations/004_config_timezone.sql
-- Autore: AGENTE 2 — DBA
-- Data: 2026-07-17
--
-- Aggiunge il parametro di configurazione applicativo del fuso orario, usato per
-- normalizzare la visualizzazione delle date-ora. Default IANA 'Europe/Rome'.
--
-- Applicabile a un DB Server GIA' esistente.
--   docker exec -i pulse-postgres psql -U pulse -d pulse < deploy/migrations/004_config_timezone.sql
--
-- IDEMPOTENTE / RI-ESEGUIBILE: INSERT ... ON CONFLICT (key) DO NOTHING.
-- Nota: value e' di tipo jsonb; il valore stringa e' memorizzato come stringa
-- JSON ("Europe/Rome"), coerente con lo stile del seed.
-- =============================================================================

BEGIN;

INSERT INTO configuration (key, value, type, sensitive, requires_restart, description)
VALUES (
    'timezone',
    '"Europe/Rome"',
    'string',
    false,
    false,
    'Fuso orario IANA per la visualizzazione delle date-ora (es. Europe/Rome, UTC).'
)
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- =============================================================================
-- FINE 004_config_timezone.sql
-- =============================================================================
