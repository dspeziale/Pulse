# Pulse — Dashboard SERVER (Flask)

Frontend web del **Server** Pulse. Consuma esclusivamente le API REST della
sezione BACKEND di `docs/api/DOCUMENTO_API.md` (nessun accesso diretto a
DB/OpenSearch). Implementa le pagine **P-01 … P-19** della sezione FRONTEND.

## Pagine implementate (sezione FRONTEND del DOCUMENTO_API)

| Pagina | Blueprint / route base | Endpoint BACKEND consumati |
|---|---|---|
| P-01 Login | `auth` (`/login`, `/logout`) | `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` |
| P-02 Dashboard aggregata | `dashboard` (`/dashboard`) | `GET /dashboard/aggregate`, `GET /probes`, `GET /alarms?status=active` |
| P-03 Dettaglio/Selezione Probe | `probes` (`/probes/<id>`) | `GET /probes/{id}`, `/probes/{id}/status`, `/dashboard/probe/{id}`, `/probes/{id}/heartbeats` |
| P-04 Query builder | `query` (`/query`) | `POST /probes/{id}/query`, `GET /systems`, `GET /systems/{id}/checks` |
| P-05 Grafici/Analisi | `query` (`/charts`) | `POST /probes/{id}/query`, `GET /probes/{id}/heartbeats` |
| P-06 Utenti | `users` (`/users`) | `GET/POST /users`, `GET/PUT/DELETE /users/{id}`, `PUT /users/{id}/roles`, `POST /users/{id}/reset-password`, `GET /roles` |
| P-07 Ruoli | `roles` (`/roles`) | `GET/POST /roles`, `GET/PUT/DELETE /roles/{id}`, `PUT /roles/{id}/permissions`, `GET /permissions` |
| P-08 Catalogo Permessi | `permissions` (`/permissions`) | `GET /permissions` |
| P-09 Gestione Sonde | `probes` (`/probes`) | `GET/POST /probes`, `GET/PUT/DELETE /probes/{id}`, `POST /probes/{id}/rotate-credentials`, `GET /probes/{id}/status` |
| P-10 Sistemi monitorati | `systems` (`/systems`) | `GET/POST /systems`, `GET/PUT/DELETE /systems/{id}`, `GET /systems/{id}/checks`, `GET /probes` |
| P-11 Canali notifica | `notifications` (`/notification-channels`) | `GET/POST/PUT/DELETE /notification-channels[/{id}]`, `POST /notification-channels/{id}/test` |
| P-12 Workflow notifiche | `workflows` (`/notification-workflows`) | `GET/POST/PUT/DELETE /notification-workflows[/{id}]`, `PUT .../enabled`, `POST .../simulate`, `GET /notification-channels` |
| P-13 Storico notifiche | `notifications` (`/notifications/history`) | `GET /notifications/history` |
| P-14 Allarmi | `alarms` (`/alarms`) | `GET /alarms`, `POST /alarms/{id}/ack` |
| P-15 Identità di canale | `identities` (`/channel-identities`) | `GET/POST /channel-identities`, `DELETE /channel-identities/{id}` |
| P-16 Audit Log | `audit` (`/audit`) | `GET /audit`, `GET /audit/{id}` |
| P-17 Log di sistema | `logs` (`/logs`) | `GET /logs` |
| P-18 Configurazione | `config_bp` (`/config`) | `GET /config`, `PUT /config` |
| P-19 Profilo utente | `profile` (`/profile`) | `GET /auth/me`, `POST /auth/change-password` |

Route infrastrutturali: `/` (redirect login/dashboard), `/healthz` (liveness).

## Autenticazione e RBAC lato UI

- Login → il backend emette JWT (`access_token`/`refresh_token`); token e profilo
  (con i permessi) sono salvati nella **sessione Flask server-side** (firmata).
- Ogni route è protetta da `permission_required(...)` con il permesso RBAC
  dell'endpoint corrispondente; il menu (`base.html`) mostra/nasconde le voci con
  `can('<permesso>')`. L'autorizzazione **reale** resta lato backend (deny-by-default).
- I permessi NON sono cablati nel frontend: si usa l'elenco restituito da
  `GET /auth/me` / login (fonte: `06_rbac.md`).
- Gestione errori centralizzata: `401`→redirect login (sessione scaduta),
  `403/404/409/422/500`→pagina d'errore con messaggio del backend, backend
  irraggiungibile→`503`.

## Configurazione (variabili d'ambiente)

Vedi `.env.example`. Principali: `PULSE_SERVER_API_BASE` (base URL backend),
`PULSE_SERVER_SECRET_KEY`, `PULSE_SERVER_DASH_PORT` (default **5000**),
`PULSE_HTTP_TIMEOUT`, `PULSE_VERIFY_TLS`.

## Avvio locale

```bash
python -m venv .venv && . .venv/Scripts/activate   # (Linux: source .venv/bin/activate)
pip install ../../frontend_common          # pacchetto condiviso pulse-fe-common
pip install -r requirements.txt
export PULSE_SERVER_API_BASE=http://localhost:8000/api/v1
# sviluppo:
python app.py
# produzione (WSGI):
gunicorn --bind 0.0.0.0:5000 app:app
```

## Container

`Dockerfile` incluso (Python slim + gunicorn, healthcheck su `/healthz`, porta da
env). **NB build context** — vedi SCOSTAMENTI: il context deve essere la radice
del repository. Esempio compose (per il BE):

```yaml
dashboard-server:
  build: { context: ., dockerfile: server/dashboard/Dockerfile }
  environment:
    PULSE_SERVER_DASH_PORT: 5000
    PULSE_SERVER_API_BASE: http://backend:8000/api/v1
    PULSE_SERVER_SECRET_KEY: <secret>
  ports: ["5000:5000"]
```

## Test e coverage

Il backend è simulato (FakeApiClient): i test **non** richiedono un backend reale.

```bash
pip install -r requirements-dev.txt
pytest tests -q                     # 50 test
pytest tests --cov=. --cov-report=term-missing
```

Coverage complessiva del frontend (frontend_common + server + probe): **100%**
(vedi comando combinato nel README della Probe / `.coveragerc` in radice).

## SCOSTAMENTI rispetto al DOCUMENTO_API / convenzioni (per Analista/QA/BE)

1. **Libreria grafici senza CDN**: i template originali caricavano `chart.js` da
   `cdn.jsdelivr.net`. Il requisito vieta CDN esterni obbligatori: sostituita con
   `static/pulse-charts.js`, micro-libreria locale self-contained (sottoinsieme
   API di Chart.js, bar/line). Nessun endpoint API coinvolto.
2. **Docker build context = radice repo**: la convenzione indicava context
   `./server/dashboard`, ma la dashboard dipende dal pacchetto condiviso
   `frontend_common/` che vive fuori dalla cartella. Il Dockerfile richiede quindi
   context `.` con `dockerfile: server/dashboard/Dockerfile`. Restano rispettati:
   porta letta da env (default 5000 documentato) e healthcheck su `/healthz`.
3. **Template query mancanti aggiunti**: `templates/query/builder.html` e
   `templates/query/charts.html` (le viste P-04/P-05 già li referenziavano).
4. **Esecuzione test per-pacchetto**: le due dashboard hanno moduli entrypoint con
   lo stesso nome (`app`, `sdk`, `views`); i test vanno eseguiti in invocazioni
   pytest separate (server / probe / frontend_common) — vedi comandi sopra.
5. **Catalogo permessi**: il conteggio "40 vs 37" segnalato dal DBA non impatta il
   FE, che non cabla alcun catalogo e usa i permessi restituiti dal backend.
