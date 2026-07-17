# Pulse — Proxy nmap esterno (host Windows)

Su **Docker Desktop (Windows/WSL2)** il container della Probe e' dietro NAT nella
VM WSL2: **non** e' sul segmento L2 della rete fisica. Le scansioni raw
(`-sS`/`-sU`/`-O`) e la host-discovery della subnet locale **non** funzionano dal
container (le sole connect scan verso IP instradabili escono via NAT).

Questo componente esegue **nmap nativo sull'host Windows** (con Npcap) per conto
dell'agent Probe. L'agent, se rileva il proxy configurato e raggiungibile, gli
delega automaticamente l'esecuzione di nmap; altrimenti usa nmap nel container.

## Sicurezza

- **mTLS**: il proxy richiede un certificato client firmato dalla CA dedicata
  (generata dall'installer). Solo l'agent Probe ha quel certificato.
- **Token Bearer** condiviso su ogni richiesta.
- **Bind** su `0.0.0.0` (necessario perche' il container raggiunge l'host via
  `host.docker.internal`; `127.0.0.1` non e' raggiungibile dal container). La
  protezione e' data da mTLS + token, non dall'interfaccia.
- **Ri-validazione dell'argv**: ogni argv ricevuto e' ri-controllato con la
  stessa whitelist dell'agent (`pulse_probe.nmap_scan.assert_safe_argv`): niente
  comandi arbitrari, output XML solo su stdout, target validati. Il binario reale
  di nmap sostituisce `argv[0]`.

## Installazione automatica

Dalla cartella del repository, in **PowerShell come amministratore**:

```powershell
cd probe\nmap-proxy
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
```

Lo script (idempotente):

1. installa **nmap + Npcap** se mancanti (winget);
2. crea un venv e installa il proxy + il pacchetto agent (validazione condivisa);
3. genera **CA + certificato server + certificato client** e un **token**;
4. registra un'**attivita' pianificata** che avvia il proxy ad ogni boot
   (SYSTEM, elevata, riavvio automatico) e apre la porta nel firewall;
5. copia CA + certificato client in `deploy/certs/nmap-proxy/` e valorizza
   `deploy/.env.probe` con URL/token/percorsi (interni al container).

Poi applica la configurazione all'agent:

```powershell
cd ..\..\deploy
docker compose -f docker-compose.probe.yml --env-file .env.probe up -d probe-agent
```

L'agent rilevera' il proxy in automatico: in `GET /status` comparira'
`scan_backend: "proxy"`. Se il proxy non e' raggiungibile all'avvio, l'agent usa
nmap locale (`scan_backend: "local"`).

Disinstallazione: `powershell -ExecutionPolicy Bypass -File .\uninstall-windows.ps1`.

## Configurazione (variabili PULSE_NMAP_PROXY_)

| Variabile | Descrizione | Default |
|---|---|---|
| `HOST` | interfaccia di bind | `0.0.0.0` |
| `PORT` | porta TCP | `8556` |
| `TOKEN` | token Bearer condiviso | — (obbligatorio) |
| `TLS_CERT_PATH` / `TLS_KEY_PATH` | certificato/chiave del server | — |
| `TLS_CLIENT_CA_PATH` | CA che firma i certificati client | — |
| `NMAP_PATH` | percorso di nmap nativo | `nmap` |
| `MAX_SCAN_TIMEOUT` | tetto al timeout scansione (s) | `3600` |

## Avvio manuale (debug)

```powershell
& "$env:ProgramData\Pulse\nmap-proxy\venv\Scripts\python.exe" -m pulse_nmap_proxy
```

## API

- `GET /health` → `{status, nmap_available, nmap_version}` (auth Bearer + mTLS).
- `POST /scan` `{argv, timeout}` → `{returncode, stdout, stderr}` (auth Bearer +
  mTLS; argv ri-validato, `argv[0]` sostituito con `NMAP_PATH`).

## Test

```bash
cd probe/nmap-proxy
PYTHONPATH="../agent:." python -m pytest -q
```
