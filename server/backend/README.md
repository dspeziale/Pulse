# Pulse — Server backend (FastAPI)

Backend del **Server centrale** di Pulse. Implementa la sezione BACKEND del
`docs/api/DOCUMENTO_API.md` sopra lo schema PostgreSQL 16 del DBA
(`deploy/schema.sql` + `deploy/seed.sql`).

## Stack

- Python 3.12+ / FastAPI / SQLAlchemy 2.0 (ORM sync) / psycopg 3
- Pydantic v2 per request/response, JWT (PyJWT), bcrypt, Fernet (cifratura segreti a riposo)
- Documentazione OpenAPI su `/api/v1/docs` (Swagger) e `/api/v1/redoc`

## Struttura

```
pulse_server/
  main.py            factory FastAPI + registrazione router
  config.py          impostazioni via env (prefisso PULSE_)
  db.py              engine/session SQLAlchemy
  models.py          ORM mappato 1:1 sullo schema fisico (nessuna ridefinizione)
  schemas.py         modelli Pydantic v2 (contratto API)
  serializers.py     ORM -> schema di risposta
  security.py        bcrypt, JWT, token opachi, Fernet, HMAC
  deps.py            autenticazione + RBAC (require_permission)
  errors.py          formato errore standard + exception handler
  audit.py           scrittura audit_log e system_logs
  notifications.py   provider Email/Telegram/WhatsApp + cifratura config
  workflow.py        motore workflow (trigger/scope/condizioni/soppressione/allarmi)
  commands.py        esecuzione comandi in ingresso dai canali
  proxy.py           client Server->Probe (drill-down heartbeat/query)
  context.py         provider SecretBox / ProbeQueryClient
  routers/           un modulo per area del DOCUMENTO_API
```

## Configurazione

Tutte le variabili hanno prefisso `PULSE_` (vedi `.env.example`). Le principali:

| Variabile | Default | Note |
|---|---|---|
| `PULSE_DATABASE_URL` | `postgresql+psycopg://pulse:pulse@localhost:5432/pulse` | DB Server |
| `PULSE_API_PORT` | `8443` | porta applicativa |
| `PULSE_JWT_SECRET` | (placeholder) | **impostare in produzione** |
| `PULSE_ACCESS_TOKEN_TTL_SECONDS` | `900` | durata access token |
| `PULSE_REFRESH_TOKEN_TTL_SECONDS` | `1209600` | durata refresh token |
| `PULSE_SECRETS_ENCRYPTION_KEY` | derivata da JWT_SECRET | chiave Fernet segreti canali |
| `PULSE_PROBE_QUERY_TOKEN` | `server-to-probe-token` | token verso la API di query Probe |
| `PULSE_TLS_*` | vuoto | path certificati mTLS (vedi Sicurezza) |

I parametri runtime (TTL, soglie, retention) sono anche nella tabella
`configuration` e modificabili via `PUT /api/v1/config`.

## Avvio locale

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# DB: usa il compose del DBA
docker compose -f ../../deploy/docker-compose.yml up -d
export PULSE_DATABASE_URL=postgresql+psycopg://pulse:pulse@localhost:5432/pulse
uvicorn pulse_server.main:app --host 0.0.0.0 --port 8443
```

Login iniziale (seed): utente `admin`, password `ChangeMe123!` (**cambiarla al primo accesso**).

## Docker

```bash
docker build -t pulse-server-backend .
docker run -p 8443:8443 --env-file .env pulse-server-backend
```

Lo stack completo (postgres + backend + dashboard FE) è in
`deploy/docker-compose.server.yml`.

## Test e coverage

```bash
pip install -r requirements-dev.txt
pytest --cov=pulse_server --cov-report=term-missing
```

I test avviano automaticamente un container PostgreSQL 16 effimero via Docker
(porta host `5433`, override con `PULSE_TEST_PG_PORT`) e applicano
`deploy/schema.sql` + `deploy/seed.sql`. Ogni test gira in una transazione con
savepoint e viene annullato al termine (isolamento senza perdere il seed).
In alternativa impostare `PULSE_TEST_DATABASE_URL` per puntare a un DB esistente.

**Coverage reale raggiunta: 98%** (181 test). Le righe residue non coperte sono
rami difensivi/di I/O (lettura file certificato CA in `/probe/register`, provider
`ProbeQueryClient` istanziato solo in produzione, combinazioni di filtri
ridondanti, casi "ultimo SuperAdmin" raggiungibili solo con più SuperAdmin
attivi simultanei). Nessun test è saltato o fallito.

## Sicurezza Server↔Probe (mTLS)

- **Livello applicativo (implementato)**: token opaco per-Probe (hash SHA-256 in
  `probes.token_hash`), enrollment monouso a scadenza (`enrollment_tokens`),
  rotazione via `POST /probes/{id}/rotate-credentials`. Il Server presenta a sua
  volta un token alla API di query della Probe (`PULSE_PROBE_QUERY_TOKEN`).
- **Livello di trasporto (mTLS)**: si attiva fornendo i certificati e terminando
  il TLS su uvicorn/reverse proxy. Per abilitarlo:
  1. generare CA interna, certificati server e client (per-Probe);
  2. montare i file e impostare `PULSE_TLS_CA_CERT_PATH`,
     `PULSE_TLS_SERVER_CERT_PATH`, `PULSE_TLS_SERVER_KEY_PATH`,
     `PULSE_PROBE_CLIENT_CERT_PATH`, `PULSE_PROBE_CLIENT_KEY_PATH`;
  3. avviare uvicorn con `--ssl-keyfile/--ssl-certfile --ssl-ca-certs` e
     `--ssl-cert-reqs 2` (CERT_REQUIRED) oppure delegare a un reverse proxy mTLS.
  Il `ca_certificate` viene restituito alla Probe in fase di `/probe/register`.

## Comportamento provider notifiche

I provider Email (SMTP), Telegram (Bot API) e WhatsApp (Business API) effettuano
invii reali quando la config del canale contiene credenziali valide. In test o
senza credenziali, l'invio fallisce in modo controllato e viene registrato in
`notification_deliveries` con stato `failed` (nessuna eccezione propagata). I
segreti sono cifrati a riposo (Fernet) e mascherati (`********`) nelle risposte API.

## SCOSTAMENTI rilevati rispetto al DOCUMENTO_API / schema

Da segnalare all'Analista/QA (nessuna invenzione: scelte coerenti col DB reale):

1. **Conteggio permessi**: il DOCUMENTO_API/06_rbac citano "37 permessi" ma il
   catalogo enumerato e il `seed.sql` contengono **40** codici. È stato adottato
   il catalogo reale del seed (autoritativo) — 40 permessi. Già segnalato dal DBA (I-1).
2. **`POST /probes/{id}/rotate-credentials`**: l'API descrive "rigenera
   secret/certificato". Lo schema non prevede storage del certificato client
   emesso; l'implementazione rigenera il **token per-Probe** (revoca il precedente)
   ed emette un nuovo token di enrollment, riportando la Probe a `pending`
   (re-enroll). L'emissione del certificato X.509 è demandata al livello PKI/mTLS.
3. **`GET /probes/{id}/heartbeats` e `POST /probes/{id}/query`**: sono **proxy**
   verso la API di query della Probe (API-02). Se la Probe non ha
   `query_endpoint` configurato o è irraggiungibile, viene restituito `503`.
4. **`test` canale**: l'esito viene sempre riportato con `200` e
   `delivered: true|false` (invece di `503` su errore provider) per dare alla UI
   un feedback uniforme; l'errore provider è nel campo `detail`.
5. **`channel-identities`**: la verifica del `verification_code` è strutturale
   (non vuoto) in assenza di un canale di distribuzione del codice; l'aggancio a
   un codice inviato realmente è un TODO lato workflow di verifica.
6. **Log Probe verso Server (`system_logs`)**: la tabella è pronta e interrogabile
   via `GET /logs`; l'ingest dei log Probe avviene tramite i push di
   liveness/eventi (API-03). Non esiste un endpoint dedicato di ingest log nel
   DOCUMENTO_API: coerente con la scelta dell'Analista.
```
