# Open WebUI Integrations Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect Open WebUI to the remaining stack components — Obsidian vault, existing RAG documents, n8n workflows, and ComfyUI image generation — to make it a unified interface for the entire system.

**Architecture:** Five integrations, ordered by value/effort ratio. Each is independent — failures in one don't block others. The Obsidian sync and Qdrant filter run inside Open WebUI (no new containers). n8n tools use a Workspace Tool (no new container). ComfyUI is a new profiled service sharing the GPU with Ollama.

**Tech Stack:** Open WebUI Functions/Filters, Python (uv), systemd timers, Docker Compose, ComfyUI, n8n webhooks

---

### Task 1: Obsidian Vault as Knowledge Base

Sync the Obsidian vault (`~/Documents/Personal/`) into Open WebUI as a searchable knowledge collection. Vectors go into Qdrant via Open WebUI's configured embedding pipeline (nomic-embed-text-v2-moe, 768d).

**Files:**
- Create: `~/projects/distro-work/scripts/sync-obsidian-to-webui.py`
- Create: `~/.config/systemd/user/obsidian-webui-sync.service`
- Create: `~/.config/systemd/user/obsidian-webui-sync.timer`

**Step 1: Generate an Open WebUI API key**

In browser at http://localhost:3080:
1. User Settings (click avatar) > Account > API Keys
2. Click "Create new secret key"
3. Copy the key
4. Store it: `pass insert webui/api-key` and paste

**Step 2: Add API key to llm-stack .envrc**

Add to `~/llm-stack/.envrc`:
```bash
export WEBUI_API_KEY="$(pass show webui/api-key 2>/dev/null || echo '')"
```

Run: `cd ~/llm-stack && direnv allow`

**Step 3: Write the sync script**

Create `~/projects/distro-work/scripts/sync-obsidian-to-webui.py`:

```python
#!/usr/bin/env python3
"""Sync Obsidian vault markdown files to Open WebUI knowledge base.

Tracks file hashes to only upload new/changed files. Designed to run
on a systemd timer for incremental sync.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

VAULT_PATH = Path(os.environ.get("OBSIDIAN_VAULT_PATH", Path.home() / "Documents/Personal"))
WEBUI_URL = os.environ.get("WEBUI_URL", "http://127.0.0.1:3080")
WEBUI_API_KEY = os.environ["WEBUI_API_KEY"]
STATE_FILE = Path(os.environ.get("SYNC_STATE_FILE", Path.home() / ".cache/obsidian-webui-sync/state.json"))
KB_NAME = "Obsidian Vault"

# Directories to skip (relative to vault root)
SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", ".smart-connections"}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"kb_id": None, "files": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_headers() -> dict:
    return {"Authorization": f"Bearer {WEBUI_API_KEY}"}


def find_or_create_kb(client: httpx.Client) -> str:
    """Find existing KB by name or create new one."""
    resp = client.get(f"{WEBUI_URL}/api/v1/knowledge/", headers=get_headers())
    resp.raise_for_status()
    for kb in resp.json():
        if kb.get("name") == KB_NAME:
            return kb["id"]

    resp = client.post(
        f"{WEBUI_URL}/api/v1/knowledge/create",
        headers={**get_headers(), "Content-Type": "application/json"},
        json={"name": KB_NAME, "description": "Synced from Obsidian vault"},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def upload_file(client: httpx.Client, path: Path) -> str | None:
    """Upload a file and return its ID, or None on failure."""
    try:
        with open(path, "rb") as f:
            resp = client.post(
                f"{WEBUI_URL}/api/v1/files/",
                headers=get_headers(),
                files={"file": (path.name, f, "text/markdown")},
            )
        resp.raise_for_status()
        return resp.json()["id"]
    except Exception as e:
        print(f"  FAIL upload {path.name}: {e}", file=sys.stderr)
        return None


def wait_for_processing(client: httpx.Client, file_id: str, timeout: int = 60) -> bool:
    """Poll until file processing completes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = client.get(
                f"{WEBUI_URL}/api/v1/files/{file_id}",
                headers=get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            meta = data.get("meta", {})
            if meta.get("collection_name"):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def add_to_kb(client: httpx.Client, kb_id: str, file_id: str) -> bool:
    """Add a processed file to the knowledge base."""
    try:
        resp = client.post(
            f"{WEBUI_URL}/api/v1/knowledge/{kb_id}/file/add",
            headers={**get_headers(), "Content-Type": "application/json"},
            json={"file_id": file_id},
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  FAIL add to KB: {e}", file=sys.stderr)
        return False


def collect_markdown_files(vault: Path) -> list[Path]:
    """Walk vault and collect .md files, skipping excluded dirs."""
    files = []
    for path in vault.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.relative_to(vault).parts):
            continue
        if path.stat().st_size == 0:
            continue
        files.append(path)
    return sorted(files)


def main() -> None:
    state = load_state()

    with httpx.Client(timeout=60.0) as client:
        kb_id = state.get("kb_id") or find_or_create_kb(client)
        state["kb_id"] = kb_id

        md_files = collect_markdown_files(VAULT_PATH)
        print(f"Found {len(md_files)} markdown files in vault")

        uploaded = 0
        skipped = 0
        failed = 0

        for path in md_files:
            rel = str(path.relative_to(VAULT_PATH))
            current_hash = file_hash(path)

            if state["files"].get(rel) == current_hash:
                skipped += 1
                continue

            print(f"  Syncing: {rel}")
            file_id = upload_file(client, path)
            if not file_id:
                failed += 1
                continue

            if not wait_for_processing(client, file_id):
                print(f"  TIMEOUT processing: {rel}", file=sys.stderr)
                failed += 1
                continue

            if add_to_kb(client, kb_id, file_id):
                state["files"][rel] = current_hash
                uploaded += 1
            else:
                failed += 1

            save_state(state)

        # Remove state entries for deleted files
        vault_rels = {str(p.relative_to(VAULT_PATH)) for p in md_files}
        removed = [r for r in state["files"] if r not in vault_rels]
        for r in removed:
            del state["files"][r]

        save_state(state)
        print(f"Done: {uploaded} uploaded, {skipped} unchanged, {failed} failed, {len(removed)} removed from state")


if __name__ == "__main__":
    main()
```

**Step 4: Test the sync script**

Run:
```bash
cd ~/projects/distro-work && \
  WEBUI_API_KEY="$(pass show webui/api-key)" \
  OBSIDIAN_VAULT_PATH="$HOME/Documents/Personal" \
  uv run --with httpx scripts/sync-obsidian-to-webui.py
```

Expected: Files start uploading. Check http://localhost:3080 sidebar for "Obsidian Vault" knowledge base.

Note: First run may take a while depending on vault size. Subsequent runs only sync changed files.

**Step 5: Create systemd timer for recurring sync**

Create `~/.config/systemd/user/obsidian-webui-sync.service`:
```ini
[Unit]
Description=Sync Obsidian vault to Open WebUI
After=network-online.target
OnFailure=notify-failure@%n.service

[Service]
Type=oneshot
ExecStart=/home/hapaxlegomenon/.local/bin/uv run --with httpx /home/hapaxlegomenon/projects/distro-work/scripts/sync-obsidian-to-webui.py
WorkingDirectory=/home/hapaxlegomenon/projects/distro-work
Environment=PATH=/home/hapaxlegomenon/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/hapaxlegomenon
Environment=GNUPGHOME=/home/hapaxlegomenon/.gnupg
Environment=PASSWORD_STORE_DIR=/home/hapaxlegomenon/.password-store
Environment=WEBUI_URL=http://127.0.0.1:3080
Environment=OBSIDIAN_VAULT_PATH=/home/hapaxlegomenon/Documents/Personal
ExecStartPre=/bin/bash -c 'export WEBUI_API_KEY="$(pass show webui/api-key)"'
MemoryMax=512M
SyslogIdentifier=obsidian-webui-sync
```

Create `~/.config/systemd/user/obsidian-webui-sync.timer`:
```ini
[Unit]
Description=Sync Obsidian vault to Open WebUI every 6 hours

[Timer]
OnCalendar=*-*-* 00/6:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

Enable:
```bash
systemctl --user daemon-reload
systemctl --user enable --now obsidian-webui-sync.timer
```

**Step 6: Commit**

```bash
cd ~/projects/distro-work && git add scripts/sync-obsidian-to-webui.py && git commit -m "feat: add Obsidian vault to Open WebUI sync script"
```

---

### Task 2: Qdrant Documents Collection Filter

Create a built-in Filter Function that queries the existing `documents` Qdrant collection (populated by the rag-pipeline) and injects relevant context into every chat message. This bridges the rag-pipeline's ingested documents with Open WebUI chat.

**Files:**
- UI-only: paste code into Admin Panel > Functions

**Step 1: Create the filter function**

In browser at http://localhost:3080:
1. Admin Panel > Functions > "+" button
2. Set type to "Filter"
3. Paste this code:

```python
"""
title: Qdrant RAG Context Filter
author: hapax
version: 1.0
description: Queries existing Qdrant documents collection and injects context.
requirements: qdrant-client, httpx
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class Filter:
    class Valves(BaseModel):
        pipelines: List[str] = ["*"]
        priority: int = 0
        qdrant_url: str = Field(default="http://qdrant:6333")
        collection_name: str = Field(default="documents")
        ollama_url: str = Field(default="http://ollama:11434")
        embedding_model: str = Field(default="nomic-embed-text-v2-moe")
        top_k: int = Field(default=5)
        score_threshold: float = Field(default=0.3)
        enabled: bool = Field(default=True)

    def __init__(self):
        self.valves = self.Valves()

    async def _get_embedding(self, text: str) -> List[float]:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.valves.ollama_url}/api/embed",
                json={"model": self.valves.embedding_model, "input": f"search_query: {text}"},
            )
            response.raise_for_status()
            return response.json()["embeddings"][0]

    async def _query_qdrant(self, embedding: List[float]) -> list:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=self.valves.qdrant_url)
        results = client.query_points(
            collection_name=self.valves.collection_name,
            query=embedding,
            limit=self.valves.top_k,
            score_threshold=self.valves.score_threshold,
        )
        return results.points

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.enabled:
            return body
        messages = body.get("messages", [])
        if not messages:
            return body

        user_message = None
        for msg in reversed(messages):
            if msg["role"] == "user":
                user_message = msg["content"]
                break
        if not user_message or not isinstance(user_message, str):
            return body

        try:
            embedding = await self._get_embedding(user_message)
            points = await self._query_qdrant(embedding)
            if not points:
                return body

            parts = []
            for pt in points:
                payload = pt.payload or {}
                text = payload.get("text", payload.get("content", payload.get("chunk", "")))
                source = payload.get("source", payload.get("filename", "unknown"))
                if text:
                    parts.append(f"[Source: {source}]\n{text}")
            if not parts:
                return body

            context = "\n\n---\n\n".join(parts)
            system_msg = {
                "role": "system",
                "content": f"Relevant context from knowledge base:\n\n{context}\n\nUse this context if relevant to the user's question.",
            }
            insert_idx = 0
            for i, msg in enumerate(messages):
                if msg["role"] == "system":
                    insert_idx = i + 1
            messages.insert(insert_idx, system_msg)
            body["messages"] = messages
        except Exception as e:
            print(f"[Qdrant RAG Filter] Error: {e}")

        return body

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        return body
```

4. Save the function
5. Toggle it ON for all models (or specific models you want RAG-enhanced)

**Step 2: Test the filter**

Start a chat with any model. Ask a question about a topic covered by documents in your `documents` Qdrant collection. The response should include information from those documents.

Check logs:
```bash
docker logs open-webui 2>&1 | grep -i "qdrant\|RAG Filter" | tail -5
```

**Step 3: Tune valves if needed**

In Admin Panel > Functions > Qdrant RAG Context Filter > gear icon:
- Adjust `top_k` (fewer = faster, more = richer context)
- Adjust `score_threshold` (higher = only very relevant matches)
- Toggle `enabled` to quickly disable without removing

---

### Task 3: n8n Workflow Tools (Workspace Tool)

Create a Workspace Tool that lets chat trigger n8n workflows via webhook. Start with a system health check workflow as proof of concept. No extra container needed.

**Files:**
- UI-only: paste code into Workspace > Tools
- n8n: create webhook workflow

**Step 1: Create an n8n webhook workflow**

In browser at http://localhost:5678:
1. Create new workflow: "System Health Check"
2. Add a Webhook node:
   - Method: POST
   - Path: `system-health`
   - Authentication: Header Auth
   - Create credential: Header Name = `X-N8N-Key`, Value = generate a secret
   - Response: Last Node
3. Add an Execute Command node after the webhook:
   - Command: `curl -sf http://host.docker.internal:3080/health && echo "webui:ok" || echo "webui:down"`
   - (Or whatever health checks make sense)
4. Wire Webhook → Execute Command
5. Activate the workflow

Store the webhook auth key:
```bash
pass insert n8n/webhook-key
```

**Step 2: Create the Workspace Tool**

In browser at http://localhost:3080:
1. Workspace > Tools > "+" (Create)
2. Paste:

```python
"""
title: n8n Workflow Tools
description: Trigger n8n automation workflows from chat
version: 0.1.0
requirements: requests
"""

import requests
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        n8n_url: str = Field(default="http://n8n:5678", description="n8n base URL")
        n8n_key: str = Field(default="", description="Webhook auth header value")

    def __init__(self):
        self.valves = self.Valves()

    def check_system_health(self) -> str:
        """
        Run a system health check via the n8n automation workflow.
        Returns the current status of all monitored services.
        """
        resp = requests.post(
            f"{self.valves.n8n_url}/webhook/system-health",
            json={},
            headers={"X-N8N-Key": self.valves.n8n_key},
            timeout=30,
        )
        resp.raise_for_status()
        return str(resp.json())

    def run_backup(self) -> str:
        """
        Trigger the LLM stack backup workflow via n8n.
        Returns the backup status and location.
        """
        resp = requests.post(
            f"{self.valves.n8n_url}/webhook/run-backup",
            json={},
            headers={"X-N8N-Key": self.valves.n8n_key},
            timeout=120,
        )
        resp.raise_for_status()
        return str(resp.json())
```

3. Save
4. Configure Valves: set `n8n_url` to `http://n8n:5678`, `n8n_key` to the webhook secret

**Step 3: Test in chat**

Start a chat with a model that supports tool calling (claude-sonnet recommended). Enable tools (toggle in chat). Ask: "Check the system health" — the model should call the tool.

**Step 4: Extend as needed**

Add more methods to the Tools class for each n8n webhook workflow you create. Each method becomes an available tool. The method docstring tells the model when to use it.

---

### Task 4: ComfyUI Image Generation

Deploy ComfyUI as a Docker service with GPU access for local image generation from Open WebUI chat. Uses a `comfyui` profile so it only starts on demand.

**Files:**
- Modify: `~/llm-stack/docker-compose.yml` (add comfyui service + open-webui env vars)

**Step 1: Create directories**

```bash
mkdir -p ~/llm-stack/comfyui/{run,basedir}
```

**Step 2: Add ComfyUI service to docker-compose.yml**

Add before the `volumes:` section:

```yaml
  # --- ComfyUI (Image Generation) ---
  comfyui:
    image: mmartial/comfyui-nvidia-docker:latest
    container_name: comfyui
    restart: unless-stopped
    logging: *default-logging
    ports:
      - "127.0.0.1:8188:8188"
    volumes:
      - ./comfyui/run:/comfy/mnt
      - ./comfyui/basedir:/basedir
    environment:
      USE_UV: "true"
      WANTED_UID: "1000"
      WANTED_GID: "1000"
      BASE_DIRECTORY: "/basedir"
      SECURITY_LEVEL: "normal"
      CLI_ARGS: "--listen 0.0.0.0 --reserve-vram 4.0"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    mem_limit: 16g
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8188/ || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
    profiles:
      - comfyui
```

**Step 3: Add image generation env vars to open-webui**

Add to the open-webui environment block:
```yaml
      ENABLE_IMAGE_GENERATION: "True"
      IMAGE_GENERATION_ENGINE: "comfyui"
      COMFYUI_BASE_URL: "http://comfyui:8188"
```

**Step 4: Start ComfyUI (first run takes several minutes)**

```bash
cd ~/llm-stack && eval "$(direnv export zsh)" && docker compose --profile comfyui up -d comfyui
```

Wait for container to initialize:
```bash
docker logs -f comfyui 2>&1 | head -50
```

**Step 5: Download SDXL base model (~6.5GB)**

Wait for the basedir structure to be created by the container, then:
```bash
wget -P ~/llm-stack/comfyui/basedir/models/checkpoints/ \
  https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors
```

SDXL uses ~7GB VRAM during generation, leaving ~17GB for Ollama. The `--reserve-vram 4.0` flag prevents ComfyUI from claiming all VRAM. Ollama's 5-minute auto-unload ensures the GPU is shared gracefully.

**Step 6: Export API workflow from ComfyUI**

1. Open http://localhost:8188 in browser
2. Load the default text-to-image workflow (or create one)
3. Settings (gear) → enable Dev Mode
4. Menu → Export (API) → saves `workflow_api.json`

**Step 7: Configure Open WebUI image generation**

Recreate open-webui to pick up env vars:
```bash
cd ~/llm-stack && eval "$(direnv export zsh)" && docker compose up -d open-webui
```

Then in browser at http://localhost:3080:
1. Admin Settings > Images
2. Engine: ComfyUI (should be pre-selected from env)
3. Upload the `workflow_api.json`
4. Map node IDs:
   - Prompt node: the CLIPTextEncode (Positive) node ID
   - Negative prompt: the CLIPTextEncode (Negative) node ID
   - Width/Height: the EmptyLatentImage node ID
   - Steps/Seed: the KSampler node ID

**Step 8: Test image generation**

In chat, ask a model to generate an image, or use the image generation UI directly. ComfyUI should process the request and return the generated image.

**Step 9: Commit**

```bash
cd ~/llm-stack && git add docker-compose.yml && git commit -m "feat: add ComfyUI image generation with SDXL"
```

---

### Task 5: Shared Memory (Optional, Low Priority)

Not recommended for immediate implementation. The risk of context pollution between casual Open WebUI chat and Claude Code dev work outweighs the benefit.

**If pursued later:** Create a dedicated Qdrant collection `webui-memory` (separate from `claude-memory`) and use Open WebUI's built-in memory feature. The two memory stores remain isolated. Cross-pollination would require a deliberate sync mechanism, not a shared collection.

**Skip this task for now.**

---

## Execution Order

1. **Task 2: Qdrant filter** — fastest to implement (paste code in UI), immediate value
2. **Task 1: Obsidian sync** — high value, needs script + timer
3. **Task 3: n8n tools** — medium value, needs n8n workflow creation
4. **Task 4: ComfyUI** — largest effort (download model, configure workflow)
5. ~~Task 5: Shared memory~~ — deferred

Tasks 1 and 2 are independent and can be done in parallel. Task 3 requires n8n webhook setup first. Task 4 is standalone.
