# Pulse — Specifica Tecnica

Documento: `02_specifica_tecnica.md`
Autore: AGENTE 1 — ANALISTA
Data: 2026-07-15

---

## 1. Stack tecnologico

| Componente | Tecnologia | Note |
|---|---|---|
| Backend Server | Python 3.12+ / **FastAPI** | API REST, logica RBAC/workflow/notifiche, endpoint dedicati per le Probe. |
| Frontend Server | Python / **Flask** | Dashboard aggregata, gestione, consultazione. Consuma le API REST del backend. |
| Backend Probe | Python 3.12+ / **FastAPI** | Poller heartbeat, ingest OpenSearch, API di query, comunicazione col Server. |
| Frontend Probe | Python / **Flask** | Dashboard completa locale, interrogazione diretta. |
| DB Probe | **OpenSearch** (locale per Probe) | Serie temporali heartbeat + eventi connettività. |
| DB Server | **Da scegliere dal DBA** | Modello logico agnostico in `docs/database/DOCUMENTO_DATABASE.md`. |
| Runtime Probe | **Docker / Podman** | Immagini OCI, compose per Docker e Podman. |
| Comunicazione Server↔Probe | HTTPS + **mTLS** + token applicativo | Vedi §4. |

Motivazioni stack: FastAPI offre validazione tipata (Pydantic), async I/O adatto a polling/ingest e generazione OpenAPI; Flask è adeguato a UI server-rendered; OpenSearch è imposto dai requisiti ed è ottimale per serie temporali/ricerca.

---

## 2. Componenti e responsabilità

### 2.1 Server
- **API Gateway/Backend (FastAPI)**: espone tutte le API applicative (auth, gestione, dashboard) e gli **endpoint dedicati alle Probe** su porta configurabile.
- **Servizio RBAC**: autenticazione (JWT), autorizzazione per permesso.
- **Motore Workflow/Notifiche**: valuta gli eventi ricevuti dalle Probe, applica workflow, invia notifiche, gestisce escalation e comandi in ingresso (webhook).
- **Registro Probe/Sistemi**: enrollment, configurazione, assegnazione sistemi.
- **Aggregatore**: raccoglie i rollup delle Probe per la dashboard aggregata; effettua query on-demand alle Probe per il drill-down.
- **Audit & Log**: persistenza audit log e log di sistema.
- **DB Server**: persistenza di tutte le entità gestionali (vedi documento database).
- **Frontend Flask**: UI amministrativa e di consultazione.

### 2.2 Probe
- **Poller**: interroga `GET /api/heartbeat` dei sistemi assegnati secondo l'intervallo configurato; misura raggiungibilità/latenza.
- **Ingestor**: normalizza e indicizza i documenti su **OpenSearch locale**.
- **Rilevatore eventi**: calcola cambi di stato/connettività e li invia al Server.
- **API di query (FastAPI)**: espone query filtrate sull'OpenSearch locale (usate dal Server e dalla dashboard Probe).
- **Client Server**: enrollment, pull configurazione, push liveness/eventi/rollup.
- **Frontend Flask**: dashboard completa locale + interrogazione diretta.
- **OpenSearch locale**: storage serie temporali.

### 2.3 Sistemi monitorati (esterni)
- Espongono `GET /api/heartbeat` (schema §4 della specifica funzionale). Passivi rispetto a Pulse.

---

## 3. Porte e networking

| Interfaccia | Default proposto | Configurabile | Note |
|---|---|---|---|
| Server — API applicative (frontend/backend) | 8443 (HTTPS) | Sì | Usata dalle UI/utenti. |
| Server — **endpoint dedicati Probe** | 9443 (HTTPS+mTLS) | **Sì (requisito)** | Porta "nota alle Probe". |
| Probe — API di query | 8444 (HTTPS+mTLS) | Sì | Usata dal Server per drill-down. |
| Probe — dashboard locale | 8080/8443 | Sì | Accesso diretto operatori. |
| OpenSearch Probe | 9200 | Sì | Locale/interno alla Probe. |

Nota: separare la porta applicativa da quella dedicata alle Probe consente policy di rete/firewall distinte.

---

## 4. Cifratura e sicurezza del canale Server↔Probe (scelta motivata)

### 4.1 Requisito
"Comunicazione CIFRATA tra Server e Probe"; "Il Server espone endpoint dedicati su una porta configurabile, nota alle Probe".

### 4.2 Meccanismo scelto: **TLS con autenticazione mutua (mTLS) + token applicativo per-Probe**

Livelli:

1. **Trasporto — TLS 1.2+ (preferito 1.3)** su tutte le connessioni Server↔Probe. Cifratura in transito.
2. **Autenticazione mutua — mTLS**:
   - Il Server presenta il proprio certificato server.
   - Ogni Probe presenta un **certificato client** individuale, emesso da una **CA interna di Pulse** durante l'enrollment.
   - Il Server valida che il certificato client corrisponda a una Probe registrata e non revocata.
3. **Autenticazione applicativa — token/segreto per-Probe (Bearer)**:
   - Emesso all'enrollment, ruotabile (`probes.rotate_key`), legato a `probe_id`.
   - Aggiunge un secondo fattore indipendente dal certificato e consente revoca immediata senza rigenerare la PKI.
4. **Integrità/anti-replay (opzionale, rafforzativo)**: firma HMAC del corpo con `probe_secret` + timestamp/nonce sugli endpoint di ingest/eventi, per respingere replay anche in caso di compromissione TLS a valle di un proxy.

### 4.3 Enrollment (bootstrap sicuro)
- Alla creazione della Probe sul Server viene generato un **token di enrollment** monouso a scadenza.
- La Probe, al primo avvio, chiama `POST /api/v1/probe/register` presentando il token di enrollment su canale TLS; riceve `probe_id`, certificato client (o CSR firmata) e `probe_secret`.
- Da quel momento usa mTLS + Bearer per tutte le chiamate.

### 4.4 Motivazione della scelta
- **mTLS** garantisce che solo Probe autorizzate parlino col Server (e viceversa), senza dipendere da segreti condivisi statici deboli.
- Il **token applicativo** disaccoppia l'identità applicativa dalla PKI, permettendo **rotazione e revoca rapide** (requisito `probes.rotate_key`).
- Soluzione **standard, self-contained, portabile** in container, senza dipendenze da servizi esterni di identità.
- Alternative scartate: solo API-key statica (nessuna mutua autenticazione, rotazione debole); VPN/wireguard (aggiunge dipendenza infrastrutturale non richiesta); mTLS senza token (revoca più onerosa). Vedi QUESTIONI APERTE §9.

### 4.5 Sicurezza applicativa generale
- Password utente con hashing forte (es. Argon2/bcrypt) — scelta implementativa del BE.
- JWT firmati per le sessioni utente (access token short-lived + refresh token revocabile).
- Segreti (SMTP, token bot Telegram, credenziali WhatsApp, chiavi Probe) cifrati a riposo nel DB Server / gestiti via variabili d'ambiente o secret store.
- Tutti gli endpoint HTTP esposti agli utenti sono in HTTPS.

---

## 5. Persistenza

### 5.1 OpenSearch (Probe)
- Indici serie temporali heartbeat (naming e mapping in `docs/database/DOCUMENTO_DATABASE.md`).
- Politiche di retention/rollover (ISM) configurabili localmente.
- Nessun dato gestionale (utenti/ruoli/ecc.) su OpenSearch.

### 5.2 DB Server (logico, motore da scegliere dal DBA)
- Contiene tutte le entità gestionali: utenti, ruoli, permessi, probe, sistemi, canali, workflow, audit, log, configurazione, sessioni/token.
- **Non** contiene la serie temporale grezza degli heartbeat (solo rollup/snapshot per la dashboard aggregata).
- Requisiti dati (transazionalità, relazioni, immutabilità audit, volumi) elencati nel documento database per guidare la scelta del motore.

---

## 6. Configurazione

### 6.1 Configurazione Server (fonti: variabili d'ambiente + tabella `configuration`)
- Porta API applicativa; **porta dedicata Probe (configurabile)**.
- Parametri DB Server (connessione).
- Policy password, TTL access/refresh token, soglia tentativi login.
- Parametri PKI/mTLS (CA, path certificati).
- Default SMTP; credenziali bot Telegram; credenziali provider WhatsApp.
- Soglie predefinite (es. `response_ms` warn/error), finestre di manutenzione globali.
- Livello di log, retention log/audit.

### 6.2 Configurazione Probe (variabili d'ambiente + pull dal Server)
- Endpoint + porta del Server; token di enrollment (primo avvio).
- Identità/credenziali (`probe_id`, `probe_secret`, certificati) dopo enrollment.
- Parametri connessione OpenSearch locale.
- Intervallo di sincronizzazione configurazione e di push rollup.
- I **sistemi assegnati** e i relativi parametri di polling sono **scaricati dal Server** (`GET /api/v1/probe/config`).

### 6.3 Precedenza
Variabili d'ambiente (bootstrap/segreti) > valori scaricati dal Server > default applicativi.

---

## 7. Deploy

### 7.1 Probe (Docker/Podman) — requisito
- Immagine OCI unica della Probe (FastAPI + poller + Flask) + OpenSearch (container separato o servizio) orchestrati via **compose**.
- Forniti file `docker-compose.yml` e `podman-compose.yml` equivalenti (vedi `deploy/`).
- Config via variabili d'ambiente + volume per persistenza OpenSearch.
- Healthcheck container su endpoint `/api/v1/health`.

### 7.2 Server
- Deploy come servizio (container o host) con backend FastAPI + frontend Flask + DB Server.
- Reverse proxy/terminazione TLS a scelta del deploy (documentata dal BE/Deploy).

### 7.3 Portabilità Docker/Podman
- Nessuna dipendenza da funzionalità esclusive di un runtime.
- Immagini rootless-friendly (compatibili Podman).
- Nota operativa: sulla macchina di sviluppo è disponibile solo Docker (Podman non installato) — i file Podman sono prodotti ma verificati con Docker (vedi DIARIO iterazione 0).

---

## 8. Osservabilità
- **Log di sistema** strutturati (JSON) per Server e Probe, con livello configurabile.
- **Audit log** immutabile lato Server.
- **Health/readiness** endpoint per orchestrazione.
- Metriche operative di base (stato Probe, esiti polling, invii notifica) esposte nelle dashboard.

---

## 9. QUESTIONI APERTE / DECISIONI

| # | Tema | Decisione | Motivazione | Da confermare a |
|---|---|---|---|---|
| QT-01 | Meccanismo cifratura Server↔Probe | mTLS (TLS 1.2+/1.3) + token per-Probe + HMAC opzionale | Mutua autenticazione + revoca/rotazione rapida, self-contained e portabile. | BE / Committente |
| QT-02 | Gestione PKI (CA interna) | CA interna Pulse gestita dal Server; certificati client emessi all'enrollment | Evita dipendenze esterne; centralizza revoca. Da valutare integrazione con CA aziendale. | Committente |
| QT-03 | Motore DB Server | Non deciso (compito DBA) | Requisito esplicito: scelta e motivazione del DBA. | DBA |
| QT-04 | Raggiungibilità Probe dal Server per query | Assunta raggiungibilità diretta su porta query mTLS | Necessaria al drill-down; se NAT, valutare canale inverso/proxy. | BE / Committente |
| QT-05 | Terminazione TLS lato Server (reverse proxy vs app) | Rimandata al deploy | Dipende dall'infrastruttura target. | Deploy / BE |
| QT-06 | Rollup vs query live per dashboard aggregata | Rollup periodici push + query on-demand per dettaglio | Riduce carico e latenza sul Server mantenendo il drill-down accurato. | BE |
