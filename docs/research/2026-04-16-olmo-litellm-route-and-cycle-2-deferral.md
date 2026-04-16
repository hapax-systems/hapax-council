---
title: OLMo LiteLLM route + claim-shaikh cycle 2 partial deploy
date: 2026-04-16
queue_item: '212'
depends_on: '211'
epic: lrr
phase: substrate-scenario-2
status: shipped-with-deferral
---

# OLMo LiteLLM route + claim-shaikh cycle 2 partial deploy

Wires the parallel TabbyAPI :5001 (deployed in queue #211) into the
LiteLLM gateway as `local-research-instruct`, then partially executes
claim-shaikh cycle 2.

## Shipped

### Route added

- `local-research-instruct` → `openai/olmo-3-7b-instruct-exl3-5.0bpw` at
  `http://172.18.0.1:5001/v1`. Inserted in `~/llm-stack/litellm-config.yaml`
  immediately after `reasoning`.
- `shared/config.py` MODELS dict updated with the new alias.
- LiteLLM container restarted via `docker restart litellm`.

### Smoke test

```
$ curl -s -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model":"local-research-instruct",
       "messages":[{"role":"user","content":"Reply with exactly: ROUTE_OK"}],
       "max_tokens":20,"temperature":0.0}'
... "content": "ROUTE_OK" ...
```

Round trip LiteLLM gateway → parallel TabbyAPI → OLMo-3 returns the
exact prompted output. No fallback engaged.

### Network fix

Initial attempt timed out. The Docker bridge network (172.18.0.0/16)
already had ACCEPT rules for `:5000` (primary TabbyAPI) but none for
`:5001`. Added:

```
ufw allow from 172.18.0.0/16 to any port 5001 proto tcp \
    comment "TabbyAPI parallel (OLMo) from Docker llm-stack"
```

Persistent across reboot via `/etc/ufw/user.rules`. No changes required
to docker-compose or LiteLLM config.

## Deferred: cycle 2 isogenic SFT/DPO/Think comparison

The original queue #212 spec called for `local-research-{sft,dpo,rlvr}`
routes pointing to OLMo-2-1124-7B-{SFT,DPO,Instruct} variants for an
isogenic SFT-vs-DPO-vs-RLVR grounding comparison per drop #62 §10 Q1.

The substrate pivot (queue #211) replaced OLMo-2 with OLMo-3-7B because
exllamav3 0.0.29 does not support `Olmo2ForCausalLM`. OLMo-3 7B does
have SFT/DPO/Think variants:

- `allenai/Olmo-3-7B-Instruct-SFT`
- `allenai/Olmo-3-7B-Instruct-DPO`
- `allenai/Olmo-3-7B-Think-SFT`
- `allenai/Olmo-3-7B-Think-DPO`
- `allenai/Olmo-3-7B-Think`

But no pre-quantized EXL3 weights exist on HuggingFace for any of the
non-Instruct variants. Only `kaitchup/Olmo-3-7B-Instruct-exl3` is
published.

To complete cycle 2 isogenic comparison, the SFT/DPO/Think checkpoints
must be locally quantized:

1. Download raw weights (~14 GB each, ~42 GB total).
2. Quantize each to EXL3 5.0bpw via the parallel venv's exllamav3
   convert pipeline (~1-1.5 hours per checkpoint on the 3090).
3. Add three additional LiteLLM routes (`local-research-sft`,
   `local-research-dpo`, `local-research-think`).
4. Either run a parallel TabbyAPI per checkpoint OR use TabbyAPI's
   admin model-swap API on a single instance.
5. Run claim-shaikh cycle 2 across all four routes.
6. Score each: clarification rate, refusal, hallucination, grounding
   per Shaikh framework rubric.
7. Author findings drop with per-checkpoint scores + SFT/DPO/Think
   divergence analysis.

Total deferred effort: ~5-7 hours. Target: separate queue follow-up
item, scheduled when the operator can absorb a 5-7h compute window
without blocking other LRR work.

## Acceptance partial-checklist

- [x] Route `local-research-instruct` live and smoke-tested
- [x] `shared/config.py` MODELS dict updated
- [x] ufw rule added for :5001 from Docker bridge
- [ ] Cycle 2 isogenic SFT/DPO/Think comparison (deferred — see follow-up)
- [ ] Per-checkpoint cycle 2 scores documented (deferred)
- [ ] SFT vs DPO vs Think analysis (deferred)

## Follow-up queue item

Open a new queue item `local-research-{sft,dpo,think} quant + cycle 2
isogenic` capturing the deferred work above. Dependency: this item
(#212) closed.
