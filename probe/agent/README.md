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
| GET | `/status` | token Server | stato interno (poller, OpenSearch, coda eventi) |
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

## Sicurezza

- Token del Server verificato in tempo costante (`hmac.compare_digest`).
- Token per-Probe verso il Server via Bearer; mTLS attivabile fornendo
  `PULSE_PROBE_TLS_CA_CERT_PATH`, `PULSE_PROBE_TLS_CLIENT_CERT_PATH`,
  `PULSE_PROBE_TLS_CLIENT_KEY_PATH` e terminando il TLS su uvicorn/reverse proxy.
- La query è **strutturata** (non DSL raw): nessuna query arbitraria contro
  OpenSearch (API-01).
```
