# ============================================================
# HyperSpace-AGI v1.0 — Setup Wizard (Windows PowerShell)
# ============================================================
#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Ok   { param($m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[!!] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "[XX] $m" -ForegroundColor Red }
function Write-Sep  { Write-Host ("━" * 48) -ForegroundColor Cyan }

Clear-Host
Write-Host @"
  _   _                      ____
 | | | |_   _ _ __   ___ _ _/ ___| _ __   __ _  ___ ___
 | |_| | | | | '_ \ / _ \ '__\___ \| '_ \ / _' |/ __/ _ \
 |  _  | |_| | |_) |  __/ |   ___) | |_) | (_| | (_|  __/
 |_| |_|\__, | .__/ \___|_|  |____/| .__/ \__,_|\___\___|
        |___/|_|                   |_|
         AGI v1.0 — Setup Wizard (Windows)
"@ -ForegroundColor Cyan

# ── Tailscale hostname (auto-detect) ───────────────────────
$MyTailscaleHost = ''
try {
    $tsJson = tailscale status --json 2>$null
    $tsStatus = $tsJson | ConvertFrom-Json
    $MyTailscaleHost = $tsStatus.Self.DNSName.TrimEnd('.')
    if ($MyTailscaleHost -ne '') { Write-Ok "Tailscale rilevato: $MyTailscaleHost" }
} catch {}

# ── Check Docker ───────────────────────────────────────────
try {
    $dv = (docker --version) 2>&1
    Write-Ok "Docker trovato: $dv"
} catch {
    Write-Err "Docker non trovato. Installalo da https://docs.docker.com/desktop/windows/"
    exit 1
}
try {
    docker info 2>&1 | Out-Null
    Write-Ok "Docker in esecuzione"
} catch {
    Write-Err "Docker non e' in esecuzione. Avvia Docker Desktop e riprova."
    exit 1
}

# ── Wizard ─────────────────────────────────────────────────
Write-Host ""
Write-Sep
Write-Host " Configurazione del tuo nodo HyperSpace-AGI" -ForegroundColor White
Write-Sep

# 1. NICKNAME
Write-Host ""
Write-Host "[1/5] Scegli un nickname per questo nodo" -ForegroundColor Cyan
Write-Host "      (es: pc-luca, server-casa, workstation-marco)"
do {
    $NODE_NICKNAME = (Read-Host "      Nickname").ToLower() -replace '[^a-z0-9-]','-'
} while ($NODE_NICKNAME.Length -lt 3)
$suffix = -join ((97..122) + (48..57) | Get-Random -Count 4 | ForEach-Object {[char]$_})
$NODE_ID = "$NODE_NICKNAME-$suffix"

# 2. SECRET
Write-Host ""
Write-Host "[2/5] Cluster Secret" -ForegroundColor Cyan
Write-Host "      Tutti i nodi devono usare lo stesso secret."
Write-Host "      Lascia vuoto per disabilitare (solo sviluppo locale)."
$CLUSTER_SECRET = Read-Host "      Secret"

# 3. RAM
Write-Host ""
Write-Host "[3/5] RAM disponibile (GB)" -ForegroundColor Cyan
$DetectedRam = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Write-Host "      Rilevata: ${DetectedRam}GB"
$ramInput = Read-Host "      Conferma o inserisci valore diverso [$DetectedRam]"
$NODE_RAM_GB = if ($ramInput -eq '') { $DetectedRam } else { [int]$ramInput }

# 4. LOCATION
Write-Host ""
Write-Host "[4/5] Descrizione macchina (opzionale)" -ForegroundColor Cyan
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$DefaultLocation = "Windows - $cpu"
$locInput = Read-Host "      Descrizione [$DefaultLocation]"
$NODE_LOCATION = if ($locInput -eq '') { $DefaultLocation } else { $locInput }

# 5. AUTHORITY URL
Write-Host ""
Write-Host "[5/5] Authority URL — nodo principale della rete" -ForegroundColor Cyan
Write-Host "      • Sei il NODO PRINCIPALE? → lascia vuoto (premi Invio)"
Write-Host "      • Sei un NODO SECONDARIO? → inserisci l'URL del nodo principale"
Write-Host ""
if ($MyTailscaleHost -ne '') {
    Write-Host "      Tailscale rilevato — il tuo hostname e':" -ForegroundColor Yellow
    Write-Host "        http://${MyTailscaleHost}:8766" -ForegroundColor White
    Write-Host "      Comunica questo URL al collega per il passo [5/5]" -ForegroundColor Yellow
    Write-Host ""
}
Write-Host "      Esempi:"
Write-Host "        http://macbook-alberto.tail12345.ts.net:8766   (Tailscale)"
Write-Host "        http://192.168.1.10:8766                       (LAN)"
Write-Host ""
$AUTHORITY_URL_INPUT = Read-Host "      Authority URL [vuoto = sono il nodo principale]"

$IS_MAIN_NODE = $false
if ($AUTHORITY_URL_INPUT -eq '') {
    $IS_MAIN_NODE = $true
    $AUTHORITY_URL = 'http://authority:8766'
    Write-Ok "Ruolo: NODO PRINCIPALE"
} else {
    $AUTHORITY_URL = $AUTHORITY_URL_INPUT
    Write-Ok "Ruolo: NODO SECONDARIO -> Authority: $AUTHORITY_URL"
}

# ── Riepilogo ───────────────────────────────────────────────
Write-Host ""
Write-Sep
Write-Host " Riepilogo configurazione" -ForegroundColor White
Write-Sep
Write-Host "  Nickname  : $NODE_NICKNAME"
Write-Host "  Node ID   : $NODE_ID"
Write-Host "  Secret    : $(if ($CLUSTER_SECRET) {$CLUSTER_SECRET} else {'<nessuno>'})"
Write-Host "  RAM       : ${NODE_RAM_GB}GB"
Write-Host "  Location  : $NODE_LOCATION"
Write-Host "  Authority : $AUTHORITY_URL"
Write-Host "  Ruolo     : $(if ($IS_MAIN_NODE) {'Nodo Principale'} else {'Nodo Secondario'})"
Write-Host ""

# ── Scrivi .env ─────────────────────────────────────────────
$envContent = @"
# HyperSpace-AGI — generato da setup.ps1 il $(Get-Date -Format 'yyyy-MM-dd HH:mm')
# NON committare questo file

# Identita'
NODE_NICKNAME=$NODE_NICKNAME
NODE_ID=$NODE_ID
NODE_LOCATION=$NODE_LOCATION
NODE_RAM_GB=$NODE_RAM_GB
NODE_TAGS=dev,windows,amd64
NODE_OWNER=$NODE_NICKNAME

# Sicurezza
HYPERSPACE_CLUSTER_SECRET=$CLUSTER_SECRET

# Discovery
AUTHORITY_URL=$AUTHORITY_URL
"@
$envContent | Out-File -FilePath '.env' -Encoding utf8 -NoNewline
Write-Ok ".env scritto"

# ── Suggerimento per il collega (nodo principale con Tailscale) ──
if ($IS_MAIN_NODE -and $MyTailscaleHost -ne '') {
    Write-Host ""
    Write-Sep
    Write-Host " Da comunicare al collega" -ForegroundColor Yellow
    Write-Sep
    Write-Host "  Al passo [5/5] del suo setup deve inserire:"
    Write-Host ""
    Write-Host "    http://${MyTailscaleHost}:8766" -ForegroundColor Green
    Write-Host ""
}

# ── Build & Up ──────────────────────────────────────────────
$start = Read-Host "`nAvviare i container ora? [S/n]"
if ($start -eq '' -or $start -match '^[Ss]') {
    Write-Ok "Build in corso..."
    if ($IS_MAIN_NODE) {
        docker compose up -d --build
    } else {
        docker compose -f docker-compose.external-node.yml up -d --build
    }
    Write-Host ""
    Write-Ok "Health check:"
    Start-Sleep -Seconds 3
    try { Invoke-RestMethod http://localhost:8765/health | ConvertTo-Json }
    catch { Write-Warn "Nodo non ancora pronto, riprova tra qualche secondo." }
} else {
    Write-Host ""
    if ($IS_MAIN_NODE) {
        Write-Ok "Per avviare: docker compose up -d --build"
    } else {
        Write-Ok "Per avviare: docker compose -f docker-compose.external-node.yml up -d --build"
    }
}

Write-Host ""
Write-Sep
Write-Host " HyperSpace-AGI pronto!" -ForegroundColor Green
Write-Sep
Write-Host "  Node health : http://localhost:8765/health"
if ($IS_MAIN_NODE) {
    Write-Host "  Authority   : http://localhost:8766/health"
    Write-Host "  Dashboard   : http://localhost:8769"
    Write-Host "  WebUI       : http://localhost:8080"
}
Write-Host ""
