<#
.SYNOPSIS
  Installer AUTOMATICO del proxy nmap di Pulse sull'host Windows.

.DESCRIPTION
  Su Docker Desktop (Windows/WSL2) il container Probe e' dietro NAT e non
  raggiunge la LAN fisica: le scansioni raw (-sS/-sU/-O) e la discovery della
  subnet locale non funzionano dal container. Questo installer configura un
  proxy nmap che gira NATIVO sull'host (Npcap) e a cui l'agent delega
  automaticamente l'esecuzione di nmap.

  Esegue, in modo idempotente:
    1. Verifica privilegi admin (si ri-lancia elevato se necessario).
    2. Installa nmap + Npcap se mancanti (winget).
    3. Crea un venv Python e installa il proxy + il pacchetto agent (per la
       validazione condivisa dell'argv).
    4. Genera il materiale mTLS (CA + certificato server + certificato client)
       e un token condiviso.
    5. Scrive la config del proxy e registra un'attivita' pianificata che lo
       avvia ad ogni boot (SYSTEM, elevata, riavvio automatico).
    6. Copia CA + certificato client in deploy/certs/nmap-proxy/ e valorizza
       deploy/.env.probe cosi' che l'agent usi il proxy in automatico.
    7. Verifica /health e stampa i passi finali.

.PARAMETER Port
  Porta TCP del proxy (default 8556).

.PARAMETER InstallDir
  Cartella di installazione (default C:\ProgramData\Pulse\nmap-proxy).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
#>
[CmdletBinding()]
param(
  [int]$Port = 8556,
  [string]$InstallDir = "$env:ProgramData\Pulse\nmap-proxy"
)

$ErrorActionPreference = "Stop"
$TaskName = "PulseNmapProxy"

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Write-Warn2($m){ Write-Host "    $m" -ForegroundColor Yellow }

# --- 1) Elevazione ----------------------------------------------------------
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Warn2 "Privilegi amministrativi richiesti: ri-lancio elevato..."
  $argList = @("-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"","-Port",$Port,"-InstallDir","`"$InstallDir`"")
  Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs
  return
}

# Percorsi del repository (lo script vive in probe/nmap-proxy).
$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$AgentPkg   = Join-Path $RepoRoot "probe\agent"
$ProxyPkg   = Join-Path $RepoRoot "probe\nmap-proxy"
$DeployDir  = Join-Path $RepoRoot "deploy"
$EnvProbe   = Join-Path $DeployDir ".env.probe"
$DeployCerts= Join-Path $DeployDir "certs\nmap-proxy"
$CertDir    = Join-Path $InstallDir "certs"

Write-Step "Installazione proxy nmap Pulse (host: $env:COMPUTERNAME, porta: $Port)"

# --- 2) Python --------------------------------------------------------------
Write-Step "Verifica Python"
$py = $null
foreach ($cand in @("py -3","python")) {
  try { & ([scriptblock]::Create("$cand --version")) *>$null; if ($LASTEXITCODE -eq 0) { $py = $cand; break } } catch {}
}
if (-not $py) { throw "Python 3 non trovato. Installa Python 3.11+ (winget install Python.Python.3.12) e riesegui." }
Write-Ok "Python: $py"

# --- 3) nmap + Npcap --------------------------------------------------------
Write-Step "Verifica nmap + Npcap"
$nmapCmd = (Get-Command nmap -ErrorAction SilentlyContinue)
if (-not $nmapCmd) {
  Write-Warn2 "nmap non trovato: installo via winget (include Npcap)..."
  winget install -e --id Insecure.Nmap --silent --accept-package-agreements --accept-source-agreements
  # Aggiorna la PATH del processo corrente.
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
  $nmapCmd = (Get-Command nmap -ErrorAction SilentlyContinue)
}
if (-not $nmapCmd) {
  # fallback: percorso tipico
  $guess = "C:\Program Files (x86)\Nmap\nmap.exe"
  if (Test-Path $guess) { $nmapCmd = Get-Item $guess }
}
if (-not $nmapCmd) { throw "nmap non installato. Installa Nmap (con Npcap) e riesegui." }
$NmapPath = $nmapCmd.Source
Write-Ok "nmap: $NmapPath"

$npcap = Get-Service -Name npcap -ErrorAction SilentlyContinue
if (-not $npcap) {
  Write-Warn2 "Npcap non rilevato: le scansioni raw richiedono Npcap. Se l'installer di Nmap"
  Write-Warn2 "non l'ha installato in modalita' silenziosa, completa l'installazione di Npcap"
  Write-Warn2 "(una sola finestra) e riesegui questo script."
} else {
  Write-Ok "Npcap presente (servizio '$($npcap.Status)')."
}

# --- 4) venv + pacchetti ----------------------------------------------------
Write-Step "Creazione ambiente Python del proxy"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$VenvPy = Join-Path $InstallDir "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { & ([scriptblock]::Create("$py -m venv `"$InstallDir\venv`"")) }
& $VenvPy -m pip install --upgrade pip *>$null
Write-Ok "Installo il pacchetto agent (validazione condivisa) e il proxy..."
& $VenvPy -m pip install "$AgentPkg" "$ProxyPkg"
if ($LASTEXITCODE -ne 0) { throw "pip install fallito." }

# --- 5) Certificati mTLS + token -------------------------------------------
Write-Step "Generazione materiale mTLS + token"
# SAN del certificato server: host.docker.internal (nome usato dal container) + IP host.
$ips = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "169.254.*" } | Select-Object -Expand IPAddress) -join ","
$san = "host.docker.internal,localhost,127.0.0.1"
if ($ips) { $san = "$san,$ips" }
New-Item -ItemType Directory -Force -Path $CertDir | Out-Null
& $VenvPy -m pulse_nmap_proxy.gen_certs --out-dir "$CertDir" --server-san "$san"
if ($LASTEXITCODE -ne 0) { throw "Generazione certificati fallita." }

$Token = (& $VenvPy -c "import secrets; print(secrets.token_urlsafe(32))").Trim()
Write-Ok "Token generato."

# --- 6) Config proxy (.env) -------------------------------------------------
Write-Step "Scrittura configurazione proxy"
$proxyEnv = @"
PULSE_NMAP_PROXY_HOST=0.0.0.0
PULSE_NMAP_PROXY_PORT=$Port
PULSE_NMAP_PROXY_TOKEN=$Token
PULSE_NMAP_PROXY_TLS_CERT_PATH=$CertDir\server.crt
PULSE_NMAP_PROXY_TLS_KEY_PATH=$CertDir\server.key
PULSE_NMAP_PROXY_TLS_CLIENT_CA_PATH=$CertDir\ca.crt
PULSE_NMAP_PROXY_NMAP_PATH=$NmapPath
"@
Set-Content -Path (Join-Path $InstallDir ".env") -Value $proxyEnv -Encoding UTF8
Write-Ok "Config scritta in $InstallDir\.env"

# --- 7) Materiale client per il container + wiring .env.probe --------------
Write-Step "Wiring lato agent (container)"
New-Item -ItemType Directory -Force -Path $DeployCerts | Out-Null
Copy-Item (Join-Path $CertDir "ca.crt")     $DeployCerts -Force
Copy-Item (Join-Path $CertDir "client.crt") $DeployCerts -Force
Copy-Item (Join-Path $CertDir "client.key") $DeployCerts -Force

function Set-EnvVar($file, $key, $value) {
  if (-not (Test-Path $file)) { New-Item -ItemType File -Path $file -Force | Out-Null }
  $lines = @(Get-Content $file -ErrorAction SilentlyContinue)
  $out = @(); $found = $false
  foreach ($l in $lines) {
    if ($l -match "^\s*$([regex]::Escape($key))=") { $out += "$key=$value"; $found = $true }
    else { $out += $l }
  }
  if (-not $found) { $out += "$key=$value" }
  Set-Content -Path $file -Value $out -Encoding UTF8
}
# Percorsi INTERNI al container (vedi volume in docker-compose.probe.yml).
Set-EnvVar $EnvProbe "PULSE_PROBE_NMAP_PROXY_URL"             "https://host.docker.internal:$Port"
Set-EnvVar $EnvProbe "PULSE_PROBE_NMAP_PROXY_TOKEN"           $Token
Set-EnvVar $EnvProbe "PULSE_PROBE_NMAP_PROXY_CA_CERT_PATH"    "/certs/nmap-proxy/ca.crt"
Set-EnvVar $EnvProbe "PULSE_PROBE_NMAP_PROXY_CLIENT_CERT_PATH" "/certs/nmap-proxy/client.crt"
Set-EnvVar $EnvProbe "PULSE_PROBE_NMAP_PROXY_CLIENT_KEY_PATH"  "/certs/nmap-proxy/client.key"
Write-Ok "deploy/.env.probe aggiornato + certificati client copiati."

# --- 8) Attivita' pianificata (avvio automatico) ---------------------------
Write-Step "Registrazione servizio (Scheduled Task) ad avvio automatico"
$action  = New-ScheduledTaskAction -Execute $VenvPy -Argument "-m pulse_nmap_proxy" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principalT = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principalT -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Ok "Attivita' '$TaskName' registrata e avviata."

# --- 9) Firewall + health ---------------------------------------------------
Write-Step "Regola firewall (inbound TCP $Port)"
if (-not (Get-NetFirewallRule -DisplayName "Pulse nmap proxy" -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName "Pulse nmap proxy" -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $Port -Profile Any | Out-Null
}
Write-Ok "Regola firewall presente."

Write-Step "Verifica /health"
Start-Sleep -Seconds 3
$check = @"
import ssl, json, urllib.request
ctx = ssl.create_default_context(cafile=r'$CertDir\ca.crt')
ctx.load_cert_chain(r'$CertDir\client.crt', r'$CertDir\client.key')
req = urllib.request.Request('https://localhost:$Port/health', headers={'Authorization':'Bearer $Token'})
print(urllib.request.urlopen(req, timeout=8, context=ctx).read().decode())
"@
try {
  $res = & $VenvPy -c $check
  Write-Ok "Health: $res"
} catch {
  Write-Warn2 "Health non verificabile ora: $($_.Exception.Message)"
  Write-Warn2 "Controlla l'attivita' '$TaskName' e i log Eventi se persiste."
}

Write-Host "`nCOMPLETATO." -ForegroundColor Green
Write-Host "Applica la configurazione all'agent Probe:" -ForegroundColor Green
Write-Host "  cd `"$DeployDir`"" -ForegroundColor Gray
Write-Host "  docker compose -f docker-compose.probe.yml --env-file .env.probe up -d probe-agent" -ForegroundColor Gray
Write-Host "L'agent rilevera' il proxy in automatico (status: scan_backend=proxy)." -ForegroundColor Green
