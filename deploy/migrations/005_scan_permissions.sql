-- =============================================================================
-- Pulse — Migrazione 005: permessi RBAC per scansioni di rete (NMAP)
-- File: deploy/migrations/005_scan_permissions.sql
-- Autore: AGENTE 2 — DBA
-- Data: 2026-07-17
--
-- Aggiunge due permessi al catalogo e le relative assegnazioni ai ruoli
-- predefiniti, per la funzionalita' di scansione di rete (NMAP) dalla Probe.
--
-- Applicabile a un DB Server GIA' esistente.
--   docker exec -i pulse-postgres psql -U pulse -d pulse < deploy/migrations/005_scan_permissions.sql
--
-- IDEMPOTENTE / RI-ESEGUIBILE: INSERT ... ON CONFLICT DO NOTHING.
--
-- Assegnazioni (06_rbac.md aggiornato):
--   scans.run  -> SuperAdmin, Admin, Operator
--   scans.read -> SuperAdmin, Admin, Operator, Viewer, Auditor
-- SuperAdmin/Admin ricevono i permessi anche via i blocchi SELECT del seed su
-- installazioni pulite; qui vengono aggiunti ESPLICITAMENTE per sicurezza sul DB
-- esistente (idempotente).
-- =============================================================================

BEGIN;

-- 1) Catalogo permessi --------------------------------------------------------
INSERT INTO permissions (code, area, description) VALUES
    ('scans.run',  'scans', 'Avviare scansioni di rete (NMAP) dalla Probe.'),
    ('scans.read', 'scans', 'Consultare le scansioni di rete e i risultati.')
ON CONFLICT (code) DO NOTHING;

-- 2) Assegnazioni ruolo x permesso -------------------------------------------
-- Id ruoli predefiniti (coerenti col seed):
--   SuperAdmin ...0001, Admin ...0002, Operator ...0003, Viewer ...0004, Auditor ...0005
INSERT INTO role_permissions (role_id, permission_code) VALUES
    -- scans.run
    ('00000000-0000-0000-0000-000000000001', 'scans.run'),   -- SuperAdmin
    ('00000000-0000-0000-0000-000000000002', 'scans.run'),   -- Admin
    ('00000000-0000-0000-0000-000000000003', 'scans.run'),   -- Operator
    -- scans.read
    ('00000000-0000-0000-0000-000000000001', 'scans.read'),  -- SuperAdmin
    ('00000000-0000-0000-0000-000000000002', 'scans.read'),  -- Admin
    ('00000000-0000-0000-0000-000000000003', 'scans.read'),  -- Operator
    ('00000000-0000-0000-0000-000000000004', 'scans.read'),  -- Viewer
    ('00000000-0000-0000-0000-000000000005', 'scans.read')   -- Auditor
ON CONFLICT DO NOTHING;

COMMIT;

-- =============================================================================
-- FINE 005_scan_permissions.sql
-- =============================================================================
