#!/usr/bin/env bash
# ============================================================
# HyperSpace-AGI v1.0 — Setup Wizard (macOS / Linux)
# ============================================================
# NON usiamo set -e perche' echo/printf con caratteri speciali
# puo' ritornare exit code non-zero su alcuni terminali Linux
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { printf "${GREEN}[OK]${NC} %s\n" "$*" || true; }
warn() { printf "${YELLOW}[!!]${NC} %s\n" "$*" || true; }
err()  { printf "${RED}[XX]${NC} %s\n" "$*" >&2 || true; }
sep()  { printf "%s\n" "-----------------------------------------------" || true; }

clear || true
printf "${CYAN}"
cat <<'BANNER'
  _   _                      ____
 | | | |_   _ _ __   ___ _ _/ ___| _ __   __ _  ___ ___
 | |_| | | | | '_ \ / _ \ '__\___ \| '_ \ / _` |/ __/ _ \
 |  _  | |_| | |_) |  __/ |   ___) | |_) | (_| | (_|  __/
 |_| |_|\__, | .__/ \___|_|  |____/| .__/ \__,_|\___\___|
        |___/|_|                   |_|
         AGI v1.0 - Setup Wizard
BANNER
printf "${NC}\n"

# -- Detect OS -----------------------------------------------
OS_TYPE="linux"
if [[ "$(uname)" == "Darwin" ]]; then
  OS_TYPE="macos"
fi
log "Sistema rilevato: ${OS_TYPE}"

# -- Tailscale hostname (auto-detect) ------------------------
MY_TAILSCALE_HOST=""
if command -v tailscale &>/dev/null; then
  MY_TAILSCALE_HOST=$(tailscale status --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Self',{}).get('DNSName','').rstrip('.'))" 2>/dev/null || true)
  if [[ -n "$MY_TAILSCALE_HOST" ]]; then
    log "Tailscale rilevato: ${MY_TAILSCALE_HOST}"
  fi
fi

# -- Check Docker --------------------------------------------
if ! command -v docker &>/dev/null; then
  err "Docker non trovato. Installalo da https://docs.docker.com/get-docker/"
  exit 1
fi
if ! docker info &>/dev/null; then
  err "Docker non e' in esecuzione. Avvialo e riprova."
  exit 1
fi
log "Docker OK ($(docker --version | cut -d' ' -f3 | tr -d ','))"

# -- Wizard --------------------------------------------------
printf "\n"
sep
printf " Configurazione del tuo nodo HyperSpace-AGI\n"
sep
printf "\n"

# 1. NICKNAME
printf "${CYAN}[1/5] Scegli un nickname per questo nodo${NC}\n"
printf "      (es: macbook-alberto, server-casa, workstation-marco)\n"
while true; do
  printf "      Nickname: "
  read -r NODE_NICKNAME
  NODE_NICKNAME=$(echo "$NODE_NICKNAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g')
  if [[ ${#NODE_NICKNAME} -ge 3 ]]; then
    break
  fi
  warn "Nickname troppo corto (min 3 caratteri)"
done
NODE_ID="${NODE_NICKNAME}-$(cat /dev/urandom | LC_ALL=C tr -dc 'a-z0-9' | head -c4)"
printf "\n"

# 2. CLUSTER SECRET
printf "${CYAN}[2/5] Cluster Secret${NC}\n"
printf "      Tutti i nodi della rete devono usare lo stesso secret.\n"
printf "      Lascia vuoto per disabilitare (solo sviluppo locale).\n"
printf "      Secret: "
read -r CLUSTER_SECRET
printf "\n"

# 3. RAM
printf "${CYAN}[3/5] RAM disponibile su questa macchina (GB)${NC}\n"
if [[ "$OS_TYPE" == "macos" ]]; then
  DETECTED_RAM=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
else
  DETECTED_RAM=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
fi
printf "      Rilevata: %sGB\n" "$DETECTED_RAM"
printf "      Conferma o inserisci valore diverso [%s]: " "$DETECTED_RAM"
read -r NODE_RAM_GB
NODE_RAM_GB=${NODE_RAM_GB:-$DETECTED_RAM}
printf "\n"

# 4. LOCATION
printf "${CYAN}[4/5] Descrizione macchina (opzionale)${NC}\n"
printf "      (es: MacBook Air M5, Ubuntu Server, Workstation RTX 4090)\n"
if [[ "$OS_TYPE" == "macos" ]]; then
  CHIP=$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Chip/{print $2}' | xargs || echo "Apple Silicon")
  DEFAULT_LOCATION="macOS - ${CHIP}"
else
  DEFAULT_LOCATION="Linux - $(uname -m)"
fi
printf "      Descrizione [%s]: " "$DEFAULT_LOCATION"
read -r NODE_LOCATION
NODE_LOCATION=${NODE_LOCATION:-$DEFAULT_LOCATION}
printf "\n"

# 5. AUTHORITY URL — discovery automatico P2P
printf "${CYAN}[5/5] Authority URL - nodo principale della rete${NC}\n"
printf "      - Sei il NODO PRINCIPALE? -> lascia vuoto (premi Invio)\n"
printf "      - Sei un NODO SECONDARIO? -> inserisci l'URL del nodo principale\n"
printf "\n"
if [[ -n "$MY_TAILSCALE_HOST" ]]; then
  printf "      ${YELLOW}Tailscale rilevato - il tuo hostname e':${NC}\n"
  printf "        http://%s:8766\n" "$MY_TAILSCALE_HOST"
  printf "      ${YELLOW}Comunica questo URL al collega per il passo [5/5]${NC}\n"
  printf "\n"
fi
printf "      Esempi:\n"
printf "        http://macbook-alberto.tail12345.ts.net:8766   (Tailscale)\n"
printf "        http://192.168.1.10:8766                       (LAN)\n"
printf "\n"
printf "      Authority URL [vuoto = sono il nodo principale]: "
read -r AUTHORITY_URL_INPUT
printf "\n"

IS_MAIN_NODE=false
if [[ -z "$AUTHORITY_URL_INPUT" ]]; then
  IS_MAIN_NODE=true
  AUTHORITY_URL="http://authority:8766"
  log "Ruolo: NODO PRINCIPALE"
else
  AUTHORITY_URL="$AUTHORITY_URL_INPUT"
  log "Ruolo: NODO SECONDARIO -> Authority: ${AUTHORITY_URL}"
fi

# -- Riepilogo -----------------------------------------------
printf "\n"
sep
printf " Riepilogo configurazione\n"
sep
printf "  Nickname  : %s\n" "$NODE_NICKNAME"
printf "  Node ID   : %s\n" "$NODE_ID"
printf "  Secret    : %s\n" "${CLUSTER_SECRET:-<nessuno>}"
printf "  RAM       : %sGB\n" "$NODE_RAM_GB"
printf "  Location  : %s\n" "$NODE_LOCATION"
printf "  Authority : %s\n" "$AUTHORITY_URL"
if $IS_MAIN_NODE; then
  printf "  Ruolo     : Nodo Principale\n"
else
  printf "  Ruolo     : Nodo Secondario\n"
fi
printf "\n"

# -- Scrivi .env ---------------------------------------------
cat > .env <<EOF
# HyperSpace-AGI - generato da setup.sh il $(date)
# NON committare questo file - e' gia' in .gitignore

# Identita
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

log ".env scritto"

# -- Suggerimento per il collega (nodo principale con Tailscale) --
if $IS_MAIN_NODE && [[ -n "$MY_TAILSCALE_HOST" ]]; then
  printf "\n"
  sep
  printf " Da comunicare al collega\n"
  sep
  printf "  Al passo [5/5] del suo setup deve inserire:\n\n"
  printf "    http://%s:8766\n\n" "$MY_TAILSCALE_HOST"
fi

# -- Build & Up ----------------------------------------------
printf "Avviare i container ora? [S/n]: "
read -r START
START=${START:-S}
if [[ "$START" =~ ^[Ss]$ ]]; then
  log "Build in corso..."
  if $IS_MAIN_NODE; then
    docker compose up -d --build
  else
    docker compose -f docker-compose.external-node.yml up -d --build
  fi
  printf "\n"
  log "Health check:"
  sleep 3
  curl -s http://localhost:8765/health | python3 -m json.tool 2>/dev/null || \
    printf "(nodo non ancora pronto, riprova tra qualche secondo)\n"
else
  printf "\n"
  if $IS_MAIN_NODE; then
    log "Per avviare: docker compose up -d --build"
  else
    log "Per avviare: docker compose -f docker-compose.external-node.yml up -d --build"
  fi
fi

printf "\n"
sep
printf " HyperSpace-AGI pronto!\n"
sep
printf "  Node health : http://localhost:8765/health\n"
if $IS_MAIN_NODE; then
  printf "  Authority   : http://localhost:8766/health\n"
  printf "  Dashboard   : http://localhost:8769\n"
  printf "  WebUI       : http://localhost:8080\n"
fi
printf "\n"
