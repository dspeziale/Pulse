-- =============================================================================
-- Pulse — Dati iniziali DB Server (PostgreSQL 16)
-- File: deploy/seed.sql
-- Autore: AGENTE 2 — DBA
-- Data: 2026-07-15
--
-- Contiene:
--   1) Catalogo permessi RBAC (da 06_rbac.md §2)
--   2) Ruoli predefiniti (06_rbac.md §3)
--   3) Matrice ruoli x permessi (06_rbac.md §4)
--   4) Utente amministratore iniziale (SuperAdmin)
--   5) Parametri di configurazione di default
--
-- Idempotente: tutti gli INSERT usano ON CONFLICT DO NOTHING.
-- Eseguibile dopo schema.sql.
--
-- NOTA HASHING PASSWORD:
--   L'analisi (RNF-003) richiede "hashing forte e salato" senza fissare
--   l'algoritmo. Scelta del DBA: **bcrypt** (cost/rounds = 12), standard
--   ampiamente supportato in Python (passlib/bcrypt) coerente con lo stack
--   Backend FastAPI. In alternativa il Backend puo' adottare argon2id: in tal
--   caso rigenerare l'hash sottostante con lo stesso schema. La colonna
--   users.password_hash e' varchar(255) e ospita l'intero hash modulare
--   ($2b$... per bcrypt, $argon2id$... per argon2).
--
--   L'hash seguente e' il bcrypt di 'ChangeMe123!'.
--   >>> CAMBIARE OBBLIGATORIAMENTE la password al primo accesso. <<<
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1) CATALOGO PERMESSI (fisso)
-- -----------------------------------------------------------------------------
-- NB: il catalogo enumerato in 06_rbac.md §2 contiene 40 codici distinti
-- (vedi INCONGRUENZE in SCHEMA_FISICO.md). Vengono inseriti tutti, esattamente
-- come definiti dall'Analista: nessun codice inventato.
INSERT INTO permissions (code, area, description) VALUES
    -- Profilo personale
    ('profile.read',              'profile',       'Leggere il proprio profilo.'),
    ('profile.update',            'profile',       'Aggiornare il proprio profilo / cambiare la propria password.'),
    -- Utenti
    ('users.read',                'users',         'Elencare/consultare utenti.'),
    ('users.create',              'users',         'Creare utenti.'),
    ('users.update',              'users',         'Modificare utenti, stato, reset password.'),
    ('users.delete',              'users',         'Eliminare/disabilitare utenti.'),
    ('users.assign_roles',        'users',         'Assegnare/rimuovere ruoli agli utenti.'),
    -- Ruoli
    ('roles.read',                'roles',         'Consultare ruoli.'),
    ('roles.create',              'roles',         'Creare ruoli.'),
    ('roles.update',              'roles',         'Modificare ruoli.'),
    ('roles.delete',              'roles',         'Eliminare ruoli.'),
    ('roles.assign_permissions',  'roles',         'Assegnare permessi ai ruoli.'),
    -- Permessi
    ('permissions.read',          'permissions',   'Consultare il catalogo permessi.'),
    -- Probe
    ('probes.read',               'probes',        'Consultare Probe e stato.'),
    ('probes.create',             'probes',        'Registrare/enrollare Probe.'),
    ('probes.update',             'probes',        'Modificare definizione Probe.'),
    ('probes.delete',             'probes',        'Eliminare Probe.'),
    ('probes.rotate_key',         'probes',        'Ruotare/revocare credenziali/certificato Probe.'),
    -- Sistemi monitorati
    ('systems.read',              'systems',       'Consultare sistemi monitorati.'),
    ('systems.create',            'systems',       'Creare sistemi monitorati.'),
    ('systems.update',            'systems',       'Modificare sistemi monitorati.'),
    ('systems.delete',            'systems',       'Eliminare sistemi monitorati.'),
    -- Check
    ('checks.read',               'checks',        'Consultare i check scoperti dei sistemi.'),
    -- Heartbeat / Query / Dashboard
    ('dashboard.read',            'dashboard',     'Accedere alle dashboard (aggregata Server e Probe).'),
    ('heartbeats.read',           'heartbeats',    'Leggere serie temporali/heartbeat (drill-down, grafici).'),
    ('heartbeats.query',          'heartbeats',    'Eseguire interrogazioni dirette/avanzate su OpenSearch.'),
    -- Notifiche / Canali
    ('notifications.read',        'notifications', 'Consultare canali e storico invii.'),
    ('notifications.create',      'notifications', 'Creare canali notifica.'),
    ('notifications.update',      'notifications', 'Modificare canali notifica.'),
    ('notifications.delete',      'notifications', 'Eliminare canali notifica.'),
    ('notifications.test',        'notifications', 'Inviare messaggi di test su un canale.'),
    -- Workflow notifiche
    ('workflows.read',            'workflows',     'Consultare workflow.'),
    ('workflows.create',          'workflows',     'Creare workflow.'),
    ('workflows.update',          'workflows',     'Modificare/abilitare/disabilitare workflow.'),
    ('workflows.delete',          'workflows',     'Eliminare workflow.'),
    -- Comandi in ingresso
    ('commands.execute',          'commands',      'Associare la propria identita'' di canale ed eseguire comandi consentiti.'),
    -- Audit
    ('audit.read',                'audit',         'Consultare l''audit log.'),
    -- Log di sistema
    ('syslog.read',               'syslog',        'Consultare i log di sistema.'),
    -- Configurazione
    ('config.read',               'config',        'Consultare la configurazione.'),
    ('config.update',             'config',        'Modificare la configurazione.')
ON CONFLICT (code) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2) RUOLI PREDEFINITI (is_builtin = true, non eliminabili — RF-012)
--    UUID fissi per stabilita' e idempotenza dei riferimenti.
-- -----------------------------------------------------------------------------
INSERT INTO roles (id, name, description, is_builtin) VALUES
    ('00000000-0000-0000-0000-000000000001', 'SuperAdmin',
        'Controllo totale, inclusa gestione ruoli/permessi e degli altri amministratori.', true),
    ('00000000-0000-0000-0000-000000000002', 'Admin',
        'Gestione operativa completa e gestione utenti; non gestisce la struttura di ruoli/permessi.', true),
    ('00000000-0000-0000-0000-000000000003', 'Operator',
        'Operativita'' su probe/sistemi/notifiche/workflow, consultazione, esecuzione comandi.', true),
    ('00000000-0000-0000-0000-000000000004', 'Viewer',
        'Sola consultazione (dashboard, heartbeat, sistemi, probe).', true),
    ('00000000-0000-0000-0000-000000000005', 'Auditor',
        'Sola consultazione di audit log e log di sistema (+ dashboard base).', true)
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 3) MATRICE RUOLI x PERMESSI (06_rbac.md §4)
-- -----------------------------------------------------------------------------

-- SuperAdmin: TUTTI i permessi.
INSERT INTO role_permissions (role_id, permission_code)
SELECT '00000000-0000-0000-0000-000000000001', code FROM permissions
ON CONFLICT DO NOTHING;

-- Admin: tutti tranne la gestione della struttura ruoli/permessi.
INSERT INTO role_permissions (role_id, permission_code)
SELECT '00000000-0000-0000-0000-000000000002', code FROM permissions
WHERE code NOT IN ('roles.create','roles.update','roles.delete','roles.assign_permissions')
ON CONFLICT DO NOTHING;

-- Operator.
INSERT INTO role_permissions (role_id, permission_code) VALUES
    ('00000000-0000-0000-0000-000000000003', 'profile.read'),
    ('00000000-0000-0000-0000-000000000003', 'profile.update'),
    ('00000000-0000-0000-0000-000000000003', 'probes.read'),
    ('00000000-0000-0000-0000-000000000003', 'probes.update'),
    ('00000000-0000-0000-0000-000000000003', 'systems.read'),
    ('00000000-0000-0000-0000-000000000003', 'systems.create'),
    ('00000000-0000-0000-0000-000000000003', 'systems.update'),
    ('00000000-0000-0000-0000-000000000003', 'checks.read'),
    ('00000000-0000-0000-0000-000000000003', 'dashboard.read'),
    ('00000000-0000-0000-0000-000000000003', 'heartbeats.read'),
    ('00000000-0000-0000-0000-000000000003', 'heartbeats.query'),
    ('00000000-0000-0000-0000-000000000003', 'notifications.read'),
    ('00000000-0000-0000-0000-000000000003', 'notifications.create'),
    ('00000000-0000-0000-0000-000000000003', 'notifications.update'),
    ('00000000-0000-0000-0000-000000000003', 'notifications.test'),
    ('00000000-0000-0000-0000-000000000003', 'workflows.read'),
    ('00000000-0000-0000-0000-000000000003', 'workflows.create'),
    ('00000000-0000-0000-0000-000000000003', 'workflows.update'),
    ('00000000-0000-0000-0000-000000000003', 'commands.execute')
ON CONFLICT DO NOTHING;

-- Viewer.
INSERT INTO role_permissions (role_id, permission_code) VALUES
    ('00000000-0000-0000-0000-000000000004', 'profile.read'),
    ('00000000-0000-0000-0000-000000000004', 'profile.update'),
    ('00000000-0000-0000-0000-000000000004', 'probes.read'),
    ('00000000-0000-0000-0000-000000000004', 'systems.read'),
    ('00000000-0000-0000-0000-000000000004', 'checks.read'),
    ('00000000-0000-0000-0000-000000000004', 'dashboard.read'),
    ('00000000-0000-0000-0000-000000000004', 'heartbeats.read')
ON CONFLICT DO NOTHING;

-- Auditor.
INSERT INTO role_permissions (role_id, permission_code) VALUES
    ('00000000-0000-0000-0000-000000000005', 'profile.read'),
    ('00000000-0000-0000-0000-000000000005', 'profile.update'),
    ('00000000-0000-0000-0000-000000000005', 'dashboard.read'),
    ('00000000-0000-0000-0000-000000000005', 'audit.read'),
    ('00000000-0000-0000-0000-000000000005', 'syslog.read')
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- 4) UTENTE AMMINISTRATORE INIZIALE (SuperAdmin)
--    username: admin   password: ChangeMe123!  (bcrypt, cost 12)
--    RF-021: deve esistere almeno un SuperAdmin attivo.
--    >>> CAMBIARE LA PASSWORD AL PRIMO ACCESSO <<<
-- -----------------------------------------------------------------------------
INSERT INTO users (id, username, email, full_name, password_hash, status) VALUES
    ('00000000-0000-0000-0000-0000000000a1',
     'admin',
     'admin@pulse.example.com',
     'Pulse Administrator',
     '$2b$12$/dbOlipZecqErctsrVMG1ukAzlM69NU2/WZFPNyTkC8IfvFWmNWeO',
     'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_roles (user_id, role_id) VALUES
    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000001')
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- 5) CONFIGURAZIONE DI DEFAULT
--    Valori indicativi (RQ-01/RQ-02): da confermare in esercizio.
--    I valori sono JSON tipizzati; 'type' documenta il tipo logico.
-- -----------------------------------------------------------------------------
INSERT INTO configuration (key, value, type, sensitive, requires_restart, description) VALUES
    ('api_port',                            '8443',    'int',  false, true,  'Porta HTTPS API applicative (utente).'),
    ('probe_endpoint_port',                 '9443',    'int',  false, true,  'Porta HTTPS+mTLS endpoint dedicati Probe.'),
    ('access_token_ttl_seconds',            '900',     'int',  false, false, 'Durata access token JWT (RF-002).'),
    ('refresh_token_ttl_seconds',           '1209600', 'int',  false, false, 'Durata refresh token (RF-002).'),
    ('failed_login_threshold',              '5',       'int',  false, false, 'Tentativi falliti prima del blocco account (RF-005).'),
    ('probe_offline_timeout_seconds',       '120',     'int',  false, false, 'Timeout oltre il quale una Probe e'' considerata offline.'),
    ('retention_system_logs_days',          '90',      'int',  false, false, 'Retention log di sistema (DB-06).'),
    ('retention_notification_deliveries_days','180',   'int',  false, false, 'Retention storico invii notifiche (DB-06).'),
    ('retention_inbound_commands_days',     '90',      'int',  false, false, 'Retention log comandi in ingresso (DB-06).'),
    ('retention_probe_rollups_days',        '7',       'int',  false, false, 'Retention snapshot rollup dashboard (DB-07).'),
    ('timezone',                            '"Europe/Rome"', 'string', false, false, 'Fuso orario IANA per la visualizzazione delle date-ora (es. Europe/Rome, UTC).')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- FINE seed.sql
-- =============================================================================
