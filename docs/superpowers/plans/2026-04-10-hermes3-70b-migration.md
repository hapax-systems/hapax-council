# Hermes 3 70B Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate voice and local inference from Qwen3.5-9B to Hermes 3 70B (SFT-only) on a dual-GPU platform (RTX 3090 24GB + RTX 5060 Ti 16GB), using layer-split inference via ExllamaV3 at EXL3 3.0 bpw.

**Architecture:** Layer-split (autosplit) across two GPUs — 96% of model on RTX 3090 (high bandwidth), 4% overflow + STT on RTX 5060 Ti. TabbyAPI serves via ExllamaV2/V3. LiteLLM routes unchanged except model name. Minimal Python code changes — this is primarily a config/infrastructure migration.

**Tech Stack:** TabbyAPI, ExllamaV2/V3, LiteLLM, systemd, NVIDIA driver 575+, CUDA 12.8+, faster-whisper

**Spec:** `docs/superpowers/specs/2026-04-10-hermes3-70b-voice-architecture-design.md`

---

## Pre-Requisites

Hardware physically installed and booting:
- AMD Ryzen 7 7700X on ASUS TUF X870-PLUS WIFI
- 64 GB DDR5 (4x16 G.Skill Trident Z5 Neo)
- RTX 3090 in primary x16 slot, RTX 5060 Ti in secondary x4 slot
- Both GPUs visible in BIOS

---

## Task 1: Driver and CUDA Validation

**Files:** None (system-level)

- [ ] **Step 1: Install NVIDIA driver 575+**

CachyOS provides nvidia-open-dkms via cachyos repo. Target driver 575.57.08 or newer confirmed Ampere+Blackwell compatible:

```bash
paru -S nvidia-open-dkms nvidia-utils
```

Reboot after install.

- [ ] **Step 2: Verify both GPUs detected**

```bash
nvidia-smi -L
```

Expected:
```
GPU 0: NVIDIA GeForce RTX 3090 (UUID: ...)
GPU 1: NVIDIA GeForce RTX 5060 Ti (UUID: ...)
```

If ordering is reversed, note this — all `gpu_split` values and CUDA device indices in later tasks must swap.

- [ ] **Step 3: Verify CUDA version**

```bash
nvidia-smi | grep "CUDA Version"
```

Expected: `CUDA Version: 12.8` or higher.

- [ ] **Step 4: Basic compute test on both GPUs**

```bash
python3 -c "
import torch
for i in range(torch.cuda.device_count()):
    d = torch.device(f'cuda:{i}')
    t = torch.randn(1000, 1000, device=d)
    print(f'GPU {i}: {torch.cuda.get_device_name(i)} — OK')
"
```

Expected: Both GPUs complete without error.

---

## Task 2: Download Hermes 3 70B EXL3

**Files:**
- Create: `~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/`

- [ ] **Step 1: Search for pre-quantized EXL3**

```bash
huggingface-cli search "Hermes-3-Llama-3.1-70B" --filter "exl3"
# Also check: bartowski, turboderp, Doctor-Shotgun on HuggingFace
```

If a 3.0 bpw EXL3 quant exists, download it directly to `~/projects/tabbyAPI/models/`.

- [ ] **Step 2: If no EXL3 available, self-quantize**

Download FP16 weights and quantize using exllamav3 conversion tools. FP16 weights are ~140 GB — with 64 GB DDR5 this requires swap or layer-by-layer mode. Alternative: download GGUF from `NousResearch/Hermes-3-Llama-3.1-70B-GGUF` or use bartowski EXL2 at 3.0 bpw as fallback.

- [ ] **Step 3: Verify model size**

```bash
du -sh ~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/
```

Expected: ~26-27 GB.

---

## Task 3: Configure TabbyAPI for Dual-GPU

**Files:**
- Modify: `~/projects/tabbyAPI/config.yml`

- [ ] **Step 1: Back up current config**

```bash
cp ~/projects/tabbyAPI/config.yml ~/projects/tabbyAPI/config.yml.qwen-backup
```

- [ ] **Step 2: Write new config**

Replace `~/projects/tabbyAPI/config.yml`:

```yaml
logging:
  log_generation_params: false
  log_prompt: false
  log_requests: true
model:
  backend: exllamav3
  cache_mode: Q8
  cache_size: 4096
  chunk_size: 2048
  gpu_split:
  - 23.5
  - 12.5
  inline_model_loading: false
  max_seq_len: 8192
  model_dir: models
  model_name: Hermes-3-Llama-3.1-70B-EXL3-3.0bpw
network:
  api_servers:
  - OAI
  disable_auth: true
  host: 0.0.0.0
  port: 5000
sampling:
  override_preset: safe_defaults
```

Changes: `model_name` to Hermes 3 70B, `cache_mode` to `Q8`, `max_seq_len` to `8192`, added `gpu_split: [23.5, 12.5]`.

- [ ] **Step 3: Validate YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('config.yml'))"
```

---

## Task 4: Update TabbyAPI Systemd Unit

**Files:**
- Modify: `systemd/units/tabbyapi.service`

- [ ] **Step 1: Increase startup timeout**

Change `TimeoutStartSec=120` to `TimeoutStartSec=180` (70B loads slower).

- [ ] **Step 2: Reload and commit**

```bash
systemctl --user daemon-reload
git add systemd/units/tabbyapi.service
git commit -m "chore(systemd): increase TabbyAPI timeout for 70B model load"
```

---

## Task 5: Update LiteLLM Routes

**Files:**
- Modify: `~/llm-stack/litellm-config.yaml` (lines 56-82)

- [ ] **Step 1: Update local model definitions**

Replace the three local model blocks (local-fast, coding, reasoning) with:

```yaml
  # Local models via TabbyAPI (EXL3, Hermes 3 70B on :5000)
  - model_name: local-fast
    litellm_params:
      model: openai/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw
      api_base: http://172.18.0.1:5000/v1
      api_key: "dummy"

  - model_name: coding
    litellm_params:
      model: openai/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw
      api_base: http://172.18.0.1:5000/v1
      api_key: "dummy"

  - model_name: reasoning
    litellm_params:
      model: openai/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw
      api_base: http://172.18.0.1:5000/v1
      api_key: "dummy"
```

Changes: model name updated, `chat_template_kwargs` removed (Hermes 3 uses ChatML natively).

- [ ] **Step 2: Restart LiteLLM and verify**

```bash
cd ~/llm-stack && docker compose restart litellm
curl -s http://localhost:4000/v1/models | python3 -m json.tool | grep -i "hermes\|local-fast"
```

---

## Task 6: Phase 1 — Inference Validation

**Files:** None (operational validation)

- [ ] **Step 1: Start TabbyAPI and verify GPU allocation**

```bash
systemctl --user restart tabbyapi
# Wait for load (~60-120s), then:
nvidia-smi
```

Expected: GPU 0 ~23-24 GB, GPU 1 ~3-4 GB.

- [ ] **Step 2: Test basic completion**

```bash
curl -s http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Hermes-3-Llama-3.1-70B-EXL3-3.0bpw","messages":[{"role":"user","content":"Hello, how are you?"}],"max_tokens":80}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
```

- [ ] **Step 3: Test directive compliance**

```bash
curl -s http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Hermes-3-Llama-3.1-70B-EXL3-3.0bpw","messages":[{"role":"system","content":"You are a voice assistant. When you do not understand the user, ask a clarifying question. Keep responses under 30 words. Grounding directive: rephrase."},{"role":"user","content":"Can you do the thing with the stuff?"}],"max_tokens":80}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
```

Expected: Clarifying question, under 30 words.

- [ ] **Step 4: Measure generation speed**

```bash
time curl -s http://localhost:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Hermes-3-Llama-3.1-70B-EXL3-3.0bpw","messages":[{"role":"user","content":"Write exactly 80 words about the weather."}],"max_tokens":120}' > /dev/null
```

Expected: < 4s.

- [ ] **Step 5: Sustained stability (5 min, 30 requests)**

Run 30 sequential requests at 10s intervals. Monitor `nvidia-smi` in parallel. Expected: No VRAM growth, no errors, stable temps.

---

## Task 7: STT Coexistence Validation

**Files:** None (operational validation)

- [ ] **Step 1: Test STT on GPU 1 with TabbyAPI running**

```bash
python3 -c "
from faster_whisper import WhisperModel
import numpy as np
model = WhisperModel('distil-large-v3', device='cuda', device_index=1, compute_type='int8')
audio = np.zeros(48000, dtype=np.float32)
segments, info = model.transcribe(audio)
print(f'STT on GPU 1 — OK')
"
```

- [ ] **Step 2: Verify VRAM with both loaded**

```bash
nvidia-smi
```

Expected: GPU 0 ~23-24 GB, GPU 1 ~5-6 GB, GPU 1 free ~10-11 GB.

---

## Task 8: Route STT to GPU 1

**Files:**
- Potentially modify: `agents/hapax_daimonion/config.py`, STT initialization module

- [ ] **Step 1: Find STT initialization code**

```bash
grep -rn "WhisperModel\|device_index" agents/hapax_daimonion/ --include="*.py"
```

- [ ] **Step 2: Add device_index=1 if needed**

If code defaults to GPU 0, add `stt_device_index: int = 1` to config and update WhisperModel init. If already configurable or correct, skip.

- [ ] **Step 3: Commit if changed**

```bash
git add agents/hapax_daimonion/
git commit -m "feat(daimonion): route STT to GPU 1 for dual-GPU coexistence"
```

---

## Task 9: Full Voice Pipeline Smoke Test

**Files:** None (operational validation)

- [ ] **Step 1: Restart all services**

```bash
systemctl --user restart tabbyapi
sleep 20
systemctl --user restart hapax-daimonion
```

- [ ] **Step 2: Verify both services healthy**

```bash
journalctl --user -u tabbyapi -u hapax-daimonion --since "1 min ago" --no-pager | tail -20
nvidia-smi
```

- [ ] **Step 3: Voice interaction test**

Trigger wake word. Observe: STT < 200ms, LLM < 3s, total round-trip < 4s.

- [ ] **Step 4: Verify Langfuse traces**

Confirm traces show Hermes 3 70B as model name.

---

## Task 10: Update Documentation

**Files:**
- Modify: `systemd/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update systemd README VRAM section**

Replace TabbyAPI VRAM description with dual-GPU layout: 23.5 GiB on 3090 (layers 0-76), 2.75 GiB on 5060 Ti (layers 77-79), STT 2.5 GiB on 5060 Ti, KV cache Q8 0.6 GiB.

- [ ] **Step 2: Update CLAUDE.md Tier 2**

Replace `Qwen3.5-9B (EXL3)` with `Hermes 3 70B (EXL3 3.0bpw, layer-split across RTX 3090 + RTX 5060 Ti)`. Update `shared/config.py` module description similarly.

- [ ] **Step 3: Commit**

```bash
git add systemd/README.md CLAUDE.md
git commit -m "docs: update model references and VRAM layout for Hermes 3 70B dual-GPU"
```

---

## Task 11: Directive Compliance Benchmark

**Files:** None (quality gate)

- [ ] **Step 1: Test 5 directives**

Test advance, rephrase, elaborate, request-repair, move_on through TabbyAPI with system prompts containing explicit grounding directives and word limits.

- [ ] **Step 2: Score**

For each: directive followed? Word limit respected? Conversational tone?

**Go/no-go:** >= 3/5 directive compliance, >= 4/5 word limit. If failing, upgrade to 3.5 bpw.

---

## Task 12: PR and Merge

- [ ] **Step 1: Push and create PR**

```bash
git push -u origin beta-standby
gh pr create --title "feat: Hermes 3 70B dual-GPU migration" --body "..."
```

- [ ] **Step 2: Monitor CI, merge when green**

---

## Task 13: Update Relay Status

- [ ] **Step 1: Update `~/.cache/hapax/relay/beta.yaml`**

Record migration complete, decisions made (3.0bpw, layer split), open questions (DF driver compat).

---

## Contingency: Fallback to Single-GPU

If 5060 Ti unstable: remove `gpu_split`, load 24GB-fit model (Hermes 3 70B 2.5bpw or restore Qwen3.5-9B), move STT to CPU.

## Contingency: 3.0 bpw Quality Insufficient

If directive compliance < 3/5: re-quantize 3.5 bpw, update `gpu_split` to `[23.5, 9.5]`, reduce `cache_size` if needed, re-benchmark.
