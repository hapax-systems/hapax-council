---
title: OLMo-3-7B-Instruct parallel TabbyAPI deploy
date: 2026-04-16
queue_item: '211'
epic: lrr
phase: substrate-scenario-2
substrate_decision_ref: drop-62 §16 (scenario 2 ratification), §17 (Option C pivot)
status: shipped
---

# OLMo-3-7B-Instruct parallel TabbyAPI deploy

Substrate scenario 2 (Option C) execution. Parallel TabbyAPI instance on
`:5001` serving OLMo as a non-Qwen open-models grounding substrate while the
primary `:5000` instance continues to serve Qwen3.5-9B without modification.

## Pivot from OLMo-2 → OLMo-3

The original queue #211 specification targeted `allenai/OLMo-2-1124-7B-{SFT,DPO,Instruct}`.
On verification, exllamav3 0.0.29 (the version installed in the parallel
venv) does not register `Olmo2ForCausalLM`. Only `Olmo3ForCausalLM` and
`OlmoHybridForCausalLM` are exposed in `exllamav3/architecture/architectures.py`.

Two paths were possible:

1. Downgrade exllamav3 to a version that supports OLMo-2.
2. Switch to the OLMo-3 7B series, which is natively supported.

OLMo-3 was chosen because:

- Newer release (Nov 2025) with stronger benchmarks than OLMo-2.
- `allenai/Olmo-3-7B-Instruct` matches the same param count and
  instruction-tuning posture as the originally specified OLMo-2 Instruct.
- A pre-quantized EXL3 5.0bpw weight set is available at
  `kaitchup/Olmo-3-7B-Instruct-exl3` branch `bpw-5.0-h8`, eliminating
  ~1.5 hours of local quantization time.
- Same RIFTS justification: open-models clarification-rate measurement is
  the goal; OLMo-3 is the right modern open candidate.

The 42 GB of OLMo-2 raw weights downloaded earlier remains in
`~/projects/tabbyAPI-olmo/models/raw/` and can be deleted or kept for
reference.

## Deploy artifacts

- `~/projects/tabbyAPI-olmo/models/olmo-3-7b-instruct-exl3-5.0bpw/` —
  pre-quantized EXL3 weights (~5.0 GB safetensors).
- `~/projects/tabbyAPI-olmo/config.yml` — model_name updated to
  `olmo-3-7b-instruct-exl3-5.0bpw`, port 5001, gpu_split [0, 6],
  cache_size 16384.
- `~/.config/systemd/user/tabbyapi-olmo.service` — systemd user unit,
  pinned to the RTX 3090 via `CUDA_DEVICE_ORDER=PCI_BUS_ID` +
  `CUDA_VISIBLE_DEVICES=1`.

## VRAM footprint (measured)

| GPU | Before | After OLMo load | Delta |
|---|---|---|---|
| RTX 5060 Ti (cuda:0, PCI :03) | 5.4 GB | 5.4 GB | 0 (untouched) |
| RTX 3090 (cuda:1, PCI :07) | 5.7 GB | 13.1 GB | +7.4 GB |

The 3090 budget was 12 GB (Qwen3.5-9B at ~5.7 GB + headroom). OLMo
landed at 7.4 GB including KV cache (Q4 at 16384 ≈ ~1.2 GB). Total 3090
usage 13.1 GB / 24 GB; ~10.9 GB remains for KV growth and overhead.

## Smoke test results

```
$ curl -s http://localhost:5001/health
{"status":"healthy","issues":[]}

$ curl -s -X POST http://localhost:5001/v1/chat/completions \
  -d '{"model":"olmo-3-7b-instruct-exl3-5.0bpw",
       "messages":[{"role":"user","content":"Reply with exactly: OLMO_OK"}],
       "max_tokens":20,"temperature":0.0}'
... "content":"OLMO_OK" ...
```

Cold-start model load measured at ~8 seconds from systemd start to
"Model successfully loaded" log line. Uvicorn ready at the same instant.

## Acceptance checklist

- [x] Parallel TabbyAPI dir + venv created
- [x] `Olmo3ForCausalLM` support verified in parallel venv
- [x] OLMo-3-7B-Instruct EXL3 5.0bpw weights downloaded
- [x] systemd unit `tabbyapi-olmo.service` running on :5001
- [x] Smoke test passes (health + one-shot completion)
- [x] VRAM footprint documented

## Follow-ups

- Queue #212: wire `local-research-*` LiteLLM routes to :5001 + run
  claim-shaikh cycle 2 against OLMo-3-Instruct for grounding comparison
  vs the Qwen baseline RIFTS run.
- Optional: download `Olmo-3-7B-Think` and `Olmo-3-7B-Instruct-DPO` as
  swappable model families on the same parallel instance.
- Optional: delete OLMo-2 raw weights (42 GB) once OLMo-3 is fully
  validated end-to-end.
