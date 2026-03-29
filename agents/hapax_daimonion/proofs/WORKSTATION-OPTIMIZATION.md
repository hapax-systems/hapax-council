# Workstation Optimization for Voice Grounding Research

**Generated:** 2026-03-21
**Goal:** Every layer of the stack optimized for one thing: the Cycle 2 SCED experiment.

---

## Layer 1: Kernel / OS (CachyOS)

### Already Optimal (no changes needed)
- **Scheduler**: scx_bpfland in LowLatency mode (`-m performance -w`) — correct for mixed RT audio + inference
- **CPU governor**: `performance` on all 16 threads (set by scx_bpfland)
- **I/O scheduler**: `none` on NVMe — correct, hardware handles scheduling
- **THP**: `madvise` — correct, avoids compaction stalls
- **Kernel cmdline**: `threadirqs pcie_aspm=off nowatchdog` — all correct for RT audio

### Needs Tuning

**Sysctl overrides** — create `/etc/sysctl.d/99-voice-realtime.conf`:
```ini
# Smaller, more frequent dirty page flushes (prevent I/O storms from Qdrant/filesystem-as-bus)
vm.dirty_bytes = 134217728
vm.dirty_background_bytes = 33554432
vm.dirty_writeback_centisecs = 500
vm.dirty_expire_centisecs = 1000

# Qdrant and Docker need this
vm.max_map_count = 1048576

# Disable zone reclaim (single-socket, prevents stalls)
vm.zone_reclaim_mode = 0

# Network tuning for Docker inter-service localhost traffic
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_fin_timeout = 15
net.core.somaxconn = 8192
net.core.netdev_max_backlog = 8192
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
```

**IRQ affinity** — reserve CPUs 14-15 for voice pipeline:
```ini
# /etc/systemd/system/irqbalance.service.d/override.conf
[Service]
Environment="IRQBALANCE_BANNED_CPULIST=14-15"
```
Then pin voice daemon: `taskset -c 14,15 uv run python -m agents.hapax_daimonion`

---

## Layer 2: GPU / VRAM (RTX 3090)

### Current: 14,279 / 24,576 MiB used (~58%)

**NVIDIA tuning** — create `/etc/systemd/system/nvidia-compute-tune.service`:
```ini
[Unit]
Description=NVIDIA GPU compute tuning
After=nvidia-persistenced.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/nvidia-smi --lock-gpu-clocks=1800,1800
ExecStart=/usr/bin/nvidia-smi --lock-memory-clocks=9751
ExecStart=/usr/bin/nvidia-smi --power-limit=350

[Install]
WantedBy=multi-user.target
```

**Ollama config** — `/etc/systemd/system/ollama.service.d/vram-optimize.conf`:
```ini
[Service]
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_KEEP_ALIVE=24h"
Environment="OLLAMA_CONTEXT_LENGTH=4096"
Environment="CUDA_MODULE_LOADING=LAZY"
```

**VRAM budget:**
| Component | VRAM | Status |
|-----------|------|--------|
| Hyprland + display | ~350 MiB | Fixed |
| nomic-embed-text | ~275 MiB | Keep loaded permanently |
| distil-large-v3 (STT) | ~5 GB | Replaces large-v3 (~10 GB) |
| Kokoro TTS | ~500 MiB | Keep loaded |
| Classification model | ~5.6 GB | qwen3.5:4b |
| KV cache headroom | ~2 GB | Buffer |
| **Total** | **~10.6 GB** | **~14 GB free** |

**Key decision:** Do NOT run tabbyAPI simultaneously with Ollama. Choose one backend per session.

---

## Layer 3: Docker / Services

### Container Triage: 13 → 5 during experiments

**Keep running (essential):**
| Container | RAM | Role |
|-----------|-----|------|
| qdrant | 6G limit | DU persistence, thread seeding |
| litellm | 2G limit | API routing |
| postgres | 2G limit | LiteLLM config DB |
| redis | 512M limit | Voice pipeline state |
| ntfy | 256M limit | Experiment alerts |

**Stop during experiments:**
```fish
docker stop clickhouse langfuse langfuse-worker minio open-webui n8n grafana prometheus
```

### Redis Fix (open item from RESEARCH-STATE.md)
```
redis-server --maxmemory-policy noeviction --hz 100 --save 300 1 --save 60 1000 --latency-tracking yes
```

### Qdrant Tuning
Create `/home/operator/llm-stack/qdrant-config.yaml`:
```yaml
storage:
  wal:
    wal_capacity_mb: 32
    wal_segments_ahead: 0
  performance:
    max_search_threads: 4
    max_optimization_threads: 2
  optimizers:
    flush_interval_sec: 1
    indexing_threshold: 20000
```

### Optional: Host networking for latency-critical containers
```yaml
qdrant:
  network_mode: host
redis:
  network_mode: host
```

---

## Layer 4: Audio / Voice Pipeline

### PipeWire — lower latency
Replace `10-voice-quantum.conf`:
```
context.properties = {
    default.clock.quantum = 128
    default.clock.min-quantum = 64
    default.clock.max-quantum = 1024
    default.clock.rate = 48000
    default.clock.allowed-rates = [ 16000 24000 48000 ]
}
```
Result: 2.67ms per period (was 5.3ms).

### WirePlumber ALSA — disable USB batch mode
Create `~/.config/wireplumber/wireplumber.conf.d/50-voice-alsa.conf`:
```
monitor.alsa.rules = [
    {
        matches = [
            { node.name = "~alsa_input.*" }
            { node.name = "~alsa_output.*" }
        ]
        actions = {
            update-props = {
                api.alsa.period-size = 128
                api.alsa.headroom = 0
                api.alsa.disable-batch = true
                session.suspend-timeout-seconds = 0
            }
        }
    }
]
```

### VAD Endpoint Delay — biggest single latency win
Current Silero VAD: 500-800ms endpoint delay. Options:
1. **Tune Silero**: `min_silence_duration_ms=250`, `speech_pad_ms=30` → ~250-400ms
2. **Switch to TEN VAD**: ~32% faster RTF, better endpoint detection → ~200ms
3. Accept more false endpoints — LLM handles mid-sentence interrupts better than 800ms dead air

### STT — switch to distil-large-v3
Frees ~4-5 GB VRAM, <1% WER difference, ~2x faster inference. Change in pipeline.py:
```python
stt_model = "distil-large-v3"  # was "large-v3"
```

### End-to-End Latency Budget (optimized)
| Stage | Current | Optimized |
|-------|---------|-----------|
| Audio capture | 5.3ms | 2.7ms |
| VAD endpoint | 500-800ms | 250-400ms |
| STT | 150-300ms | 80-150ms |
| LLM first token | 200-2000ms | 200-800ms |
| TTS first chunk | 200-400ms | 100-200ms |
| Audio playback | 5.3ms | 2.7ms |
| **Total** | **~1100-3500ms** | **~635-1555ms** |

---

## Layer 5: Python Runtime

### High-impact changes (priority order)

**1. uvloop** — 2-4x event loop speed, 2 lines:
```python
import uvloop
uvloop.install()
```

**2. GC tuning** — 20% faster responses:
```python
import gc
gc.collect(2)
gc.freeze()
gc.set_threshold(50_000, 50, 10)
```

**3. Shared httpx client** — eliminate connection churn:
```python
http_client = httpx.AsyncClient(
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20, keepalive_expiry=30.0),
    timeout=httpx.Timeout(connect=5.0, read=120.0, write=5.0, pool=10.0),
    http2=True,
)
```

**4. Qdrant gRPC** — faster than REST:
```python
qdrant = AsyncQdrantClient(url="http://localhost:6333", prefer_grpc=True, grpc_port=6334)
```

**5. CPU-bound work off event loop:**
```python
_cpu_pool = ProcessPoolExecutor(max_workers=2)
async def compute_gqi(params):
    return await loop.run_in_executor(_cpu_pool, _sync_gqi_compute, params)
```

**6. Pydantic** — use `Annotated` constraints (Rust-validated) over `@field_validator` (Python). Use `model_construct()` for trusted internal data.

### Don't bother
- Free-threaded Python 3.13 (not ready, async workload doesn't benefit)
- JIT compiler (not production-ready until 3.15+)
- NumPy for small arrays (pure Python math faster for <1000 elements)

---

## Layer 6: LLM Routing / Inference

### Claude API
- **Always stream** — `stream=True` for TTFT and in-flight grounding analysis
- **Prompt caching** — bundle system prompt + grounding theory + tool definitions to hit 4,096 token minimum for Opus caching. 0.1x read cost, 5-min auto-refreshing TTL.
- **Effort parameter** — replaces model switching entirely. Salience router outputs `effort: "high"/"medium"/"low"` instead of selecting models.
- **Pin model version**: `claude-opus-4-6-20250320` (not alias)
- **Temperature 0.0** for minimum variance (no seed parameter available)

### LiteLLM — keep it (sub-ms overhead, observability worth it)
```yaml
litellm_settings:
  request_timeout: 120
  num_retries: 2
  retry_after: 0.5
  cache: false  # fresh responses for research
```

### Context window discipline (~5,500-8,000 tokens total)
| Component | Tokens | Cacheable |
|-----------|--------|-----------|
| System prompt + grounding theory | ~2,300 | Yes |
| Tool definitions | ~800 | Yes |
| Stimmung state | ~200 | No |
| Thread (10 entries, compressed) | ~2,000-4,000 | Partially |
| Grounding directives | ~200-400 | No |

### Streaming in-flight analysis
Process grounding signals while response is still generating:
- Acceptance detection (regex on growing buffer)
- Monologic scoring (sentence count threshold)
- Directive compliance (grounding marker presence)
- Cancel via `stream.close()` if monologic threshold exceeded — pay only for tokens generated

### Embedding — nomic-embed-text via Ollama
768 dimensions, ~20-30ms latency, 8192 token context. Cache embeddings keyed on SHA256 of text (deterministic, never invalidates).

---

## Layer 7: Experiment Infrastructure

### Data Collection
- Session records as JSONL with Pydantic validation
- Phase arrays: `phase_A_values[]`, `phase_B_values[]` for BEST
- Checksums per session file, append-only writes
- Log every gap with reason codes

### Bayesian Analysis Stack
- **PyMC 5.x** — BEST model with t-distributed likelihood + AR(1) autocorrelation term
- **ArviZ** — posterior plots, convergence diagnostics, HDI
- **bambi** — if mixed-effects needed

### Effect Sizes
- **Primary (Bayesian):** posterior difference of means with 95% HDI, Cohen's d from BEST, P(mu_B > mu_A)
- **Secondary (non-overlap):** Tau-U (handles baseline trend), NAP
- Implement Tau-U in Python; use R SingleCaseES via rpy2 for full suite

### OSF Pre-Registration
- Standard OSF template + Johnson & Cook (2019) SCED checklist
- Specify: priors, ROPE, credible interval width, effect size thresholds, phase transition decision rules
- Register before any Cycle 2 data collection

### Session Protocol Automation
- Phase state machine enforcing minimum 5 sessions per phase (WWC standard)
- Config hash verification at session start
- Stability criterion check before phase transitions
- Write-once session records

### Reproducibility
- Git tag at experiment start
- `uv.lock` committed and frozen
- `MANIFEST.json` per cycle: git SHA + config hash + uv.lock hash + python version + dates
- Pin all model identifiers to exact versions

### Lab Journal
- Jekyll on GitHub Pages (need to enable — noted open item)
- Per-session posts with YAML front matter (phase, session number, tags)
- Git commits provide immutable audit trail

---

## Execution Priority

### Do First (immediate, before any experiment sessions)
1. Redis `noeviction` fix (resolves open item)
2. Commit batches 1-4 (85 tests, uncommitted — risk of data loss)
3. uvloop + GC tuning (2-line, 5-line changes, huge impact)
4. Qdrant gRPC client
5. STT model switch to distil-large-v3

### Do Second (same day, quick config changes)
6. Sysctl overrides
7. NVIDIA clock/power locking
8. Ollama config (context length 4096, keep-alive 24h)
9. PipeWire quantum 128
10. WirePlumber ALSA batch disable
11. Shared httpx client

### Do Third (requires more work)
12. Container triage script (experiment-start.fish)
13. VAD endpoint tuning (or TEN VAD integration)
14. Prompt caching (bundle to 4096 tokens)
15. Streaming in-flight analysis
16. IRQ affinity for voice pipeline
17. Qdrant config file

### Do Before Cycle 2 Starts
18. OSF pre-registration
19. Session protocol automation (phase state machine)
20. Lab journal setup (Jekyll + GitHub Pages)
21. MANIFEST.json for reproducibility
22. Data collection schema (Pydantic models for session records)
23. Bayesian analysis pipeline (PyMC BEST + AR(1))

---

## Sources

Full source lists in each research agent's output. Key references:
- CachyOS wiki (scheduler, kernel features)
- NVIDIA docs (nvidia-smi, persistence, MPS)
- PipeWire docs (quantum, RT module)
- Anthropic docs (prompt caching, streaming, effort parameter)
- Shadish et al. 2013 (SCED autocorrelation)
- Kratochwill et al. (WWC SCED standards)
- Johnson & Cook 2019 (SCED pre-registration)
- Kruschke 2013 (BEST)
