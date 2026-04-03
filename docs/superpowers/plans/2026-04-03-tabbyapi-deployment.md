# TabbyAPI Deployment — Qwen3-Coder-30B-A3B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy TabbyAPI serving Qwen3.5-35B-A3B (EXL3 3.0bpw) to replace qwen3:8b as the primary local model, upgrading from 8B dense to 35B MoE with better reasoning and tool calling.

**Architecture:** TabbyAPI runs as a native systemd user service on port 5000, serving an OpenAI-compatible API. LiteLLM routes `local-fast`, `reasoning`, and `coding` aliases to TabbyAPI instead of Ollama. DMN switches from Ollama's `/api/chat` to TabbyAPI's OpenAI-compatible `/v1/chat/completions`. Ollama remains running for embeddings (CPU) and as fallback only.

**Tech Stack:** TabbyAPI (ExllamaV3), EXL3 quantized model, systemd, LiteLLM, httpx

**Model selection:** Qwen3-Coder-30B-A3B (best tool calling) only available at 5.0bpw EXL2 (~19GB, won't fit). Pivoted to Qwen3.5-35B-A3B EXL3 3.0bpw (~16GB) — newer model, maintained by turboderp, native EXL3 format, 262K context, BFCL-V4 67.3 tool calling.

## Tradeoff Analysis

### What we gain

| Dimension | qwen3:8b (current) | Qwen3-Coder-30B-A3B (proposed) |
|-----------|--------------------|---------------------------------|
| Parameters | 8B dense | 30B MoE (3B active/token) |
| Tool calling | No native support | BFCL 0.82, Tau2-Bench 65.1 |
| Speed | ~87-100 tok/s | ~87 tok/s (comparable — MoE activates only 3B) |
| TTFT | ~100ms | ~100-250ms |
| Context | 128K (degrades >32K) | 256K (extensible to 1M via YaRN) |
| Concurrency | Serialized (Ollama) | Parallel (paged attention) |
| SWE-Bench | N/A | 69.6 Verified |
| VRAM | ~5.7GB | ~15.2GB (EXL2 4bpw) + ~1.5GB KV cache |

### What we risk

1. **Tool calling at 4bpw quantization** — BFCL scores measured at full precision. Quantization may degrade multi-turn structured output. Mitigated by testing before cutting over voice path.
2. **VRAM headroom shrinks** — From 12.5GB free to ~1.5GB free. No room for additional GPU-resident services. If VRAM is exhausted, inference fails hard (no graceful degradation like Ollama model eviction).
3. **Infrastructure complexity** — Two inference servers (TabbyAPI + Ollama) instead of one. Ollama still needed for CPU embeddings.
4. **EXL2 not deterministic** — ExllamaV2 prioritizes speed over reproducibility. DMN observations may vary run-to-run more than with Ollama GGUF.
5. **Startup time** — Large model loads slowly (~30-60s). Service restarts have a cold-start penalty.

### What stays unchanged

- Cloud models (Opus, Sonnet, Gemini Flash) — no change
- Voice tier routing logic — no change (model_router.py untouched)
- Stimmung-aware adaptive routing — no change
- Embedding pipeline — stays on Ollama CPU

### Rollback plan

1. Stop TabbyAPI: `systemctl --user stop tabbyapi`
2. Revert LiteLLM config: restore Ollama routes for `local-fast`, `reasoning`, `coding`
3. Revert DMN: change `TABBY_CHAT_URL` back to Ollama `OLLAMA_CHAT_URL`
4. Restart LiteLLM: `cd ~/llm-stack && docker compose restart litellm`
5. Restart DMN: `systemctl --user restart hapax-dmn`

Total rollback time: ~2 minutes. No data loss.

---

## File Map

| File | Action | Task | Purpose |
|------|--------|------|---------|
| `tabbyAPI/config.yml` | Create | 1 | TabbyAPI configuration |
| `systemd/units/tabbyapi.service` | Create | 2 | systemd user unit |
| `llm-stack/litellm-config.yaml` | Modify | 3 | Route aliases to TabbyAPI |
| `agents/dmn/ollama.py` | Modify | 4 | Switch DMN to TabbyAPI OpenAI API |
| `agents/health_monitor/` | Modify | 5 | Add TabbyAPI health check |

---

### Task 1: Download Model and Create TabbyAPI Config

**Files:**
- Create: `tabbyAPI/config.yml`

- [ ] **Step 1: Download the EXL2 model**

Check available branches, then download the 4.0bpw revision. If 4.0bpw is not available, use 3.5bpw or 3.0bpw (lower bpw = less VRAM, slightly lower quality).

Expected: model files downloaded to `tabbyAPI/models/Qwen3-Coder-30B-A3B-Instruct-EXL2-4.0bpw/`. Should be ~15-17GB total.

- [ ] **Step 2: Verify model files exist**

Should contain: config.json, tokenizer.json, *.safetensors, etc.

- [ ] **Step 3: Create TabbyAPI config**

Key choices:
- `max_seq_len: 8192` — limits KV cache VRAM. Sufficient for DMN (short prompts) and voice (moderate context).
- `cache_mode: Q8` — saves ~50% KV cache VRAM vs FP16 with negligible quality loss.
- `disable_auth: true` — localhost only.

```yaml
network:
  host: 127.0.0.1
  port: 5000
  disable_auth: true
  api_servers: ["OAI"]

logging:
  log_prompt: false
  log_generation_params: false
  log_requests: false

model:
  model_dir: models
  model_name: Qwen3-Coder-30B-A3B-Instruct-EXL2-4.0bpw
  max_seq_len: 8192
  cache_size: 8192
  cache_mode: Q8
  chunk_size: 2048
  inline_model_loading: false

sampling:
  override_preset: safe_defaults
```

- [ ] **Step 4: Test TabbyAPI launches and loads the model**

Start TabbyAPI, wait for "Uvicorn running on http://127.0.0.1:5000", then stop.

- [ ] **Step 5: Test inference via curl**

Send a simple chat completion request to port 5000. Verify valid JSON response.

- [ ] **Step 6: Test tool calling**

Send a request with `tools` parameter containing a function schema. Verify response contains `tool_calls` with correct function name and arguments. If tool calling fails or returns malformed output, evaluate whether to proceed or try Qwen3.5-35B-A3B EXL3 instead.

Stop TabbyAPI after testing.

---

### Task 2: Create systemd User Unit

**Files:**
- Create: `systemd/units/tabbyapi.service`

- [ ] **Step 1: Create the service unit**

```ini
[Unit]
Description=TabbyAPI — EXL2 inference engine on :5000
After=network.target
After=ollama.service

[Service]
Type=simple
WorkingDirectory=%h/projects/tabbyAPI
ExecStart=%h/projects/tabbyAPI/start.sh
Restart=on-failure
RestartSec=15
TimeoutStartSec=120
MemoryMax=4G
Environment=PYTORCH_CUDA_ALLOC_CONF=backend:cudaMallocAsync

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Symlink, enable, and start**

Symlink to `~/.config/systemd/user/`, daemon-reload, enable, unload qwen3:8b from Ollama, then start TabbyAPI.

- [ ] **Step 3: Verify VRAM usage**

TabbyAPI should use ~15-17GB. Free VRAM should be ~1-3GB. If free <500MB, reduce `max_seq_len` to 4096 in config.yml.

- [ ] **Step 4: Commit**

---

### Task 3: Route LiteLLM Aliases to TabbyAPI

**Files:**
- Modify: `llm-stack/litellm-config.yaml`

- [ ] **Step 1: Add TabbyAPI routes**

Add `local-fast`, `coding`, `reasoning` entries pointing to `http://host.docker.internal:5000/v1` with `model: openai/<model-name>`. Remove the existing Ollama entries for those aliases. Keep `qwen3:8b` route as fallback target.

- [ ] **Step 2: Add fallback chain**

```yaml
    - local-fast: [qwen3:8b]
    - coding: [qwen3:8b]
    - reasoning: [qwen3:8b]
```

- [ ] **Step 3: Restart LiteLLM and verify routing**

Restart, then test via curl that `local-fast` returns a response from the Coder model.

---

### Task 4: Switch DMN to TabbyAPI

**Files:**
- Modify: `agents/dmn/ollama.py`

The DMN calls Ollama directly (not through LiteLLM). Switch to TabbyAPI's OpenAI-compatible endpoint with Ollama fallback.

- [ ] **Step 1: Rewrite DMN inference**

Key changes:
- URL: `http://localhost:5000/v1/chat/completions` (OpenAI format)
- Request body: `{"model": "...", "messages": [...], "max_tokens": 256, "temperature": 0.3}`
- Response parsing: `data["choices"][0]["message"]["content"]` (not `data["message"]["content"]`)
- Add `_ollama_fallback()` function for resilience
- Single `DMN_MODEL` constant (not separate fast/think)

```python
TABBY_CHAT_URL = "http://localhost:5000/v1/chat/completions"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DMN_MODEL = "Qwen3-Coder-30B-A3B-Instruct-EXL2-4.0bpw"
DMN_MODEL_OLLAMA_FALLBACK = "qwen3:8b"
```

Both `_tabby_fast` and `_tabby_think` call TabbyAPI first, fall back to Ollama on failure.

- [ ] **Step 2: Restart DMN and verify ticks**

Sensory ticks should fire via TabbyAPI (check journalctl for HTTP 200s).

- [ ] **Step 3: Commit**

---

### Task 5: Add TabbyAPI Health Check

**Files:**
- Modify: `agents/health_monitor/` (endpoints check)

- [ ] **Step 1: Add TabbyAPI to endpoint checks**

Add `http://localhost:5000/health` as a monitored endpoint in the health monitor.

- [ ] **Step 2: Run health monitor to verify**

- [ ] **Step 3: Commit**

---

## Post-Deployment Verification

1. All services running (tabbyapi, hapax-dmn, hapax-daimonion, logos-api)
2. VRAM budget — TabbyAPI ~16GB, free ~1-3GB
3. DMN ticking via TabbyAPI (journalctl)
4. LiteLLM routing local-fast to TabbyAPI
5. Tool calling quality test (3 tools, verify correct selection)
6. Full health check passes

If tool calling produces malformed output or selects wrong tools:
- Try Qwen3.5-35B-A3B EXL3 3.0bpw (better general quality, slightly worse tool calling scores)
- Or roll back to qwen3:8b (2 minutes, documented above)
