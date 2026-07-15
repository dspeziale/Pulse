# Pulse — Casi d'Uso

Documento: `04_casi_uso.md`
Autore: AGENTE 1 — ANALISTA
Data: 2026-07-15

Convenzioni: ogni caso d'uso ha ID `UC-##`, attori, precondizioni, flusso base, flussi alternativi/eccezioni, postcondizioni. I permessi citati sono definiti in `06_rbac.md`; gli endpoint in `docs/api/DOCUMENTO_API.md`.

Indice aree: Autenticazione (UC-01..03), Utenti (UC-10..14), Ruoli/Permessi (UC-20..23), Probe (UC-30..35), Sistemi monitorati (UC-40..44), Dashboard/Consultazione (UC-50..54), Notifiche/Canali (UC-60..64), Workflow (UC-70..73), Comandi in ingresso (UC-80..81), Audit/Log (UC-90..91), Configurazione (UC-95).

---

## Area: Autenticazione

### UC-01 — Login
- **Attori**: qualsiasi utente.
- **Precondizioni**: utente esistente e attivo.
- **Flusso base**: 1) l'utente inserisce username/password; 2) il sistema verifica le credenziali; 3) genera access + refresh token; 4) registra audit login; 5) l'utente accede alla dashboard secondo i propri permessi.
- **Alternativi/eccezioni**: A1 credenziali errate → 401, incrementa contatore tentativi, audit fallimento; A2 account bloccato/disabilitato → 403; A3 troppi tentativi → blocco temporaneo secondo policy.
- **Postcondizioni**: sessione attiva.

### UC-02 — Refresh / Logout
- **Attori**: utente autenticato.
- **Precondizioni**: refresh token valido (per refresh); sessione attiva (per logout).
- **Flusso base (refresh)**: presenta refresh token → riceve nuovo access token. **Logout**: revoca refresh token → sessione terminata + audit.
- **Eccezioni**: refresh token scaduto/revocato → 401, forza re-login.

### UC-03 — Cambio password propria
- **Attori**: utente autenticato (`profile.update`).
- **Flusso base**: fornisce password attuale + nuova; validazione policy; aggiorna hash; audit.
- **Eccezioni**: password attuale errata → 400; nuova non conforme a policy → 422.

---

## Area: Gestione Utenti

### UC-10 — Elenca utenti
- **Attori**: Super Admin, Admin (`users.read`).
- **Flusso base**: elenco paginato/filtrabile per stato, ruolo, testo.

### UC-11 — Crea utente
- **Attori**: Super Admin, Admin (`users.create`).
- **Precondizioni**: username/email univoci.
- **Flusso base**: inserisce dati + ruoli iniziali; sistema crea utente, imposta credenziali iniziali; audit.
- **Eccezioni**: username/email duplicati → 409; dati invalidi → 422.

### UC-12 — Modifica utente
- **Attori** (`users.update`): aggiorna anagrafica/stato. **Eccezione**: non è consentito auto-disabilitarsi; deve restare ≥1 Super Admin attivo.

### UC-13 — Elimina/disabilita utente
- **Attori** (`users.delete`): elimina o disabilita. **Eccezioni**: ultimo Super Admin → 409 rifiuto; auto-eliminazione → vietata.

### UC-14 — Assegna ruoli / reset password
- **Attori** (`users.assign_roles` per ruoli; `users.update` per reset): assegna/rimuove ruoli; forza reset password; audit.

---

## Area: Ruoli e Permessi

### UC-20 — Elenca ruoli e permessi
- **Attori**: Super Admin, Admin (`roles.read`, `permissions.read`).
- **Flusso base**: elenco ruoli con permessi associati; catalogo permessi in sola lettura.

### UC-21 — Crea ruolo
- **Attori**: Super Admin (`roles.create`): nome univoco + descrizione; audit. **Eccezione**: nome duplicato → 409.

### UC-22 — Modifica/elimina ruolo
- **Attori**: Super Admin (`roles.update`/`roles.delete`). **Eccezioni**: ruolo predefinito → struttura non modificabile/eliminabile (409); ruolo assegnato a utenti → richiede riassegnazione o blocco eliminazione.

### UC-23 — Assegna permessi a un ruolo
- **Attori**: Super Admin (`roles.assign_permissions`): seleziona permessi dal catalogo; audit. Effetto immediato sugli utenti del ruolo.

---

## Area: Gestione Sonde (Probe)

### UC-30 — Elenca Probe e stato
- **Attori**: Admin, Operatore, Viewer (`probes.read`).
- **Flusso base**: elenco Probe con stato (online/offline, ultimo contatto, versione, n. sistemi).

### UC-31 — Registra (enrolla) una Probe
- **Attori**: Admin (`probes.create`).
- **Flusso base**: crea definizione Probe; sistema genera token di enrollment monouso; l'operatore configura la Probe (container) con token + endpoint Server; la Probe chiama `POST /api/v1/probe/register`, riceve identità/credenziali/certificato; passa a stato "in attesa primo contatto".
- **Eccezioni**: token scaduto/riutilizzato → 401; nome duplicato → 409.

### UC-32 — Modifica Probe
- **Attori**: Admin (`probes.update`): aggiorna nome, descrizione, endpoint query, tag, abilitazione. Audit.

### UC-33 — Elimina Probe
- **Attori**: Admin (`probes.delete`). **Eccezione**: Probe con sistemi assegnati → richiede riassegnazione/rimozione sistemi prima (409). Revoca credenziali/certificato.

### UC-34 — Ruota credenziali Probe
- **Attori**: Admin (`probes.rotate_key`): genera nuovo `probe_secret`/certificato, revoca il precedente; la Probe si ri-autentica; audit.

### UC-35 — Consulta stato/liveness Probe
- **Attori** (`probes.read`): dettaglio ultimo contatto, esiti sincronizzazione, errori. Deriva dai push di liveness della Probe.

---

## Area: Gestione Sistemi Monitorati

### UC-40 — Elenca sistemi
- **Attori** (`systems.read`): elenco filtrabile per Probe, stato, testo.

### UC-41 — Crea sistema monitorato
- **Attori**: Admin, Operatore (`systems.create`).
- **Precondizioni**: `system_id` univoco; Probe assegnataria esistente.
- **Flusso base**: inserisce `system_id`, nome, URL endpoint heartbeat, intervallo polling, timeout, soglie, Probe assegnata, finestre manutenzione; la Probe scaricherà la nuova configurazione al successivo pull; audit.
- **Eccezioni**: `system_id` duplicato → 409; URL/intervallo invalidi → 422.

### UC-42 — Modifica sistema
- **Attori** (`systems.update`): aggiorna parametri; effetto al prossimo pull config della Probe.

### UC-43 — Elimina sistema
- **Attori** (`systems.delete`): rimuove definizione; la Probe cessa il polling al prossimo pull. I dati storici restano su OpenSearch (retention). Audit.

### UC-44 — Consulta check scoperti di un sistema
- **Attori** (`checks.read`): elenco check (`check_id`/`check_name`) osservati negli heartbeat del sistema.

---

## Area: Dashboard e Consultazione

### UC-50 — Dashboard aggregata (Server)
- **Attori**: Admin, Operatore, Viewer (`dashboard.read`).
- **Flusso base**: vista d'insieme di Probe e sistemi con KPI (disponibilità, allarmi attivi, latenze), basata sui rollup. Aggiornamento periodico.

### UC-51 — Selezione Probe e drill-down (Server)
- **Attori** (`dashboard.read` + `heartbeats.read`).
- **Flusso base**: seleziona Probe → il Server interroga la Probe → mostra sistemi/check/serie temporali. **Eccezione**: Probe offline/irraggiungibile → messaggio + eventuale ultimo rollup disponibile.

### UC-52 — Dashboard Probe (locale)
- **Attori** (`dashboard.read`, `heartbeats.read`): dashboard completa dei sistemi della singola Probe (via UI Probe o via Server).

### UC-53 — Interrogazione diretta OpenSearch
- **Attori** (`heartbeats.query`).
- **Flusso base**: definisce query (sistema, check, intervallo, stato, soglie) → risultati tabellari/grafici. **Eccezione**: query malformata → 400; timeout → messaggio.

### UC-54 — Grafici serie temporali
- **Attori** (`heartbeats.read`): visualizza andamento `response_ms`, uptime %, distribuzione stati, timeline eventi per sistema/check.

---

## Area: Notifiche e Canali

### UC-60 — Elenca canali
- **Attori**: Admin, Operatore (`notifications.read`).

### UC-61 — Crea canale (Email/Telegram/WhatsApp)
- **Attori** (`notifications.create`).
- **Flusso base**: seleziona tipo, inserisce parametri (SMTP/mittente; token bot/chat; credenziali WhatsApp/template); abilita eventuale ricezione comandi; audit (segreti mascherati).
- **Eccezioni**: parametri mancanti/invalidi → 422.

### UC-62 — Modifica/elimina canale
- **Attori** (`notifications.update`/`notifications.delete`). **Eccezione**: canale usato da workflow → avviso/blocco eliminazione (409).

### UC-63 — Test invio su canale
- **Attori** (`notifications.test`): invia messaggio di prova; mostra esito; audit.

### UC-64 — Storico invii
- **Attori** (`notifications.read`): elenco invii con canale, destinatario, workflow, esito, timestamp.

---

## Area: Workflow Notifiche

### UC-70 — Elenca workflow
- **Attori**: Admin, Operatore (`workflows.read`).

### UC-71 — Crea workflow
- **Attori** (`workflows.create`).
- **Flusso base**: definisce nome, trigger/evento, ambito (probe/sistemi/check), condizioni, azioni per canale con template e destinatari, escalation, throttling, finestre attive; abilita; audit. Dettaglio modello in `07_workflow_notifiche.md`.
- **Eccezioni**: riferimenti a canali inesistenti → 422; condizioni incoerenti → 422.

### UC-72 — Modifica/elimina workflow
- **Attori** (`workflows.update`/`workflows.delete`): modifica configurazione; abilita/disabilita; elimina; audit.

### UC-73 — Simulazione/verifica workflow (dry-run)
- **Attori** (`workflows.update`): valuta un evento campione contro il workflow senza inviare; mostra match/azioni previste. (Nota: funzione di supporto, vedi QUESTIONI APERTE.)

---

## Area: Comandi in Ingresso

### UC-80 — Associa identità di canale a utente
- **Attori**: utente (`commands.execute`) o Admin.
- **Flusso base**: l'utente collega la propria identità di canale (es. chat_id Telegram) all'account Pulse tramite codice di verifica; audit.
- **Eccezioni**: codice errato/scaduto → 400; identità già associata → 409.

### UC-81 — Esegui comando da canale
- **Attori**: utente di canale associato (`commands.execute` + permesso dell'operazione richiesta).
- **Flusso base**: invia comando (es. `/status`, `/silence`); il webhook verifica segreto, risolve identità → utente, verifica permessi, esegue, risponde sul canale; audit.
- **Eccezioni**: identità non associata → rifiuto; permesso mancante → rifiuto + audit; comando non supportato dal canale → messaggio (vedi matrice `07_workflow_notifiche.md`).

---

## Area: Audit e Log di Sistema

### UC-90 — Consulta audit log
- **Attori**: Super Admin, Admin, Auditor (`audit.read`).
- **Flusso base**: elenco filtrabile per attore, azione, entità, esito, intervallo; sola lettura (immutabile).

### UC-91 — Consulta log di sistema
- **Attori**: Super Admin, Admin, Auditor (`syslog.read`).
- **Flusso base**: elenco filtrabile per componente (Server/Probe), livello, intervallo, testo.

---

## Area: Configurazione

### UC-95 — Gestione configurazione
- **Attori**: Super Admin, Admin (`config.read`/`config.update`).
- **Flusso base**: consulta e aggiorna parametri (porta dedicata Probe, policy password, TTL token, default SMTP, soglie, livello log, retention); validazione; audit. **Eccezione**: valore invalido → 422; parametro che richiede riavvio → segnalazione.

---

## QUESTIONI APERTE / DECISIONI

| # | Tema | Decisione | Motivazione |
|---|---|---|---|
| UC-QA-01 | Dry-run workflow (UC-73) | Incluso come funzione di supporto opzionale | Riduce errori di configurazione; non altera stato/invii. Da confermare priorità. |
| UC-QA-02 | Reset password: self-service via email | Non incluso (nessun requisito esplicito) | Solo reset amministrativo (UC-14). Da valutare col committente. |
| UC-QA-03 | Comandi disponibili via canale | Insieme minimo: `/status`, `/silence`, `/help` | Dettaglio e limiti per canale in `07_workflow_notifiche.md`. |
