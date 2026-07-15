# Pulse

Sistema distribuito per il monitoraggio della connettività e dello stato applicativo di sistemi HTTP/HTTPS.

## Architettura (sintesi)
- **Server centrale**: legge i dati delle Probe, dashboard aggregata, selezione della Probe da consultare.
- **Probe** (1..N): interrogano gli endpoint `GET /api/heartbeat` dei sistemi monitorati, archiviano su **OpenSearch locale**, espongono dashboard e query dirette.
- **Comunicazione cifrata** Server ↔ Probe.
- **Deploy Probe**: container Docker / Podman.

## Stack
- Backend: Python + FastAPI
- Frontend: Python + Flask
- DB Probe: OpenSearch
- DB Server: scelto e motivato dal DBA

## Stato pipeline
| Fase | Agente | Stato |
|------|--------|-------|
| 1 | ANALISTA | ✅ completata |
| 2 | DBA | ✅ completata (PostgreSQL 16, schema validato) |
| 3 | BE | ✅ completata (72/72 endpoint, coverage 100%) |
| 4 | FE | ✅ completata (24/24 pagine, coverage 100%) |
| 5 | QA | ✅ **PASS** (0 bug bloccanti/maggiori, 0 test falliti) |

**Progetto CERTIFICATO** — vedi `QA_REPORT.md`. Verdetto QA: PASS. Coverage: Backend server 100%, Probe agent 100%, Frontend 100%.

Vedi `DIARIO.md` per la cronologia completa e `docs/` per gli artefatti.
