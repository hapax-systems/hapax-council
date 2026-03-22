# Open WebUI Optimization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fully optimize the Open WebUI installation to leverage the existing infrastructure (LiteLLM, Qdrant, Chatterbox TTS, Tavily, MCP servers) and harden for single-operator use.

**Architecture:** Open WebUI at :3080 connects to LiteLLM (:4000) for all model access, Qdrant (:6333) for RAG vectors, Chatterbox (:4123) for local TTS, and MCPO proxy for MCP tool access. All services communicate via the Docker `llm-stack_default` network using container names.

**Tech Stack:** Docker Compose, Open WebUI v0.8.x, MCPO proxy, Chatterbox TTS, Tavily API, Qdrant, bash scripting

---

### Task 1: Switch TTS to Chatterbox (Local)

The compose file currently points TTS at LiteLLM (which would route to OpenAI cloud). Chatterbox is already running locally at :4123 with an OpenAI-compatible `/v1/audio/speech` endpoint and model `chatterbox-tts-1`.

**Files:**
- Modify: `~/llm-stack/docker-compose.yml` (open-webui environment block)

**Step 1: Update TTS environment variables**

Change the open-webui environment in docker-compose.yml:
```yaml
# Replace these lines:
      AUDIO_TTS_ENGINE: "openai"
      AUDIO_TTS_OPENAI_API_BASE_URL: "http://litellm:4000/v1"
      AUDIO_TTS_OPENAI_API_KEY: "${LITELLM_MASTER_KEY}"
      AUDIO_TTS_MODEL: "tts-1"
      AUDIO_TTS_VOICE: "onyx"

# With:
      AUDIO_TTS_ENGINE: "openai"
      AUDIO_TTS_OPENAI_API_BASE_URL: "http://chatterbox:5123/v1"
      AUDIO_TTS_OPENAI_API_KEY: "unused"
      AUDIO_TTS_MODEL: "chatterbox-tts-1"
      AUDIO_TTS_VOICE: "default"
```

Note: Chatterbox internal port is 5123, not 4123 (4123 is the host-mapped port). Use the container name `chatterbox` on the Docker network.

**Step 2: Verify Chatterbox is on the same Docker network**

Run: `docker inspect chatterbox --format='{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}'`
Expected: `llm-stack_default` (same network as open-webui)

If NOT on the same network, add `networks: [default]` to the chatterbox service in docker-compose.yml, or connect it:
```bash
docker network connect llm-stack_default chatterbox
```

**Step 3: Recreate open-webui container**

Run:
```bash
cd ~/llm-stack && eval "$(direnv export zsh)" && docker compose up -d open-webui
```

**Step 4: Test TTS in the UI**

Open http://localhost:3080, send a message to any model, click the speaker icon on the response. Audio should play using local Chatterbox voice.

**Step 5: Commit**

```bash
cd ~/llm-stack && git add docker-compose.yml && git commit -m "feat: switch Open WebUI TTS to local Chatterbox"
```

---

### Task 2: Deploy MCPO Proxy for MCP Tool Access

Open WebUI v0.8.x supports MCP natively but only via Streamable HTTP transport. Our MCP servers are stdio-based. MCPO bridges this gap.

**Files:**
- Modify: `~/llm-stack/docker-compose.yml` (add mcpo service)
- Create: `~/llm-stack/mcpo-config.json`

**Step 1: Create MCPO config file**

Create `~/llm-stack/mcpo-config.json` with the MCP servers that make sense for Open WebUI chat (skip filesystem, playwright, docker — those are dev tools):

```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    },
    "tavily": {
      "command": "npx",
      "args": ["-y", "tavily-mcp@latest"],
      "env": {
        "TAVILY_API_KEY": "${TAVILY_API_KEY}"
      }
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp@latest"]
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    }
  }
}
```

**Step 2: Add MCPO service to docker-compose.yml**

Add after the open-webui service block:

```yaml
  # --- MCPO (MCP-to-OpenAPI proxy for Open WebUI) ---
  mcpo:
    image: ghcr.io/open-webui/mcpo:latest
    container_name: mcpo
    restart: unless-stopped
    logging: *default-logging
    mem_limit: 512m
    ports:
      - "127.0.0.1:8300:8000"
    volumes:
      - ./mcpo-config.json:/config.json:ro
    environment:
      TAVILY_API_KEY: "${TAVILY_API_KEY}"
    command: ["--config", "/config.json", "--port", "8000"]
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

**Step 3: Start the MCPO container**

Run:
```bash
cd ~/llm-stack && eval "$(direnv export zsh)" && docker compose up -d mcpo
```

Wait for healthy:
```bash
docker inspect mcpo --format='{{.State.Health.Status}}'
```
Expected: `healthy`

**Step 4: Verify MCPO is serving tools**

Run:
```bash
curl -s http://localhost:8300/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(list(d.get('paths',{}).keys())[:10], indent=2))"
```
Expected: List of tool endpoints

**Step 5: Register MCPO in Open WebUI**

In the browser at http://localhost:3080:
1. Go to Admin Settings (gear icon) > External Tools
2. Click + (Add Server)
3. URL: `http://mcpo:8000` (Docker network name, not localhost)
4. Type: MCP (Streamable HTTP)
5. Auth: None
6. Save

**Step 6: Test MCP tools in chat**

Start a new chat. Enable tools (toggle icon). Ask a question that would trigger a tool, e.g. "Search the web for latest COSMIC desktop news" (should use tavily).

**Step 7: Commit**

```bash
cd ~/llm-stack && git add docker-compose.yml mcpo-config.json && git commit -m "feat: add MCPO proxy for MCP tool access in Open WebUI"
```

---

### Task 3: Add Open WebUI to Backup Routine

The SQLite database at `/app/backend/data/webui.db` holds chat history, user config, and uploaded documents. Not currently backed up.

**Files:**
- Modify: `~/Scripts/setup/llm-stack-scripts/llm-stack/scripts/backup.sh`

**Step 1: Add Open WebUI backup section**

Add after the n8n workflows section (after line 81) in `backup.sh`:

```bash
# -- Open WebUI database ---------------------------------------------------------
COMPOSE_FILE="${COMPOSE_FILE:-$HOME/llm-stack/docker-compose.yml}"
if docker compose -f "$COMPOSE_FILE" ps open-webui --format json 2>/dev/null | grep -q running; then
    mkdir -p "$BACKUP_DIR/open-webui"
    docker cp open-webui:/app/backend/data/webui.db "$BACKUP_DIR/open-webui/webui.db" && \
        log "  Open WebUI database" || \
        log "  Open WebUI database copy failed"
else
    log "  Open WebUI not running, skipping"
fi
```

Note: Uses `docker cp` instead of volume mount because the SQLite DB should be copied while the container is running (SQLite handles concurrent reads safely). Do NOT use `sqlite3 .backup` since sqlite3 is not in the container.

**Step 2: Test the backup section**

Run:
```bash
cd ~/llm-stack && eval "$(<$HOME/projects/ai-agents/.envrc)" && bash ~/Scripts/setup/llm-stack-scripts/llm-stack/scripts/backup.sh /tmp/test-backup
```
Expected: Output includes "Open WebUI database" and `/tmp/test-backup/*/open-webui/webui.db` exists.

Verify:
```bash
ls -la /tmp/test-backup/*/open-webui/webui.db
```

**Step 3: Clean up test backup**

```bash
rm -rf /tmp/test-backup
```

**Step 4: Commit**

```bash
cd ~/Scripts/setup/llm-stack-scripts && git add llm-stack/scripts/backup.sh && git commit -m "feat: add Open WebUI database to backup routine"
```

---

### Task 4: Verify Qdrant RAG Integration

Qdrant is configured in the compose env vars but hasn't been tested. Verify it works end-to-end.

**Step 1: Check Open WebUI logs for Qdrant connection**

Run:
```bash
docker logs open-webui 2>&1 | grep -i -E '(qdrant|vector|chroma)' | tail -10
```
Expected: Messages about Qdrant connection, no ChromaDB fallback errors.

**Step 2: Upload a test document**

In the browser at http://localhost:3080:
1. Click the + icon in the sidebar > Knowledge
2. Create a new knowledge base called "Test"
3. Upload a small text or PDF file
4. Wait for embedding to complete (progress indicator)

**Step 3: Verify document landed in Qdrant**

Run:
```bash
curl -s http://localhost:6333/collections | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'{c[\"name\"]}: {c.get(\"points_count\",\"?\")} points') for c in d.get('result',{}).get('collections',[])]"
```
Expected: A new collection appears (Open WebUI creates collections per knowledge base).

**Step 4: Test RAG retrieval in chat**

Start a new chat with any model. Attach the "Test" knowledge base (# icon). Ask a question about the uploaded document content. Verify the model references the document.

**Step 5: Clean up test knowledge base**

Delete the "Test" knowledge base from the sidebar to keep things clean.

---

### Task 5: Verify Tavily Web Search

Web search is configured but untested.

**Step 1: Check web search is enabled in admin**

In browser at http://localhost:3080:
1. Admin Settings > RAG (or Documents)
2. Verify Web Search is toggled ON
3. Verify engine shows "Tavily"

**Step 2: Test web search in chat**

Start a new chat with any model (Claude recommended for tool use). Type a query with `+` prefix:
```
+What are the latest features in COSMIC desktop epoch 1?
```

Expected: Model performs a web search, shows search results indicator, and includes web-sourced information in response.

**Step 3: Check logs for search activity**

Run:
```bash
docker logs open-webui 2>&1 | grep -i tavily | tail -5
```
Expected: API call logs, no auth errors.

---

### Task 6: Configure Model Display Names

LiteLLM exposes many model aliases. Clean up the model selector in Open WebUI to show friendly names.

**Step 1: Open model management**

In browser at http://localhost:3080:
1. Admin Settings > Models
2. You should see all models from LiteLLM listed

**Step 2: Set display names and descriptions for primary models**

For each of these models, click edit and set:

| Model ID | Display Name | Description |
|----------|-------------|-------------|
| `claude-sonnet` | Claude Sonnet | Fast, capable — daily driver |
| `claude-opus` | Claude Opus | Deep reasoning, complex tasks |
| `claude-haiku` | Claude Haiku | Quick, cheap tasks |
| `gemini-flash` | Gemini Flash | Fast iteration, large context |
| `gemini-pro` | Gemini Pro | Google's flagship |
| `qwen-coder-32b` | Qwen Coder 32B (local) | Code generation, private |
| `qwen-7b` | Qwen 7B (local) | Lightweight local tasks |

**Step 3: Hide unnecessary model aliases**

Models like `anthropic/*` wildcards, version-specific aliases (e.g. `claude-sonnet-4-5-20250514`), and `nomic-embed` (embedding-only) clutter the selector. For each unwanted model:
1. Click the model
2. Toggle "Hidden" or set visibility to admin-only

**Step 4: Set default model**

Admin Settings > General > Default Model: set to `claude-sonnet` (the balanced default).

---

### Task 7: Customize Open WebUI Settings

Fine-tune admin and user settings for the single-operator workflow.

**Step 1: General settings**

In Admin Settings > General:
- Default model: `claude-sonnet`
- Enable community sharing: OFF

**Step 2: Interface settings**

In Admin Settings > Interface (or User Settings > Interface):
- Default: dark mode (matches COSMIC theme)
- Chat bubble UI: choose preferred layout
- Show model selector in chat: ON
- Rich text input: ON

**Step 3: Enable native tools**

In Admin Settings > Features (or wherever tool toggles are):
- Web Search: ON (already configured)
- Code Interpreter: ON if available (sandboxed execution)
- Memory: ON (Open WebUI's built-in conversation memory)

**Step 4: Set system prompt default**

User Settings > General > System Prompt:
```
You are a helpful assistant. Be concise and direct. Use markdown formatting. When uncertain, say so rather than speculating. Route through available tools (web search, code execution) when they would improve the answer.
```

---

### Task 8: Update Docker Image (if needed)

The current image is from 2026-03-02. If a newer version is available, update.

**Step 1: Check for updates**

Run:
```bash
docker pull ghcr.io/open-webui/open-webui:main 2>&1 | tail -3
```

If output says "Image is up to date" — skip to Step 4.
If output shows "Downloaded newer image" — continue.

**Step 2: Get new digest**

Run:
```bash
docker inspect ghcr.io/open-webui/open-webui:main --format='{{index .RepoDigests 0}}'
```

Update the image line in `~/llm-stack/docker-compose.yml`:
```yaml
image: ghcr.io/open-webui/open-webui:main@sha256:<NEW_DIGEST>
```

**Step 3: Backup before upgrade**

Run:
```bash
docker cp open-webui:/app/backend/data/webui.db /tmp/webui-pre-upgrade.db
```

**Step 4: Recreate with new image**

Run:
```bash
cd ~/llm-stack && eval "$(direnv export zsh)" && docker compose up -d open-webui
```

**Step 5: Verify health**

Run:
```bash
for i in $(seq 1 20); do health=$(docker inspect --format='{{.State.Health.Status}}' open-webui 2>/dev/null); echo "$i: $health"; [ "$health" = "healthy" ] && break; sleep 3; done
```

**Step 6: Smoke test**

Open http://localhost:3080, verify login works, send a test message, confirm models load.

**Step 7: Commit if image was updated**

```bash
cd ~/llm-stack && git add docker-compose.yml && git commit -m "chore: update Open WebUI image to latest"
```

---

## Execution Order

Tasks 1-3 are infrastructure changes (compose + backup). Tasks 4-5 are verification only. Tasks 6-7 are UI configuration. Task 8 is maintenance.

Recommended order: 1 → 2 → 3 → 8 → 4 → 5 → 6 → 7

Tasks 4+5 (verification) and 6+7 (UI config) can be done in parallel if desired.

## Out of Scope (deferred)

- **Image generation (ComfyUI/DALL-E):** Requires separate ComfyUI deployment and VRAM management strategy. Do as a separate project.
- **Pipelines container:** Only needed for custom Python processing. Deploy when a specific use case arises.
- **Chunk size tuning:** Current 512/50 defaults are reasonable. Tune after real RAG usage reveals needs.
