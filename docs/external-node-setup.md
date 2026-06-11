# Setup Nodo Esterno via Tailscale

Guida per connettere un nodo HyperSpace-AGI da una macchina remota
alla rete P2P tramite Tailscale VPN.

---

## Prerequisiti

- Docker + Docker Compose installati
- Account Tailscale gratuito su [tailscale.com](https://tailscale.com)
- Stesso account Tailscale del nodo principale (o invito da admin)
- Git

---

## Step 1 — Installa Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# segui il link per autenticarti
```

Recupera il tuo IP Tailscale:
```bash
tailscale ip -4
# esempio: 100.64.2.5
```

Verifica connettività con l'Authority (chiedi l'IP a Alberto):
```bash
curl http://<IP_ALBERTO>:8766/health
# deve rispondere: {"status": "ok", "service": "authority"}
```

---

## Step 2 — Clona il repo e configura

```bash
git clone https://github.com/opodark/hyperspace-agi-1.0
cd hyperspace-agi-1.0
```

Modifica `docker-compose.external-node.yml` — cambia solo le righe marcate con ★:

```yaml
- NODE_ID=node-fr              # ID univoco del tuo nodo
- NODE_HOST=100.64.2.5         # ★ tuo IP Tailscale
- NODE_NICKNAME=server-france  # nome nella Peer Map
- NODE_LOCATION=Paris, FR      # posizione
- NODE_COLOR=#ef4444           # colore card (hex)
- NODE_RAM_GB=16               # ★ RAM disponibile
- AUTHORITY_URL=http://100.64.1.1:8766  # ★ IP Tailscale di Alberto
```

---

## Step 3 — Avvia

```bash
docker compose -f docker-compose.external-node.yml up -d --build
```

---

## Step 4 — Verifica

```bash
# health del nodo locale
curl http://localhost:8765/health | python3 -m json.tool

# verifica registrazione sull'Authority
curl http://<IP_ALBERTO>:8766/peers | python3 -m json.tool
# deve apparire il tuo node_id nella lista

# stato auto-pull modelli
curl http://localhost:8765/auto-pull/status | python3 -m json.tool
```

Se tutto ok, il nodo appare nella **Peer Map** della dashboard con il tuo avatar. 🚀

---

## Troubleshooting

| Problema | Causa probabile | Fix |
|---|---|---|
| `curl authority` timeout | Tailscale non connesso | `sudo tailscale up` |
| Nodo non appare in Peer Map | `NODE_HOST` errato | Controlla `tailscale ip -4` |
| Gossip fallisce | Firewall blocca porta | `sudo ufw allow 8765` |
| Auto-pull non parte | `NODE_RAM_GB` mancante | Aggiungi la variabile env |
| Disco pieno | Versione vecchia auto_pull | Aggiorna il repo con `git pull` |

---

## Aggiornamenti

```bash
git pull
docker compose -f docker-compose.external-node.yml up -d --build node
```
