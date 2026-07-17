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

| P-nuova Compendio sistema | `report` (`/systems/<id>/report`) | `GET /systems/{id}`, `GET /systems/{id}/checks`, `POST /probes/{probe_id}/query`, `GET /probes/{probe_id}/heartbeats`, `GET /alarms` |

Route infrastrutturali: `/` (redirect login/dashboard), `/healthz` (liveness).

## Compendio sistema + Report PDF (P-nuova)

Dal dettaglio di un Sistema (P-10) il pulsante **Compendio** apre
`GET /systems/<id>/report`: un riepilogo di ciò che è rilevante nel **periodo**
selezionato (default **Oggi**; preset come in P-04 — Ultima ora / Oggi / Ultime
24h / 7 giorni / 30 giorni / intervallo personalizzato). Il periodo è calcolato
nel fuso configurato (coerente con `localdt`) e convertito in UTC per le query.

Contenuti (solo endpoint esistenti): intestazione (system_id/nome/tipo/Sonda/
periodo), stato complessivo nel periodo (stato peggiore + distribuzione, con
LED/badge), KPI (uptime %, response_ms avg/min/max, n. campioni, n. check,
n. incidenti), tabella **per-check** (ultimo stato, uptime %, avg/min/max ms,
ultimo contatto — aggregazioni via `POST /probes/{id}/query`), allarmi del
periodo (`GET /alarms`, best-effort: senza `workflows.read` il resto della
pagina si rende comunque) e un grafico `response_ms` (riuso di `pulse-charts.js`).

### Export PDF — approccio scelto: **fpdf2** (non WeasyPrint)

Il pulsante **Scarica PDF** genera `GET /systems/<id>/report.pdf`
(`Content-Type: application/pdf`, `Content-Disposition` con nome file
significativo `compendio_<system_id>_<da>_<a>.pdf`). Il PDF è prodotto **lato
server** da `report_pdf.py`.

Il DOCUMENTO richiedeva come approccio preferito WeasyPrint (HTML→PDF); è stato
invece scelto **fpdf2** perché:

- **puro Python, nessuna libreria di sistema** (WeasyPrint richiede
  pango/cairo/gdk-pixbuf, che su Windows/CI non sono banali da installare); così
  il report è generabile e **verificabile davvero** in ogni ambiente, test
  inclusi (la rotta produce un `%PDF` valido, non isolato/mockato);
- **coerenza di carattere** con la UI: viene embeddato **PT Sans Narrow** (pesi
  400/700). I `.ttf` in `static/vendor/fonts/pt-sans-narrow/` (`PTSansNarrow-Regular.ttf`,
  `PTSansNarrow-Bold.ttf`) sono ottenuti dai `.woff2` già vendorizzati per la UI
  (conversione `fontTools`, font OFL — ridistribuzione consentita).

Cura estetica: intestazione ripetuta col titolo **“Pulse — Compendio sistema”**,
nome sistema e periodo; testo ben leggibile (corpo 9.5–11 pt, titoli 12–15 pt,
niente testo minuscolo); tabelle ordinate a righe alternate dimensionate sulla
larghezza utile A4 (180 mm, margini 15 mm) con salto pagina e header ripetuto;
badge di stato colorati (coerenti coi `b-*` della UI); footer con data di
generazione (fuso locale) e numero di pagina (`Pagina X di N`).

**Dipendenze**: aggiunto `fpdf2` a `requirements.txt` (nessuna dipendenza di
sistema → **nessuna modifica al Dockerfile**: il `COPY server/dashboard/` porta
già font e codice, e `pip install -r requirements.txt` installa fpdf2).

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
