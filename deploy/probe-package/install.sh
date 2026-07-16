#!/usr/bin/env bash
# =============================================================================
# Pulse - Installer SONDA (Docker / Podman) - Linux / macOS
# File: deploy/probe-package/install.sh
#
# Cosa fa:
#   1. Rileva il runtime container disponibile (docker compose | podman-compose).
#   2. Verifica i prerequisiti.
#   3. Copia .env.probe.example -> .env se .env non esiste (idempotente).
#   4. Controlla che le variabili OBBLIGATORIE siano valorizzate.
#   5. Builda e avvia lo stack (up -d --build).
#   6. Attende l'health dell'agent (http://localhost:PORT/api/v1/health).
#   7. Stampa i passi di verifica.
#
# Uso:
#   ./install.sh                 # auto-rileva runtime
#   RUNTIME=docker ./install.sh  # forza docker
#   RUNTIME=podman ./install.sh  # forza podman
#
# Idempotente: puo' essere rieseguito senza effetti distruttivi.
# Exit code != 0 in caso di errore.
# =============================================================================
set -euo pipefail

# --- Directory dello script (per funzionare da qualunque cwd) -----------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.probe.example"

# --- Colori (se TTY) ----------------------------------------------------------
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_BLU=$'\033[34m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_BLU=""; C_RST=""
fi
info()  { echo "${C_BLU}[INFO]${C_RST} $*"; }
ok()    { echo "${C_GRN}[ OK ]${C_RST} $*"; }
warn()  { echo "${C_YEL}[WARN]${C_RST} $*"; }
err()   { echo "${C_RED}[FAIL]${C_RST} $*" >&2; }

# --- 1. Rilevamento runtime ---------------------------------------------------
COMPOSE_FILE=""
COMPOSE_CMD=""
detect_runtime() {
  local pref="${RUNTIME:-auto}"
  if { [ "$pref" = "docker" ] || [ "$pref" = "auto" ]; } \
        && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
    ok "Runtime rilevato: docker compose"
    return 0
  fi
  if { [ "$pref" = "podman" ] || [ "$pref" = "auto" ]; } \
        && command -v podman-compose >/dev/null 2>&1; then
    COMPOSE_CMD="podman-compose"
    COMPOSE_FILE="$SCRIPT_DIR/podman-compose.yml"
    ok "Runtime rilevato: podman-compose"
    return 0
  fi
  err "Nessun runtime compatibile trovato."
  err "Installare Docker (con plugin 'docker compose') oppure podman-compose."
  return 1
}

# --- 4. Controllo variabili obbligatorie -------------------------------------
# Legge una chiave dal file .env (ultima occorrenza vince).
read_env() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

check_required() {
  local missing=0
  local server_url enroll probe_token
  server_url="$(read_env PULSE_PROBE_SERVER_BASE_URL)"
  enroll="$(read_env PULSE_PROBE_ENROLLMENT_TOKEN)"
  probe_token="$(read_env PULSE_PROBE_PROBE_TOKEN)"

  if [ -z "$server_url" ] || echo "$server_url" | grep -q "CAMBIAMI"; then
    err "PULSE_PROBE_SERVER_BASE_URL non valorizzato (o placeholder) in .env"
    missing=1
  else
    ok "PULSE_PROBE_SERVER_BASE_URL = $server_url"
  fi

  if [ -z "$enroll" ] && [ -z "$probe_token" ]; then
    err "Serve PULSE_PROBE_ENROLLMENT_TOKEN (monouso) oppure PULSE_PROBE_PROBE_TOKEN in .env"
    missing=1
  elif [ -n "$enroll" ]; then
    ok "PULSE_PROBE_ENROLLMENT_TOKEN presente (enrollment al primo avvio)"
  else
    ok "PULSE_PROBE_PROBE_TOKEN presente (token per-Sonda preconfigurato)"
  fi

  if [ "$missing" -ne 0 ]; then
    err "Configurazione incompleta: modifica $ENV_FILE e riprova."
    return 1
  fi
}

# --- 6. Attesa health agent ---------------------------------------------------
wait_health() {
  local port; port="$(read_env PULSE_PROBE_API_PORT)"; port="${port:-8444}"
  local url="http://localhost:${port}/api/v1/health"
  info "Attendo l'health dell'agent su ${url} (max ~120s)..."
  local i
  for i in $(seq 1 40); do
    if command -v curl >/dev/null 2>&1; then
      if curl -sf "$url" >/dev/null 2>&1; then ok "probe-agent risponde: $url"; return 0; fi
    elif command -v wget >/dev/null 2>&1; then
      if wget -q -O /dev/null "$url"; then ok "probe-agent risponde: $url"; return 0; fi
    else
      warn "curl/wget assenti: salto il controllo HTTP dell'health."; return 0
    fi
    sleep 3
  done
  warn "probe-agent non ha risposto entro il timeout. Controlla i log:"
  warn "  $COMPOSE_CMD -f \"$COMPOSE_FILE\" logs probe-agent"
  return 1
}

main() {
  info "=== Pulse - Installazione SONDA ==="
  detect_runtime

  # --- 3. Copia .env se manca ---
  if [ ! -f "$ENV_FILE" ]; then
    if [ ! -f "$ENV_EXAMPLE" ]; then
      err "Template non trovato: $ENV_EXAMPLE"; exit 1
    fi
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    warn "Creato $ENV_FILE da template. MODIFICALO (SERVER_BASE_URL, ENROLLMENT_TOKEN) e rilancia."
    exit 1
  fi
  ok "File .env presente: $ENV_FILE"

  check_required

  # --- 5. Build & up ---
  info "Avvio dello stack (build + up -d)..."
  # shellcheck disable=SC2086
  $COMPOSE_CMD -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

  # --- 6. Health ---
  local port; port="$(read_env PULSE_PROBE_API_PORT)"; port="${port:-8444}"
  local dash; dash="$(read_env PULSE_PROBE_DASH_PORT)"; dash="${dash:-5001}"
  wait_health || true

  echo
  ok "Stack avviato. Passi di verifica:"
  echo "  1) Health agent:    curl -sf http://localhost:${port}/api/v1/health"
  echo "  2) Dashboard Sonda: http://localhost:${dash}"
  echo "  3) Sul Server la Probe deve risultare 'online' (dashboard Sonde)."
  echo "  4) Log:             $COMPOSE_CMD -f \"$COMPOSE_FILE\" logs -f probe-agent"
  echo
  info "Nota: il probe_token dell'enrollment e' tenuto in MEMORIA dall'agent."
  info "Un riavvio del container richiede un nuovo ENROLLMENT_TOKEN oppure una"
  info "rotazione credenziali dal Server (rotate-credentials). Vedi INSTALL.md."
}

main "$@"
