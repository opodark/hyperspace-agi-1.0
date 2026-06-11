# ============================================================
# HyperSpace-AGI v1.0 — Setup Wizard (Windows PowerShell)
# ============================================================
#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Ok   { param($m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[!!] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "[XX] $m" -ForegroundColor Red }
function Write-Sep  { Write-Host ("─" * 48) -ForegroundColor Cyan }

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

# ── Check Docker ─────────────────────────────────────────────
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
    Write-Err "Docker non è in esecuzione. Avvia Docker Desktop e riprova."
    exit 1
}

# ── Wizard ───────────────────────────────────────────────────
Write-Host ""
Write-Sep
Write-Host " Configurazione del tuo nodo HyperSpace-AGI" -ForegroundColor White
Write-Sep

# 1. NICKNAME
Write-Host ""
Write-Host "[1/4] Scegli un nickname per questo nodo" -ForegroundColor Cyan
Write-Host "      (es: pc-luca, server-casa, workstation-marco)"
do {
    $NODE_NICKNAME = (Read-Host "      Nickname").ToLower() -replace '[^a-z0-9-]','-'
} while ($NODE_NICKNAME.Length -lt 3)

$suffix = -join ((97..122) + (48..57) | Get-Random -Count 4 | ForEach-Object {[char]$_})
$NODE_ID = "$NODE_NICKNAME-$suffix"

# 2. SECRET
Write-Host ""
Write-Host "[2/4] Cluster Secret" -ForegroundColor Cyan
Write-Host "      Tutti i nodi devono usare lo stesso secret."
Write-Host "      Lascia vuoto per disabilitare (solo sviluppo locale)."
$CLUSTER_SECRET = Read-Host "      Secret"

# 3. RAM
Write-Host ""
Write-Host "[3/4] RAM disponibile (GB)" -ForegroundColor Cyan
$DetectedRam = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Write-Host "      Rilevata: ${DetectedRam}GB"
$ramInput = Read-Host "      Conferma o inserisci valore diverso [$DetectedRam]"
$NODE_RAM_GB = if ($ramInput -eq '') { $DetectedRam } else { [int]$ramInput }

# 4. LOCATION
Write-Host ""
Write-Host "[4/4] Descrizione macchina (opzionale)" -ForegroundColor Cyan
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$DefaultLocation = "Windows - $cpu"
$locInput = Read-Host "      Descrizione [$DefaultLocation]"
$NODE_LOCATION = if ($locInput -eq '') { $DefaultLocation } else { $locInput }

# ── Riepilogo ────────────────────────────────────────────────
Write-Host ""
Write-Sep
Write-Host " Riepilogo configurazione" -ForegroundColor White
Write-Sep
Write-Host "  Nickname : $NODE_NICKNAME" -ForegroundColor White
Write-Host "  Node ID  : $NODE_ID" -ForegroundColor White
Write-Host "  Secret   : $(if ($CLUSTER_SECRET) {$CLUSTER_SECRET} else {'<nessuno>'})" -ForegroundColor White
Write-Host "  RAM      : ${NODE_RAM_GB}GB" -ForegroundColor White
Write-Host "  Location : $NODE_LOCATION" -ForegroundColor White
Write-Host ""

# ── Scrivi .env ──────────────────────────────────────────────
$envContent = @"
# HyperSpace-AGI — generato da setup.ps1 il $(Get-Date -Format 'yyyy-MM-dd HH:mm')
# NON committare questo file — e' gia' in .gitignore

NODE_NICKNAME=$NODE_NICKNAME
NODE_ID=$NODE_ID
NODE_LOCATION=$NODE_LOCATION
NODE_RAM_GB=$NODE_RAM_GB
HYPERSPACE_CLUSTER_SECRET=$CLUSTER_SECRET
NODE_TAGS=dev,windows,amd64
NODE_OWNER=$NODE_NICKNAME
"@

$envContent | Out-File -FilePath '.env' -Encoding utf8 -NoNewline
Write-Ok ".env scritto"

# ── Build & Up ───────────────────────────────────────────────
$start = Read-Host "`nAvviare i container ora? [S/n]"
if ($start -eq '' -or $start -match '^[Ss]') {
    Write-Ok "Build in corso..."
    docker compose up -d --build
    Write-Host ""
    Write-Ok "Cluster avviato! Health check:"
    Start-Sleep -Seconds 3
    try { Invoke-RestMethod http://localhost:8765/health | ConvertTo-Json }
    catch { Write-Warn "Nodo non ancora pronto, riprova tra qualche secondo." }
} else {
    Write-Host ""
    Write-Ok "Per avviare in seguito: docker compose up -d --build"
}

Write-Host ""
Write-Sep
Write-Host " HyperSpace-AGI pronto!" -ForegroundColor Green
Write-Sep
Write-Host "  Node health   : http://localhost:8765/health"
Write-Host "  Authority     : http://localhost:8766/health"
Write-Host "  Dashboard     : http://localhost:8769"
Write-Host "  WebUI Ollama  : http://localhost:8080"
Write-Host ""
