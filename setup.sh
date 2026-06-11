#!/usr/bin/env bash
# ============================================================
# HyperSpace-AGI v1.0 — Setup Wizard (macOS / Linux)
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${GREEN}✔${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✖${NC}  $*" >&2; }
bold() { echo -e "${BOLD}$*${NC}"; }

clear
echo -e "${CYAN}"
cat <<'BANNER'
  _   _                      ____
 | | | |_   _ _ __   ___ _ _/ ___| _ __   __ _  ___ ___
 | |_| | | | | '_ \ / _ \ '__\___ \| '_ \ / _` |/ __/ _ \
 |  _  | |_| | |_) |  __/ |   ___) | |_) | (_| | (_|  __/
 |_| |_|\__, | .__/ \___|_|  |____/| .__/ \__,_|\___\___|
        |___/|_|                   |_|
         AGI v1.0 — Setup Wizard
BANNER
echo -e "${NC}"

# ── Detect OS ────────────────────────────────────────────────
OS_TYPE="linux"
if [[ "$(uname)" == "Darwin" ]]; then
  OS_TYPE="macos"
fi
log "Sistema rilevato: ${OS_TYPE}"

# ── Check Docker ─────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  err "Docker non trovato. Installalo da https://docs.docker.com/get-docker/"
  exit 1
fi
if ! docker info &>/dev/null; then
  err "Docker non è in esecuzione. Avvialo e riprova."
  exit 1
fi
log "Docker OK ($(docker --version | cut -d' ' -f3 | tr -d ','))"

# ── Wizard ───────────────────────────────────────────────────
echo ""
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bold " Configurazione del tuo nodo HyperSpace-AGI"
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. NICKNAME
echo -e "${CYAN}[1/4] Scegli un nickname per questo nodo${NC}"
echo -e "      (es: macbook-alberto, server-casa, workstation-marco)"
while true; do
  read -rp "      Nickname: " NODE_NICKNAME
  NODE_NICKNAME=$(echo "$NODE_NICKNAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g')
  if [[ ${#NODE_NICKNAME} -ge 3 ]]; then
    break
  fi
  warn "Nickname troppo corto (min 3 caratteri)"
done

# 2. NODE_ID (dal nickname + suffisso random)
NODE_ID="${NODE_NICKNAME}-$(cat /dev/urandom | LC_ALL=C tr -dc 'a-z0-9' | head -c4)"
echo ""

# 3. CLUSTER SECRET
echo -e "${CYAN}[2/4] Cluster Secret${NC}"
echo -e "      Tutti i nodi della rete devono usare lo stesso secret."
echo -e "      Lascia vuoto per disabilitare (solo sviluppo locale)."
read -rp "      Secret: " CLUSTER_SECRET
echo ""

# 4. RAM
echo -e "${CYAN}[3/4] RAM disponibile su questa macchina (GB)${NC}"
if [[ "$OS_TYPE" == "macos" ]]; then
  DETECTED_RAM=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
else
  DETECTED_RAM=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
fi
echo -e "      Rilevata: ${BOLD}${DETECTED_RAM}GB${NC}"
read -rp "      Conferma o inserisci valore diverso [${DETECTED_RAM}]: " NODE_RAM_GB
NODE_RAM_GB=${NODE_RAM_GB:-$DETECTED_RAM}
echo ""

# 5. LOCATION (opzionale)
echo -e "${CYAN}[4/4] Descrizione macchina (opzionale)${NC}"
echo -e "      (es: MacBook Air M5, Ubuntu Server, Workstation RTX 4090)"
if [[ "$OS_TYPE" == "macos" ]]; then
  CHIP=$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Chip/{print $2}' | xargs || echo "Apple Silicon")
  DEFAULT_LOCATION="macOS - ${CHIP}"
else
  DEFAULT_LOCATION="Linux - $(uname -m)"
fi
read -rp "      Descrizione [${DEFAULT_LOCATION}]: " NODE_LOCATION
NODE_LOCATION=${NODE_LOCATION:-$DEFAULT_LOCATION}
echo ""

# ── Scrivi .env ──────────────────────────────────────────────
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bold " Riepilogo configurazione"
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Nickname : ${BOLD}${NODE_NICKNAME}${NC}"
echo -e "  Node ID  : ${BOLD}${NODE_ID}${NC}"
echo -e "  Secret   : ${BOLD}${CLUSTER_SECRET:-<nessuno>}${NC}"
echo -e "  RAM      : ${BOLD}${NODE_RAM_GB}GB${NC}"
echo -e "  Location : ${BOLD}${NODE_LOCATION}${NC}"
echo ""

cat > .env <<EOF
# HyperSpace-AGI — generato da setup.sh il $(date)
# NON committare questo file — è già in .gitignore

NODE_NICKNAME=${NODE_NICKNAME}
NODE_ID=${NODE_ID}
NODE_LOCATION=${NODE_LOCATION}
NODE_RAM_GB=${NODE_RAM_GB}
HYPERSPACE_CLUSTER_SECRET=${CLUSTER_SECRET}
NODE_TAGS=dev,$(uname | tr '[:upper:]' '[:lower:]'),$(uname -m)
NODE_OWNER=${NODE_NICKNAME}
EOF

log ".env scritto ✅"

# ── Build & Up ───────────────────────────────────────────────
read -rp "\nAvviare i container ora? [S/n]: " START
START=${START:-S}
if [[ "$START" =~ ^[Ss]$ ]]; then
  log "Build in corso..."
  docker compose up -d --build
  echo ""
  log "Cluster avviato! Health check:"
  sleep 3
  curl -s http://localhost:8765/health | python3 -m json.tool 2>/dev/null || \
    echo "(nodo non ancora pronto, riprova tra qualche secondo)"
else
  echo ""
  log "Per avviare in seguito: docker compose up -d --build"
fi

echo ""
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bold " HyperSpace-AGI pronto 🚀"
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Node health   : http://localhost:8765/health"
echo -e "  Authority     : http://localhost:8766/health"
echo -e "  Dashboard     : http://localhost:8769"
echo -e "  WebUI Ollama  : http://localhost:8080"
echo ""
