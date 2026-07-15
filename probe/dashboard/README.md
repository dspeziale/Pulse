# Pulse — Dashboard PROBE (Flask)

Frontend web **locale** della Probe. Consuma esclusivamente le API di query della
PROBE descritte nella sezione BACKEND di `docs/api/DOCUMENTO_API.md`
("Endpoint sulla PROBE", base `/api/v1`). Implementa le pagine **PP-01 … PP-05**.

## Pagine implementate (sezione FRONTEND del DOCUMENTO_API)

| Pagina | Blueprint / route | Endpoint PROBE consumati |
|---|---|---|
| PP-01 Login (locale) | `auth` (`/login`, `/logout`) | — (credenziali locali, vedi FE-02) |
| PP-02 Dashboard Probe | `dashboard` (`/dashboard`) | `GET /status`, `GET /systems`, `GET /query/heartbeats` |
| PP-03 Dettaglio sistema/check | `dashboard` (`/systems/<id>`) | `GET /query/heartbeats`, `POST /query` |
| PP-04 Interrogazione diretta | `query` (`/query`) | `POST /query` |
| PP-05 Stato Probe / Salute | `status` (`/status`) | `GET /status`, `GET /health/ready` |

Route infrastrutturali: `/` (redirect login/dashboard), `/healthz` (liveness).

## Autenticazione

- **PP-01 login locale** (decisione FE-02 / QUESTIONE APERTA API-04): la dashboard
  Probe autentica un operatore locale con credenziali da env
  (`PULSE_PROBE_DASH_USER` / `PULSE_PROBE_DASH_PASSWORD`), confronto costante nel
  tempo. Scelta per garantire operatività anche a Server irraggiungibile; non
  esiste RBAC granulare sulla Probe (sole viste di lettura dei dati locali).
- Le chiamate al **probe-agent** usano un token Bearer da env
  `PULSE_PROBE_AGENT_TOKEN` (decisione FE-03). Errori dal probe-agent
  (`401/4xx/5xx`, irraggiungibile→`503`) sono gestiti con pagina d'errore.

## Configurazione (variabili d'ambiente)

Vedi `.env.example`. Principali: `PULSE_PROBE_API_BASE` (base URL probe-agent),
`PULSE_PROBE_AGENT_TOKEN`, `PULSE_PROBE_DASH_USER`, `PULSE_PROBE_DASH_PASSWORD`,
`PULSE_PROBE_SECRET_KEY`, `PULSE_PROBE_DASH_PORT` (default **5001**),
`PULSE_HTTP_TIMEOUT`, `PULSE_VERIFY_TLS`.

## Avvio locale

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Linux: source .venv/bin/activate)
pip install ../../frontend_common          # pacchetto condiviso pulse-fe-common
pip install -r requirements.txt
export PULSE_PROBE_API_BASE=http://localhost:8444/api/v1
export PULSE_PROBE_AGENT_TOKEN=<token>
python app.py                              # sviluppo
gunicorn --bind 0.0.0.0:5001 app:app       # produzione (WSGI)
```

## Container

`Dockerfile` incluso (Python slim + gunicorn, healthcheck su `/healthz`, porta da
env, default 5001). **Build context = radice repo** (vedi SCOSTAMENTI). Esempio
compose (per il BE):

```yaml
dashboard-probe:
  build: { context: ., dockerfile: probe/dashboard/Dockerfile }
  environment:
    PULSE_PROBE_DASH_PORT: 5001
    PULSE_PROBE_API_BASE: https://probe-agent:8444/api/v1
    PULSE_PROBE_AGENT_TOKEN: <token>
    PULSE_PROBE_SECRET_KEY: <secret>
  ports: ["5001:5001"]
```

## Test e coverage

Il probe-agent è simulato (FakeApiClient): nessun agent reale richiesto.

```bash
pip install -r requirements-dev.txt
pytest tests -q                     # 27 test
```

### Coverage COMBINATA (frontend_common + server + probe) — 100%

Le due dashboard condividono nomi di modulo entrypoint (`app`, `sdk`, `views`):
i test vanno eseguiti in invocazioni separate e la coverage combinata (config in
`.coveragerc` alla radice del repo):

```bash
cd <repo-root>
coverage run --parallel-mode -m pytest frontend_common/tests
coverage run --parallel-mode -m pytest server/dashboard/tests
coverage run --parallel-mode -m pytest probe/dashboard/tests
coverage combine && coverage report
# TOTAL ... 100%
```

Risultato reale verificato: **1054 statement, 92 branch, 0 miss → 100%**;
**104 test totali** (27 + 50 + 27), tutti verdi.

## SCOSTAMENTI rispetto al DOCUMENTO_API / convenzioni (per Analista/QA/BE)

1. **PP-01 autenticazione locale** (FE-02 / API-04): credenziali locali via env,
   indipendenti dal RBAC del Server. Da confermare col Committente l'eventuale SSO
   col Server.
2. **Token probe-agent** (FE-03): la dashboard invia `Authorization: Bearer
   <PULSE_PROBE_AGENT_TOKEN>` verso gli endpoint della Probe. L'accesso reale
   resta protetto da mTLS + token lato probe-agent.
3. **Libreria grafici senza CDN**: `static/pulse-charts.js` locale (vedi README
   Server, punto 1).
4. **Docker build context = radice repo** (dipendenza da `frontend_common/`).
   Porta da env (default 5001) e healthcheck `/healthz` rispettati.
