#!/usr/bin/env bash
# =============================================================================
# Pulse - Disinstallazione SONDA (Docker / Podman) - Linux / macOS
# File: deploy/probe-package/uninstall.sh
#
# Ferma e rimuove lo stack della Sonda.
#
# Uso:
#   ./uninstall.sh            # down (mantiene il volume dati OpenSearch)
#   ./uninstall.sh --volumes  # down + rimozione volumi (CANCELLA i dati!)
#   RUNTIME=podman ./uninstall.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_RST=""
fi
ok()   { echo "${C_GRN}[ OK ]${C_RST} $*"; }
warn() { echo "${C_YEL}[WARN]${C_RST} $*"; }
err()  { echo "${C_RED}[FAIL]${C_RST} $*" >&2; }

REMOVE_VOLUMES=0
for arg in "$@"; do
  case "$arg" in
    --volumes|-v) REMOVE_VOLUMES=1 ;;
    *) err "Argomento non riconosciuto: $arg"; exit 2 ;;
  esac
done

COMPOSE_CMD=""; COMPOSE_FILE=""
pref="${RUNTIME:-auto}"
if { [ "$pref" = "docker" ] || [ "$pref" = "auto" ]; } \
      && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"; COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
elif { [ "$pref" = "podman" ] || [ "$pref" = "auto" ]; } \
      && command -v podman-compose >/dev/null 2>&1; then
  COMPOSE_CMD="podman-compose"; COMPOSE_FILE="$SCRIPT_DIR/podman-compose.yml"
else
  err "Nessun runtime compatibile trovato (docker compose / podman-compose)."; exit 1
fi
ok "Runtime: $COMPOSE_CMD"

DOWN_ARGS=(down --remove-orphans)
if [ "$REMOVE_VOLUMES" -eq 1 ]; then
  warn "Rimozione volumi ABILITATA: i dati OpenSearch verranno CANCELLATI."
  DOWN_ARGS+=(--volumes)
fi

# shellcheck disable=SC2086
$COMPOSE_CMD -f "$COMPOSE_FILE" "${DOWN_ARGS[@]}"
ok "Stack Sonda rimosso."
[ "$REMOVE_VOLUMES" -eq 1 ] && ok "Volumi rimossi (dati cancellati)." || warn "Volume dati mantenuto (usa --volumes per rimuoverlo)."
