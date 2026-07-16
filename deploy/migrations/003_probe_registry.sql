-- =============================================================================
-- Pulse — Migrazione 003: dati anagrafici della Sonda (probe registry)
-- File: deploy/migrations/003_probe_registry.sql
-- Autore: AGENTE 2 — DBA
-- Data: 2026-07-16
--
-- Estende la tabella probes con dati anagrafici opzionali della Sonda:
-- posizione/sede, referente e relativi contatti.
--
-- Applicabile a un DB Server GIA' esistente (non ricreabile).
--   docker exec -i pulse-postgres psql -U pulse -d pulse < deploy/migrations/003_probe_registry.sql
--
-- IDEMPOTENTE / RI-ESEGUIBILE: ADD COLUMN IF NOT EXISTS (nativo PG).
--
-- COMPATIBILITA' DATI ESISTENTI: tutte le colonne sono NULLABLE, quindi le
-- righe preesistenti restano valide (valore NULL).
-- =============================================================================

BEGIN;

ALTER TABLE probes
    ADD COLUMN IF NOT EXISTS location      varchar(255);

ALTER TABLE probes
    ADD COLUMN IF NOT EXISTS contact_name  varchar(255);

ALTER TABLE probes
    ADD COLUMN IF NOT EXISTS contact_email varchar(255);

ALTER TABLE probes
    ADD COLUMN IF NOT EXISTS contact_phone varchar(50);

COMMIT;

-- =============================================================================
-- FINE 003_probe_registry.sql
-- =============================================================================
