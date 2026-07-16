<#
=============================================================================
 Pulse - Disinstallazione SONDA (Docker / Podman) - Windows PowerShell
 File: deploy/probe-package/uninstall.ps1

 Ferma e rimuove lo stack della Sonda.

 Uso:
   ./uninstall.ps1                 # down (mantiene il volume dati OpenSearch)
   ./uninstall.ps1 -Volumes        # down + rimozione volumi (CANCELLA i dati!)
   ./uninstall.ps1 -Runtime podman
=============================================================================
#>
[CmdletBinding()]
param(
  [ValidateSet('auto','docker','podman')]
  [string]$Runtime = 'auto',
  [switch]$Volumes
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Ok   { param($m) Write-Host "[ OK ] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red }

function Test-DockerCompose {
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    try { docker compose version *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
  }
  return $false
}

$ComposeArgs = $null; $ComposeFile = $null
if (($Runtime -eq 'docker' -or $Runtime -eq 'auto') -and (Test-DockerCompose)) {
  $ComposeArgs = @('docker','compose'); $ComposeFile = Join-Path $ScriptDir 'docker-compose.yml'
} elseif (($Runtime -eq 'podman' -or $Runtime -eq 'auto') -and (Get-Command podman-compose -ErrorAction SilentlyContinue)) {
  $ComposeArgs = @('podman-compose'); $ComposeFile = Join-Path $ScriptDir 'podman-compose.yml'
} else {
  Write-Err 'Nessun runtime compatibile trovato (docker compose / podman-compose).'; exit 1
}
Write-Ok ("Runtime: " + ($ComposeArgs -join ' '))

$extra = @('down','--remove-orphans')
if ($Volumes) {
  Write-Warn 'Rimozione volumi ABILITATA: i dati OpenSearch verranno CANCELLATI.'
  $extra += '--volumes'
}

$all = $ComposeArgs + @('-f', $ComposeFile) + $extra
& $all[0] $all[1..($all.Count-1)]
if ($LASTEXITCODE -ne 0) { Write-Err "Comando down fallito (exit $LASTEXITCODE)"; exit $LASTEXITCODE }

Write-Ok 'Stack Sonda rimosso.'
if ($Volumes) { Write-Ok 'Volumi rimossi (dati cancellati).' } else { Write-Warn 'Volume dati mantenuto (usa -Volumes per rimuoverlo).' }
