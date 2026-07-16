<#
=============================================================================
 Pulse - Installer SONDA (Docker / Podman) - Windows PowerShell
 File: deploy/probe-package/install.ps1

 Cosa fa:
   1. Rileva il runtime (docker compose | podman-compose).
   2. Verifica i prerequisiti.
   3. Copia .env.probe.example -> .env se .env non esiste (idempotente).
   4. Controlla che le variabili OBBLIGATORIE siano valorizzate.
   5. Builda e avvia lo stack (up -d --build).
   6. Attende l'health dell'agent (http://localhost:PORT/api/v1/health).
   7. Stampa i passi di verifica.

 Uso:
   ./install.ps1
   ./install.ps1 -Runtime docker
   ./install.ps1 -Runtime podman

 Idempotente. Exit code != 0 in caso di errore.
=============================================================================
#>
[CmdletBinding()]
param(
  [ValidateSet('auto','docker','podman')]
  [string]$Runtime = 'auto'
)

$ErrorActionPreference = 'Stop'
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile    = Join-Path $ScriptDir '.env'
$EnvExample = Join-Path $ScriptDir '.env.probe.example'

function Write-Info { param($m) Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

# --- 1. Rilevamento runtime ---
$ComposeArgs = $null   # array di token (es. @('docker','compose'))
$ComposeFile = $null

function Test-DockerCompose {
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    try { docker compose version *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
  }
  return $false
}
function Test-PodmanCompose {
  return [bool](Get-Command podman-compose -ErrorAction SilentlyContinue)
}

if (($Runtime -eq 'docker' -or $Runtime -eq 'auto') -and (Test-DockerCompose)) {
  $ComposeArgs = @('docker','compose')
  $ComposeFile = Join-Path $ScriptDir 'docker-compose.yml'
  Write-Ok 'Runtime rilevato: docker compose'
} elseif (($Runtime -eq 'podman' -or $Runtime -eq 'auto') -and (Test-PodmanCompose)) {
  $ComposeArgs = @('podman-compose')
  $ComposeFile = Join-Path $ScriptDir 'podman-compose.yml'
  Write-Ok 'Runtime rilevato: podman-compose'
} else {
  Write-Err 'Nessun runtime compatibile trovato.'
  Write-Err "Installare Docker (con 'docker compose') oppure podman-compose."
  exit 1
}

function Invoke-Compose {
  param([string[]]$Extra)
  $all = $ComposeArgs + @('-f', $ComposeFile, '--env-file', $EnvFile) + $Extra
  & $all[0] $all[1..($all.Count-1)]
  if ($LASTEXITCODE -ne 0) { throw "Comando compose fallito (exit $LASTEXITCODE)" }
}

# --- 3. Copia .env se manca ---
if (-not (Test-Path $EnvFile)) {
  if (-not (Test-Path $EnvExample)) { Write-Err "Template non trovato: $EnvExample"; exit 1 }
  Copy-Item $EnvExample $EnvFile
  Write-Warn "Creato $EnvFile da template. MODIFICALO (SERVER_BASE_URL, ENROLLMENT_TOKEN) e rilancia."
  exit 1
}
Write-Ok "File .env presente: $EnvFile"

# --- helper lettura .env ---
function Get-EnvValue {
  param([string]$Key)
  $line = Select-String -Path $EnvFile -Pattern "^$([regex]::Escape($Key))=" -ErrorAction SilentlyContinue | Select-Object -Last 1
  if ($null -eq $line) { return '' }
  return ($line.Line -replace "^$([regex]::Escape($Key))=", '')
}

# --- 4. Controllo variabili obbligatorie ---
$missing = $false
$serverUrl  = Get-EnvValue 'PULSE_PROBE_SERVER_BASE_URL'
$enroll     = Get-EnvValue 'PULSE_PROBE_ENROLLMENT_TOKEN'
$probeToken = Get-EnvValue 'PULSE_PROBE_PROBE_TOKEN'

if ([string]::IsNullOrWhiteSpace($serverUrl) -or $serverUrl -match 'CAMBIAMI') {
  Write-Err 'PULSE_PROBE_SERVER_BASE_URL non valorizzato (o placeholder) in .env'; $missing = $true
} else { Write-Ok "PULSE_PROBE_SERVER_BASE_URL = $serverUrl" }

if ([string]::IsNullOrWhiteSpace($enroll) -and [string]::IsNullOrWhiteSpace($probeToken)) {
  Write-Err 'Serve PULSE_PROBE_ENROLLMENT_TOKEN (monouso) oppure PULSE_PROBE_PROBE_TOKEN in .env'; $missing = $true
} elseif (-not [string]::IsNullOrWhiteSpace($enroll)) {
  Write-Ok 'PULSE_PROBE_ENROLLMENT_TOKEN presente (enrollment al primo avvio)'
} else {
  Write-Ok 'PULSE_PROBE_PROBE_TOKEN presente (token per-Sonda preconfigurato)'
}

if ($missing) { Write-Err "Configurazione incompleta: modifica $EnvFile e riprova."; exit 1 }

# --- 5. Build & up ---
Write-Info 'Avvio dello stack (build + up -d)...'
Invoke-Compose -Extra @('up','-d','--build')

# --- 6. Health ---
$port = Get-EnvValue 'PULSE_PROBE_API_PORT'; if ([string]::IsNullOrWhiteSpace($port)) { $port = '8444' }
$dash = Get-EnvValue 'PULSE_PROBE_DASH_PORT'; if ([string]::IsNullOrWhiteSpace($dash)) { $dash = '5001' }
$healthUrl = "http://localhost:$port/api/v1/health"
Write-Info "Attendo l'health dell'agent su $healthUrl (max ~120s)..."
$healthy = $false
for ($i = 0; $i -lt 40; $i++) {
  try {
    $r = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    if ($r.StatusCode -eq 200) { Write-Ok "probe-agent risponde: $healthUrl"; $healthy = $true; break }
  } catch { Start-Sleep -Seconds 3 }
}
if (-not $healthy) {
  Write-Warn 'probe-agent non ha risposto entro il timeout. Controlla i log:'
  Write-Warn ("  " + ($ComposeArgs -join ' ') + " -f `"$ComposeFile`" logs probe-agent")
}

Write-Host ''
Write-Ok 'Stack avviato. Passi di verifica:'
Write-Host "  1) Health agent:    curl http://localhost:$port/api/v1/health"
Write-Host "  2) Dashboard Sonda: http://localhost:$dash"
Write-Host "  3) Sul Server la Probe deve risultare 'online' (dashboard Sonde)."
Write-Host ("  4) Log:             " + ($ComposeArgs -join ' ') + " -f `"$ComposeFile`" logs -f probe-agent")
Write-Host ''
Write-Info 'Nota: il probe_token dell''enrollment e'' tenuto in MEMORIA dall''agent.'
Write-Info 'Un riavvio del container richiede un nuovo ENROLLMENT_TOKEN oppure una'
Write-Info 'rotazione credenziali dal Server (rotate-credentials). Vedi INSTALL.md.'
