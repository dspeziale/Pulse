# Pulse — Documento API

Documento: `docs/api/DOCUMENTO_API.md`
Autore: AGENTE 1 — ANALISTA
Data: 2026-07-15

Documento API UNICO. Sezione **BACKEND** (endpoint REST) e sezione **FRONTEND** (pagine/componenti/flussi e chiamate REST).

Coerenza garantita con: permessi in `docs/analisi/06_rbac.md`, entità in `docs/database/DOCUMENTO_DATABASE.md`, casi d'uso in `docs/analisi/04_casi_uso.md`.

---

## Convenzioni generali

- **Base path Server**: `/api/v1` (porta applicativa configurabile, default 8443/HTTPS).
- **Base path endpoint dedicati Probe** (Server): `/api/v1/probe/*` (porta dedicata configurabile, default 9443/HTTPS+mTLS).
- **Base path Probe (API di query)**: `/api/v1` sulla Probe (default 8444/HTTPS+mTLS).
- **Autenticazione utente**: Bearer JWT (`Authorization: Bearer <access_token>`), salvo login/health.
- **Autenticazione Probe↔Server**: mTLS + `Authorization: Bearer <probe_token>`.
- **Autenticazione webhook inbound**: segreto/firma specifica del canale (no JWT).
- **Formato**: JSON. Timestamp ISO-8601 UTC.
- **Autorizzazione**: ogni endpoint indica il permesso RBAC richiesto (deny-by-default).

### Errori standard (comuni a tutti gli endpoint)

| Status | Significato |
|---|---|
| 400 Bad Request | Richiesta malformata / parametri invalidi. |
| 401 Unauthorized | Assente/invalido token di autenticazione. |
| 403 Forbidden | Autenticato ma privo del permesso richiesto. |
| 404 Not Found | Risorsa inesistente. |
| 409 Conflict | Conflitto (duplicato, vincolo di integrità, ultimo SuperAdmin, risorsa in uso). |
| 422 Unprocessable Entity | Validazione semantica fallita. |
| 429 Too Many Requests | Rate limit superato. |
| 500 Internal Server Error | Errore interno. |
| 503 Service Unavailable | Dipendenza non disponibile (es. Probe offline, OpenSearch). |

Formato corpo errore:
```json
{ "error": { "code": "STRING", "message": "STRING", "details": {} } }
```

---

# SEZIONE 1 — BACKEND (API REST)

## 1.1 Area: Auth

### POST /api/v1/auth/login
- **Descrizione**: autentica un utente ed emette i token.
- **Auth**: nessuna. **Permesso**: nessuno.
- **Request**: `{ "username": string, "password": string }`
- **Response 200**: `{ "access_token": string, "refresh_token": string, "token_type": "bearer", "expires_in": int, "user": { "id": string, "username": string, "roles": [string], "permissions": [string] } }`
- **Errori**: 400, 401 (credenziali errate), 403 (account disabilitato/bloccato), 429.

### POST /api/v1/auth/refresh
- **Descrizione**: rinnova l'access token.
- **Auth**: refresh token. **Permesso**: nessuno.
- **Request**: `{ "refresh_token": string }`
- **Response 200**: `{ "access_token": string, "expires_in": int }`
- **Errori**: 400, 401 (refresh scaduto/revocato).

### POST /api/v1/auth/logout
- **Descrizione**: revoca il refresh token / sessione.
- **Auth**: Bearer JWT. **Permesso**: nessuno.
- **Request**: `{ "refresh_token": string }`
- **Response 204**. **Errori**: 401.

### GET /api/v1/auth/me
- **Descrizione**: profilo e permessi dell'utente corrente.
- **Auth**: Bearer JWT. **Permesso**: `profile.read`.
- **Response 200**: `{ "id": string, "username": string, "email": string, "full_name": string, "roles": [string], "permissions": [string], "status": string }`
- **Errori**: 401.

### POST /api/v1/auth/change-password
- **Descrizione**: cambia la propria password.
- **Auth**: Bearer JWT. **Permesso**: `profile.update`.
- **Request**: `{ "current_password": string, "new_password": string }`
- **Response 204**. **Errori**: 400 (password attuale errata), 422 (policy), 401.

---

## 1.2 Area: Utenti

### GET /api/v1/users
- **Descrizione**: elenca utenti (paginato/filtrabile).
- **Auth**: JWT. **Permesso**: `users.read`.
- **Query**: `page:int, page_size:int, q:string, status:string, role:string, sort:string`
  - `sort` (esteso su richiesta utente: DataTables): `campo` (asc) o `-campo` (desc). Colonne ordinabili: `username, full_name, email, created_at, last_login_at, status`. Campo non ammesso -> ordinamento di default (nessun errore).
- **Response 200**: `{ "items": [User], "total": int, "page": int, "page_size": int }`
  - `User`: `{ "id": string, "username": string, "email": string, "full_name": string, "status": "active|disabled|locked", "roles": [string], "created_at": string, "updated_at": string, "last_login_at": string|null }`
- **Errori**: 401, 403.

### POST /api/v1/users
- **Descrizione**: crea utente. **Auth**: JWT. **Permesso**: `users.create`.
- **Request**: `{ "username": string, "email": string, "full_name": string, "password": string, "role_ids": [string], "status": "active|disabled" }`
- **Response 201**: `User`. **Errori**: 409 (username/email duplicati), 422, 401, 403.

### GET /api/v1/users/{id}
- **Permesso**: `users.read`. **Response 200**: `User`. **Errori**: 404, 401, 403.

### PUT /api/v1/users/{id}
- **Descrizione**: aggiorna utente (anagrafica/stato). **Permesso**: `users.update`.
- **Request**: `{ "email"?: string, "full_name"?: string, "status"?: string }`
- **Response 200**: `User`. **Errori**: 409 (auto-disabilitazione/ultimo SuperAdmin), 422, 404, 401, 403.

### DELETE /api/v1/users/{id}
- **Descrizione**: elimina/disabilita utente. **Permesso**: `users.delete`.
- **Response 204**. **Errori**: 409 (auto-eliminazione/ultimo SuperAdmin), 404, 401, 403.

### PUT /api/v1/users/{id}/roles
- **Descrizione**: assegna ruoli. **Permesso**: `users.assign_roles`.
- **Request**: `{ "role_ids": [string] }`. **Response 200**: `User`. **Errori**: 422, 404, 401, 403.

### POST /api/v1/users/{id}/reset-password
- **Descrizione**: reset amministrativo password. **Permesso**: `users.update`.
- **Request**: `{ "new_password": string }` (o generazione automatica). **Response 204**. **Errori**: 422, 404, 401, 403.

---

## 1.3 Area: Ruoli

### GET /api/v1/roles
- **Permesso**: `roles.read`. **Query**: `page, page_size, q, sort`.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `name, created_at`; formato `campo`/`-campo`; campo non ammesso -> default.
- **Response 200**: `{ "items": [Role], "total": int }`
  - `Role`: `{ "id": string, "name": string, "description": string, "is_builtin": bool, "permissions": [string], "created_at": string }`
- **Errori**: 401, 403.

### POST /api/v1/roles
- **Permesso**: `roles.create`. **Request**: `{ "name": string, "description": string, "permission_codes": [string] }`
- **Response 201**: `Role`. **Errori**: 409 (nome duplicato), 422, 401, 403.

### GET /api/v1/roles/{id}
- **Permesso**: `roles.read`. **Response 200**: `Role`. **Errori**: 404, 401, 403.

### PUT /api/v1/roles/{id}
- **Permesso**: `roles.update`. **Request**: `{ "name"?: string, "description"?: string }`
- **Response 200**: `Role`.
- **Nota (ruoli predefiniti / builtin)**: qualsiasi PUT su un ruolo predefinito (`is_builtin = true`) restituisce **409**, **inclusa la modifica della sola `description`**. I ruoli predefiniti sono immutabili in ogni loro campo; per personalizzazioni creare un ruolo custom.
- **Errori**: 409 (ruolo predefinito — qualunque campo, description compresa), 404, 422, 401, 403.

### DELETE /api/v1/roles/{id}
- **Permesso**: `roles.delete`. **Response 204**.
- **Nota (ruoli predefiniti / builtin)**: DELETE su un ruolo predefinito (`is_builtin = true`) restituisce sempre **409** (non eliminabile).
- **Errori**: 409 (predefinito, oppure assegnato a utenti), 404, 401, 403.

### PUT /api/v1/roles/{id}/permissions
- **Descrizione**: imposta i permessi del ruolo. **Permesso**: `roles.assign_permissions`.
- **Request**: `{ "permission_codes": [string] }`. **Response 200**: `Role`. **Errori**: 409 (predefinito), 422 (codice inesistente), 404, 401, 403.

---

## 1.4 Area: Permessi

### GET /api/v1/permissions
- **Descrizione**: catalogo permessi (fisso). **Permesso**: `permissions.read`.
- **Response 200**: `{ "items": [ { "code": string, "area": string, "description": string } ] }`
- **Errori**: 401, 403.

---

## 1.5 Area: Probe

### GET /api/v1/probes
- **Permesso**: `probes.read`. **Query**: `page, page_size, q, status, sort`.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `name, status, last_seen_at, created_at, location, contact_name, enabled`; formato `campo`/`-campo`; campo non ammesso -> default.
- **Response 200**: `{ "items": [Probe], "total": int }`
  - `Probe`: `{ "id": string, "name": string, "description": string, "query_endpoint": string, "tags": [string], "location": string|null, "contact_name": string|null, "contact_email": string|null, "contact_phone": string|null, "enabled": bool, "status": "online|offline|pending", "last_seen_at": string|null, "version": string|null, "systems_count": int, "created_at": string }`
  - `location`, `contact_name`, `contact_email`, `contact_phone` (esteso su richiesta utente): dati anagrafici opzionali della Sonda (sede/posizione, referente e contatti).
- **Errori**: 401, 403.

### POST /api/v1/probes
- **Descrizione**: registra una Probe; genera token di enrollment. **Permesso**: `probes.create`.
- **Request**: `{ "name": string, "description": string, "query_endpoint": string, "tags": [string], "location"?: string, "contact_name"?: string, "contact_email"?: string, "contact_phone"?: string, "enabled": bool }`
  - Campi anagrafici (esteso su richiesta utente) tutti opzionali. `contact_email`, se valorizzato, deve essere un'email valida (una stringa vuota viene normalizzata a `null`); gli altri sono stringhe libere.
- **Response 201**: `{ "probe": Probe, "enrollment_token": string, "enrollment_expires_at": string }`
- **Errori**: 409 (nome duplicato), 422 (es. `contact_email` non valida), 401, 403.

### GET /api/v1/probes/{id}
- **Permesso**: `probes.read`. **Response 200**: `Probe`. **Errori**: 404, 401, 403.

### PUT /api/v1/probes/{id}
- **Permesso**: `probes.update`. **Request**: `{ "name"?, "description"?, "query_endpoint"?, "tags"?, "location"?, "contact_name"?, "contact_email"?, "contact_phone"?, "enabled"? }` (campi anagrafici esteso su richiesta utente; update parziale, `contact_email` validata se valorizzata).
- **Response 200**: `Probe`. **Errori**: 409, 422, 404, 401, 403.

### DELETE /api/v1/probes/{id}
- **Permesso**: `probes.delete`. **Response 204**. **Errori**: 409 (sistemi assegnati), 404, 401, 403.

### POST /api/v1/probes/{id}/rotate-credentials
- **Descrizione**: rigenera secret/certificato, revoca il precedente. **Permesso**: `probes.rotate_key`.
- **Response 200**: `{ "enrollment_token": string, "enrollment_expires_at": string }`
- **Errori**: 404, 401, 403.

### GET /api/v1/probes/{id}/status
- **Descrizione**: stato/liveness dettagliato. **Permesso**: `probes.read`.
- **Response 200**: `{ "id": string, "status": string, "last_seen_at": string|null, "version": string|null, "last_sync_at": string|null, "last_error": string|null }`
- **Errori**: 404, 401, 403.

---

## 1.6 Area: Sistemi monitorati

### GET /api/v1/systems
- **Permesso**: `systems.read`. **Query**: `page, page_size, q, probe_id, enabled, kind, sort`.
  - `kind` (esteso su richiesta utente): filtra per tipo di controllo, valori ammessi `http` | `tcp` (utile per separare Applicazioni=http e Connettivita'=tcp nella UI); combinabile con gli altri filtri. Un valore diverso da `http`/`tcp` restituisce 422.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `system_id, system_name, kind, created_at, enabled`; formato `campo`/`-campo`; campo non ammesso -> default.
- **Response 200**: `{ "items": [System], "total": int }`
  - `System`: `{ "id": string, "system_id": string, "system_name": string, "kind": "http"|"tcp", "heartbeat_url": string|null, "tcp_host": string|null, "tcp_port": int|null, "probe_id": string, "poll_interval_seconds": int, "timeout_seconds": int, "enabled": bool, "thresholds": { "response_ms_warn": int|null, "response_ms_error": int|null }, "maintenance_windows": [ { "start": string, "end": string, "note": string } ], "created_at": string }`
  - `kind` (esteso su richiesta utente): `"http"` = controllo heartbeat HTTP/HTTPS su `heartbeat_url`; `"tcp"` = controllo di connettivita' TCP su `tcp_host:tcp_port`. Per `kind="http"` valorizzato `heartbeat_url` (e `tcp_*` null); per `kind="tcp"` valorizzati `tcp_host`/`tcp_port` (e `heartbeat_url` puo' essere null).
- **Errori**: 401, 403.

### POST /api/v1/systems
- **Permesso**: `systems.create`.
- **Request**: `{ "system_id": string, "system_name": string, "kind"?: "http"|"tcp" (default "http"), "heartbeat_url"?: string, "tcp_host"?: string, "tcp_port"?: int (1..65535), "probe_id": string, "poll_interval_seconds": int, "timeout_seconds": int, "enabled": bool, "thresholds"?: {...}, "maintenance_windows"?: [...] }`
  - Coerenza per `kind` (esteso su richiesta utente): se `kind="http"` → `heartbeat_url` **obbligatorio** (URL http/https valido); se `kind="tcp"` → `tcp_host` e `tcp_port` (1..65535) **obbligatori**. In caso contrario 422.
- **Response 201**: `System`. **Errori**: 409 (`system_id` duplicato), 422 (URL/host/porta incoerenti col `kind`, intervallo manutenzione invalido, probe inesistente), 401, 403.

### POST /api/v1/systems/test
- **Descrizione**: testa un sistema prima di crearlo/modificarlo (aggiunta/estesa su richiesta utente). Per `kind="http"` esegue una GET diagnostica verso `heartbeat_url`, misura il tempo di risposta e prova a interpretare la risposta come schema canonico Pulse (oggetto singolo o array). Per `kind="tcp"` apre una connessione TCP a `tcp_host:tcp_port` col timeout indicato e misura il tempo di connessione. **Non persiste nulla e non crea il sistema.**
- **Permesso**: `systems.create` **OPPURE** `systems.update`.
- **Request**: `{ "kind"?: "http"|"tcp" (default "http"), "heartbeat_url"?: string (URL http/https, obbligatorio se kind="http"), "tcp_host"?: string (obbligatorio se kind="tcp"), "tcp_port"?: int (1..65535, obbligatorio se kind="tcp"), "timeout_seconds"?: int (default 5, range 1..60) }`
- **Response 200**: `{ "reachable": bool, "http_status": int|null, "response_ms": int, "valid_schema": bool, "checks_count": int, "documents": [ { "system_id": string, "system_name": string|null, "check_id": string, "check_name": string|null, "status": string, "response_ms": number|null, "message": string|null } ], "error": string|null }`
  - **HTTP**: `reachable=true` anche con risposta 4xx/5xx del target (vedi `http_status`). `documents` limitato a 20 elementi; `checks_count` conteggia tutti i documenti trovati; `valid_schema=true` solo se la risposta e' JSON conforme (campi essenziali: `system_id`, `check_id`, `status`).
  - **TCP** (esteso su richiesta utente): `http_status=null`; se la connessione riesce → `reachable=true`, `valid_schema=true`, `checks_count=1`, `documents=[{ check_id:"tcp", check_name:"Connettivita' TCP", status:"ok", response_ms, message }]`, `error=null`; se fallisce → `reachable=false`, `valid_schema=false`, `documents=[{ ..., status:"down", message }]` ed `error` valorizzato. `response_ms` = tempo di connessione in ms.
  - L'irraggiungibilita' del target **non** e' un errore HTTP dell'endpoint: ritorna 200 con `reachable=false` ed `error` valorizzato (sia HTTP che TCP).
- **Errori**: 422 (campi incoerenti col `kind`: URL mancante/non http-https per http, host/porta mancanti o porta fuori 1..65535 per tcp; `timeout_seconds` fuori range), 401, 403.

### GET /api/v1/systems/{id}
- **Permesso**: `systems.read`. **Response 200**: `System`. **Errori**: 404, 401, 403.

### PUT /api/v1/systems/{id}
- **Permesso**: `systems.update`. **Request**: campi di `System` modificabili (inclusi `kind`, `heartbeat_url`, `tcp_host`, `tcp_port` — esteso su richiesta utente). Update parziale: se `kind` e' fornito, i campi obbligatori del nuovo tipo devono essere presenti nella stessa richiesta; `tcp_port` (se fornito) sempre validato in 1..65535; `heartbeat_url` (se fornito) sempre validato come URL http/https. **Response 200**: `System`. **Errori**: 409, 422, 404, 401, 403.

### DELETE /api/v1/systems/{id}
- **Permesso**: `systems.delete`. **Response 204** (dati storici restano su OpenSearch). **Errori**: 404, 401, 403.

### GET /api/v1/systems/{id}/checks
- **Descrizione**: check scoperti per il sistema. **Permesso**: `checks.read`.
- **Response 200**: `{ "items": [ { "check_id": string, "check_name": string, "last_status": string, "last_seen_at": string } ] }`
- **Errori**: 404, 401, 403.

---

## 1.7 Area: Check

### GET /api/v1/checks
- **Descrizione**: elenco check scoperti (filtrabile per sistema/probe). **Permesso**: `checks.read`.
- **Query**: `system_id, probe_id, page, page_size`.
- **Response 200**: `{ "items": [ { "system_id": string, "check_id": string, "check_name": string, "probe_id": string, "last_status": string, "last_seen_at": string } ], "total": int }`
- **Errori**: 401, 403.

---

## 1.8 Area: Heartbeat / Query OpenSearch (via Server, proxy verso Probe)

### GET /api/v1/probes/{id}/heartbeats
- **Descrizione**: legge heartbeat dalla Probe (il Server inoltra alla API di query della Probe). **Permesso**: `heartbeats.read`.
- **Query**: `system_id, check_id, status, from (ISO), to (ISO), page, page_size, sort`.
- **Response 200**: `{ "items": [Heartbeat], "total": int }`
  - `Heartbeat`: `{ "@timestamp": string, "system_id": string, "system_name": string, "check_id": string, "check_name": string, "status": string, "response_ms": int, "message": string|null, "details": string, "probe_id": string, "reachable": bool, "http_status": int|null, "latency_ms": int|null, "ingested_at": string }`
- **Errori**: 404 (probe), 503 (probe offline/OpenSearch), 400, 401, 403.

### POST /api/v1/probes/{id}/query
- **Descrizione**: interrogazione avanzata/diretta su OpenSearch della Probe (query strutturata Pulse, non DSL raw). **Permesso**: `heartbeats.query`.
- **Request**: `{ "filters": [ { "field": string, "op": string, "value": any } ], "from": string, "to": string, "aggregations"?: [ { "type": "avg|min|max|count|uptime", "field"?: string, "interval"?: string } ], "page"?: int, "page_size"?: int, "sort"?: string }`
- **Response 200**: `{ "items": [Heartbeat], "aggregations": {...}, "total": int }`
- **Errori**: 400 (query malformata), 404, 503, 401, 403.

### GET /api/v1/dashboard/aggregate
- **Descrizione**: dati dashboard aggregata (da rollup). **Permesso**: `dashboard.read`.
- **Query**: `window` (es. `1h`, `24h`).
- **Response 200**: `{ "probes": [ { "probe_id": string, "status": string, "systems_total": int, "systems_down": int } ], "systems_summary": { "ok": int, "warn": int, "error": int, "down": int, "unknown": int }, "active_alarms": int, "generated_at": string }`
- **Errori**: 401, 403.

### GET /api/v1/dashboard/probe/{id}
- **Descrizione**: dati dashboard per singola Probe. **Permesso**: `dashboard.read` (+ `heartbeats.read` per dettaglio).
- **Query**: `window`.
- **Response 200**: `{ "probe": Probe, "systems": [ { "system_id": string, "system_name": string, "status": string, "avg_response_ms": number, "uptime_pct": number, "checks": [ { "check_id": string, "status": string } ] } ], "generated_at": string }`
- **Errori**: 404, 503 (probe offline → può restituire ultimo rollup), 401, 403.

---

## 1.9 Area: Comunicazione Server↔Probe (endpoint dedicati)

> Autenticazione: **mTLS + Bearer probe_token**. Nessun permesso RBAC utente. Attore: Probe.

### POST /api/v1/probe/register
- **Descrizione**: enrollment della Probe (primo contatto). **Auth**: token di enrollment (mTLS di bootstrap).
- **Request**: `{ "enrollment_token": string, "hostname": string, "version": string, "csr"?: string }`
- **Response 200**: `{ "probe_id": string, "probe_token": string, "client_certificate"?: string, "ca_certificate": string, "server_probe_endpoint": string }`
- **Errori**: 401 (token invalido/scaduto/riusato), 409, 400.

### GET /api/v1/probe/config
- **Descrizione**: la Probe scarica la propria configurazione (sistemi assegnati + parametri). **Auth**: probe_token.
- **Response 200**: `{ "probe_id": string, "poll_defaults": {...}, "systems": [ { "system_id": string, "system_name": string, "kind": "http"|"tcp", "heartbeat_url": string|null, "tcp_host": string|null, "tcp_port": int|null, "poll_interval_seconds": int, "timeout_seconds": int, "enabled": bool, "thresholds": {...} } ], "config_version": string }`
  - `kind`/`tcp_host`/`tcp_port` (esteso su richiesta utente) indicano alla Probe come interrogare il sistema: heartbeat HTTP su `heartbeat_url` (`kind="http"`) oppure connettivita' TCP su `tcp_host:tcp_port` (`kind="tcp"`).
- **Errori**: 401, 403 (probe disabilitata/revocata).

### POST /api/v1/probe/heartbeat
- **Descrizione**: liveness/stato della Probe stessa. **Auth**: probe_token.
- **Request**: `{ "version": string, "uptime_seconds": int, "opensearch_healthy": bool, "systems_polled": int, "last_poll_at": string }`
- **Response 200**: `{ "config_version": string }` (segnala se serve un nuovo pull config). **Errori**: 401, 403.

### POST /api/v1/probe/events
- **Descrizione**: la Probe invia eventi (cambi stato/connettività) per la valutazione dei workflow. **Auth**: probe_token.
- **Request**: `{ "events": [ { "type": "status_changed|system_unreachable|system_recovered|response_time_exceeded|sustained_state", "system_id": string, "check_id": string|null, "status": string, "previous_status": string|null, "response_ms": int|null, "reachable": bool, "message": string|null, "timestamp": string } ] }`
- **Response 202**: `{ "accepted": int }`. **Errori**: 400, 401, 403.

### POST /api/v1/probe/rollup
- **Descrizione**: push periodico di metriche aggregate per la dashboard del Server. **Auth**: probe_token.
- **Request**: `{ "window": string, "generated_at": string, "systems": [ { "system_id": string, "status": string, "avg_response_ms": number, "uptime_pct": number, "checks": [ { "check_id": string, "status": string } ] } ] }`
- **Response 202**: `{ "accepted": true }`. **Errori**: 400, 401, 403.

### Endpoint sulla PROBE (invocati dal Server per drill-down)
> Sulla Probe, base `/api/v1`. Auth: **mTLS + token del Server**.

- **GET /api/v1/query/heartbeats** — Query filtrata su OpenSearch locale. Stessi parametri/response di `GET /api/v1/probes/{id}/heartbeats`.
- **POST /api/v1/query** — Query avanzata. Stessi parametri/response di `POST /api/v1/probes/{id}/query`.
- **GET /api/v1/systems** — Sistemi attualmente monitorati dalla Probe (config effettiva).
- **GET /api/v1/status** — Stato interno della Probe (poller, OpenSearch, code eventi).
- **GET /api/v1/health** — Health della Probe (no auth).

---

## 1.10 Area: Notifiche / Canali

### GET /api/v1/notification-channels
- **Permesso**: `notifications.read`. **Query**: `type, enabled, page, page_size, sort`.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `name, type, created_at, enabled`; formato `campo`/`-campo`; campo non ammesso -> default.
- **Response 200**: `{ "items": [Channel], "total": int }`
  - `Channel`: `{ "id": string, "name": string, "type": "email|telegram|whatsapp", "enabled": bool, "inbound_enabled": bool, "config": {...campi non sensibili, segreti mascherati...}, "created_at": string }`
- **Errori**: 401, 403.

### POST /api/v1/notification-channels
- **Permesso**: `notifications.create`.
- **Request (email)**: `{ "name": string, "type": "email", "enabled": bool, "inbound_enabled": bool, "config": { "smtp_host": string, "smtp_port": int, "use_tls": bool, "username": string, "password": string, "from_address": string, "imap_host"?: string, "imap_port"?: int } }`
- **Request (telegram)**: `{ "name", "type": "telegram", "enabled", "inbound_enabled", "config": { "bot_token": string, "webhook_secret": string } }`
- **Request (whatsapp)**: `{ "name", "type": "whatsapp", "enabled", "inbound_enabled", "config": { "provider": string, "api_base": string, "api_token": string, "phone_number_id": string, "webhook_secret": string } }`
- **Response 201**: `Channel` (segreti mascherati). **Errori**: 422, 409 (nome duplicato), 401, 403.

### GET /api/v1/notification-channels/{id}
- **Permesso**: `notifications.read`. **Response 200**: `Channel`. **Errori**: 404, 401, 403.

### PUT /api/v1/notification-channels/{id}
- **Permesso**: `notifications.update`. **Request**: campi modificabili. **Response 200**: `Channel`. **Errori**: 422, 404, 401, 403.

### DELETE /api/v1/notification-channels/{id}
- **Permesso**: `notifications.delete`. **Response 204**. **Errori**: 409 (usato da workflow), 404, 401, 403.

### POST /api/v1/notification-channels/{id}/test
- **Descrizione**: invio di prova. **Permesso**: `notifications.test`.
- **Request**: `{ "recipient": string, "message"?: string }`. **Response 200**: `{ "delivered": bool, "detail": string }`. **Errori**: 422, 404, 503 (provider), 401, 403.

### GET /api/v1/notifications/history
- **Descrizione**: storico invii. **Permesso**: `notifications.read`.
- **Query**: `channel_id, workflow_id, status, from, to, page, page_size, sort`.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `created_at, status, channel_id`; formato `campo`/`-campo`; campo non ammesso -> default (`created_at` desc).
- **Response 200**: `{ "items": [ { "id": string, "channel_id": string, "workflow_id": string|null, "recipient": string, "status": "sent|failed|retrying", "error": string|null, "created_at": string } ], "total": int }`
- **Errori**: 401, 403.

---

## 1.11 Area: Workflow notifiche

### GET /api/v1/notification-workflows
- **Permesso**: `workflows.read`. **Query**: `enabled, q, page, page_size, sort`.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `name, created_at, enabled`; formato `campo`/`-campo`; campo non ammesso -> default.
- **Response 200**: `{ "items": [Workflow], "total": int }`
  - `Workflow`: `{ "id": string, "name": string, "description": string, "enabled": bool, "trigger": string, "scope": { "probe_ids": [string], "system_ids": [string], "check_ids": [string] }, "conditions": [ { "field": string, "op": string, "value": any, "group": string } ], "suppression": { "cooldown_seconds": int, "dedup_window_seconds": int, "active_hours"?: {...}, "respect_maintenance": bool }, "actions": [ { "step_order": int, "channel_id": string, "recipients": [string], "template": string, "delay_seconds": int, "escalation_condition": {...}, "repeat"?: {...} } ], "created_at": string }`
- **Errori**: 401, 403.

### POST /api/v1/notification-workflows
- **Permesso**: `workflows.create`. **Request**: corpo `Workflow` (senza `id`). **Response 201**: `Workflow`. **Errori**: 422 (canale inesistente, condizioni incoerenti), 401, 403.

### GET /api/v1/notification-workflows/{id}
- **Permesso**: `workflows.read`. **Response 200**: `Workflow`. **Errori**: 404, 401, 403.

### PUT /api/v1/notification-workflows/{id}
- **Permesso**: `workflows.update`. **Request**: campi di `Workflow`. **Response 200**: `Workflow`. **Errori**: 422, 404, 401, 403.

### DELETE /api/v1/notification-workflows/{id}
- **Permesso**: `workflows.delete`. **Response 204**. **Errori**: 404, 401, 403.

### PUT /api/v1/notification-workflows/{id}/enabled
- **Descrizione**: abilita/disabilita. **Permesso**: `workflows.update`.
- **Request**: `{ "enabled": bool }`. **Response 200**: `Workflow`. **Errori**: 404, 401, 403.

### POST /api/v1/notification-workflows/{id}/simulate
- **Descrizione**: dry-run su evento campione (UC-73), non invia. **Permesso**: `workflows.update`.
- **Request**: `{ "event": {...evento...} }`. **Response 200**: `{ "matched": bool, "planned_actions": [...], "suppressed_by": string|null }`. **Errori**: 422, 404, 401, 403.

---

## 1.12 Area: Allarmi (supporto workflow/escalation)

> Necessari per ack/escalation/auto-risoluzione (vedi `07_workflow_notifiche.md` §8).

### GET /api/v1/alarms
- **Descrizione**: elenco allarmi (attivi/storici). **Permesso**: `workflows.read`.
- **Query**: `status (active|acknowledged|resolved), system_id, probe_id, from, to, page, page_size, sort`.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `opened_at, status`; formato `campo`/`-campo`; campo non ammesso -> default (`opened_at` desc).
- **Response 200**: `{ "items": [ { "id": string, "workflow_id": string, "probe_id": string, "system_id": string, "check_id": string|null, "status": string, "opened_at": string, "acknowledged_at": string|null, "acknowledged_by": string|null, "resolved_at": string|null } ], "total": int }`
- **Errori**: 401, 403.

### POST /api/v1/alarms/{id}/ack
- **Descrizione**: riconosce un allarme (ferma escalation). **Permesso**: `commands.execute`.
- **Request**: `{ "note"?: string }`. **Response 200**: allarme aggiornato. **Errori**: 404, 409 (già risolto), 401, 403.

---

## 1.13 Area: Comandi in ingresso (webhook canali)

> Auth: segreto/firma del canale (no JWT). Nessun permesso RBAC diretto: l'autorizzazione avviene risolvendo l'identità→utente e verificando i suoi permessi.

### POST /api/v1/inbound/telegram
- **Descrizione**: webhook Telegram; riceve update/comandi.
- **Auth**: header `X-Telegram-Bot-Api-Secret-Token` = `webhook_secret` del canale.
- **Request**: payload update Telegram (contiene `chat_id`, `from`, `text`).
- **Response 200**: `{ "ok": true }` (la risposta all'utente è inviata via Bot API). **Errori**: 401 (secret errato), 400.

### POST /api/v1/inbound/whatsapp
- **Descrizione**: webhook WhatsApp Business API.
- **Auth**: firma `X-Hub-Signature-256` (o equivalente provider) verificata con `webhook_secret`.
- **Request**: payload provider (numero mittente, testo). **GET** dello stesso path può servire alla verifica handshake del provider.
- **Response 200**. **Errori**: 401, 400.

### POST /api/v1/inbound/email
- **Descrizione**: ingest comando via email (webhook provider inbound o dispatcher da polling IMAP).
- **Auth**: segreto condiviso nel path/header + verifica token nel corpo (mitigazione spoofing).
- **Request**: `{ "from": string, "subject": string, "body": string, "verification_token": string }`
- **Response 200**. **Errori**: 401, 400.

### POST /api/v1/channel-identities  (associazione identità)
- **Descrizione**: l'utente associa la propria identità di canale. **Auth**: JWT. **Permesso**: `commands.execute`.
- **Request**: `{ "channel_type": "telegram|whatsapp|email", "external_id": string, "verification_code": string }`
- **Response 201**: `{ "id": string, "channel_type": string, "external_id": string, "user_id": string }`
- **Errori**: 400 (codice errato/scaduto), 409 (già associata), 401, 403.

### GET /api/v1/channel-identities
- **Descrizione**: elenca le proprie identità associate. **Auth**: JWT. **Permesso**: `commands.execute`.
- **Response 200**: `{ "items": [ChannelIdentity] }`. **Errori**: 401, 403.

### DELETE /api/v1/channel-identities/{id}
- **Descrizione**: rimuove un'associazione propria. **Permesso**: `commands.execute`.
- **Response 204**. **Errori**: 404, 401, 403.

---

## 1.14 Area: Audit

### GET /api/v1/audit
- **Descrizione**: elenco voci audit (immutabile, sola lettura). **Permesso**: `audit.read`.
- **Query**: `actor, action, entity_type, entity_id, outcome, from, to, page, page_size, sort`.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `timestamp, action, actor_type, outcome, entity_type`; formato `campo`/`-campo`; campo non ammesso -> default (`timestamp` desc).
- **Response 200**: `{ "items": [ { "id": string, "timestamp": string, "actor_type": "user|probe|system", "actor_id": string, "action": string, "entity_type": string, "entity_id": string|null, "outcome": "success|failure", "ip": string|null, "details": {} } ], "total": int }`
- **Errori**: 401, 403.

### GET /api/v1/audit/{id}
- **Permesso**: `audit.read`. **Response 200**: voce audit. **Errori**: 404, 401, 403.

---

## 1.15 Area: Log di sistema

### GET /api/v1/logs
- **Descrizione**: log di sistema di Server e Probe. **Permesso**: `syslog.read`.
- **Query**: `component (server|probe), probe_id, level, from, to, q, page, page_size, sort`.
  - `sort` (esteso su richiesta utente: DataTables): colonne ordinabili `timestamp, level, component` (alias `source`); formato `campo`/`-campo`; campo non ammesso -> default (`timestamp` desc).
- **Response 200**: `{ "items": [ { "id": string, "timestamp": string, "component": string, "probe_id": string|null, "level": "debug|info|warning|error|critical", "logger": string, "message": string, "context": {} } ], "total": int }`
- **Errori**: 401, 403.

> Nota: i log delle Probe sono raccolti dal Server tramite i push di liveness/eventi oppure consultabili localmente sulla Probe. Vedi QUESTIONI APERTE.

---

## 1.16 Area: Configurazione

### GET /api/v1/config
- **Descrizione**: parametri di configurazione (segreti mascherati). **Permesso**: `config.read`.
- **Response 200**: `{ "items": [ { "key": string, "value": any, "type": string, "sensitive": bool, "requires_restart": bool, "description": string } ] }`
- **Errori**: 401, 403.

### GET /api/v1/config/{key}
- **Permesso**: `config.read`. **Response 200**: singolo parametro. **Errori**: 404, 401, 403.

### PUT /api/v1/config
- **Descrizione**: aggiorna uno o più parametri. **Permesso**: `config.update`.
- **Request**: `{ "items": [ { "key": string, "value": any } ] }`. **Response 200**: `{ "updated": [string], "requires_restart": [string] }`. **Errori**: 422 (valore invalido), 401, 403.
- **Validazione `timezone`** (esteso su richiesta utente): se tra gli item c'e' `key="timezone"`, il valore deve essere un identificatore di fuso orario **IANA** valido (es. `Europe/Rome`, `UTC`, `America/New_York`); un valore non valido restituisce 422 e NESSUN parametro del batch viene salvato. Il parametro serve alla sola visualizzazione lato frontend: i timestamp nelle response API restano in **UTC ISO-8601** (nessuna conversione lato backend).

---

## 1.17 Area: Healthcheck

### GET /api/v1/health
- **Descrizione**: liveness. **Auth**: nessuna. **Response 200**: `{ "status": "ok" }`.

### GET /api/v1/health/ready
- **Descrizione**: readiness (DB Server / dipendenze). **Auth**: nessuna. **Response 200**: `{ "status": "ready", "checks": { "database": "ok", ... } }` / **503** se non pronto.

> Sulla Probe: `GET /api/v1/health` e `GET /api/v1/health/ready` (verifica OpenSearch/poller).

---

## 1.18 Riepilogo tracciabilità endpoint → permesso

| Area | Endpoint principali | Permessi |
|---|---|---|
| Auth | login/refresh/logout/me/change-password | — / profile.* |
| Utenti | /users* | users.* |
| Ruoli | /roles* | roles.* |
| Permessi | /permissions | permissions.read |
| Probe | /probes* | probes.* |
| Sistemi | /systems* | systems.*, checks.read |
| Check | /checks | checks.read |
| Heartbeat/Query | /probes/{id}/heartbeats, /probes/{id}/query, /dashboard/* | heartbeats.read, heartbeats.query, dashboard.read |
| Probe↔Server | /probe/register, /probe/config, /probe/heartbeat, /probe/events, /probe/rollup, (Probe) /query/* | mTLS+probe_token |
| Notifiche | /notification-channels*, /notifications/history | notifications.* |
| Workflow | /notification-workflows*, /alarms* | workflows.*, commands.execute |
| Comandi | /inbound/*, /channel-identities* | segreto canale / commands.execute |
| Audit | /audit* | audit.read |
| Log | /logs | syslog.read |
| Config | /config* | config.read, config.update |
| Health | /health, /health/ready | — |
| Nominatim gateway | /nominatim/{endpoint} | JWT Pulse **oppure** X-API-Key |

---

## 1.19 Area: Nominatim gateway (aggiunta su richiesta utente)

Proxy HTTP **GET** verso Nominatim con **base URL FISSA** da configurazione, così che
**Sonde** e **altri servizi** che NON raggiungono direttamente Nominatim possano
geocodificare passando dal Server (che invece lo raggiunge).

### GET /api/v1/nominatim/{endpoint}
- **Descrizione**: inoltra la richiesta a `f"{PULSE_NOMINATIM_URL}/{endpoint}"` preservando
  la **query string** del chiamante e forzando il metodo **GET**. Restituisce il corpo
  upstream con lo **stesso Content-Type** (di norma JSON).
- **`{endpoint}`**: ammesso SOLO se in **allowlist** `{search, reverse, lookup, status, details}`.
  Qualsiasi altro valore → **404 NOT_FOUND**. Il chiamante controlla solo `endpoint` (allowlist)
  e i query params: **host/schema NON sono modificabili** (anti-SSRF).
- **Auth (duale, una delle due)**:
  - **(a)** JWT Pulse valido di un utente **attivo** — header `Authorization: Bearer <token>`
    (riusa la logica di autenticazione esistente, senza richiedere un permesso RBAC specifico);
    **oppure**
  - **(b)** **API key**: header `X-API-Key: <chiave>` (o query param `api_key=<chiave>`) uguale a
    `PULSE_NOMINATIM_API_KEY`, **se** questa è configurata (non vuota). Se la chiave non è
    configurata, l'accesso via API key è disabilitato.
  - Nessuna delle due → **401 UNAUTHORIZED**. L'eventuale `api_key` usato per l'autenticazione
    **non viene inoltrato** a Nominatim.
- **Rate limit / cache** (rispetto ToS Nominatim ~1 req/s):
  - le chiamate **upstream** sono **serializzate e limitate** in-process all'intervallo minimo
    `PULSE_NOMINATIM_MIN_INTERVAL_MS` (default 1000 ms); in caso di burst la richiesta **attende
    brevemente** (throttle) invece di rispondere 429, così da non perdere richieste legittime;
  - una **cache in-process** con TTL `PULSE_NOMINATIM_CACHE_TTL_SECONDS` (default 300 s) evita di
    colpire upstream per richieste GET identiche ravvicinate (cache solo delle risposte 2xx).
  - Viene sempre impostato l'header `User-Agent = PULSE_NOMINATIM_USER_AGENT` (richiesto dalla ToS).
- **Errori**: endpoint fuori allowlist → **404**; credenziali assenti/non valide → **401**;
  Nominatim non raggiungibile / errore di trasporto → **503 SERVICE_UNAVAILABLE**.

**Esempi**
```bash
# (a) con JWT Pulse
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://server:8443/api/v1/nominatim/search?q=Via+Roma+1+Torino&format=json&limit=1"

# (b) con API key (altro servizio senza JWT Pulse), header
curl -H "X-API-Key: $PULSE_NOMINATIM_API_KEY" \
  "https://server:8443/api/v1/nominatim/reverse?lat=45.07&lon=7.68&format=json"

# (b) con API key via query param (equivalente; l'api_key non viene inoltrata a Nominatim)
curl "https://server:8443/api/v1/nominatim/search?q=Torino&format=json&api_key=$PULSE_NOMINATIM_API_KEY"
```

**Configurazione** (prefisso `PULSE_`, vedi `.env.example`): `NOMINATIM_URL`,
`NOMINATIM_USER_AGENT`, `NOMINATIM_API_KEY`, `NOMINATIM_MIN_INTERVAL_MS`, `NOMINATIM_CACHE_TTL_SECONDS`.

---

# SEZIONE 2 — FRONTEND (Flask)

Due frontend Flask distinti: **Frontend Server** (gestione + dashboard aggregata) e **Frontend Probe** (dashboard locale). Entrambi consumano le API REST descritte sopra. Sotto: pagine, componenti, flussi e chiamate REST per pagina.

## 2.1 Componenti comuni (Server)
- **Layout/Navbar**: menu per aree secondo permessi dell'utente (voci nascoste se manca il permesso). Sorgente permessi: `GET /api/v1/auth/me`.
- **Guardia di sessione**: gestione token (login/refresh/logout).
- **Componente Tabella** (paginazione/filtri), **Form** con validazione, **Modale conferma**, **Toast** esiti, **Badge stato** (ok/warn/error/down/unknown), **Grafico serie temporale**, **Selettore intervallo temporale**, **Selettore Probe**.

## 2.2 Pagine — Frontend Server

### P-01 Login
- **Flusso**: form credenziali → login → salvataggio token → redirect dashboard.
- **REST**: `POST /api/v1/auth/login`; poi `GET /api/v1/auth/me`.

### P-02 Dashboard aggregata (Server)
- **Contenuto**: KPI globali, stato Probe, riepilogo stati sistemi, allarmi attivi.
- **Componenti**: schede KPI, tabella Probe, grafico distribuzione stati.
- **REST**: `GET /api/v1/dashboard/aggregate`; `GET /api/v1/probes`; `GET /api/v1/alarms?status=active`.

### P-03 Dettaglio Probe / Selezione Probe (drill-down)
- **Contenuto**: selettore Probe, elenco sistemi/check della Probe, grafici, stato liveness.
- **Componenti**: selettore Probe, tabella sistemi, grafici serie temporali, selettore intervallo.
- **REST**: `GET /api/v1/probes`; `GET /api/v1/dashboard/probe/{id}`; `GET /api/v1/probes/{id}/status`; `GET /api/v1/probes/{id}/heartbeats?...`.

### P-04 Interrogazione OpenSearch (query builder)
- **Contenuto**: costruttore filtri (sistema, check, stato, intervallo, soglie), risultati tabellari + aggregazioni/grafici.
- **REST**: `POST /api/v1/probes/{id}/query`; `GET /api/v1/systems?probe_id=...`; `GET /api/v1/systems/{id}/checks`.

### P-05 Grafici / Analisi
- **Contenuto**: grafici `response_ms`, uptime %, distribuzione stati, timeline eventi per sistema/check.
- **REST**: `POST /api/v1/probes/{id}/query` (con `aggregations`); `GET /api/v1/probes/{id}/heartbeats`.

### P-06 Gestione Utenti
- **Contenuto**: tabella utenti, form crea/modifica, assegna ruoli, reset password, abilita/disabilita.
- **REST**: `GET/POST /api/v1/users`; `GET/PUT/DELETE /api/v1/users/{id}`; `PUT /api/v1/users/{id}/roles`; `POST /api/v1/users/{id}/reset-password`; `GET /api/v1/roles` (per selezione).

### P-07 Gestione Ruoli
- **Contenuto**: tabella ruoli, form crea/modifica, editor permessi (checkbox da catalogo).
- **REST**: `GET/POST /api/v1/roles`; `GET/PUT/DELETE /api/v1/roles/{id}`; `PUT /api/v1/roles/{id}/permissions`; `GET /api/v1/permissions`.

### P-08 Catalogo Permessi
- **Contenuto**: elenco permessi raggruppati per area (sola lettura).
- **REST**: `GET /api/v1/permissions`.

### P-09 Gestione Sonde (Probe)
- **Contenuto**: tabella Probe con stato, form crea (mostra token enrollment), modifica, elimina, rotazione credenziali.
- **REST**: `GET/POST /api/v1/probes`; `GET/PUT/DELETE /api/v1/probes/{id}`; `POST /api/v1/probes/{id}/rotate-credentials`; `GET /api/v1/probes/{id}/status`.

### P-10 Gestione Sistemi Monitorati
- **Contenuto**: tabella sistemi (filtro per Probe), form crea/modifica (URL heartbeat, intervallo, timeout, soglie, Probe, finestre manutenzione), elimina, vista check scoperti.
- **REST**: `GET/POST /api/v1/systems`; `GET/PUT/DELETE /api/v1/systems/{id}`; `GET /api/v1/systems/{id}/checks`; `GET /api/v1/probes` (selezione).

### P-11 Gestione Canali Notifica
- **Contenuto**: tabella canali, form per tipo (email/telegram/whatsapp), toggle inbound, test invio.
- **REST**: `GET/POST /api/v1/notification-channels`; `GET/PUT/DELETE /api/v1/notification-channels/{id}`; `POST /api/v1/notification-channels/{id}/test`.

### P-12 Gestione Workflow Notifiche
- **Contenuto**: tabella workflow, editor (trigger, ambito, condizioni, step/azioni, escalation, soppressione), abilita/disabilita, simulazione.
- **REST**: `GET/POST /api/v1/notification-workflows`; `GET/PUT/DELETE /api/v1/notification-workflows/{id}`; `PUT /api/v1/notification-workflows/{id}/enabled`; `POST /api/v1/notification-workflows/{id}/simulate`; `GET /api/v1/notification-channels` (selezione).

### P-13 Storico Notifiche
- **Contenuto**: tabella invii con filtri ed esiti.
- **REST**: `GET /api/v1/notifications/history`.

### P-14 Allarmi
- **Contenuto**: elenco allarmi attivi/storici, azione ack.
- **REST**: `GET /api/v1/alarms`; `POST /api/v1/alarms/{id}/ack`.

### P-15 Le mie identità di canale
- **Contenuto**: elenco identità associate, associazione nuova (codice di verifica), rimozione.
- **REST**: `GET/POST /api/v1/channel-identities`; `DELETE /api/v1/channel-identities/{id}`.

### P-16 Audit Log
- **Contenuto**: tabella audit con filtri (attore, azione, entità, esito, intervallo), dettaglio voce.
- **REST**: `GET /api/v1/audit`; `GET /api/v1/audit/{id}`.

### P-17 Log di Sistema
- **Contenuto**: tabella log con filtri (componente, probe, livello, intervallo, testo).
- **REST**: `GET /api/v1/logs`.

### P-18 Configurazione
- **Contenuto**: form parametri raggruppati, segnalazione parametri che richiedono riavvio.
- **REST**: `GET /api/v1/config`; `PUT /api/v1/config`.

### P-19 Profilo utente
- **Contenuto**: dati profilo, cambio password.
- **REST**: `GET /api/v1/auth/me`; `POST /api/v1/auth/change-password`.

## 2.3 Pagine — Frontend Probe (dashboard locale)

### PP-01 Login (Probe)
- **Nota**: la dashboard Probe autentica gli operatori locali. Vedi QUESTIONI APERTE FE-02 sull'origine delle credenziali.
- **REST (Probe)**: autenticazione locale / o SSO col Server (da confermare).

### PP-02 Dashboard Probe completa
- **Contenuto**: stato di tutti i sistemi monitorati dalla Probe, badge stato, ultime latenze, allarmi locali.
- **REST (Probe)**: `GET /api/v1/status`; `GET /api/v1/systems`; `GET /api/v1/query/heartbeats?...`.

### PP-03 Dettaglio sistema/check (Probe)
- **Contenuto**: serie temporale per sistema/check, grafici.
- **REST (Probe)**: `GET /api/v1/query/heartbeats`; `POST /api/v1/query` (aggregazioni).

### PP-04 Interrogazione diretta (Probe)
- **Contenuto**: query builder sui dati locali.
- **REST (Probe)**: `POST /api/v1/query`.

### PP-05 Stato Probe / Salute
- **Contenuto**: stato poller, OpenSearch, coda eventi, versione.
- **REST (Probe)**: `GET /api/v1/status`; `GET /api/v1/health/ready`.

## 2.4 Mappa flussi FE → BE (sintesi)

| Flusso | Pagine | Endpoint chiave |
|---|---|---|
| Autenticazione | P-01, P-19 | /auth/* |
| Consultazione aggregata | P-02, P-03 | /dashboard/*, /probes* |
| Analisi/Query | P-04, P-05, PP-03, PP-04 | /probes/{id}/query, (probe) /query/* |
| Gestione identità/accessi | P-06, P-07, P-08 | /users*, /roles*, /permissions |
| Gestione infrastruttura | P-09, P-10 | /probes*, /systems* |
| Notifiche | P-11, P-12, P-13, P-14 | /notification-channels*, /notification-workflows*, /notifications/history, /alarms* |
| Comandi/identità canale | P-15 | /channel-identities* |
| Osservabilità/governance | P-16, P-17, P-18 | /audit, /logs, /config* |

---

## QUESTIONI APERTE / DECISIONI (API)

| # | Tema | Decisione | Motivazione | Da confermare a |
|---|---|---|---|---|
| API-01 | Query OpenSearch: DSL raw vs strutturata | Query strutturata Pulse (filtri/aggregazioni), non DSL raw | Sicurezza (evita injection/query costose) e coerenza RBAC. | BE / Committente |
| API-02 | Drill-down: proxy Server o accesso diretto Probe | Proxy via Server (`/probes/{id}/heartbeats`) | Mantiene RBAC e audit centralizzati. | BE |
| API-03 | Log Probe verso Server | Ingest via push + consultazione locale | Le Probe possono essere offline; log locali sempre disponibili. | BE |
| API-04 | Autenticazione dashboard Probe (FE-02) | Preferenza: stesse credenziali del Server (validazione token via Server) con fallback locale | Coerenza RBAC; da confermare fattibilità offline. | BE / Committente |
| API-05 | Endpoint `/alarms` e `/simulate` | Inclusi come supporto a escalation/ack e riduzione errori config | Derivano da RF-083 e UC-73; non ampliano l'ambito oltre le notifiche. | Committente |
| API-06 | Versionamento API | Prefix `/api/v1` | Consente evoluzione senza rotture. | BE |
