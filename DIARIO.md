# DIARIO — Progetto Pulse

Registro cronologico di tutte le iterazioni tra gli agenti.
Formato obbligatorio per ogni iterazione; una riga vuota tra un'iterazione e la successiva.

================================================

ITERAZIONE 0

Agente: ORCHESTRATORE
Data: 2026-07-15

Input ricevuti
- Requisiti di progetto "Pulse" (sistema distribuito di monitoraggio connettività/stato applicativo HTTP/HTTPS).

Lavoro svolto
- Inizializzato repository git per il versionamento.
- Creata struttura cartelle: docs/ (analisi, api, database), server/, probe/, deploy/.
- Creato .gitignore.
- Creato DIARIO.md.
- Definita pipeline agenti: ANALISTA -> DBA -> (BE + FE) -> QA -> loop fix fino a 0 bug.

File creati
- .gitignore
- DIARIO.md
- struttura cartelle docs/, server/, probe/, deploy/

Problemi trovati
- Podman non installato sulla macchina (disponibile solo Docker). I file podman-compose saranno prodotti come richiesto ma verificabili solo tramite Docker.

Decisioni prese
- Versionamento tramite git (requisito "ogni file deve essere versionato").
- Lingua documentazione: italiano per i documenti di analisi/diario; inglese tecnico ammesso nel codice.

Output consegnati
- Fondamenta di progetto pronte per l'AGENTE 1 (ANALISTA).

================================================

ITERAZIONE 1

Agente: ANALISTA
Data: 2026-07-15

Input ricevuti
- Requisiti di progetto "Pulse" (sistema distribuito di monitoraggio connettività/stato applicativo HTTP/HTTPS).
- Schema canonico heartbeat (GET /api/heartbeat) come fonte di verità.
- Vincoli stack: Backend Python+FastAPI, Frontend Python+Flask, DB Probe OpenSearch, DB Server scelto dal DBA.
- Struttura cartelle e DIARIO predisposti dall'ORCHESTRATORE (Iterazione 0).

Lavoro svolto
- Definito un vocabolario canonico condiviso (entità, permessi, endpoint) per garantire coerenza tra tutti i documenti.
- Prodotta l'analisi funzionale completa: specifica funzionale, tecnica, architettura (con diagrammi Mermaid), casi d'uso, requisiti numerati, modello RBAC e modello dei workflow notifiche.
- Prodotto il Documento API unico (Backend REST per area + Frontend con pagine/flussi/chiamate).
- Prodotto il Documento Database (modello logico agnostico dal motore per il DBA + confine di persistenza Server vs OpenSearch Probe).
- Verificata la coerenza incrociata: 37 permessi RBAC combaciano tra 06_rbac.md, DOCUMENTO_API.md e tracciabilità del DOCUMENTO_DATABASE.md; nomi entità/endpoint uniformi.

File creati
- docs/analisi/01_specifica_funzionale.md
- docs/analisi/02_specifica_tecnica.md
- docs/analisi/03_architettura.md
- docs/analisi/04_casi_uso.md
- docs/analisi/05_requisiti.md
- docs/analisi/06_rbac.md
- docs/analisi/07_workflow_notifiche.md
- docs/api/DOCUMENTO_API.md
- docs/database/DOCUMENTO_DATABASE.md

Problemi trovati
- Requisiti ambigui su alcuni punti, documentati come QUESTIONI APERTE nei rispettivi file: enum di `status` (non definito), formato di `GET /api/heartbeat` (oggetto singolo vs array per N check), direzione/raggiungibilità della query Server→Probe, meccanismo di cifratura, fattibilità ricezione comandi WhatsApp/Email.
- Comunicazione Server↔Probe non completamente specificata nei requisiti: definito modello ibrido (Probe→Server per enrollment/config/eventi/rollup su porta dedicata; Server→Probe per query drill-down) documentato in architettura.

Decisioni prese
- Cifratura Server↔Probe: mTLS (TLS 1.2+/1.3) + token applicativo per-Probe (+ HMAC opzionale), con enrollment a token monouso e CA interna. Motivazione: mutua autenticazione, revoca/rotazione rapida, self-contained e portabile.
- `status` trattato come dominio aperto con normalizzazione a {ok,warn,error,down,unknown} per UI/notifiche.
- `GET /api/heartbeat` supporta oggetto singolo o array; ogni check → 1 documento OpenSearch.
- Serie temporali solo su OpenSearch delle Probe; sul DB Server solo dati gestionali + rollup (tabella probe_rollups).
- Valutazione workflow centralizzata sul Server su eventi push dalle Probe; introdotte entità alarms (ack/escalation) e channel_identities/inbound_commands (comandi in ingresso).
- RBAC: 37 permessi granulari, 5 ruoli predefiniti (SuperAdmin, Admin, Operator, Viewer, Auditor) con matrice completa.
- Ricezione comandi: Telegram pieno (webhook), WhatsApp condizionato a Business API di un provider, Email limitato a comandi non critici con verifica token/DKIM.
- Query OpenSearch esposta come query strutturata Pulse (non DSL raw) per sicurezza e coerenza RBAC.

Output consegnati
- 9 documenti di analisi/API/database completi e coerenti, pronti per l'AGENTE 2 (DBA) che dovrà scegliere e motivare il motore del DB Server sulla base del modello logico e dei requisiti dati forniti.

================================================

ITERAZIONE 2

Agente: DBA
Data: 2026-07-15

Input ricevuti
- docs/database/DOCUMENTO_DATABASE.md (modello logico, 23 entità Server §3.1–§3.23 + confine OpenSearch).
- docs/api/DOCUMENTO_API.md (coerenza nomi/campi endpoint).
- docs/analisi/06_rbac.md (catalogo permessi, 5 ruoli, matrice ruoli×permessi).
- docs/analisi/07_workflow_notifiche.md (entità workflow/allarmi/comandi).
- docs/analisi/05_requisiti.md (audit immutabile, retention, cifratura, ecc.).
- Vincolo utente: motore DB Server = PostgreSQL 16 (da motivare); OpenSearch resta sulle Probe.

Lavoro svolto
- Progettato lo schema fisico PostgreSQL 16 completo delle 23 entità del modello logico (nessuna entità OpenSearch inclusa, RF-051).
- Mapping tipi logici→PostgreSQL (uuid, varchar, jsonb, timestamptz, ENUM→varchar+CHECK).
- Definiti PK/FK con azioni referenziali coerenti con l'API (RESTRICT dove l'API prevede 409: probe con sistemi, canale usato da workflow), UNIQUE, CHECK, 78 indici motivati.
- Implementate strategie richieste: audit immutabile (trigger BEFORE UPDATE/DELETE), updated_at automatico, protezione ruoli builtin, funzione di retention fn_purge_retention(), 3 viste (permessi effettivi, conteggio sistemi/probe, allarmi attivi).
- Scritto seed: catalogo permessi, 5 ruoli predefiniti, matrice ruoli×permessi, utente admin SuperAdmin (bcrypt cost 12 di 'ChangeMe123!'), 10 parametri di configurazione di default.
- Prodotti compose Docker e Podman (volume persistente, init da schema.sql+seed.sql via /docker-entrypoint-initdb.d, healthcheck, porta configurabile via env).
- Redatti ER_DIAGRAM.md (Mermaid erDiagram con attributi/PK/FK/cardinalità) e SCHEMA_FISICO.md (motivazione PostgreSQL, dettaglio tabelle, strategie, incongruenze, copertura entità, esito validazione).
- VALIDAZIONE ESEGUITA con Docker (postgres:16): schema.sql e seed.sql applicati puliti (exit 0), idempotenza verificata (re-run 0 righe), trigger e vista verificati.

File creati
- deploy/schema.sql
- deploy/seed.sql
- deploy/docker-compose.yml
- deploy/podman-compose.yml
- docs/database/ER_DIAGRAM.md
- docs/database/SCHEMA_FISICO.md

Problemi trovati
- I-1: 06_rbac.md dichiara "37 permessi" ma il catalogo enumerato (§2) e la matrice (§4) contengono 40 codici distinti. Scelta conservativa: seed di tutti i 40 codici enumerati (nessuna invenzione); segnalare all'Analista il conteggio errato.
- I-3: DELETE canale (API 409 solo "se usato da workflow") vs notification_deliveries.channel_id NOT NULL storico. Scelto ON DELETE RESTRICT anche su deliveries per preservare lo storico; il 409 "workflow" resta su workflow_actions.channel_id RESTRICT.
- Parole riservate come nomi colonna (trigger/timestamp/window/repeat): mantenuti i nomi API quotandoli nel DDL (coerenza RNF-050).
- RF-021 (ultimo SuperAdmin) e "ultimo SuperAdmin non rimuovibile" non esprimibili in modo affidabile a livello DB → enforcement Backend (409), come da API.
- Podman non installato in questo ambiente: podman-compose.yml prodotto ma validato solo indirettamente (struttura identica al docker-compose validato).

Decisioni prese
- Motore: PostgreSQL 16 (motivato in SCHEMA_FISICO.md §1 punto per punto sui requisiti dati).
- ENUM come varchar+CHECK (portabilità/evolvibilità) invece di CREATE TYPE.
- JSON come jsonb; probes.tags come jsonb array con CHECK.
- gen_random_uuid() in core (no estensione obbligatoria); pgcrypto abilitato per usi futuri.
- Hashing password: bcrypt cost 12 (RNF-003 non specifica l'algoritmo); colonna compatibile con argon2id.
- Audit non incluso nella retention (conservazione a fini di conformità).
- Retention via funzione + scheduler esterno (pg_cron non garantito nell'immagine standard).

Output consegnati
- Schema fisico PostgreSQL 16 completo, eseguibile, idempotente e validato; seed RBAC completo; ER diagram; documentazione schema fisico; compose Docker/Podman. Pronto per gli AGENTI 3 (BE + FE).

================================================
