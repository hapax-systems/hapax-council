# n8n Workflows

This directory contains exported n8n workflow JSON files for the multi-channel access layer. These workflows bridge the agent system to mobile (Telegram) and webhook-triggered notifications.

All workflows are tagged `multi-channel` and designed to run inside the n8n Docker container, which mounts `ai-agents/` at `/data/ai-agents/` (read-only) and `rag-sources/` at `/data/rag-sources/` (read-write).

## Workflows

### briefing-push.json

**Purpose:** Sends the daily briefing to Telegram in a mobile-friendly format. Extracts the headline and action items from `profiles/briefing.md` and formats them for Telegram Markdown.

**Trigger:** Schedule — daily at 07:15 (runs 15 minutes after the briefing agent generates the file at 07:00).

**Flow:** Schedule Trigger -> Read Briefing (shell: `cat profiles/briefing.md`) -> Format for Mobile (JS: extract headline + action items) -> Send Telegram.

**Credentials needed:**
- `telegramApi` — Telegram Bot API token (create via @BotFather)

**Environment variables:**
- `TELEGRAM_CHAT_ID` — target chat/user ID for the bot

---

### nudge-digest.json

**Purpose:** Periodically checks the briefing file for high-priority action items and sends a reminder digest to Telegram. Only sends if there are items marked `[!!]` (high priority). Caps at 3 items per message.

**Trigger:** Schedule — every 2 hours from 09:00 to 23:00.

**Flow:** Schedule Trigger -> Read Briefing File (shell) -> Filter High-Priority Actions (JS: extract `[!!]` items, skip if none) -> Send Telegram.

**Credentials needed:**
- `telegramApi` — Telegram Bot API token

**Environment variables:**
- `TELEGRAM_CHAT_ID` — target chat/user ID

---

### quick-capture.json

**Purpose:** Telegram bot that accepts commands from the operator's mobile device. Supports five commands:

| Command | Action |
|---------|--------|
| `/note <text>` (or plain text) | Saves a markdown note with YAML frontmatter to `rag-sources/captures/` for RAG ingestion |
| `/ask <question>` | Forwards to LiteLLM (claude-haiku) and replies with the response |
| `/health` | Reads last health check from `profiles/health-history.jsonl` and formats status |
| `/goals` | Reads `profiles/operator.json` and returns the first 50 lines |
| `/briefing` | Reads `profiles/briefing.md` and returns the first 50 lines |

**Trigger:** Telegram Trigger — fires on any incoming message to the bot.

**Flow:** Telegram Trigger -> Route Command (JS: parse command) -> Switch on Command -> (4 branches: note, ask, health, info).

**Credentials needed:**
- `telegramApi` — Telegram Bot API token

**Environment variables:**
- `TELEGRAM_CHAT_ID` — target chat/user ID (used in some reply nodes)
- `LITELLM_MASTER_KEY` — API key for LiteLLM gateway (used by the `/ask` branch)

---

### health-relay.json

**Purpose:** Receives health alert webhooks (from the health-monitor watchdog via `shared/notify.py send_webhook()`) and forwards them to Telegram. Formats the alert with status emoji and urgency level.

**Trigger:** Webhook — `POST /webhook/health-relay`. Responds with `{"ok": true, "status": "..."}`.

**Flow:** Health Webhook (POST) -> Format Alert (JS: emoji + urgency mapping) -> Send Alert (Telegram) -> Respond OK (webhook response).

**Credentials needed:**
- `telegramApi` — Telegram Bot API token

**Environment variables:**
- `TELEGRAM_CHAT_ID` — target chat/user ID

---

## Import Steps

1. Open n8n at `http://localhost:5678`
2. Go to **Workflows** -> **Import from File**
3. Select the `.json` file to import
4. After import, configure credentials:
   - Go to **Settings** -> **Credentials** -> **Add Credential** -> **Telegram API**
   - Enter the Bot API token from @BotFather
5. Set environment variables in the n8n container (via Docker Compose `.env` or n8n's **Settings** -> **Variables**):
   - `TELEGRAM_CHAT_ID`: your Telegram user/chat ID (get via @userinfobot)
   - `LITELLM_MASTER_KEY`: the LiteLLM API key (only needed for quick-capture)
6. In each imported workflow, open the Telegram nodes and select the configured credential
7. Activate the workflow

## Credential Summary

| Credential | Type | Used By | How to Obtain |
|-----------|------|---------|---------------|
| Telegram Bot API | `telegramApi` | All 4 workflows | Create bot via @BotFather on Telegram |

| Environment Variable | Used By | Source |
|---------------------|---------|--------|
| `TELEGRAM_CHAT_ID` | All 4 workflows | Send `/start` to @userinfobot on Telegram |
| `LITELLM_MASTER_KEY` | quick-capture | `pass show litellm/master-key` |
