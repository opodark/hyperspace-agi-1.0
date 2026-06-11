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

# ── Detect OS ──────────────────────────────────────────────
OS_TYPE="linux"
if [[ "$(uname)" == "Darwin" ]]; then
  OS_TYPE="macos"
fi
log "Sistema rilevato: ${OS_TYPE}"

# ── Tailscale hostname (auto-detect) ───────────────────────
MY_TAILSCALE_HOST=""
if command -v tailscale &>/dev/null; then
  MY_TAILSCALE_HOST=$(tailscale status --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Self',{}).get('DNSName','').rstrip('.'))" 2>/dev/null || true)
  if [[ -n "$MY_TAILSCALE_HOST" ]]; then
    log "Tailscale rilevato: ${MY_TAILSCALE_HOST}"
  fi
fi

# ── Check Docker ───────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  err "Docker non trovato. Installalo da https://docs.docker.com/get-docker/"
  exit 1
fi
if ! docker info &>/dev/null; then
  err "Docker non è in esecuzione. Avvialo e riprova."
  exit 1
fi
log "Docker OK ($(docker --version | cut -d' ' -f3 | tr -d ','))"

# ── Wizard ─────────────────────────────────────────────────
echo ""
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bold " Configurazione del tuo nodo HyperSpace-AGI"
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. NICKNAME
echo -e "${CYAN}[1/5] Scegli un nickname per questo nodo${NC}"
echo -e "      (es: macbook-alberto, server-casa, workstation-marco)"
while true; do
  read -rp "      Nickname: " NODE_NICKNAME
  NODE_NICKNAME=$(echo "$NODE_NICKNAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g')
  if [[ ${#NODE_NICKNAME} -ge 3 ]]; then
    break
  fi
  warn "Nickname troppo corto (min 3 caratteri)"
done
NODE_ID="${NODE_NICKNAME}-$(cat /dev/urandom | LC_ALL=C tr -dc 'a-z0-9' | head -c4)"
echo ""

# 2. CLUSTER SECRET
echo -e "${CYAN}[2/5] Cluster Secret${NC}"
echo -e "      Tutti i nodi della rete devono usare lo stesso secret."
echo -e "      Lascia vuoto per disabilitare (solo sviluppo locale)."
read -rp "      Secret: " CLUSTER_SECRET
echo ""

# 3. RAM
echo -e "${CYAN}[3/5] RAM disponibile su questa macchina (GB)${NC}"
if [[ "$OS_TYPE" == "macos" ]]; then
  DETECTED_RAM=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
else
  DETECTED_RAM=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
fi
echo -e "      Rilevata: ${BOLD}${DETECTED_RAM}GB${NC}"
read -rp "      Conferma o inserisci valore diverso [${DETECTED_RAM}]: " NODE_RAM_GB
NODE_RAM_GB=${NODE_RAM_GB:-$DETECTED_RAM}
echo ""

# 4. LOCATION
echo -e "${CYAN}[4/5] Descrizione macchina (opzionale)${NC}"
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

# 5. AUTHORITY URL — discovery automatico P2P
echo -e "${CYAN}[5/5] Authority URL — nodo principale della rete${NC}"
echo -e "      • Sei il NODO PRINCIPALE? → lascia vuoto (premi Invio)"
echo -e "      • Sei un NODO SECONDARIO? → inserisci l'URL del nodo principale"
echo ""
if [[ -n "$MY_TAILSCALE_HOST" ]]; then
  echo -e "      ${YELLOW}Tailscale rilevato — il tuo hostname è:${NC}"
  echo -e "      ${BOLD}  http://${MY_TAILSCALE_HOST}:8766${NC}"
  echo -e "      ${YELLOW}↑ Comunica questo URL al collega per il passo [5/5]${NC}"
  echo ""
fi
echo -e "      Esempi:"
echo -e "        http://macbook-alberto.tail12345.ts.net:8766   (Tailscale)"
echo -e "        http://192.168.1.10:8766                       (LAN)"
echo ""
read -rp "      Authority URL [vuoto = sono il nodo principale]: " AUTHORITY_URL_INPUT
echo ""

IS_MAIN_NODE=false
if [[ -z "$AUTHORITY_URL_INPUT" ]]; then
  IS_MAIN_NODE=true
  AUTHORITY_URL="http://authority:8766"
  log "Ruolo: NODO PRINCIPALE ✅"
else
  AUTHORITY_URL="$AUTHORITY_URL_INPUT"
  log "Ruolo: NODO SECONDARIO → Authority: ${AUTHORITY_URL}"
fi

# ── Riepilogo ───────────────────────────────────────────────
echo ""
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bold " Riepilogo configurazione"
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Nickname  : ${BOLD}${NODE_NICKNAME}${NC}"
echo -e "  Node ID   : ${BOLD}${NODE_ID}${NC}"
echo -e "  Secret    : ${BOLD}${CLUSTER_SECRET:-<nessuno>}${NC}"
echo -e "  RAM       : ${BOLD}${NODE_RAM_GB}GB${NC}"
echo -e "  Location  : ${BOLD}${NODE_LOCATION}${NC}"
echo -e "  Authority : ${BOLD}${AUTHORITY_URL}${NC}"
echo -e "  Ruolo     : ${BOLD}$(if $IS_MAIN_NODE; then echo 'Nodo Principale 🏠'; else echo 'Nodo Secondario 🔗'; fi)${NC}"
echo ""

# ── Scrivi .env ─────────────────────────────────────────────
cat > .env <<EOF
# HyperSpace-AGI — generato da setup.sh il $(date)
# NON committare questo file — è già in .gitignore

# Identità
NODE_NICKNAME=${NODE_NICKNAME}
NODE_ID=${NODE_ID}
NODE_LOCATION=${NODE_LOCATION}
NODE_RAM_GB=${NODE_RAM_GB}
NODE_TAGS=dev,$(uname | tr '[:upper:]' '[:lower:]'),$(uname -m)
NODE_OWNER=${NODE_NICKNAME}

# Sicurezza
HYPERSPACE_CLUSTER_SECRET=${CLUSTER_SECRET}

# Discovery
AUTHORITY_URL=${AUTHORITY_URL}
EOF

log ".env scritto ✅"

# ── Suggerimento per il collega (nodo principale con Tailscale) ──
if $IS_MAIN_NODE && [[ -n "$MY_TAILSCALE_HOST" ]]; then
  echo ""
  bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  bold " 📋 Da comunicare al collega"
  bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo -e "  Al passo [5/5] del suo setup deve inserire:"
  echo ""
  echo -e "  ${BOLD}  http://${MY_TAILSCALE_HOST}:8766${NC}"
  echo ""
fi

# ── Build & Up ──────────────────────────────────────────────
read -rp "Avviare i container ora? [S/n]: " START
START=${START:-S}
if [[ "$START" =~ ^[Ss]$ ]]; then
  log "Build in corso..."
  if $IS_MAIN_NODE; then
    docker compose up -d --build
  else
    docker compose -f docker-compose.external-node.yml up -d --build
  fi
  echo ""
  log "Health check:"
  sleep 3
  curl -s http://localhost:8765/health | python3 -m json.tool 2>/dev/null || \
    echo "(nodo non ancora pronto, riprova tra qualche secondo)"
else
  echo ""
  if $IS_MAIN_NODE; then
    log "Per avviare: docker compose up -d --build"
  else
    log "Per avviare: docker compose -f docker-compose.external-node.yml up -d --build"
  fi
fi

echo ""
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bold " HyperSpace-AGI pronto 🚀"
bold "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Node health : http://localhost:8765/health"
if $IS_MAIN_NODE; then
  echo -e "  Authority   : http://localhost:8766/health"
  echo -e "  Dashboard   : http://localhost:8769"
  echo -e "  WebUI       : http://localhost:8080"
fi
echo ""
