<#
.SYNOPSIS
  Disinstalla il proxy nmap di Pulse dall'host Windows.
.DESCRIPTION
  Ferma e rimuove l'attivita' pianificata, la regola firewall, la cartella di
  installazione e il materiale client copiato nel repo; azzera le variabili del
  proxy in deploy/.env.probe (l'agent tornera' automaticamente a nmap locale).
  NON disinstalla nmap/Npcap.
#>
[CmdletBinding()]
param(
  [string]$InstallDir = "$env:ProgramData\Pulse\nmap-proxy"
)
$ErrorActionPreference = "SilentlyContinue"
$TaskName = "PulseNmapProxy"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Start-Process -FilePath "powershell.exe" -Verb RunAs `
    -ArgumentList @("-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"","-InstallDir","`"$InstallDir`"")
  return
}

Write-Host "Rimozione proxy nmap Pulse..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName $TaskName
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Remove-NetFirewallRule -DisplayName "Pulse nmap proxy"
Remove-Item -Recurse -Force $InstallDir

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$EnvProbe = Join-Path $RepoRoot "deploy\.env.probe"
Remove-Item -Recurse -Force (Join-Path $RepoRoot "deploy\certs\nmap-proxy")
if (Test-Path $EnvProbe) {
  $keys = "PULSE_PROBE_NMAP_PROXY_URL","PULSE_PROBE_NMAP_PROXY_TOKEN",
          "PULSE_PROBE_NMAP_PROXY_CA_CERT_PATH","PULSE_PROBE_NMAP_PROXY_CLIENT_CERT_PATH",
          "PULSE_PROBE_NMAP_PROXY_CLIENT_KEY_PATH"
  $lines = Get-Content $EnvProbe | Where-Object {
    $keep = $true
    foreach ($k in $keys) { if ($_ -match "^\s*$([regex]::Escape($k))=") { $keep = $false } }
    $keep
  }
  Set-Content -Path $EnvProbe -Value $lines -Encoding UTF8
}
Write-Host "Fatto. Riavvia l'agent: docker compose ... up -d probe-agent (tornera' a nmap locale)." -ForegroundColor Green
