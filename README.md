# HyperSpace-AGI v1.0

> Framework per agenti IA distribuiti con Small Language Models, eseguiti localmente tramite Docker + Ollama.

[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-required-blue.svg)](https://docs.docker.com/get-docker/)
[![Ollama](https://img.shields.io/badge/Ollama-local%20inference-green.svg)](https://ollama.ai)

---

## Quickstart

### 1. Clona il repo

```bash
git clone https://github.com/opodark/hyperspace-agi-1.0.git
cd hyperspace-agi-1.0
```

### 2. Esegui il Setup Wizard

Il wizard ti chiede **nickname**, **cluster secret** e **RAM disponibile**, poi genera automaticamente il file `.env` e avvia i container.

**macOS / Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

**Windows (PowerShell):**
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\setup.ps1
```

> Il wizard rileva automaticamente RAM e sistema operativo. Ti verrà chiesto solo il **nickname** (il nome con cui il tuo nodo apparirà nella rete).

---

## Configurazione manuale (alternativa)

Se preferisci configurare manualmente:

```bash
cp .env.example .env
# modifica .env con i tuoi valori
nano .env
docker compose up -d --build
```

### Variabili principali in `.env`

| Variabile | Descrizione | Esempio |
|---|---|---|
| `NODE_NICKNAME` | Nome scelto da te per il nodo | `macbook-alberto` |
| `NODE_ID` | ID univoco (generato dal wizard) | `macbook-alberto-ab12` |
| `NODE_LOCATION` | Descrizione della macchina | `MacBook Air M5` |
| `NODE_RAM_GB` | RAM disponibile in GB | `16` |
| `HYPERSPACE_CLUSTER_SECRET` | Secret condiviso tra tutti i nodi | `ABRACADABRA` |

---

## Architettura

```
┌─────────────────────────────────────────────────────┐
│                  HyperSpace-AGI v1.0                │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐ │
│  │  Node    │  │Authority │  │   Control Plane   │ │
│  │ :8765    │  │  :8766   │  │      :8768        │ │
│  │          │  │          │  │                   │ │
│  │ Agent    │  │ Policy   │  │ Smart Routing     │ │
│  │ Memory   │  │ Catalog  │  │ 4-Level           │ │
│  │ Dreams   │  │ Registry │  │                   │ │
│  └──────────┘  └──────────┘  └───────────────────┘ │
│       │              │               │             │
│  ┌────▼──────────────▼───────────────▼──────────┐  │
│  │              Ollama :11434                    │  │
│  │     (qwen2.5, gemma4, phi-3, mistral…)        │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌──────────┐  ┌──────────┐                        │
│  │ Worker   │  │Dashboard │                        │
│  │  :8767   │  │  :8769   │                        │
│  └──────────┘  └──────────┘                        │
└─────────────────────────────────────────────────────┘
```

### Servizi

| Servizio | Porta | Descrizione |
|---|---|---|
| **Node** | 8765 | Agente principale — chat, memoria, dreams, gossip P2P |
| **Authority** | 8766 | Policy engine, model catalog, node registry |
| **Worker** | 8767 | Validazione dreams, memoria contestata |
| **Control Plane** | 8768 | Smart routing multi-livello |
| **Dashboard** | 8769 | Interfaccia web di monitoraggio |
| **Ollama** | 11434 | Inferenza locale LLM |
| **WebUI** | 8080 | Interfaccia Ollama (Open WebUI) |

---

## Aggiungere un nodo esterno alla rete

Su una seconda macchina (es. Ubuntu server, PC colleghi):

```bash
git clone https://github.com/opodark/hyperspace-agi-1.0.git
cd hyperspace-agi-1.0
./setup.sh
# Inserisci lo stesso CLUSTER_SECRET del nodo principale
# e l'IP del nodo principale quando richiesto
docker compose -f docker-compose.external-node.yml up -d --build
```

---

## Endpoint principali

```bash
# Stato del nodo
curl http://localhost:8765/health | python3 -m json.tool

# Stato dell'authority
curl http://localhost:8766/health | python3 -m json.tool

# Lista nodi registrati
curl http://localhost:8766/peers

# Catalogo modelli
curl http://localhost:8766/catalog

# Chat con un agente
curl -X POST http://localhost:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "test-01", "message": "Ciao!"}'

# Status auto-pull modelli
curl http://localhost:8765/auto-pull/status
```

---

## Requisiti

- **Docker** >= 24 con Docker Compose v2
- **RAM minima**: 8GB (consigliati 16GB+)
- **Spazio disco**: ~10GB per i modelli base
- **OS**: macOS (Intel/Apple Silicon), Linux (x86/ARM), Windows 10/11

---

## Modelli supportati

Selezionati automaticamente in base alla RAM disponibile:

| Modello | RAM richiesta | Ruolo |
|---|---|---|
| `qwen2.5:3b` | 4GB | agent (bassa RAM) |
| `qwen2.5:7b` | 8GB | agent |
| `qwen2.5-coder:7b` | 8GB | coder |
| `phi-3:mini` | 4GB | reasoning leggero |
| `mistral:7b` | 8GB | agent alternativo |
| `qwen2.5:32b` | 24GB | agent avanzato |
| `gemma4:27b` | 20GB | reasoning avanzato |

---

## Sicurezza

Il `HYPERSPACE_CLUSTER_SECRET` protegge gli endpoint P2P interni (`/gossip/`, `/dreams/`, `/peers/announce`). Gli endpoint pubblici (`/health`, `/chat`, `/catalog`) rimangono sempre accessibili.

Per reti esposte su internet, usa sempre un secret robusto e metti i nodi dietro una VPN (es. Tailscale).

---

## Changelog

Vedi [CHANGELOG.md](CHANGELOG.md)

---

## License

MIT — vedi [LICENSE](LICENSE)
