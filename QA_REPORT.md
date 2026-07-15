# Pulse — QA Report (AGENTE 5 — QA)

Data: 2026-07-15 (Iterazione 1) · 2026-07-16 (Re-collaudo Iterazione 2)
Ambiente: Windows 11, Python 3.13.14, Docker 29.5.3 (Podman non installato).
Fonti di verità: `docs/api/DOCUMENTO_API.md`, `docs/analisi/*`, `deploy/schema.sql`+`seed.sql`.

> **AGGIORNAMENTO (Re-collaudo Iterazione 2, 2026-07-16): VERDETTO ATTUALE = PASS.**
> Tutti i finding dell'Iterazione 1 sono stati verificati come **CHIUSI**. Il verdetto FAIL
> qui sotto è quello **storico** dell'Iterazione 1; l'esito valido è nella **§7 Re-collaudo**.

---

## 1. Sommario esecutivo (Iterazione 1 — storico)

**VERDETTO: FAIL** (nessun bug **Bloccante**; il fallimento è dovuto a **1 bug Maggiore** di
validazione contratto e al mancato raggiungimento dell'obiettivo esplicito di **coverage 100%**
su Backend e Probe-agent). Il sistema è per il resto funzionalmente solido e aderente al contratto:
RBAC deny-by-default corretto, audit immutabile, vincoli DB applicati, JWT robusto, segreti mascherati.

Conteggio bug per gravità:
- Bloccante: **0**
- Maggiore: **1** (BUG-01 validazione email)
- Media: **2** (BUG-03 coverage BE 98%, BUG-04 coverage Probe 98%)
- Minore: **3** (BUG-02 ruolo builtin, DOC-01 conteggio permessi, SEC-01 header sicurezza)

Routing fix: **BUG_BACKEND = BUG-01, BUG-03, BUG-04, SEC-01** (+ BUG-02/DOC-01 chiarimento doc/schema) — **BUG_FRONTEND = nessuno**.

Coverage reali:
- Backend server: **98%** (target 100% → gap) — 181 test, 0 falliti.
- Probe agent: **98%** (target 100% → gap) — 65 test, 0 falliti.
- Frontend (frontend_common + dashboard Server + dashboard Probe): **100%** sul codice applicativo — 104 test, 0 falliti.

Totale test automatici eseguiti: **350 pytest** (0 falliti) + **127 asserzioni integrazione live** (125 pass, 2 fail = i 2 bug) + **7 verifiche vincoli/trigger DB** (tutte pass) + **7 smoke Probe live** (tutte pass).

---

## 2. Risultati per categoria di test

### 2.1 Backend Test (unit + integration pytest)
- Comando: `pytest --cov=pulse_server` nel venv `server/backend/.venv` con Postgres 16 effimero (Docker, porta 5433) + schema+seed.
- Esito: **181/181 PASS**, coverage **98%** (2706 stmt, 20 miss, 526 branch, 36 branch parziali).
- Vedi §3 per il dettaglio delle righe scoperte.

### 2.2 Probe Test (agent)
- Comando: `pytest --cov=pulse_probe` nel venv `probe/agent/.venv` (storage in-memory + httpx MockTransport).
- Esito: **65/65 PASS**, coverage **98%** (565 stmt, 6 miss).
- Smoke live: probe-agent avviato (uvicorn, in-memory fallback) → `/health`=200, `/health/ready`=200,
  `/status` senza token=401, con token=200, `/systems`=200, `/query/heartbeats`=200, `POST /query` token errato=401.
  Parsing schema canonico (oggetto/array), query strutturata e auth in tempo costante coperti dalla suite.

### 2.3 Frontend Test (Flask, backend mockato)
- `frontend_common/tests`: **27 PASS**, coverage **100%** (auth/config/http_client/rbac).
- `server/dashboard/tests`: **50 PASS**, coverage **100%** sul codice app (app/sdk/views P-01..P-19).
- `probe/dashboard/tests`: **27 PASS**, coverage **100%** sul codice app (app/sdk/views PP-01..PP-05).
- (Le uniche righe non coperte sono in `tests/conftest.py`, cioè helper di test, non codice applicativo.)

### 2.4 API Test / Integration Test (server live vs DOCUMENTO_API)
- Postgres 16 Docker (porta 5434) + schema+seed; backend uvicorn reale su :8600.
- Campione ampio e rappresentativo (**127 asserzioni**) su tutte le aree del contratto: Auth (login/refresh/me/logout/change-password),
  Utenti, Ruoli, Permessi, Probe, Sistemi, Check, Heartbeat/Query (proxy), Dashboard, Comunicazione Server↔Probe
  (register/config/heartbeat/events/rollup), Notifiche/Canali (+test), Workflow (+simulate/enabled), Allarmi,
  Channel-identities, Audit, Log, Config, Health.
- Verificati status code e forma della response contro il documento. **125 PASS, 2 FAIL** (→ BUG-01, BUG-02).

### 2.5 Functional / Workflow / Notification Test
- Creazione canale email → segreti mascherati (`SECRET123` assente in response); `test` canale → 200 `{delivered:false,...}`
  in assenza di credenziali (degradazione controllata, coerente con SCOSTAMENTO BE #4).
- Workflow: create con canale valido=201; con canale inesistente=422; toggle `enabled`=200; `simulate`=200 con `matched`.
- Vincolo d'uso: DELETE canale usato da workflow → 409 (FK RESTRICT su `workflow_actions.channel_id`).
- Allarmi: list/filtri=200; ack di allarme inesistente=404.

### 2.6 RBAC Test
- Creati utenti reali via API con ruoli **Operator/Viewer/Auditor** e verificati accessi:
  - Viewer: `systems.read`=200; `users.read`/`roles.read`/`audit.read` = **403**.
  - Operator: `notifications.read`=200; `users.read`/`config.read` = **403**.
  - Auditor: `audit.read`/`syslog.read`=200; `systems.read`/`probes.read` = **403**.
- Deny-by-default: endpoint senza token = **401**. Matrice seed verificata (SuperAdmin 40, Admin 36, Operator 19, Viewer 7, Auditor 5).
- Integrità RBAC: auto-eliminazione admin=409, auto-disabilitazione admin=409, delete/modifica ruoli builtin=409 (via API e via trigger DB).

### 2.7 Security Test
- JWT: firma manomessa=401; token firmato con secret errato=401; token scaduto (secret corretto)=401.
- Masking segreti: config canale non espone password/token in chiaro (GET e create).
- SQL injection su `q`/`status` di `/users`: gestita (nessun 500; ORM parametrizzato) → 200/422.
- Header sicurezza: **assenti** (X-Frame-Options, X-Content-Type-Options, CSP, HSTS) e header `Server: uvicorn`
  che rivela lo stack → SEC-01 (Minore; non richiesto dal contratto, hardening consigliato).

### 2.8 Audit Test / Log Test
- Le azioni sensibili producono voci in `audit_log` (verificato: `GET /audit` popolato dopo le operazioni).
- Immutabilità (RNF-006): UPDATE su `audit_log` → **ERRORE** `audit_log è immutabile ... UPDATE vietata`;
  DELETE → **ERRORE ... DELETE vietata` (trigger `fn_audit_log_immutable`). `GET /audit/{id}`=200.
- `GET /logs` (system_logs) accessibile con `syslog.read`.

### 2.9 Database Test (vincoli/trigger/seed)
- Trigger audit immutabile: OK (UPDATE/DELETE bloccati).
- Trigger protezione ruoli builtin: DELETE SuperAdmin → errore; UPDATE `name` SuperAdmin → errore. OK.
- UNIQUE `users.username`: violazione → errore. OK.
- CHECK `poll_interval_seconds > 0`: violazione → errore. OK.
- FK RESTRICT `monitored_systems.probe_id`: DELETE probe con sistemi → errore. OK (a livello API = 409).
- Seed: 40 permessi, 5 ruoli builtin, matrice corretta, admin SuperAdmin, 10 parametri config. OK.

### 2.10 Performance Test (smoke)
- Login (bcrypt cost 12): media **256 ms** (atteso per l'hashing forte).
- List endpoint autenticati (n=20 ciascuno): media **11–18 ms**, max ~24 ms.
- 100 richieste sequenziali `/health`: totale ~137 ms (media 1.4 ms). Nessun errore.

### 2.11 Deploy Test
- `docker compose config`: **VALIDO** su `docker-compose.server.yml`, `docker-compose.probe.yml`, `docker-compose.yml`.
- Coerenza porte/env/healthcheck: Dockerfile backend/dashboard con `HEALTHCHECK` e porta da env; postgres/opensearch con healthcheck e `depends_on: service_healthy`. OK.
- Podman: **revisione statica** (non installato). Presenti `podman-compose.{server,probe,}.yml`, struttura allineata ai compose Docker validati.

---

## 3. Coverage — gap rispetto al 100%

### Backend server (98%) — righe/rami non coperti
| File | Missing |
|---|---|
| context.py | 26 |
| deps.py | 113->112 |
| routers/auth.py | 123, 138->140 |
| routers/dashboard.py | 114->121 |
| routers/inbound.py | 104, 126-127 |
| routers/notifications.py | 34->37, 37->40, 231-233, 237->241, 241->245 |
| routers/observability.py | 112, 115->117, 117->119, 119->121 |
| routers/probe_comm.py | 48, 62-64, 90 |
| routers/probes.py | 41->44, 44->49 |
| routers/roles.py | 43->47, 108, 109->111 |
| routers/systems.py | 60->64, 64->67, 67->72, 233->236, 236->240 |
| routers/users.py | 39->41, 150, 185 |
| routers/workflows.py | 100->103, 103->107, 195->197 |
| workflow.py | 220->217, 261, 305, 405 |

### Probe agent (98%) — righe/rami non coperti
| File | Missing |
|---|---|
| main.py | 88->exit, 97-99 |
| query.py | 16, 71->75, 92->83, 114-115 |

Nota: gran parte dei residui sono rami difensivi/I-O (lettura CA in `/probe/register`, provider di produzione,
combinazioni di filtro ridondanti, casi "ultimo SuperAdmin"), ma essendo l'obiettivo richiesto **100%**, il gap
è registrato come finding di gravità Media (BUG-03/BUG-04).

---

## 4. Tabella BUG

| ID | Area | Titolo | Descrizione / Passi | Gravità | Fix suggerito | File coinvolto |
|---|---|---|---|---|---|---|
| BUG-01 | BACKEND | Validazione formato email assente su create/update utente | `POST /api/v1/users` con `email:"clearly-not-an-email"` → **201** e valore memorizzato tale e quale (verificato via DB). Il contratto definisce `email` come campo email e prevede **422** per validazione fallita. Vale anche per `PUT /users/{id}` (`UserUpdate.email`). Il DB non ha CHECK di formato. | **Maggiore** | Usare `pydantic.EmailStr` per `UserCreate.email` e `UserUpdate.email` (o validator regex) → risponde 422 su formato non valido. | `server/backend/pulse_server/schemas.py:95` (e `:103`) |
| BUG-02 | DOC | `PUT /roles/{id}` modifica la `description` di un ruolo predefinito | `PUT /roles/{SuperAdmin}` con `{"description":"HACKED-DESC"}` → **200** e la descrizione viene persistita. Il DOCUMENTO_API §1.3 elenca per PUT su ruolo predefinito l'errore **409 (ruolo predefinito)**. Ambiguità: il trigger DB `fn_protect_builtin_roles` **consente volutamente** la modifica di `description` (blocca solo `name`/`is_builtin`), e RB-02 parla di "struttura bloccata". Conflitto tra API doc e schema → classificato DOC/Minore. | **Minore** | Chiarire nel DOCUMENTO_API se la sola `description` è modificabile sui builtin; in caso negativo, il backend deve restituire 409 anche per la description (allineare a schema.sql). | `server/backend/pulse_server/routers/roles.py`; `deploy/schema.sql:68-88`; `docs/api/DOCUMENTO_API.md:135-137` |
| BUG-03 | BACKEND | Coverage backend 98% < obiettivo 100% | Suite `pytest --cov=pulse_server`: 20 stmt + 36 rami parziali non coperti (dettaglio §3). Obiettivo richiesto = 100%. | **Media** | Aggiungere test per i rami elencati (probe_comm, notifications, observability, systems, users, workflow) o marcare `pragma: no cover` i rami difensivi non testabili. | vedi §3 |
| BUG-04 | BACKEND | Coverage probe-agent 98% < obiettivo 100% | Suite `pytest --cov=pulse_probe`: 6 stmt non coperti (main.py 97-99, query.py 16/114-115). Obiettivo richiesto = 100%. | **Media** | Test su lifespan/bootstrap e sul ramo di parsing timestamp in query.py, oppure `pragma: no cover` motivato. | `probe/agent/pulse_probe/main.py`, `probe/agent/pulse_probe/query.py` |
| DOC-01 | DOC | Conteggio permessi "37" vs 40 reali | `docs/analisi/06_rbac.md` §2 dichiara "Totale: 37 permessi", ma il catalogo enumerato e `seed.sql` contengono **40** codici (verificato: `permissions=40`). Già segnalato da DBA (I-1) e BE (SCOSTAMENTO 1). | **Minore** | Correggere il totale in 40 nel documento RBAC (i codici sono corretti; è errato solo il totale dichiarato). | `docs/analisi/06_rbac.md:124` |
| SEC-01 | BACKEND | Header di sicurezza HTTP assenti + banner server | Le response non includono `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Strict-Transport-Security`; header `Server: uvicorn` espone lo stack. Non richiesto esplicitamente dal contratto (quindi non violazione), ma hardening consigliato. | **Minore** | Middleware che aggiunge gli header di sicurezza e rimuove/normalizza `Server`. Da concordare con l'Analista se renderlo requisito (RNF sicurezza). | `server/backend/pulse_server/main.py` |

---

## 5. Test falliti (dettaglio)

Nessun test **pytest** fallito (350/350 verdi). I 2 fallimenti provengono dall'harness di integrazione live e corrispondono ai bug:

1. **`update builtin role 409` → ottenuto 200** (BUG-02).
   - Passi: login admin → `GET /roles` → prendi id SuperAdmin → `PUT /roles/{id}` body `{"description":"HACKED-DESC"}`.
   - Atteso (API doc): 409. Ottenuto: 200, descrizione persistita (confermato con `GET /roles/{id}`).

2. **`create user bad email 422` → ottenuto 201** (BUG-01).
   - Passi: login admin → `POST /users` body con `email:"clearly-not-an-email"`, password valida, `role_ids:[]`.
   - Atteso (API doc): 422 (validazione). Ottenuto: 201, email non valida memorizzata (confermato via `psql`).

---

## 6. Elenco per routing del fix

- **BUG_BACKEND** (area BACKEND / DB / DEPLOY lato server): **BUG-01, BUG-03, BUG-04, SEC-01**
  (+ **BUG-02** e **DOC-01** come chiarimento contratto/doc — non richiedono modifica FE).
- **BUG_FRONTEND** (area FRONTEND): **nessuno** (coverage FE 100%, tutte le pagine P-01..P-19 / PP-01..PP-05 verdi).

---

## 7. Re-collaudo — Iterazione 2 (2026-07-16)

Contesto: BE e ANALISTA hanno applicato i fix dell'Iterazione 1. Eseguito re-collaudo mirato
(verifica dei bug chiusi) + regressione rapida. **Nessuna modifica al codice da parte del QA.**

### 7.1 Verdetto aggiornato

**VERDETTO: PASS.** Nessun bug Bloccante o Maggiore residuo. Nessun test fallito.
Coverage obiettivo 100% raggiunto su Backend server e Probe-agent.

### 7.2 Stato di ciascun bug

| ID | Gravità (It.1) | Stato | Evidenza re-collaudo |
|---|---|---|---|
| BUG-01 | Maggiore | **CHIUSO** | `POST /users` email malformata (`clearly-not-an-email`, `noatsign.com`) → **422**; email valida standard → **201**; `PUT /users/{id}` email valida → **200**, malformata → **422**. Fix con `EmailStr` verificato. (Vedi OSS-01 per nota minore sul TLD `.local`.) |
| BUG-02 | Minore | **CHIUSO** | `PUT /roles/{SuperAdmin}` con `description` → **409** (descrizione **non** persistita, confermato con GET); `PUT` con `name` → **409**; `DELETE` → **409**; `PUT .../permissions` → **409**. Ruoli **custom** restano creabili (201) e modificabili (200). |
| BUG-03 | Media | **CHIUSO** | `pytest --cov=pulse_server`: **100%** (2725 stmt, 0 miss, 526 branch, 0 parziali), **208 test, 0 falliti**. |
| BUG-04 | Media | **CHIUSO** | `pytest --cov=pulse_probe`: **100%** (565 stmt, 0 miss, 124 branch, 0 parziali), **65 test, 0 falliti**. |
| SEC-01 | Minore | **CHIUSO** | Response con `X-Content-Type-Options: nosniff`, `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy`; header `Server: uvicorn` **neutralizzato**. Header presenti su response sia pubbliche sia autenticate. Nuovo modulo `pulse_server/middleware.py` (coperto al 100%). |
| DOC-01 | Minore | **CHIUSO** | `06_rbac.md` §2 → "Totale: **40 permessi**"; `DOCUMENTO_DATABASE.md` → "40 permessi". Unico "37" residuo è la voce di tracciamento incongruenza in `SCHEMA_FISICO.md` (I-1) che spiega esplicitamente che "37 è un conteggio errato" — coerente, non è un'asserzione incoerente. |

### 7.3 Nuova osservazione (Iterazione 2)

| ID | Area | Titolo | Descrizione | Gravità |
|---|---|---|---|---|
| OSS-01 | BACKEND/DOC | `EmailStr` rifiuta il TLD `.local` (reserved name) | Effetto collaterale del fix BUG-01: `EmailStr` (email-validator) rifiuta con 422 i domini `.local` (RFC 6762, special-use). Questo confligge con la **convenzione interna del progetto**, che usa `admin@pulse.local` nel seed e negli esempi doc. Le email reali (es. `@example.com`, `@gmail.com`) sono accettate; l'admin di seed è inserito via SQL (bypassa Pydantic) quindi non è impattato, ma la **creazione via API** di utenti con dominio `@pulse.local` viene rifiutata. | **Minore** (non bloccante) |

Fix suggerito OSS-01: valutare se allineare la convenzione doc/seed a un dominio non riservato
(es. `@pulse.example`) oppure configurare email-validator per accettare domini special-use se il
requisito prevede l'uso di `.local` interno. Non impatta il verdetto PASS.

### 7.4 Regressione rapida (nessuna regressione rilevata)

- Auth: login admin=200 (40 permessi), password errata=401.
- RBAC deny-by-default: endpoint senza token=401; Viewer → `systems.read`=200, `users.read`/`audit.read`/`roles.read`=403.
- Endpoint core (permissions/roles/users/probes/systems/notification-channels/notification-workflows/alarms/audit/logs/config/dashboard.aggregate): tutti **200**. `permissions`=40.
- Sicurezza: JWT manomesso=401; segreti canale mascherati (password non in chiaro).
- Audit immutabile: UPDATE/DELETE su `audit_log` → errore trigger (invariato).
- Deploy: `docker compose config` VALIDO su stack server e probe.
- Frontend (regressione): `frontend_common` 27 test/100%, dashboard Server 50 test/100% app, dashboard Probe 27 test/100% app — invariati (i fix non toccano il FE).

### 7.5 Coverage finali (Iterazione 2)

| Componente | Test | Coverage | Falliti |
|---|---|---|---|
| Backend server (`pulse_server`) | 208 | **100%** | 0 |
| Probe agent (`pulse_probe`) | 65 | **100%** | 0 |
| frontend_common | 27 | 100% | 0 |
| dashboard Server (codice app) | 50 | 100% | 0 |
| dashboard Probe (codice app) | 27 | 100% | 0 |

### 7.6 Routing residuo

- **BUG_BACKEND aperti**: nessuno bloccante/maggiore. Resta solo **OSS-01** (Minore, opzionale).
- **BUG_FRONTEND aperti**: nessuno.
