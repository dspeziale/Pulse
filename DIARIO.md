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

ITERAZIONE 3

Agente: BE
Data: 2026-07-15

Input ricevuti
- docs/api/DOCUMENTO_API.md (sezione BACKEND: endpoint/request/response/errori/auth/permessi — specifica vincolante).
- deploy/schema.sql + deploy/seed.sql e docs/database/SCHEMA_FISICO.md (schema PostgreSQL 16 reale e validato; 40 permessi nel seed = autoritativo).
- docs/analisi/06_rbac.md, 07_workflow_notifiche.md, 05_requisiti.md, 02_specifica_tecnica.md, 03_architettura.md.
- Schema canonico heartbeat (01_specifica_funzionale.md §4: oggetto singolo o array, status a dominio aperto, campi aggiunti dalla Probe).

Lavoro svolto
- Server backend (FastAPI): completata l'implementazione preesistente (auth/utenti/ruoli/permessi/probe/sistemi/dashboard) aggiungendo tutti i router mancanti: notifiche/canali, storico invii, workflow, allarmi (ack), comunicazione Server<->Probe (register/config/heartbeat/events/rollup), comandi in ingresso (webhook Telegram/WhatsApp/Email) + identita' di canale, audit, log di sistema, configurazione, healthcheck; assemblaggio main.py con OpenAPI curato (tag/summary) e handler errori standard.
- Autenticazione JWT (access+refresh, lockout), RBAC deny-by-default via dependency require_permission sul catalogo 40 permessi del seed; audit_log su azioni sensibili; log di sistema.
- Motore notifiche multi-canale (Email SMTP, Telegram Bot API, WhatsApp Business API) con cifratura segreti a riposo (Fernet), mascheramento in output, degradazione a "failed" senza credenziali. Motore workflow (trigger/scope/condizioni AND-OR/soppressione cooldown-dedup-manutenzione-orari/escalation/auto-risoluzione allarmi). Dispatcher comandi (/help,/status,/silence,/unsilence,/ack,/probes) con risoluzione identita'->utente e RBAC.
- Probe agent (FastAPI): poller heartbeat (parsing schema canonico singolo/array, normalizzazione status, documenti connettivita'), storage OpenSearch locale (indici+mapping) con fallback in-memory equivalente, motore di query strutturata Pulse (filtri/aggregazioni avg/min/max/count/uptime), endpoint di query interrogati dal Server (/query/heartbeats, /query, /systems, /status, /health), client verso il Server (enrollment/config/liveness/eventi/rollup), rilevazione eventi (status_changed/unreachable/recovered/response_time_exceeded).
- Sicurezza Server<->Probe a livello applicativo: token opaco per-Probe (hash SHA-256), enrollment monouso a scadenza, rotazione credenziali; token del Server verso la API di query della Probe; predisposizione mTLS via path certificati/config (documentata l'attivazione).
- Container: Dockerfile Server backend e Probe agent (python slim, gunicorn/uvicorn, porta via env, healthcheck). Compose deploy/docker-compose.server.yml (postgres+backend+dashboard FE) e deploy/docker-compose.probe.yml (opensearch+probe-agent+dashboard FE), equivalenti podman-compose.*, .env.server.example/.env.probe.example. Build context dashboard = radice repo (contratto FE) rispettato.
- Test: pytest+coverage con Postgres 16 effimero via Docker (schema+seed reali, isolamento per-test con savepoint) per il Server; storage in-memory + httpx.MockTransport per la Probe. mypy --strict pulito su entrambi i pacchetti.

File creati
- server/backend/pulse_server/main.py, commands.py; routers/{notifications,workflows,inbound,probe_comm,observability,health}.py; _helpers.flush_or_conflict.
- server/backend/{requirements.txt,requirements-dev.txt,pyproject.toml,Dockerfile,.env.example,README.md}; server/backend/tests/* (conftest + 13 file di test).
- probe/agent/pulse_probe/{__init__,config,schemas,canonical,query,store,server_client,state,poller,errors,deps,main}.py.
- probe/agent/{requirements.txt,requirements-dev.txt,pyproject.toml,Dockerfile,.env.example,README.md}; probe/agent/tests/* (conftest + 6 file di test).
- deploy/{docker-compose.server.yml,docker-compose.probe.yml,podman-compose.server.yml,podman-compose.probe.yml,.env.server.example,.env.probe.example}.

Problemi trovati
- Bug latente nel codice BE preesistente: parametri endpoint con annotazione Annotated+Depends (CurrentUserDep) E default Depends(require_permission(...)) — vietato da FastAPI; l'app non si assemblava. Corretto su tutti i router (annotazione CurrentUser + Depends).
- I create-endpoint eseguivano session.flush() prima del commit guardato: le violazioni UNIQUE emergevano come 500 anziche' 409. Introdotto helper flush_or_conflict.
- Porte Windows in range riservato Hyper-V per i container Postgres di test (55432 non bindabile): usata 5433 (test) / 5434 (verifica), override via env.
- Mount volume schema.sql/seed.sql fallito in Git Bash per traduzione path: in verifica lo schema/seed sono stati applicati via `docker exec psql` (come nel conftest).

Decisioni prese
- Catalogo permessi = 40 codici del seed (autoritativo), non 37 citati altrove (gia' segnalato dal DBA, I-1): documentato in SCOSTAMENTI del README backend per Analista/QA.
- Query OpenSearch strutturata (non DSL raw) e drill-down via proxy Server->Probe (API-01/API-02).
- Storage Probe con backend OpenSearch reale + fallback in-memory a semantica identica (resilienza/testabilita', documentato).
- Cifratura segreti canali a riposo con Fernet; test canale riporta sempre 200 con delivered true/false.
- rotate-credentials rigenera il token per-Probe e riporta la Probe a pending (emissione certificato X.509 demandata al livello PKI/mTLS).

Output consegnati
- Server backend: tutti i 72 endpoint del DOCUMENTO_API implementati (tutte le aree §1.1-§1.17; 73 operazioni esposte in OpenAPI su 52 path template), coverage 98% su 181 test, mypy strict pulito.
- Probe agent: API di query + poller + comunicazione col Server, coverage 98% su 65 test, mypy strict pulito.
- Verifica reale eseguita: server-backend avviato (uvicorn) contro Postgres 16 Docker con schema+seed; GET /api/v1/health = {"status":"ok"}, /health/ready database ok, login admin/'ChangeMe123!' = HTTP 200 (token, ruolo SuperAdmin, 40 permessi), GET /permissions autenticato = 200 (40), GET /users senza token = 401, OpenAPI = 73 operazioni / 52 path. docker compose config valido su entrambi gli stack.
- Bug noti residui: nessun test fallito; righe non coperte (2% per pacchetto) = rami difensivi/I-O (lettura CA in /probe/register, loop poller runtime, combinazioni di filtri ridondanti, casi "ultimo SuperAdmin" con piu' admin simultanei). Podman non installato: compose podman prodotti ma non eseguiti (struttura identica ai docker validati).

================================================

ITERAZIONE 4

Agente: FE
Data: 2026-07-15

Input ricevuti
- docs/api/DOCUMENTO_API.md (sezione FRONTEND: pagine P-01..P-19, PP-01..PP-05; sezione BACKEND: contratti REST consumati).
- docs/analisi/06_rbac.md (37/40 permessi, 5 ruoli, matrice ruoli x permessi) per l'enforcement UI.
- docs/analisi 01/02/03/07 per contesto funzionale, architettura e workflow/notifiche.
- Codice FE preesistente (frontend_common/, server/dashboard/) da completare e correggere.

Lavoro svolto
- Completata la dashboard SERVER (Flask): verificate e integrate tutte le viste/blueprint P-01..P-19; corretti gap (aggiunti template query/builder.html e query/charts.html mancanti; aggiunta route /healthz).
- Rimossa la dipendenza da CDN esterno (Chart.js): introdotta micro-libreria locale static/pulse-charts.js (bar/line) referenziata via url_for('static', ...).
- Implementata da zero la dashboard PROBE (Flask): app factory, login locale (FE-02), sdk verso probe-agent con token da env (FE-03), viste PP-01..PP-05, template, /healthz.
- Enforcement RBAC lato UI: permission_required su ogni route + menu che mostra/nasconde le voci con can('<permesso>'); nessun catalogo cablato (usa i permessi da /auth/me).
- Gestione errori coerente coi codici backend: 401->redirect login, 403/404/409/422/500->pagina errore, backend/agent irraggiungibile->503.
- Contratto deploy: Dockerfile (Python slim + gunicorn, porta da env, healthcheck /healthz) e .env.example per entrambe le dashboard; requirements.txt/requirements-dev.txt con versioni.
- Test pytest con backend simulato (FakeApiClient, nessun backend reale): 104 test totali (frontend_common 27, server 50, probe 27). Coverage combinata REALE 100% (1054 stmt, 92 branch, 0 miss) via .coveragerc in radice.
- README per entrambe le dashboard con avvio/env/test/coverage e sezione SCOSTAMENTI.
- VERIFICA eseguita: venv + install, pytest per-pacchetto tutti verdi, coverage 100%; smoke test WSGI (app:app) per Server e Probe: /healthz 200, /login 200, pagina protetta anonima -> 302.

File creati
- server/dashboard/static/pulse-charts.js
- server/dashboard/templates/query/builder.html, server/dashboard/templates/query/charts.html
- server/dashboard/Dockerfile, server/dashboard/.env.example, server/dashboard/requirements.txt, server/dashboard/requirements-dev.txt, server/dashboard/README.md
- server/dashboard/tests/conftest.py, test_app_and_auth.py, test_views_crud.py, test_views_more.py
- probe/dashboard/app.py, probe/dashboard/sdk.py, probe/dashboard/probe_auth.py
- probe/dashboard/views/__init__.py, auth.py, dashboard.py, query.py, status.py
- probe/dashboard/templates/base.html, error.html, auth/login.html, dashboard/index.html, dashboard/system.html, query/builder.html, status/index.html
- probe/dashboard/static/pulse-charts.js
- probe/dashboard/Dockerfile, probe/dashboard/.env.example, probe/dashboard/requirements.txt, probe/dashboard/requirements-dev.txt, probe/dashboard/README.md
- probe/dashboard/tests/conftest.py, test_probe_dashboard.py, test_probe_auth.py
- frontend_common/tests/test_rbac.py, test_config.py, test_http_client.py, test_auth.py
- .coveragerc
File modificati
- server/dashboard/app.py (route /healthz), server/dashboard/templates/dashboard/index.html e probes/detail.html (rimozione CDN), .gitignore.

Problemi trovati
- Viste query P-04/P-05 referenziavano template inesistenti (query/builder.html, query/charts.html): creati.
- Template Server usavano Chart.js via CDN esterno (vietato dai requisiti): sostituito con libreria locale.
- Nessuna route di healthcheck presente: aggiunta /healthz su entrambe le dashboard.
- Le due dashboard hanno moduli entrypoint omonimi (app/sdk/views): i test vanno eseguiti in invocazioni pytest separate; coverage unificata via coverage combine.
- QUESTIONE APERTA API-04/FE-02 (auth dashboard Probe) e FE-03 (token agent) non definite nel dettaglio: adottate credenziali locali via env + token Bearer via env; da confermare a BE/Committente.

Decisioni prese
- Grafici: micro-libreria JS locale self-contained (no CDN), sottoinsieme API Chart.js. Motivazione: requisito "niente CDN esterni".
- Sessione: JWT del backend salvato in sessione Flask server-side firmata; refresh token conservato per logout.
- Docker build context = radice repository (non ./server|probe/dashboard) perche' le dashboard dipendono dal pacchetto condiviso frontend_common/; porta via env e healthcheck /healthz rispettati (snippet compose forniti nei README per il BE).
- RBAC UI senza catalogo cablato: fonte permessi = risposta backend (/auth/login, /auth/me).

Output consegnati
- Due frontend Flask completi (Server P-01..P-19, Probe PP-01..PP-05) allineati al DOCUMENTO_API, con Dockerfile/.env.example/requirements/README; suite pytest a copertura 100% con backend mockato. Pronto per QA.

================================================

ITERAZIONE 5

Agente: QA
Data: 2026-07-15

Input ricevuti
- docs/api/DOCUMENTO_API.md (contratto API vincolante: endpoint, response, errori, permessi, pagine FE).
- docs/analisi/* (RF/RNF, RBAC 40 permessi + matrice 5 ruoli, workflow/notifiche, casi d'uso).
- deploy/schema.sql + seed.sql (DB reale) e deploy/docker-compose.*.yml.
- Codice: server/backend (FastAPI), probe/agent (FastAPI), server/dashboard + probe/dashboard (Flask), frontend_common.
- READMEs con procedure di test/coverage per-pacchetto.

Lavoro svolto
- Eseguite TUTTE le categorie richieste: API, Integration, Regression, Functional, Security, RBAC, Performance, Notification, Workflow, Audit, Log, Probe, Server, Frontend, Backend, Database, Deploy.
- Suite pytest reali con coverage: backend 181 test / 98%; probe-agent 65 test / 98%; frontend_common 27 / 100%; dashboard Server 50 / 100% (codice app); dashboard Probe 27 / 100% (codice app). Totale 350 test, 0 falliti.
- Integrazione LIVE: Postgres 16 Docker + schema+seed, backend uvicorn reale; harness httpx con 127 asserzioni su tutte le aree del DOCUMENTO_API (status code + forma response + casi 401/403/404/409/422). 125 pass, 2 fail (= 2 bug).
- RBAC: creati utenti Operator/Viewer/Auditor via API e verificati accessi negati/consentiti; deny-by-default (401 senza token); integrita' (self-delete/disable admin=409, ruoli builtin protetti).
- Security: JWT manomesso/forgiato/scaduto=401; masking segreti canali OK; SQL injection su parametri gestita (no 500); rilevata assenza header di sicurezza (hardening).
- Audit/DB: verificata immutabilita' audit_log (UPDATE/DELETE bloccati da trigger), protezione ruoli builtin, UNIQUE, CHECK poll_interval>0, FK RESTRICT probe->sistemi; seed (40 permessi/5 ruoli/matrice/admin/10 config).
- Probe: avvio live agent con storage in-memory (fallback), health/ready/status/systems/query verdi, auth token in tempo costante.
- Performance smoke: login 256ms (bcrypt), list endpoint 11-18ms, 100 health seq ~137ms.
- Deploy: docker compose config VALIDO su server/probe/base; Dockerfile con healthcheck e porta da env; Podman revisione statica (non installato).

File creati
- QA_REPORT.md (radice): sommario, esiti per categoria, coverage con gap, tabella BUG, test falliti, routing BUG_BACKEND/BUG_FRONTEND.
- (file di lavoro temporanei nello scratchpad di sessione: harness integrazione, log; non versionati.)

Problemi trovati
- BUG-01 (BACKEND, Maggiore): POST/PUT /users accetta email non valida (schemas.py usa str invece di EmailStr) -> 201 invece di 422.
- BUG-02 (DOC, Minore): PUT /roles/{id} modifica la description di un ruolo predefinito (200) mentre l'API doc indica 409; ambiguita' con lo schema (trigger consente la sola description). Da chiarire.
- BUG-03/BUG-04 (BACKEND, Media): coverage backend 98% e probe-agent 98% < obiettivo 100%.
- DOC-01 (DOC, Minore): 06_rbac.md dichiara "37 permessi" ma sono 40 (gia' noto DBA/BE).
- SEC-01 (BACKEND, Minore): header di sicurezza HTTP assenti + banner Server (non richiesto dal contratto; hardening).
- Nessun bug Bloccante. Nessun bug lato FRONTEND.

Decisioni prese
- Verdetto QA: FAIL, motivato da 1 bug Maggiore (validazione email) e dal mancato obiettivo di coverage 100% BE/probe; nessun blocco funzionale.
- Comportamenti ambigui tra API doc e schema (description ruolo builtin) classificati come DOC/Minore, non come bug di codice, per non inventare requisiti.
- Assenza header di sicurezza classificata Minore (non prevista dal contratto): segnalata come hardening, non come violazione.

Output consegnati
- QA_REPORT.md completo con tabella bug (6 finding: 1 Maggiore, 2 Media, 3 Minore; 0 Bloccanti) e routing fix (BUG_BACKEND: BUG-01, BUG-03, BUG-04, SEC-01 [+BUG-02/DOC-01 doc]; BUG_FRONTEND: nessuno). Coverage reali: BE 98%, Probe 98%, FE 100%.

================================================
