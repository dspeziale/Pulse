# Pulse — Specifica Funzionale

Documento: `01_specifica_funzionale.md`
Autore: AGENTE 1 — ANALISTA
Data: 2026-07-15
Stato: Bozza per pipeline (DBA → BE/FE → QA)

---

## 1. Scopo e visione

Pulse è un sistema distribuito per il **monitoraggio della connettività e dello stato applicativo** di sistemi che espongono un endpoint HTTP/HTTPS di heartbeat. Il sistema è composto da un **Server centrale** e da una o più **Probe** dislocate (tipicamente vicine ai sistemi da monitorare o all'interno delle reti da osservare).

Obiettivi funzionali:

- Interrogare periodicamente l'endpoint `GET /api/heartbeat` dei sistemi monitorati e registrarne lo stato.
- Archiviare la serie temporale degli heartbeat su **OpenSearch locale a ciascuna Probe**.
- Offrire una **dashboard aggregata** sul Server e una **dashboard completa** su ciascuna Probe.
- Consentire di **selezionare la Probe da consultare** dal Server.
- Gestire **utenti, ruoli, permessi (RBAC)**, **audit log**, **log di sistema**, **configurazione**.
- Gestire **sonde (Probe)** e **sistemi monitorati**.
- Inviare **notifiche** (Email, Telegram, WhatsApp) tramite **workflow completamente configurabili** e, ove tecnicamente possibile, **ricevere comandi** dagli stessi canali.
- Garantire **comunicazione cifrata** tra Server e Probe.

Questo documento descrive il COSA. Il COME (stack, cifratura, deploy) è in `02_specifica_tecnica.md`; l'architettura in `03_architettura.md`.

---

## 2. Glossario (vocabolario canonico)

I termini seguenti sono usati in modo identico in TUTTI i documenti (analisi, API, database).

| Termine | Definizione |
|---|---|
| **Server** | Componente centrale: aggregazione dati, gestione, dashboard aggregata, punto unico di amministrazione. |
| **Probe (Sonda)** | Componente distribuito che interroga i sistemi monitorati, archivia gli heartbeat su OpenSearch locale ed espone dashboard/query dirette. Deploy come container Docker/Podman. |
| **Sistema monitorato (System)** | Applicazione/servizio HTTP/HTTPS che espone `GET /api/heartbeat`. Assegnato a una Probe. |
| **Check** | Singolo controllo interno a un sistema monitorato (`check_id` / `check_name`), es. `db`/`Database`. Un sistema espone 1..N check. |
| **Heartbeat** | Documento restituito da `GET /api/heartbeat` per un check, secondo lo schema canonico (§4). |
| **Stato di connettività** | Esito della chiamata HTTP della Probe verso il sistema (raggiungibile / non raggiungibile / timeout). Distinto dallo `status` applicativo dentro l'heartbeat. |
| **Canale notifica (Channel)** | Configurazione di un mezzo di invio/ricezione: Email, Telegram, WhatsApp. |
| **Workflow notifiche** | Regola configurabile trigger → condizioni → azioni → escalation. |
| **Comando in ingresso (Inbound command)** | Comando ricevuto da un canale (es. `/status`) mappato a un'operazione consentita in base all'identità del mittente. |
| **RBAC** | Role-Based Access Control: utenti → ruoli → permessi. |
| **Audit log** | Registro immutabile delle azioni degli utenti/attori sul sistema. |
| **Log di sistema** | Log tecnici/applicativi dei componenti (Server e Probe). |

---

## 3. Attori

| Attore | Descrizione |
|---|---|
| **Super Amministratore** | Controllo totale, inclusa gestione ruoli/permessi e degli altri amministratori. |
| **Amministratore** | Gestione operativa completa (probe, sistemi, notifiche, workflow, utenti in lettura). |
| **Operatore** | Gestisce probe/sistemi/notifiche/workflow a livello operativo, consulta dashboard, esegue comandi. |
| **Visualizzatore (Viewer)** | Sola consultazione di dashboard, stato, serie temporali. |
| **Auditor** | Sola consultazione di audit log e log di sistema. |
| **Probe (attore di sistema)** | Identità non umana: si autentica al Server, scarica la propria configurazione, invia stato/eventi/rollup. |
| **Sistema monitorato (attore esterno)** | Espone `GET /api/heartbeat`; passivo rispetto a Pulse. |
| **Utente di canale** | Persona che interagisce via Email/Telegram/WhatsApp; può ricevere notifiche e inviare comandi previa associazione identità. |

Il modello RBAC dettagliato (permessi, ruoli, matrice) è in `06_rbac.md`.

---

## 4. Schema canonico dell'heartbeat (fonte di verità)

Ogni sistema monitorato espone `GET /api/heartbeat`. Ogni documento heartbeat rispetta ESATTAMENTE:

```json
{
  "@timestamp": "2026-07-13T10:00:00Z",
  "system_id": "myapp",
  "system_name": "MyApp",
  "check_id": "db",
  "check_name": "Database",
  "status": "ok",
  "response_ms": 12,
  "message": null,
  "details": "{\"response_ms\":12,\"metrics\":{}}"
}
```

Campi:

| Campo | Tipo | Note |
|---|---|---|
| `@timestamp` | stringa ISO-8601 UTC | Istante del check lato sistema monitorato. |
| `system_id` | stringa | Identificatore tecnico del sistema. |
| `system_name` | stringa | Nome leggibile del sistema. |
| `check_id` | stringa | Identificatore tecnico del check. |
| `check_name` | stringa | Nome leggibile del check. |
| `status` | stringa | Stato applicativo del check (es. `ok`, `warn`, `error`; valori possibili in §4.1). |
| `response_ms` | intero | Tempo di risposta interno del check in millisecondi. |
| `message` | stringa \| null | Messaggio descrittivo opzionale. |
| `details` | stringa (JSON serializzato) | Dettaglio strutturato serializzato come stringa. |

### 4.1 Valori di `status`

I requisiti forniscono l'esempio `ok`. Pulse tratta `status` come **stringa a dominio aperto** e riconosce, per la logica di colorazione/notifica, i seguenti valori normalizzati: `ok`, `warn`, `error`, `down`, `unknown`. Valori non riconosciuti sono trattati come `unknown`. Vedi QUESTIONI APERTE §12.

### 4.2 Un sistema, N check

Poiché un sistema espone più check, `GET /api/heartbeat` può restituire **un singolo oggetto** o un **array** di oggetti conformi allo schema (uno per check). La Probe indicizza ciascun oggetto come documento distinto su OpenSearch. Vedi QUESTIONI APERTE §12.

### 4.3 Stato di connettività (aggiunto dalla Probe)

Oltre allo `status` applicativo, la Probe registra l'esito della chiamata HTTP verso il sistema (raggiungibilità, codice HTTP, latenza di rete, timeout). Se il sistema è irraggiungibile, la Probe genera un documento con stato di connettività `unreachable` e status normalizzato `down`. I campi aggiunti dalla Probe (`probe_id`, `ingested_at`, `reachable`, `http_status`, `latency_ms`) sono definiti nel modello dati (`docs/database/DOCUMENTO_DATABASE.md`).

---

## 5. Aree funzionali

### 5.1 Autenticazione
- Login con username/password.
- Emissione token di accesso (short-lived) e refresh token.
- Refresh e logout (revoca refresh token).
- Cambio password propria.
- Blocco account dopo N tentativi falliti (configurabile).

### 5.2 Autorizzazione (RBAC)
- Ogni operazione è protetta da un permesso granulare.
- Utente → uno o più ruoli → insieme di permessi.
- Ruoli predefiniti non eliminabili + ruoli personalizzati.
- Dettaglio in `06_rbac.md`.

### 5.3 Gestione utenti
- CRUD utenti, abilitazione/disabilitazione, assegnazione ruoli, reset password.
- Un utente non può eliminare/disabilitare sé stesso (evita lock-out); almeno un Super Amministratore attivo deve sempre esistere.

### 5.4 Gestione ruoli
- CRUD ruoli personalizzati, assegnazione permessi ai ruoli.
- I ruoli predefiniti sono in sola lettura per la struttura ma i loro assegnatari sono gestibili.

### 5.5 Gestione permessi
- I permessi sono definiti dal sistema (catalogo fisso, non creabili dall'utente).
- Consultazione del catalogo permessi e loro assegnazione ai ruoli.

### 5.6 Gestione sonde (Probe)
- Registrazione (enrollment) di una Probe: creazione definizione + credenziali/segreto di enrollment.
- CRUD definizione Probe (nome, descrizione, endpoint di query, tag/localizzazione, stato abilitazione).
- Rotazione credenziali/chiavi della Probe.
- Visualizzazione stato/liveness di ciascuna Probe (online/offline, ultimo contatto, versione).
- Assegnazione dei sistemi monitorati a una Probe.

### 5.7 Gestione sistemi monitorati
- CRUD sistemi monitorati: `system_id`, nome, URL base/endpoint heartbeat, intervallo di polling, timeout, Probe assegnata, abilitazione, soglie (es. soglia `response_ms`), finestre di manutenzione.
- Consultazione dei check scoperti per ciascun sistema (derivati dagli heartbeat).
- Distribuzione della configurazione: la Probe scarica dal Server i sistemi a lei assegnati.

### 5.8 Dashboard e consultazione
- **Dashboard aggregata (Server)**: stato complessivo di tutte le Probe e sistemi, KPI, allarmi attivi.
- **Selezione Probe (Server)**: scelta di una Probe per drill-down sui suoi sistemi/check.
- **Dashboard Probe**: stato completo dei sistemi monitorati dalla singola Probe.
- **Grafici**: serie temporali di `response_ms`, disponibilità (uptime %), distribuzione stati, timeline eventi.
- **Interrogazione diretta OpenSearch**: query filtrata (per sistema, check, intervallo temporale, stato) sui dati della Probe.

### 5.9 Gestione notifiche
- CRUD canali notifica per tipo (Email, Telegram, WhatsApp) con parametri specifici.
- Test di invio su un canale.
- Storico invii (delivery log) con esito.
- Abilitazione ricezione comandi per i canali che la supportano (§5.11).

### 5.10 Gestione workflow notifiche
- CRUD workflow completamente configurabili: trigger/evento, condizioni, azioni per canale, escalation, throttling, finestre attive.
- Abilitazione/disabilitazione workflow.
- Dettaglio in `07_workflow_notifiche.md`.

### 5.11 Ricezione comandi dai canali
- Associazione identità di canale (es. chat_id Telegram) ↔ utente Pulse.
- Esecuzione di comandi consentiti (es. stato sistema, silenziamento allarme) previa autorizzazione RBAC dell'utente associato.
- Matrice di fattibilità per canale in `07_workflow_notifiche.md`.

### 5.12 Audit log
- Registrazione immutabile di: login/logout, modifiche a utenti/ruoli/permessi/probe/sistemi/canali/workflow/configurazione, esecuzione comandi, invii notifica.
- Consultazione filtrata (attore, azione, entità, intervallo temporale).

### 5.13 Log di sistema
- Log tecnici/applicativi di Server e Probe (livello, componente, messaggio, timestamp).
- Consultazione filtrata; livello di log configurabile.

### 5.14 Configurazione
- Parametri globali del Server (porta dedicata Probe, policy password, TTL token, SMTP di default, soglie predefinite, livello log, ecc.).
- Configurazione locale della Probe (endpoint Server, credenziali, intervallo di sincronizzazione, parametri OpenSearch).

### 5.15 Healthcheck
- Endpoint di liveness/readiness per Server e Probe (uso operativo/orchestrazione container).

---

## 6. Comunicazione Server ↔ Probe (vista funzionale)

- Il **Server espone endpoint dedicati** su una **porta configurabile nota alle Probe**.
- La **Probe** (client) verso il Server:
  1. **Enrollment/registrazione** con segreto di enrollment.
  2. **Pull della configurazione** (sistemi assegnati + parametri di polling).
  3. **Push di liveness/stato** della Probe (heartbeat della Probe stessa).
  4. **Push di eventi** (cambi di stato/connettività) per l'attivazione dei workflow.
  5. **Push di rollup** aggregati per la dashboard del Server.
- Il **Server** verso la **Probe** (per drill-down su selezione Probe): **query** ai dati OpenSearch della Probe tramite l'API di query della Probe.
- Tutta la comunicazione è **cifrata** (meccanismo scelto e motivato in `02_specifica_tecnica.md`).

Le decisioni su direzione dei flussi e raggiungibilità sono documentate in QUESTIONI APERTE §12 e in `03_architettura.md`.

---

## 7. Regole di business principali

1. Un sistema monitorato appartiene a **esattamente una** Probe.
2. Gli heartbeat/serie temporali risiedono **solo** su OpenSearch della Probe; il Server **non** archivia la serie temporale grezza (usa rollup + query on-demand).
3. Deve sempre esistere **almeno un Super Amministratore attivo**.
4. I permessi sono un **catalogo fisso**; non sono creabili a runtime.
5. Ogni azione che modifica lo stato del sistema produce **una voce di audit**.
6. L'invio di una notifica è governato **esclusivamente** da un workflow abilitato.
7. Un comando in ingresso è eseguito solo se l'identità di canale è associata a un utente con il permesso richiesto.
8. Le finestre di manutenzione sospendono la generazione di allarmi/notifiche per i sistemi interessati.

---

## 8. Requisiti non funzionali (sintesi)
Dettaglio e numerazione in `05_requisiti.md`. In sintesi: sicurezza (cifratura, RBAC, audit), performance (polling scalabile, query efficienti), disponibilità (Probe indipendenti dal Server per il monitoraggio locale), osservabilità (log/audit/health), portabilità (Docker/Podman).

---

## 9. Vincoli
- Backend Python + FastAPI; Frontend Python + Flask.
- DB Probe: OpenSearch (locale a ciascuna Probe).
- DB Server: scelto dal DBA (modello logico in `docs/database/DOCUMENTO_DATABASE.md`).
- Probe eseguite come container Docker/Podman.
- Documentazione in italiano.

---

## 10. Fuori ambito (esplicitamente escluso)
- Provisioning/gestione dei sistemi monitorati stessi (Pulse li osserva, non li amministra).
- APM/tracing distribuito applicativo (Pulse monitora heartbeat, non traccia transazioni interne).
- Qualsiasi funzionalità non elencata nei requisiti (nessuna feature extra).

---

## 11. Tracciabilità
Ogni area funzionale è tracciata su requisiti (`05_requisiti.md`), casi d'uso (`04_casi_uso.md`), endpoint API (`docs/api/DOCUMENTO_API.md`) ed entità dati (`docs/database/DOCUMENTO_DATABASE.md`).

---

## 12. QUESTIONI APERTE / DECISIONI

| # | Tema | Decisione presa | Motivazione | Da confermare a |
|---|---|---|---|---|
| QA-01 | Valori ammessi di `status` | Dominio aperto con normalizzazione a {ok, warn, error, down, unknown} | I requisiti mostrano solo `ok`; non è dato l'enum completo. Dominio aperto evita perdita di dati; la normalizzazione serve solo a UI/notifiche. | Committente |
| QA-02 | `GET /api/heartbeat`: singolo oggetto o array | Supportare entrambi; ogni check → 1 documento OpenSearch | Un sistema ha N check ma lo schema mostra un singolo oggetto. | Committente / BE |
| QA-03 | Direzione query Server→Probe (raggiungibilità) | Query diretta Server→Probe su canale cifrato; assunzione: Probe raggiungibile dal Server | Il Server deve leggere dati di dettaglio per il drill-down. Se le Probe fossero dietro NAT servirebbe un canale inverso. | BE / Committente |
| QA-04 | Contenuto di `details` | Trattato come stringa JSON opaca; indicizzato anche come oggetto parsato ove valido | Lo schema lo definisce stringa; il parsing abilita query sui `metrics`. | BE / DBA |
| QA-05 | Comandi in ingresso via Email/WhatsApp | Vedi matrice in `07_workflow_notifiche.md` | Fattibilità e sicurezza differiscono per canale. | Committente |
