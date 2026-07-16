# Pulse - Installazione della SONDA (Probe)

Guida passo-passo per installare una **Sonda Pulse** su un host con **Docker**
oppure **Podman**. La Sonda raccoglie gli heartbeat/eventi dei sistemi monitorati
in un OpenSearch locale, si registra sul Server Pulse ed espone una dashboard
locale.

Lo stack e' composto da tre servizi:

| Servizio          | Ruolo                                             | Porta host (default) |
|-------------------|---------------------------------------------------|----------------------|
| `opensearch`      | Archivio locale serie temporali (heartbeat/eventi)| 9200 (solo interna)  |
| `probe-agent`     | Agent FastAPI: poller + API di query              | **8444**             |
| `probe-dashboard` | Dashboard locale della Sonda (Flask)              | **5001**             |

> **Contenuto del pacchetto** (`deploy/probe-package/`):
> `docker-compose.yml`, `podman-compose.yml`, `.env.probe.example`,
> `install.sh` / `install.ps1`, `uninstall.sh` / `uninstall.ps1`, questo `INSTALL.md`.
>
> **Nota importante sui build context**: il pacchetto **compila le immagini dai
> sorgenti del repository**. I `build.context` nei file compose sono relativi
> alla **cartella del file compose** (`deploy/probe-package/`): Docker/Podman
> Compose risolvono sempre i context rispetto alla directory del file compose,
> quindi lo stack funziona **da qualunque cwd** purche' il pacchetto resti
> dentro l'albero del repo. Questo e' l'approccio piu' robusto (non dipende dalla
> directory da cui lanci il comando):
> - `probe-agent` -> context `../../probe/agent` (usa `probe/agent/Dockerfile`)
> - `probe-dashboard` -> context `../..` = radice repo (usa `probe/dashboard/Dockerfile`,
>   che dipende dal pacchetto condiviso `frontend_common/`)

---

## Prerequisiti

- **Docker** con il plugin `docker compose` (Docker Engine 20.10+), **oppure**
  **Podman** con `podman-compose`.
- **Sorgenti del repository Pulse** presenti sull'host (il pacchetto builda dai
  Dockerfile del repo). Il pacchetto vive in `deploy/probe-package/`.
- **Memoria**: OpenSearch e' configurato con heap 512 MB (`-Xms512m -Xmx512m`).
  Prevedere **almeno ~1.5-2 GB di RAM liberi** per il solo OpenSearch, piu' agent
  e dashboard. Su Linux e' consigliato `vm.max_map_count >= 262144` (vedi
  Troubleshooting).
- **Porte libere sull'host**: `8444` (agent) e `5001` (dashboard). Sono
  configurabili via `.env`.
- **Rete**: la Sonda deve poter **raggiungere il Server** all'URL
  `PULSE_PROBE_SERVER_BASE_URL`. Per il **drill-down** (il Server interroga la
  Sonda) il Server deve poter raggiungere la Sonda sulla porta `8444`.

---

## Passo 1 - Creare la Probe sul Server e ottenere l'ENROLLMENT TOKEN

La Sonda si registra sul Server con un **token di enrollment monouso**, che si
ottiene creando la Probe sul Server.

**Opzione A - Dashboard Server (consigliata)**
1. Accedere alla dashboard del Server.
2. Menu **Sonde** -> **Nuova**.
3. Compilare nome/descrizione e salvare.
4. **Copiare l'ENROLLMENT TOKEN mostrato** (viene visualizzato una sola volta).

**Opzione B - API**
```bash
curl -sf -X POST https://<server>:<porta>/api/v1/probes \
  -H "Authorization: Bearer <ACCESS_TOKEN_ADMIN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"sonda-sede-milano","description":"Sonda DC Milano"}'
```
La risposta contiene `enrollment_token` (e `enrollment_expires_at`). **Copiarlo.**

> Annotare anche il **query token** concordato per questa Sonda (il token che il
> Server presentera' alle API di query della Sonda): andra' in
> `PULSE_PROBE_SERVER_QUERY_TOKEN` e deve combaciare con quanto configurato sul
> Server per la stessa Probe.

---

## Passo 2 - Configurare `.env`

Dalla cartella del pacchetto:

```bash
cd deploy/probe-package
cp .env.probe.example .env      # Linux/macOS
# Copy-Item .env.probe.example .env   # Windows PowerShell
```

Aprire `.env` e valorizzare **almeno** le variabili obbligatorie:

- `PULSE_PROBE_SERVER_BASE_URL` — URL del Server **raggiungibile dalla Sonda**
  (es. `https://pulse-server.miodominio.it:9443`).
- `PULSE_PROBE_ENROLLMENT_TOKEN` — il token copiato al Passo 1
  (oppure, in alternativa, `PULSE_PROBE_PROBE_TOKEN` se possiedi gia' un token
  per-Sonda).

Rivedere anche (consigliato in produzione):
`PULSE_PROBE_SERVER_QUERY_TOKEN`, `PULSE_PROBE_DASH_USER/PASSWORD`,
`PULSE_PROBE_SECRET_KEY`, `OPENSEARCH_ADMIN_PASSWORD`, `PULSE_PROBE_HTTP_VERIFY`.

Tutte le variabili sono documentate in `.env.probe.example`.

---

## Passo 3 - Installare (avviare lo stack)

### Con lo script (consigliato)

**Linux / macOS**
```bash
cd deploy/probe-package
chmod +x install.sh
./install.sh
```

**Windows PowerShell**
```powershell
cd deploy\probe-package
./install.ps1
```

Lo script: rileva il runtime, verifica i prerequisiti, crea `.env` da template se
manca (e in tal caso si ferma chiedendoti di compilarlo), controlla le variabili
obbligatorie, esegue `up -d --build`, attende l'health dell'agent e stampa i passi
di verifica. E' **idempotente** (rieseguibile) e ritorna **exit code != 0** in caso
di errore.

Per forzare il runtime: `RUNTIME=docker ./install.sh` /
`./install.ps1 -Runtime podman`.

### Comandi compose manuali equivalenti

**Docker**
```bash
docker compose -f deploy/probe-package/docker-compose.yml \
  --env-file deploy/probe-package/.env up -d --build
```

**Podman**
```bash
podman-compose -f deploy/probe-package/podman-compose.yml \
  --env-file deploy/probe-package/.env up -d --build
```

---

## Passo 4 - Verifica

1. **Health dell'agent**
   ```bash
   curl -sf http://<host>:8444/api/v1/health
   # atteso: {"status":"ok"}
   ```
   Readiness (include OpenSearch): `curl http://<host>:8444/api/v1/health/ready`.

2. **La Probe risulta "online" sul Server**: nella dashboard del Server, menu
   **Sonde**, la Sonda appena creata deve passare da `pending` a `online` dopo il
   primo enrollment + heartbeat.

3. **Dashboard locale della Sonda**: aprire `http://<host>:5001` e autenticarsi
   con `PULSE_PROBE_DASH_USER` / `PULSE_PROBE_DASH_PASSWORD`.

4. **Log** (in caso di problemi):
   ```bash
   docker compose -f deploy/probe-package/docker-compose.yml logs -f probe-agent
   ```

---

## Disinstallazione

**Linux / macOS**
```bash
./uninstall.sh            # ferma e rimuove i container (mantiene i dati)
./uninstall.sh --volumes  # rimuove anche i volumi (CANCELLA i dati OpenSearch)
```

**Windows PowerShell**
```powershell
./uninstall.ps1
./uninstall.ps1 -Volumes
```

---

## Troubleshooting

### Token di enrollment monouso / riavvio del container
Il `probe_token` ottenuto con l'enrollment e' tenuto **in memoria** dall'agent
(non persistito). Di conseguenza:

- Il `PULSE_PROBE_ENROLLMENT_TOKEN` e' **monouso**: dopo il primo enrollment
  riuscito viene consumato.
- Se il container `probe-agent` viene **riavviato/ricreato** (es. `up` dopo un
  `down`, reboot dell'host, aggiornamento immagine), l'agent **perde il token in
  memoria** e deve ri-registrarsi. Un token di enrollment gia' usato **non**
  funzionera' di nuovo.

**Come procedere a un riavvio:**
1. **Rotazione credenziali dal Server** (consigliato): dalla dashboard Sonde del
   Server usare l'azione di **rotazione credenziali**, oppure via API
   `POST /api/v1/probes/{probe_id}/rotate-credentials`. Si ottiene un nuovo
   token di enrollment: inserirlo in `PULSE_PROBE_ENROLLMENT_TOKEN` e rilanciare
   `install.sh` / `up -d`.
2. In alternativa, se disponi di un **token per-Sonda persistente**, valorizzare
   `PULSE_PROBE_PROBE_TOKEN` (invece dell'enrollment): l'agent lo riusa a ogni
   avvio senza nuovo enrollment.

> In sintesi: **un enrollment token = un avvio**. Per ambienti che si riavviano
> spesso, preferire un `PULSE_PROBE_PROBE_TOKEN` oppure automatizzare la
> rotazione.

### Rete Server <-> Sonda
- La Sonda deve **raggiungere** `PULSE_PROBE_SERVER_BASE_URL`. Verificare da
  dentro il container:
  ```bash
  docker exec -it pulse-probe-agent \
    python -c "import urllib.request as u; print(u.urlopen('https://<server>:9443', timeout=5).status)"
  ```
  (con TLS self-signed impostare `PULSE_PROBE_HTTP_VERIFY=false`).
- Per il **drill-down** il Server deve raggiungere la Sonda sulla porta `8444`:
  aprire il firewall e verificare che la porta sia esposta/instradabile.
- **Caso "tutto sullo stesso host"**: questo pacchetto usa una rete Docker
  dedicata (`pulse-probe-net`) e raggiunge il Server via URL. Se invece Server e
  Sonda girano sullo stesso host Docker e vuoi collegarli via rete Docker
  condivisa, usa `deploy/docker-compose.probe.yml` (che prevede la rete esterna
  `pulse-shared`) anziche' questo pacchetto.

### OpenSearch: memoria / ulimits / max_map_count
- Se `opensearch` non diventa `healthy`, quasi sempre e' un problema di
  memoria/limiti di sistema. Su Linux:
  ```bash
  sudo sysctl -w vm.max_map_count=262144
  # persistente: echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf
  ```
- Gli `ulimits` (`memlock unlimited`, `nofile 65536`) sono gia' impostati nel
  compose. Con `bootstrap.memory_lock=true` il container richiede il permesso di
  memlock: se fallisce, verificare i limiti dell'host/daemon.
- Ridurre/aumentare l'heap in base alla RAM disponibile modificando
  `OPENSEARCH_JAVA_OPTS` (attualmente `-Xms512m -Xmx512m`).
- Controllare i log: `docker compose ... logs opensearch`.

### Podman: rootless / SELinux
- **Rootless**: usare le porte di default (>1024, gia' configurate: 8444/5001);
  le porte <1024 richiedono privilegi.
- `podman-compose` potrebbe **ignorare** `depends_on.condition: service_healthy`:
  in tal caso, se l'agent parte prima di OpenSearch, attendere e riavviare
  l'agent, oppure attendere che OpenSearch sia pronto prima di avviare l'agent.
  Lo `install.sh` attende comunque l'health dell'agent via HTTP.
- `vm.max_map_count`/memlock: valgono le stesse note di OpenSearch; in rootless
  potrebbero servire aggiustamenti di sistema (eseguibili da root).
- **SELinux**: se compaiono errori di permesso sui volumi, aggiungere il suffisso
  `:Z` ai mount. Il pacchetto usa un **volume gestito** (`pulse_osdata`), che di
  norma non presenta problemi SELinux.

---

## Nota su Docker vs Podman

- I due file compose (`docker-compose.yml` e `podman-compose.yml`) sono
  **funzionalmente identici**; cambiano solo il binario di avvio e alcune note
  operative Podman.
- **Podman non e' installato nell'ambiente di sviluppo**: il file
  `podman-compose.yml` e' stato validato **solo staticamente** (schema identico a
  quello Docker, gia' validato con `docker compose config`).
- Con Podman, se la tua versione rifiuta il campo top-level `name:`, rimuoverlo
  (i nomi espliciti di rete/volume restano validi).
