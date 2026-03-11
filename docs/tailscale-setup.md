# Tailscale Setup Guide

Tailscale provides secure remote access to localhost services via WireGuard mesh VPN. Once configured, Open WebUI, n8n, ntfy, and Langfuse are accessible from your phone and other devices without port forwarding or dynamic DNS.

## Prerequisites

- Tailscale account (free personal plan: 100 devices)
- Android phone for mobile access

## 1. Install Tailscale on Host

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Follow the authentication URL printed to terminal. This registers your machine on your Tailnet.

Verify:
```bash
tailscale status
# Should show your machine as online
```

## 2. Install Tailscale on Android

1. Install Tailscale from Google Play / F-Droid
2. Sign in with the same account
3. Both devices should appear in `tailscale status`

## 3. Configure `tailscale serve` for Services

Expose localhost services via Tailscale's built-in reverse proxy (HTTPS with auto-certs):

```bash
# Open WebUI — primary mobile chat interface
sudo tailscale serve --bg --https=443 http://localhost:3080

# n8n — workflow automation (webhooks need to be reachable)
sudo tailscale serve --bg --https=5678 http://localhost:5678

# ntfy — push notification server
sudo tailscale serve --bg --https=8090 http://localhost:8090

# Langfuse — observability (optional, for monitoring from other devices)
sudo tailscale serve --bg --https=3000 http://localhost:3000
```

Verify from your phone's browser:
```
https://<your-machine>.tail<your-net>.ts.net/          → Open WebUI
https://<your-machine>.tail<your-net>.ts.net:5678/     → n8n
https://<your-machine>.tail<your-net>.ts.net:8090/     → ntfy
https://<your-machine>.tail<your-net>.ts.net:3000/     → Langfuse
```

To view current serve configuration:
```bash
tailscale serve status
```

## 4. Services NOT Exposed

These services remain localhost-only (internal plumbing, not user-facing):

| Service | Port | Reason |
|---------|------|--------|
| LiteLLM | 4000 | API gateway — agents access directly |
| PostgreSQL | 5432 | Database — no remote access needed |
| Qdrant | 6333 | Vector DB — agents access directly |
| Ollama | 11434 | LLM inference — routed via LiteLLM |
| ClickHouse | 8123 | Langfuse backend — no direct access |
| Redis | 6379 | Langfuse cache — internal only |
| MinIO | 9090 | S3 storage — internal only |

## 5. Firewall / ACL (Optional)

Tailscale ACLs can restrict which devices reach which services:

```json
{
  "acls": [
    {"action": "accept", "src": ["autogroup:member"], "dst": ["*:443", "*:5678", "*:8090", "*:3000"]}
  ]
}
```

Configure at: https://login.tailscale.com/admin/acls

## 6. ntfy on Android

1. Install ntfy from F-Droid (no Google Play Services dependency)
2. Add subscription:
   - Topic URL: `https://<your-machine>.tail<your-net>.ts.net:8090/cockpit`
3. Test: `curl -d "Hello from setup" http://localhost:8090/cockpit`
4. Your phone should buzz with the notification

## 7. Verify End-to-End

```bash
# From desktop
tailscale status                                    # Both devices online
curl https://<machine>.tail<net>.ts.net/health      # Open WebUI via Tailscale

# From phone browser
# Navigate to https://<machine>.tail<net>.ts.net/   # Open WebUI login

# Push notification
curl -H "Title: Test" -d "Setup complete" http://localhost:8090/cockpit
```

## Troubleshooting

```bash
# Check Tailscale daemon
sudo systemctl status tailscaled

# Check serve config
tailscale serve status

# DNS resolution
tailscale status --json | jq '.Self.DNSName'

# Network debug
tailscale ping <other-device>
tailscale netcheck
```

## Systemd Integration

Tailscale installs its own systemd service (`tailscaled.service`). It starts automatically on boot. The health monitor checks Tailscale via `tailscale status --json` in the `connectivity` check group.
