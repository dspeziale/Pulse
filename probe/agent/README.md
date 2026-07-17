# Pulse — Probe agent (FastAPI)

Agent della **Probe**: interroga periodicamente gli heartbeat dei sistemi
assegnati, li indicizza su **OpenSearch locale**, espone le **API di query**
strutturata (interrogate dal Server per il drill-down) e comunica col Server
centrale (enrollment, pull config, liveness, eventi, rollup).

Aderente al `docs/api/DOCUMENTO_API.md` (endpoint Probe §1.9) e allo schema
canonico heartbeat (`docs/analisi/01_specifica_funzionale.md` §4).

## Stack

- Python 3.12+ / FastAPI / httpx / opensearch-py / Pydantic v2
- OpenAPI su `/api/v1/docs` e `/api/v1/redoc`

## Endpoint (base `/api/v1`)

| Metodo | Path | Auth | Descrizione |
|---|---|---|---|
| GET | `/query/heartbeats` | token Server | query filtrata su OpenSearch locale |
| POST | `/query` | token Server | query strutturata avanzata (filtri + aggregazioni) |
| GET | `/systems` | token Server | sistemi attualmente monitorati (config effettiva) |
| GET | `/status` | token Server | stato interno (poller, OpenSearch, coda eventi, `nmap_available`) |
| POST | `/scan` | token Server | avvia una scansione NMAP (ritorna `scan_id`, `status:running`) |
| GET | `/scans` | token Server | elenco scansioni (paginato) |
| GET | `/scan/{scan_id}` | token Server | dettaglio scansione (host/porte/script) |
| GET | `/health` | nessuna | liveness |
| GET | `/health/ready` | nessuna | readiness (OpenSearch/poller) |

Autenticazione: **mTLS** (livello trasporto) + **Bearer token del Server**
(`PULSE_PROBE_SERVER_QUERY_TOKEN`) a livello applicativo.

## Struttura

```
pulse_probe/
  main.py         factory FastAPI, endpoint, lifespan (bootstrap + poller loop)
  config.py       impostazioni via env (prefisso PULSE_PROBE_)
  canonical.py    parsing/normalizzazione schema canonico heartbeat (oggetto o array)
  query.py        motore di query strutturata Pulse (filtri/aggregazioni)
  store.py        storage: InMemoryStore (fallback/test) + OpenSearchStore
  poller.py       polling sistemi, rilevazione eventi, rollup, ciclo completo
  server_client.py client verso /api/v1/probe/* del Server
  state.py        stato runtime (config, ultimi stati, code, metriche)
  deps.py         auth token Server + accesso allo stato
  errors.py       formato errore standard
  schemas.py      modelli Pydantic v2
```

## Flusso operativo

1. All'avvio (lifespan): se manca `probe_token` ma è presente `enrollment_token`,
   la Probe si registra (`POST /probe/register`) ottenendo il token per-Probe;
   quindi scarica la configurazione (`GET /probe/config`).
2. Il **poller** interroga ogni sistema abilitato (`GET /api/heartbeat`), misura
   raggiungibilità/latenza, normalizza lo `status`, indicizza un documento per
   check su OpenSearch, rileva eventi (cambi stato, irraggiungibilità, recupero,
   soglia response_ms) e li invia al Server (`POST /probe/events`).
3. Periodicamente invia liveness (`POST /probe/heartbeat`) e rollup
   (`POST /probe/rollup`). Se il Server segnala un nuovo `config_version`,
   ricarica la configurazione.

## Storage OpenSearch (degradazione)

`build_store()` usa **OpenSearch** se `PULSE_PROBE_OPENSEARCH_URL` è impostato e
il cluster risponde; crea gli indici `pulse-heartbeats`/`pulse-events` con i
mapping (§5 del DOCUMENTO_DATABASE). In assenza/irraggiungibilità di OpenSearch
usa uno **storage in-memory** equivalente (semantica di query identica) — utile
in sviluppo/test e come fallback resiliente. Comportamento documentato e loggato.

## Avvio locale

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
export PULSE_PROBE_SERVER_BASE_URL=https://localhost:9443
export PULSE_PROBE_ENROLLMENT_TOKEN=<token dal Server>
uvicorn pulse_probe.main:app --host 0.0.0.0 --port 8444
```

## Docker

```bash
docker build -t pulse-probe-agent .
docker run -p 8444:8444 --env-file .env pulse-probe-agent
```

Stack completo (opensearch + probe-agent + dashboard FE) in
`deploy/docker-compose.probe.yml`.

## Test e coverage

```bash
pip install -r requirements-dev.txt
pytest --cov=pulse_probe --cov-report=term-missing
```

I test usano lo storage in-memory e `httpx.MockTransport` (nessuna rete, nessun
OpenSearch reale). **Coverage reale: 100%** (72 test) — statement + branch.
Escluse con `# pragma: no cover` motivato solo le righe eseguibili unicamente a
runtime: il loop periodico del poller (`_poller_loop`), l'avvio del task del
poller e il suo annullamento allo shutdown, e il backend `OpenSearchStore` (che
richiede un cluster OpenSearch reale; la logica di query è testata al 100% via
`InMemoryStore`, che ne condivide il motore). `mypy --strict` pulito.

## Scansioni NMAP (eseguite dalla Sonda)

La Sonda può eseguire scansioni **nmap** verso un IP/hostname/subnet e salvare i
risultati su OpenSearch locale (indice `pulse-nmap-scans`), interrogabili via API.

- `POST /api/v1/scan` avvia una scansione in background e ritorna
  `{scan_id, status:"running", started_at, target}`.
- `GET /api/v1/scans?page=&page_size=` elenca le scansioni (riepilogo).
- `GET /api/v1/scan/{scan_id}` ritorna il dettaglio (host, porte, servizi,
  script NSE, OS match, hostscript) o **404** se assente.

Contratto opzioni (body `POST /scan`, stesso usato dal FE):

```json
{ "target": "192.168.1.0/24 10.0.0.5", "timing": "T3",
  "technique": "connect|syn|udp|ping", "ports": "22,80,443", "top_ports": 100,
  "service_version": true, "version_intensity": 5, "os_detection": false,
  "no_ping": false, "scripts": ["default","http-title"], "script_args": "user=x",
  "min_rate": 100, "max_rate": 1000, "max_retries": 2, "extra": "-A --reason" }
```

### Sicurezza dell'esecuzione (argv, mai shell)

- nmap è invocato con **argv come lista** (`subprocess.run([...], shell=False)`):
  nessun input utente raggiunge una shell.
- Ogni parametro è validato con **whitelist/regex** (target IP/host/CIDR;
  `ports` `^[0-9,\-]+$`; `technique`/`timing` enum; `scripts` `^[A-Za-z0-9_\-.\*]+$`
  senza slash/percorsi; `extra` tokenizzato e confrontato con una **allowlist** di
  flag sicure). Un valore non ammesso → **422**.
- I **target che iniziano con `-` sono rifiutati** (previene l'argument injection,
  es. un target `-oX` che nmap interpreterebbe come flag di output su file).
- L'output XML è **forzato** su stdout (`-oX -`); le flag di output/lettura file
  (`-oN/-oX/-oG/-oA`, `-iL`, `--datadir`, `-e`, `--interactive`, `--script` con
  percorsi) **non sono in allowlist** e vengono rifiutate.
- Timeout per scansione: `PULSE_PROBE_SCAN_TIMEOUT` (default **1800s**, cap 3600).
  Concorrenza massima: `PULSE_PROBE_SCAN_MAX_CONCURRENCY` (default 2).

Esempio di argv generato (`technique=syn`, `top_ports=100`, `-sV`):
`["nmap","-sS","-T3","--top-ports","100","-sV","-oX","-","10.0.0.5"]`.

### NMAP in container (Windows/Docker Desktop)

L'immagine installa `nmap` e applica
`setcap cap_net_raw,cap_net_admin+eip /usr/bin/nmap`, così l'utente **non-root**
può eseguire scansioni RAW. Nei compose della Sonda il servizio `probe-agent`
dichiara `cap_add: [NET_RAW, NET_ADMIN]`.

- **Docker Desktop (Windows)** esegue i container in una VM **WSL2**: `cap_add`
  e `setcap` **sono onorati**, quindi SYN/UDP/OS scan (`-sS`/`-sU`/`-O`)
  funzionano se le capabilities sono presenti.
- **Senza** privilegi RAW funzionano comunque: **connect scan** (`-sT`), `-sV`,
  **ping** (`-sn`), **NSE** e la scansione delle **porte**. SYN/UDP/OS scan
  falliscono con un errore chiaro ("richiede privilegi/CAP_NET_RAW").
- **Target instradabili/esterni** (host applicativi, IP pubblici) sono
  raggiungibili dal container tramite il **NAT della VM**.
- **Scansione della LAN FISICA dell'host Windows**: Docker Desktop **non** espone
  la LAN dell'host al container come avviene su Linux (niente `network_mode: host`
  reale). Per scansionare una rete fisica conviene installare la **Sonda su un
  host Linux appartenente alla rete target** (dove `cap_add` + host networking
  danno accesso diretto al segmento), oppure predisporre una **rete dedicata**
  instradabile verso il container. Questo è un limite dell'ambiente di rete, non
  del motore di scansione.
- Il campo `nmap_available` (e `nmap_version`) in `GET /api/v1/status` riporta il
  **self-check** eseguito all'avvio (nmap presente nel container e sua versione).

## Sicurezza

- Token del Server verificato in tempo costante (`hmac.compare_digest`).
- Token per-Probe verso il Server via Bearer; mTLS attivabile fornendo
  `PULSE_PROBE_TLS_CA_CERT_PATH`, `PULSE_PROBE_TLS_CLIENT_CERT_PATH`,
  `PULSE_PROBE_TLS_CLIENT_KEY_PATH` e terminando il TLS su uvicorn/reverse proxy.
- La query è **strutturata** (non DSL raw): nessuna query arbitraria contro
  OpenSearch (API-01).
```
