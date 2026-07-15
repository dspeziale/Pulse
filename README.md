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
| 1 | ANALISTA | in corso |
| 2 | DBA | in attesa |
| 3 | BE | in attesa |
| 4 | FE | in attesa |
| 5 | QA | in attesa |

Vedi `DIARIO.md` per la cronologia completa e `docs/` per gli artefatti.
