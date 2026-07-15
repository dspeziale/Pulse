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
