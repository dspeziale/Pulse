# Pulse — Schema Fisico DB Server (PostgreSQL 16)

Documento: `docs/database/SCHEMA_FISICO.md`
Autore: AGENTE 2 — DBA
Data: 2026-07-15

Documentazione dello schema fisico del **DB Server**. Fonte di verita' per le
entita': `DOCUMENTO_DATABASE.md` (modello logico §3). Coerenza dei nomi/campi
con `DOCUMENTO_API.md`, permessi con `06_rbac.md`, requisiti dati con
`05_requisiti.md`, entita' workflow con `07_workflow_notifiche.md`.

DDL eseguibile: `deploy/schema.sql`. Dati iniziali: `deploy/seed.sql`.
Diagramma: `docs/database/ER_DIAGRAM.md`.

> Ambito: SOLO dati gestionali + rollup del Server. Le serie temporali
> (heartbeat/eventi) sono su **OpenSearch** locale alle Probe (RF-051) e NON
> compaiono in questo schema.

---

## 1. Motivazione della scelta: PostgreSQL 16

Il motore e' stato fissato dall'utente a **PostgreSQL 16**. Di seguito si
dimostra che soddisfa integralmente i "Requisiti dati" (§6 di
`DOCUMENTO_DATABASE.md`).

| # | Requisito dato | Come PostgreSQL 16 lo soddisfa |
|---|---|---|
| 1 | **Relazionalita' forte** (RBAC N:N, FK, integrita' referenziale) | RDBMS relazionale completo: PK/FK con `ON DELETE/UPDATE`, vincoli `UNIQUE`, `CHECK`, chiavi composte. Le associative `user_roles`/`role_permissions` modellano le N:N con integrita' garantita dal motore. |
| 2 | **Transazionalita' (ACID)** | Transazioni ACID native con isolamento MVCC; operazioni multi-tabella (utente+ruoli, workflow+condizioni+azioni) sono atomiche. |
| 3 | **Immutabilita' audit** (append-only, RNF-006) | Trigger `BEFORE UPDATE OR DELETE` su `audit_log` che solleva eccezione: nessun percorso applicativo puo' alterare l'audit. Rafforzabile con GRANT (solo INSERT/SELECT) e/o partizionamento. |
| 4 | **Campi JSON** (`config`, `scope`, `suppression`, `recipients`, `details`, ...) | Tipo **`jsonb`** nativo: storage binario, indicizzabile (GIN), interrogabile con operatori/`jsonb_path`. Permette query sui documenti senza rinunciare al modello relazionale. |
| 5 | **Volumi crescenti** (`audit_log`, `system_logs`, `notification_deliveries`, `inbound_commands`) | Indici B-tree su colonne temporali; funzione di retention `fn_purge_retention()`; possibilita' di partizionamento nativo per intervallo temporale se i volumi crescono. Le serie grandi restano su OpenSearch. |
| 6 | **Unicita' e vincoli** (username, email, system_id, name) | `UNIQUE` a livello colonna/tabella + `CHECK` per i domini enumerati; enforcement lato DB (deny-by-default sui dati). |
| 7 | **Cifratura a riposo** (segreti in `config`/canali, RNF-004) | Cifratura applicativa dei valori dentro `jsonb` (chiavi gestite dal Backend/secret store); a livello volume, cifratura del filesystem/immagine. `pgcrypto` disponibile se si volesse cifrare lato DB. |
| 8 | **Concorrenza** (UI + ingest eventi/rollup) | MVCC: letture non bloccano scritture; adeguato a concorrenza moderata. |
| 9 | **Portabilita'/deploy** | Immagine ufficiale `postgres:16`, rootless-friendly, init via `/docker-entrypoint-initdb.d`; nessun vincolo proprietario. Compose per Docker e Podman forniti. |
| 10 | **Backup/restore** | `pg_dump`/`pg_restore`/`pg_basebackup`, PITR via WAL. |

**Sintesi**: i requisiti indicano una forte componente relazionale con alcune
strutture documentali. PostgreSQL 16 e' l'unione ottimale RDBMS + `jsonb`,
coprendo sia l'integrita' relazionale sia la flessibilita' JSON, senza introdurre
un secondo motore documentale sul Server (OpenSearch resta confinato alle Probe).

---

## 2. Convenzioni e mapping dei tipi

| Tipo logico (§2 modello) | Tipo PostgreSQL | Motivazione |
|---|---|---|
| UUID | `uuid` (default `gen_random_uuid()`) | Identificatori opachi; `gen_random_uuid()` in core da PG 13 (nessuna estensione richiesta). |
| STRING(n) | `varchar(n)` | Limiti coerenti col modello logico. |
| TEXT | `text` | Testi liberi (messaggi, template, errori). |
| INT / BIGINT | `integer` / `bigint` | — |
| DECIMAL | `numeric` | (non usato sul Server; i valori numerici da metriche sono su OpenSearch) |
| BOOLEAN | `boolean` | — |
| TIMESTAMP (UTC) | `timestamptz` | Sempre UTC; timezone-aware, coerente con ISO-8601 delle API. |
| ENUM(...) | `varchar` + `CHECK (col IN (...))` | Piu' portabile e **evolvibile** di `CREATE TYPE`: aggiungere un valore non richiede `ALTER TYPE`, solo la modifica del CHECK. Idempotenza semplice dentro `CREATE TABLE IF NOT EXISTS`. |
| JSON | `jsonb` | Indicizzabile e query-abile (requisito dato #4). |
| ARRAY<STRING> | `jsonb` (array) | `probes.tags`: coerente con l'array JSON restituito dalle API; `CHECK jsonb_typeof(tags)='array'`. |

Convenzioni: ogni entita' ha `id uuid PK` (tranne `permissions` con PK naturale
`code` e `configuration` con PK naturale `key`); `created_at`/`updated_at` dove
utile; nomi tabella al plurale (come da modello logico).

**Identificatori quotati** (parole riservate PostgreSQL): `"trigger"`
(`notification_workflows`), `"timestamp"` (`audit_log`, `system_logs`),
`"window"` (`probe_rollups`), `"repeat"` (`workflow_actions`). I nomi sono stati
mantenuti identici al modello/API per coerenza (RNF-050); l'ORM del Backend
mappera' questi campi con i medesimi nomi JSON.

---

## 3. Tabelle (dettaglio)

Per ogni tabella: colonne (tipo Postgres), PK, FK con azioni referenziali,
UNIQUE, CHECK, indici e motivazione. Le tabelle seguono la numerazione del
modello logico §3.1–§3.23.

### 3.1 users
PK `id`. UNIQUE `username`, `email`. CHECK `status IN (active,disabled,locked)`,
`failed_login_count >= 0`. Trigger `updated_at`. Indice `idx_users_status`
(filtro `GET /users?status`). `password_hash varchar(255)` ospita hash bcrypt
o argon2 (vedi §5).

### 3.2 roles
PK `id`. UNIQUE `name`. `is_builtin` marca i 5 ruoli predefiniti. Trigger
`updated_at` + trigger `fn_protect_builtin_roles` (blocca DELETE e la modifica di
`name`/`is_builtin` sui ruoli builtin — RF-012, RB-02).

### 3.3 permissions
PK naturale `code varchar(64)`. `area`, `description` NOT NULL. Catalogo **fisso**
popolato dal seed (non creabile via API — RF-014). Indice `idx_permissions_area`.

### 3.4 user_roles (associativa N:N)
PK composta `(user_id, role_id)`. FK `user_id`→users `ON DELETE CASCADE`,
`role_id`→roles `ON DELETE CASCADE` (rimuovendo utente/ruolo si puliscono le
associazioni). Indice `idx_user_roles_role` per la ricerca inversa "utenti per
ruolo" (`GET /users?role`).

### 3.5 role_permissions (associativa N:N)
PK composta `(role_id, permission_code)`. FK `role_id`→roles `ON DELETE CASCADE`;
FK `permission_code`→permissions `ON UPDATE CASCADE ON DELETE RESTRICT` (il
catalogo e' fisso: un permesso non si cancella se assegnato). Indice
`idx_role_permissions_code`.

### 3.6 probes
PK `id`. UNIQUE `name`. `tags jsonb` con CHECK `jsonb_typeof(tags)='array'`.
CHECK `status IN (pending,online,offline)`. `token_hash`/`certificate_fingerprint`
per mTLS+token (RNF-002). Trigger `updated_at`. Indici su `status` e `enabled`
(filtri `GET /probes?status`). `systems_count` dell'API e' derivato dalla vista
`v_probe_system_counts`.

**Dati anagrafici della Sonda** (tutti NULLABLE, opzionali):
- `location varchar(255)` — posizione/sede fisica o logica.
- `contact_name varchar(255)` — referente.
- `contact_email varchar(255)` — email del referente.
- `contact_phone varchar(50)` — telefono del referente.

Su installazioni pulite i campi sono in `deploy/schema.sql`; sui DB gia'
esistenti sono aggiunti dalla migrazione `deploy/migrations/003_probe_registry.sql`
(idempotente). Essendo nullable, i dati preesistenti restano validi.

### 3.7 enrollment_tokens
PK `id`. FK `probe_id`→probes `ON DELETE CASCADE`. Token monouso a scadenza
(`expires_at`, `used_at`) — RNF-007. Indici: `probe_id`, `token_hash` (lookup in
`POST /probe/register`), `expires_at` (purge).

### 3.8 monitored_systems
PK `id`. UNIQUE `system_id` (coincide con `system_id` heartbeat). FK
`probe_id`→probes **`ON DELETE RESTRICT`**: implementa il 409 di
`DELETE /probes/{id}` quando esistono sistemi assegnati. CHECK
`poll_interval_seconds > 0`, `timeout_seconds > 0`, soglie `>= 0`. Trigger
`updated_at`. Indici su `probe_id` (filtro + pull config Probe) e `enabled`.

**Tipo di controllo (`kind`)** — un sistema puo' essere monitorato in due modi:
- `kind varchar(10) NOT NULL DEFAULT 'http'` con CHECK `kind IN ('http','tcp')`.
  Il default `'http'` garantisce che i sistemi preesistenti restino validi.
- `kind='http'`: controllo via heartbeat HTTP/HTTPS su `heartbeat_url`.
- `kind='tcp'`: controllo di connettivita' TCP su `tcp_host varchar(255)` +
  `tcp_port integer` (CHECK `tcp_port IS NULL OR tcp_port BETWEEN 1 AND 65535`).
- `heartbeat_url varchar(500)` e' **NULLABLE**: obbligatorio solo per `http`.
- CHECK di coerenza `chk_monitored_systems_kind`:
  `(kind='http' AND heartbeat_url IS NOT NULL) OR (kind='tcp' AND tcp_host IS NOT NULL AND tcp_port IS NOT NULL)`.

Su installazioni pulite lo stato e' prodotto da `deploy/schema.sql`; sui DB gia'
esistenti dalla migrazione `deploy/migrations/002_tcp_checks.sql` (idempotente).

### 3.9 maintenance_windows
PK `id`. FK `system_id`→monitored_systems `ON DELETE CASCADE`, `probe_id`→probes
`ON DELETE CASCADE`, `created_by`→users `ON DELETE SET NULL`. CHECK
`end_at > start_at`. Ambito: sistema, probe o globale (entrambe le FK NULL).
Indici su `system_id`, `probe_id` e `(start_at, end_at)` (verifica "in
manutenzione ora" nella soppressione workflow).

### 3.10 discovered_checks
PK `id`. FK `system_id`→monitored_systems `ON DELETE CASCADE`, `probe_id`→probes
`ON DELETE CASCADE`. UNIQUE `(system_id, check_id)` (upsert del registro
sintetico). Indice `probe_id`. Registro per UI; i dati puntuali sono su
OpenSearch (DB-03).

### 3.11 notification_channels
PK `id`. UNIQUE `name`. CHECK `type IN (email,telegram,whatsapp)`. `config jsonb`
con segreti **cifrati a riposo** a livello applicativo (RNF-004). Trigger
`updated_at`. Indice `type`.

### 3.12 notification_workflows
PK `id`. UNIQUE `name`. Colonna `"trigger"` con CHECK sugli 8 trigger di
`07_workflow_notifiche.md` §2. `scope`/`suppression` come `jsonb`. FK
`created_by`→users `ON DELETE SET NULL`. Trigger `updated_at`. Indici su
`enabled` e `"trigger"` (selezione dei workflow candidati per tipo di evento).

### 3.13 workflow_conditions
PK `id`. FK `workflow_id`→notification_workflows `ON DELETE CASCADE`. CHECK `op IN
(eq,neq,gt,gte,lt,lte,in,not_in,contains,matches)`. `value jsonb`. Indice
`workflow_id`.

### 3.14 workflow_actions
PK `id`. FK `workflow_id`→notification_workflows `ON DELETE CASCADE`; FK
`channel_id`→notification_channels **`ON DELETE RESTRICT`** (implementa il 409 di
`DELETE /notification-channels/{id}` quando il canale e' usato da un workflow).
UNIQUE `(workflow_id, step_order)` (ordine escalation univoco). CHECK
`delay_seconds >= 0`. `recipients`/`escalation_condition`/`"repeat"` come `jsonb`.
Indice `channel_id`.

### 3.15 alarms
PK `id`. FK `workflow_id`→workflows, `probe_id`→probes, `system_id`→systems,
`acknowledged_by`→users, tutte **`ON DELETE SET NULL`** (l'allarme e' un record
storico che sopravvive alla cancellazione delle entita' collegate). CHECK
`status IN (active,acknowledged,resolved)`. Indici: `(dedup_key, status)`
(throttling/dedup), `status`, `system_id`, `probe_id`, `opened_at` (filtri
`GET /alarms`).

### 3.16 notification_deliveries
PK `id`. FK `workflow_id`/`action_id`/`alarm_id` `ON DELETE SET NULL` (storico
che sopravvive). FK `channel_id`→notification_channels `NOT NULL ON DELETE
RESTRICT` — vedi INCONGRUENZE §7 (I-3). CHECK `status IN (sent,failed,retrying)`,
`retry_count >= 0`. Indici: `channel_id`, `workflow_id`, `alarm_id`, `status`,
`created_at` (storico filtrabile `GET /notifications/history` + purge retention).

### 3.17 channel_identities
PK `id`. FK `user_id`→users `ON DELETE CASCADE`. CHECK `channel_type IN
(email,telegram,whatsapp)`. UNIQUE `(channel_type, external_id)` (una identita' →
un solo utente). Indice `user_id`.

### 3.18 inbound_commands
PK `id`. FK `user_id`→users `ON DELETE SET NULL` (log conservato anche se
l'utente viene rimosso). CHECK `channel_type IN (...)`, `outcome IN
(executed,denied,error)`. Indici: `(channel_type, external_id)`, `user_id`,
`received_at` (retention + ordinamento).

### 3.19 audit_log (append-only)
PK `id`. Colonna `"timestamp"`. CHECK `actor_type IN (user,probe,system)`,
`outcome IN (success,failure)`. `details jsonb`. **Immutabile**: trigger
`fn_audit_log_immutable` blocca UPDATE/DELETE (RNF-006). Nessuna FK verso `users`
su `actor_id` (l'attore puo' essere probe/system e l'audit deve sopravvivere alla
cancellazione dell'attore: `actor_id varchar` per attore polimorfo). Indici per i
filtri `GET /audit`: `"timestamp" DESC`, `(actor_type, actor_id)`, `action`,
`(entity_type, entity_id)`, `outcome`.

### 3.20 system_logs
PK `id`. Colonna `"timestamp"`. FK `probe_id`→probes `ON DELETE SET NULL`. CHECK
`component IN (server,probe)`, `level IN (debug,info,warning,error,critical)`.
`context jsonb`. Indici: `("timestamp", component, level)` (filtri `GET /logs`) e
`probe_id`.

### 3.21 configuration
PK naturale `key varchar(100)`. `value jsonb` tipizzato (`type` documenta il tipo
logico). `sensitive` per il mascheramento. FK `updated_by`→users `ON DELETE SET
NULL`. Trigger `updated_at`.

Parametri di default popolati da `deploy/seed.sql` (valori indicativi,
configurabili in esercizio):

| key | value | type | requires_restart | descrizione |
|---|---|---|:--:|---|
| `api_port` | 8443 | int | sì | Porta HTTPS API applicative (utente). |
| `probe_endpoint_port` | 9443 | int | sì | Porta HTTPS+mTLS endpoint dedicati Probe. |
| `access_token_ttl_seconds` | 900 | int | no | Durata access token JWT (RF-002). |
| `refresh_token_ttl_seconds` | 1209600 | int | no | Durata refresh token (RF-002). |
| `failed_login_threshold` | 5 | int | no | Tentativi falliti prima del blocco account (RF-005). |
| `probe_offline_timeout_seconds` | 120 | int | no | Timeout oltre il quale una Probe e' offline. |
| `retention_system_logs_days` | 90 | int | no | Retention log di sistema (DB-06). |
| `retention_notification_deliveries_days` | 180 | int | no | Retention storico invii notifiche (DB-06). |
| `retention_inbound_commands_days` | 90 | int | no | Retention log comandi in ingresso (DB-06). |
| `retention_probe_rollups_days` | 7 | int | no | Retention snapshot rollup dashboard (DB-07). |
| `timezone` | "Europe/Rome" | string | no | Fuso orario IANA per la visualizzazione delle date-ora (es. Europe/Rome, UTC). |

Il valore `timezone` e' memorizzato come stringa JSON (`"Europe/Rome"`) nella
colonna `value jsonb`. Su DB gia' esistenti e' aggiunto dalla migrazione
`deploy/migrations/004_config_timezone.sql` (idempotente, `ON CONFLICT DO NOTHING`).

### 3.22 sessions / refresh_tokens
PK `id`. FK `user_id`→users `ON DELETE CASCADE`. `refresh_token_hash` (mai il
token in chiaro). `revoked_at` per logout/revoca. Indici: `user_id`,
`refresh_token_hash` (lookup `POST /auth/refresh`, revoca `POST /auth/logout`),
`expires_at` (purge).

### 3.23 probe_rollups
PK `id`. FK `probe_id`→probes `ON DELETE CASCADE`. Colonna `"window"` (es.
`1h`/`24h`). `payload jsonb` (riepilogo sistemi/check/uptime). Indice
`(probe_id, generated_at DESC)` (ultimo rollup per probe). **Non e' serie
temporale grezza**: e' un riepilogo periodico con retention breve (DB-07).

---

## 4. Viste

| Vista | Scopo | Usata da |
|---|---|---|
| `v_user_effective_permissions` | Permessi effettivi per utente = unione dei permessi dei suoi ruoli (deny-by-default). | `POST /auth/login`, `GET /auth/me` (campo `permissions`) |
| `v_probe_system_counts` | Conteggio sistemi per Probe. | `GET /probes` (campo `systems_count`) |
| `v_active_alarms` | Allarmi non risolti (`active`/`acknowledged`). | Dashboard `active_alarms`, `GET /alarms?status=active` |

---

## 5. Strategie richieste

### 5.1 Audit immutabile (RNF-006, DB-05)
- **Meccanismo primario**: funzione `fn_audit_log_immutable()` + trigger
  `trg_audit_log_immutable` `BEFORE UPDATE OR DELETE ON audit_log` che solleva
  eccezione (`ERRCODE insufficient_privilege`). Verificato: UPDATE e DELETE
  falliscono, INSERT consentito.
- **Difesa in profondita' (raccomandata in produzione)**: creare un ruolo DB
  applicativo con `GRANT INSERT, SELECT ON audit_log` e **senza** UPDATE/DELETE;
  il trigger resta come rete di sicurezza anche per ruoli con privilegi elevati.
- **Retention**: l'audit **non** viene mai purgato da `fn_purge_retention()`
  (conservazione a fini di conformita'). L'eventuale archiviazione a lungo
  termine e' una decisione operativa (partizionamento per anno + export).

### 5.2 Retention log/deliveries (DB-06, RQ-02)
- Funzione `fn_purge_retention(p_system_logs_days, p_deliveries_days,
  p_inbound_days, p_rollups_days)` che elimina i record oltre soglia da
  `system_logs`, `notification_deliveries`, `inbound_commands`, `probe_rollups`,
  piu' igiene di `enrollment_tokens` scaduti e `sessions` scadute/revocate.
- **Default** allineati ai valori seed in `configuration`: system_logs 90gg,
  deliveries 180gg, inbound 90gg, rollups 7gg (valori indicativi, configurabili).
- **Schedulazione**: da invocare da uno scheduler esterno (cron di sistema o job
  del Backend) oppure da `pg_cron` se installato. `pg_cron` non e' incluso
  nell'immagine `postgres:16` standard: scelta conservativa = scheduling esterno,
  cosi' lo schema resta portabile e non dipende da estensioni non garantite.
- **Scalabilita'**: se i volumi crescono oltre le soglie gestibili con DELETE, si
  migra a **partizionamento nativo per range temporale** e si sostituisce il
  purge con `DROP PARTITION` (operazione O(1)). Predisposizione documentata; non
  attivata di default per non complicare il modello con volumi medio-bassi.

### 5.3 Seed permessi/ruoli RBAC (06_rbac.md)
- `deploy/seed.sql` popola: 40 permessi (catalogo enumerato — vedi I-1), 5 ruoli
  predefiniti (`is_builtin=true`), matrice ruoli×permessi (SuperAdmin=tutti,
  Admin=tutti tranne gestione struttura ruoli, Operator/Viewer/Auditor come da
  §4 di `06_rbac.md`), utente `admin` SuperAdmin.
- **Idempotente**: tutti gli INSERT usano `ON CONFLICT DO NOTHING`; rieseguibile
  senza errori (verificato: seconda esecuzione inserisce 0 righe).
- **RF-021** (almeno un SuperAdmin attivo): garantito dal seed iniziale; il
  vincolo dinamico "non rimuovere l'ultimo SuperAdmin" e' applicato dal Backend
  (409), poiche' dipende dalla logica applicativa (transazione + conteggio).

### 5.4 updated_at automatico
- `fn_set_updated_at()` + trigger su `users`, `roles`, `probes`,
  `monitored_systems`, `notification_channels`, `notification_workflows`,
  `configuration`.

---

## 6. Hashing password (decisione DBA)

`05_requisiti.md` RNF-003 richiede "hashing forte e salato" **senza** fissare
l'algoritmo. Il modello dati non specifica lo schema. Decisione conservativa:
**bcrypt** (cost/rounds = 12), standard consolidato, supportato nativamente dallo
stack Python/FastAPI (librerie `bcrypt`/`passlib`). La colonna
`users.password_hash varchar(255)` ospita l'intero hash modulare
(`$2b$12$...`), compatibile anche con `argon2id` (`$argon2id$...`) qualora il
Backend preferisse argon2 — in tal caso rigenerare l'hash del seed con lo stesso
schema. L'hash seed corrisponde a `ChangeMe123!` e **deve essere cambiato al
primo accesso** (documentato in `seed.sql`).

---

## 7. INCONGRUENZE / QUESTIONI APERTE

Rilevate rispetto all'analisi; per ognuna la decisione conservativa allineata
all'API. **Nessuna entita' o campo e' stato inventato.**

| # | Incongruenza | Riscontro | Decisione conservativa |
|---|---|---|---|
| **I-1** | Numero permessi RBAC | `06_rbac.md` dichiara "37 permessi" e `DOCUMENTO_DATABASE.md` idem, ma il catalogo **enumerato** in `06_rbac.md` §2 e la matrice §4 contengono **40 codici distinti**. | Seed di **tutti i 40 codici enumerati** (superset esplicitamente definito dall'Analista, necessario a matrice e API). Il "37" e' un conteggio errato nel testo, non una lista ridotta. Da segnalare all'Analista per allineare il totale. |
| **I-2** | `probes.tags` tipo | Modello: "ARRAY<STRING> / JSON" (ambiguo). | Scelto `jsonb` array con `CHECK jsonb_typeof='array'`, coerente con l'array JSON `tags:[string]` restituito dall'API `Probe`. |
| **I-3** | Cancellazione canale vs storico invii | API `DELETE /notification-channels/{id}` → 409 solo "se usato da **workflow**"; ma `notification_deliveries.channel_id` e' `NOT NULL` (modello §3.16) e le delivery sono storiche. | `channel_id NOT NULL ON DELETE RESTRICT`: preserva l'integrita' dello storico. Conseguenza: un canale con delivery storiche non e' cancellabile finche' le delivery non sono purgate per retention. Il 409 "workflow" resta implementato da `workflow_actions.channel_id RESTRICT`. Alternativa (non scelta) sarebbe rendere `channel_id` nullable, ma contraddirebbe il modello. |
| **I-4** | Parole riservate come nomi colonna | `trigger`, `timestamp`, `window`, `repeat`. | Mantenuti i nomi del modello/API (coerenza RNF-050) quotandoli nel DDL. Nessuna rinomina per non divergere dai contratti API. |
| **I-5** | `audit_log.actor_id` polimorfo | Attore puo' essere user/probe/system; `actor_id STRING(100)`. | Nessuna FK su `actor_id` (attore polimorfo + audit deve sopravvivere alla cancellazione dell'attore). Coerente col modello (tipo STRING, non UUID FK). |
| **I-6** | Ultimo SuperAdmin (RF-021) | Regola dinamica non esprimibile in modo affidabile con un semplice vincolo DB. | Enforcement a livello Backend (409), come gia' previsto dall'API. Il DB garantisce il seed iniziale e la protezione dei ruoli builtin. |

---

## 8. Copertura entita' del modello logico

Tutte e **23** le entita' del DB Server (§3.1–§3.23 di `DOCUMENTO_DATABASE.md`)
sono implementate in `deploy/schema.sql` (verificato: 23 BASE TABLE create).
Le entita' OpenSearch (§5: `heartbeats`, `events`) sono **escluse** come da
vincolo (RF-051).

| # | Entita' modello | Tabella | # | Entita' modello | Tabella |
|---|---|---|---|---|---|
| 3.1 | users | ✔ | 3.13 | workflow_conditions | ✔ |
| 3.2 | roles | ✔ | 3.14 | workflow_actions | ✔ |
| 3.3 | permissions | ✔ | 3.15 | alarms | ✔ |
| 3.4 | user_roles | ✔ | 3.16 | notification_deliveries | ✔ |
| 3.5 | role_permissions | ✔ | 3.17 | channel_identities | ✔ |
| 3.6 | probes | ✔ | 3.18 | inbound_commands | ✔ |
| 3.7 | enrollment_tokens | ✔ | 3.19 | audit_log | ✔ |
| 3.8 | monitored_systems | ✔ | 3.20 | system_logs | ✔ |
| 3.9 | maintenance_windows | ✔ | 3.21 | configuration | ✔ |
| 3.10 | discovered_checks | ✔ | 3.22 | sessions | ✔ |
| 3.11 | notification_channels | ✔ | 3.23 | probe_rollups | ✔ |
| 3.12 | notification_workflows | ✔ | | | |

---

## 9. Esito validazione

Schema validato su container **PostgreSQL 16** (Docker) — vedi `DIARIO.md`
Iterazione 2:
- `schema.sql` applicato pulito (exit 0), **23 tabelle**, 3 viste, **4 funzioni
  applicative** (`fn_set_updated_at`, `fn_audit_log_immutable`,
  `fn_protect_builtin_roles`, `fn_purge_retention`; oltre alle funzioni
  dell'estensione `pgcrypto`), **9 trigger** distinti, 78 indici.
- `seed.sql` applicato pulito: 40 permessi, 5 ruoli, matrice (SuperAdmin 40 /
  Admin 36 / Operator 19 / Viewer 7 / Auditor 5), 1 utente admin, 10 config.
- **Idempotenza** verificata: re-run di schema e seed senza errori (0 righe
  inserite al secondo passaggio).
- **Trigger** verificati: UPDATE/DELETE su `audit_log` rifiutati; DELETE e
  rinomina di ruolo builtin rifiutati.
- **Vista** `v_user_effective_permissions`: 40 permessi per l'utente admin.
