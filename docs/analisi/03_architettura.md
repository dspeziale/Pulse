# Pulse — Architettura

Documento: `03_architettura.md`
Autore: AGENTE 1 — ANALISTA
Data: 2026-07-15

Riferimenti: `01_specifica_funzionale.md`, `02_specifica_tecnica.md`, `docs/api/DOCUMENTO_API.md`, `docs/database/DOCUMENTO_DATABASE.md`.

---

## 1. Vista d'insieme

Pulse è un sistema **hub-and-spoke**: un Server centrale e N Probe. Ogni Probe è autonoma nel monitoraggio e nella persistenza locale (OpenSearch); il Server aggrega, gestisce e orchestra notifiche.

Principi architetturali:
- **Autonomia della Probe**: se il Server è irraggiungibile, la Probe continua a monitorare e archiviare localmente.
- **Sorgente unica di gestione**: utenti, ruoli, probe, sistemi, workflow gestiti sul Server.
- **Serie temporali solo su OpenSearch** delle Probe; il Server tiene rollup + query on-demand.
- **Canale cifrato** mTLS + token tra Server e Probe.

---

## 2. Diagramma dei componenti

```mermaid
graph TB
  subgraph Utenti
    U[Utente / Browser]
    CH[Utente di canale<br/>Email/Telegram/WhatsApp]
  end

  subgraph Server["SERVER CENTRALE"]
    FES[Frontend Flask<br/>Dashboard aggregata + Gestione]
    BES[Backend FastAPI]
    RBAC[Servizio RBAC/Auth]
    WF[Motore Workflow/Notifiche]
    AGG[Aggregatore rollup + Query proxy]
    REG[Registro Probe/Sistemi]
    AUD[Audit & Log]
    DBS[(DB Server<br/>motore da DBA)]
    BES --- RBAC
    BES --- WF
    BES --- AGG
    BES --- REG
    BES --- AUD
    RBAC --- DBS
    WF --- DBS
    REG --- DBS
    AUD --- DBS
    FES --> BES
  end

  subgraph ProbeN["PROBE (1..N) — Docker/Podman"]
    FEP[Frontend Flask<br/>Dashboard locale]
    BEP[Backend FastAPI]
    POLL[Poller heartbeat]
    ING[Ingestor]
    EVT[Rilevatore eventi]
    QRY[API di query]
    OS[(OpenSearch locale)]
    BEP --- POLL
    BEP --- QRY
    POLL --> ING --> OS
    POLL --> EVT
    QRY --> OS
    FEP --> BEP
  end

  subgraph Monitorati["SISTEMI MONITORATI"]
    SYS[GET /api/heartbeat]
  end

  subgraph Canali["PROVIDER CANALI"]
    SMTP[SMTP/IMAP]
    TG[Telegram Bot API]
    WA[WhatsApp Business API]
  end

  U -->|HTTPS| FES
  POLL -->|HTTP/HTTPS GET /api/heartbeat| SYS
  EVT -->|mTLS+token: eventi/rollup/liveness| BES
  BEP -->|mTLS+token: enrollment + pull config| BES
  AGG -->|mTLS+token: query drill-down| QRY
  WF -->|invio| SMTP
  WF -->|invio| TG
  WF -->|invio| WA
  CH -->|comandi| TG
  CH -->|comandi| WA
  CH -->|comandi| SMTP
  TG -->|webhook comandi| BES
  WA -->|webhook comandi| BES
  SMTP -->|inbound email| BES
```

---

## 3. Diagramma di deployment

```mermaid
graph TB
  subgraph HostServer["Host / Cluster SERVER"]
    direction TB
    cS1[Container: pulse-server-backend<br/>FastAPI :8443 app / :9443 probe-port]
    cS2[Container: pulse-server-frontend<br/>Flask]
    cS3[(DB Server<br/>motore scelto dal DBA)]
    cS1 --- cS3
    cS2 --- cS1
  end

  subgraph HostProbeA["Host Probe A — Docker/Podman"]
    cPA1[Container: pulse-probe<br/>FastAPI :8444 + Flask :8080]
    cPA2[(Container: OpenSearch :9200)]
    volA[Volume dati OpenSearch]
    cPA1 --- cPA2 --- volA
  end

  subgraph HostProbeB["Host Probe B — Docker/Podman"]
    cPB1[Container: pulse-probe]
    cPB2[(Container: OpenSearch)]
    volB[Volume dati OpenSearch]
    cPB1 --- cPB2 --- volB
  end

  subgraph Net["Rete sistemi monitorati"]
    m1[Sistema 1 /api/heartbeat]
    m2[Sistema 2 /api/heartbeat]
  end

  cPA1 -->|GET /api/heartbeat| m1
  cPB1 -->|GET /api/heartbeat| m2
  cPA1 <-->|mTLS :9443| cS1
  cPB1 <-->|mTLS :9443| cS1
  cS1 -->|mTLS query :8444| cPA1
  cS1 -->|mTLS query :8444| cPB1
  browser[Browser utente] -->|HTTPS| cS2
```

---

## 4. Sequence — Probe: polling heartbeat → OpenSearch

```mermaid
sequenceDiagram
  participant P as Probe (Poller)
  participant S as Sistema monitorato
  participant O as OpenSearch locale
  participant SRV as Server (eventi)

  loop Ogni intervallo di polling per sistema
    P->>S: GET /api/heartbeat
    alt Sistema raggiungibile
      S-->>P: 200 + heartbeat(s) [schema canonico]
      P->>P: Normalizza + arricchisce (probe_id, reachable=true, latency)
      P->>O: Index documento/i (bulk)
      P->>P: Confronta con stato precedente
    else Timeout / errore rete
      P->>P: reachable=false, status=down
      P->>O: Index documento connettività (unreachable)
    end
    opt Cambio di stato/connettività rilevato
      P->>SRV: POST /api/v1/probe/events (mTLS+token)
    end
  end
```

---

## 5. Sequence — Server → Probe: query su selezione Probe

```mermaid
sequenceDiagram
  participant U as Utente (browser)
  participant FE as Frontend Flask (Server)
  participant BE as Backend FastAPI (Server)
  participant AGG as Aggregatore/Proxy
  participant PQ as Probe API di query
  participant O as OpenSearch (Probe)

  U->>FE: Seleziona Probe X e filtri
  FE->>BE: GET /api/v1/probes/{X}/heartbeats?filtri (JWT)
  BE->>BE: AuthZ permesso heartbeats.read
  BE->>AGG: Inoltra query alla Probe X
  AGG->>PQ: GET /api/v1/query/heartbeats (mTLS+token)
  PQ->>O: Query OpenSearch
  O-->>PQ: Risultati
  PQ-->>AGG: Risultati normalizzati
  AGG-->>BE: Risultati
  BE-->>FE: 200 risultati
  FE-->>U: Rende grafici/tabelle
```

---

## 6. Sequence — Login / autenticazione

```mermaid
sequenceDiagram
  participant U as Utente
  participant FE as Frontend Flask
  participant BE as Backend FastAPI
  participant DB as DB Server

  U->>FE: Credenziali (username, password)
  FE->>BE: POST /api/v1/auth/login
  BE->>DB: Recupera utente + hash + stato
  alt Credenziali valide e utente attivo
    BE->>BE: Verifica hash, genera access+refresh token
    BE->>DB: Salva refresh token (sessione) + audit login
    BE-->>FE: 200 {access_token, refresh_token, permessi}
    FE-->>U: Sessione avviata
  else Credenziali errate
    BE->>DB: Incrementa tentativi + audit tentativo fallito
    BE-->>FE: 401 Unauthorized
    FE-->>U: Errore login
  end
```

---

## 7. Sequence — Invio notifica (workflow)

```mermaid
sequenceDiagram
  participant P as Probe
  participant BE as Backend FastAPI (Server)
  participant WF as Motore Workflow
  participant DB as DB Server
  participant CH as Canale (Email/Telegram/WhatsApp)

  P->>BE: POST /api/v1/probe/events (cambio stato)
  BE->>WF: Passa evento normalizzato
  WF->>DB: Carica workflow abilitati + condizioni
  WF->>WF: Match trigger + condizioni + finestra manutenzione + throttling
  alt Workflow applicabile
    loop Per ogni azione/step
      WF->>CH: Invia messaggio (template + destinatari)
      CH-->>WF: Esito invio
      WF->>DB: Registra delivery + audit
    end
    opt Escalation (no ack entro T)
      WF->>CH: Invia step di escalation successivo
    end
  else Nessun match / soppresso
    WF->>DB: Log evento senza notifica
  end
```

---

## 8. Sequence — Ricezione comando da canale

```mermaid
sequenceDiagram
  participant CH as Utente di canale
  participant PRV as Provider (Telegram/WhatsApp/Email)
  participant BE as Backend FastAPI (Server)
  participant DB as DB Server
  participant WF as Esecutore comandi

  CH->>PRV: Messaggio comando (es. /status myapp)
  PRV->>BE: Webhook POST /api/v1/inbound/{canale} (segreto canale)
  BE->>BE: Verifica firma/segreto webhook
  BE->>DB: Risolve identità canale -> utente Pulse
  alt Identità associata e autorizzata (permesso commands.execute + permesso op.)
    BE->>WF: Esegui comando consentito
    WF->>DB: Legge stato/esegue azione + audit
    WF-->>BE: Risultato
    BE->>PRV: Risposta al mittente
    PRV-->>CH: Messaggio di risposta
  else Identità non associata o non autorizzata
    BE->>DB: Audit tentativo comando negato
    BE->>PRV: Messaggio "non autorizzato"
    PRV-->>CH: Risposta di rifiuto
  end
```

---

## 9. Flussi dati e confini di persistenza

```mermaid
graph LR
  subgraph Probe
    HB[Heartbeat + connettività] --> OSD[(OpenSearch: serie temporali)]
  end
  subgraph Server
    RU[Rollup/snapshot] --> DBSV[(DB Server: gestione)]
    MGMT[Utenti/Ruoli/Probe/Sistemi/Workflow/Audit/Log/Config] --> DBSV
  end
  OSD -. query on-demand .-> DBSV
  HB -. eventi cambio stato .-> Server
```

Confine chiave: **la serie temporale grezza vive solo su OpenSearch delle Probe**; il Server persiste solo dati gestionali + rollup. Dettaglio entità in `docs/database/DOCUMENTO_DATABASE.md`.

---

## 10. QUESTIONI APERTE / DECISIONI

| # | Tema | Decisione | Motivazione |
|---|---|---|---|
| AR-01 | Query drill-down | Server proxy → Probe API query (mTLS) | Mantiene RBAC centralizzato e serie temporali sulle Probe. |
| AR-02 | Dashboard aggregata | Basata su rollup push dalle Probe | Evita fan-out di query a ogni caricamento pagina. |
| AR-03 | Valutazione workflow | Centralizzata sul Server su eventi ricevuti | Config unica, coerenza notifiche, storicizzazione audit. |
| AR-04 | Webhook inbound comandi | Endpoint dedicati per canale con verifica segreto | Fattibilità/sicurezza differenti per canale (vedi `07_workflow_notifiche.md`). |
| AR-05 | Deploy Server | Container o host, TLS via reverse proxy o app | Rimandato al team deploy/BE. |
