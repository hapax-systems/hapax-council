# Local Judge Stack — CompassVerifier-7B (cost-offload Tier-1)

**Authority:** ISAP `S5-CAPACITY-ROUTING-COST-OFFLOAD-TIER1` · REQ `REQ-20260613-sdlc-cost-offload-program` · case `CASE-CAPACITY-ROUTING-001`.
**Status:** served + routed + validated; **default OFF / shadow** until the council agreement gate clears (see *Promotion gate*).

## What this is

A local **answer-verification** judge — CompassVerifier-7B (Apache-2.0, Qwen2.5-7B
fine-tune) — that grades `(question, gold_answer, candidate_response) → CORRECT /
INCORRECT / INVALID`. It offloads mechanical pass/fail judging off frontier cloud
tokens at held quality. It is **not** a gold-free quality judge: the council's
existing LLM-judges (`eval_grounding` context-anchoring, `demo_eval` demo quality)
grade open-ended quality with no reference and need a rubric/GenRM judge instead.
The natural first consumer here is the **grounding-fitness Step-6 grader**
(`grounding-fitness/REPORT.md`) plus future mechanical correctness gates.

Adapter: `shared/local_judge.py` (`LocalJudge.verify(...)`, shadow-defaulted).

## Topology

- **Host:** appendix (hapax-appendix, 192.168.68.50) — the SDLC rig.
- **GPU:** GPU1 (RTX 5060 Ti, 16 GB, sm_120 Blackwell). **GPU0 (3090) grounding is
  never touched** — the container is pinned to the 5060 Ti by UUID.
- **Serving:** `ghcr.io/ggml-org/llama.cpp:server-cuda` (natively Blackwell-capable:
  `ARCHS=...,1200`, `BLACKWELL_NATIVE_FP4=1`) on `:5001`, OpenAI-compatible `/v1`.
- **Gateway:** podium LiteLLM (`:4000`) exposes it as the `local-judge` route, reached
  cross-rig at `http://192.168.68.50:5001/v1`.

## Deploy (appendix)

Model (already present): `~/models/compassverifier-7b/CompassVerifier-7B.Q5_K_M.gguf`
(5.4 GB; GGUF Q5_K_M). Pull from `opencompass/CompassVerifier-7B` and quantize, or
fetch a community GGUF, if absent.

```sh
# one-time: confirm the 5060 Ti UUID and update the unit's JUDGE_GPU_UUID if it differs
nvidia-smi --query-gpu=index,name,uuid --format=csv

docker pull ghcr.io/ggml-org/llama.cpp:server-cuda
# hand serving to systemd (replaces any manual --restart container):
docker rm -f hapax-local-judge 2>/dev/null
cp systemd/hapax-local-judge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hapax-local-judge
# verify model loaded on GPU1 and 3090 VRAM unchanged:
curl -s http://localhost:5001/v1/models | grep compassverifier
nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader
```

Manual one-liner (equivalent, for ad-hoc runs):

```sh
docker run -d --name hapax-local-judge --restart unless-stopped \
  --gpus device=<5060Ti-UUID> \
  -v ~/models/compassverifier-7b:/models:ro -p 5001:5001 \
  ghcr.io/ggml-org/llama.cpp:server-cuda \
  -m /models/CompassVerifier-7B.Q5_K_M.gguf -a compassverifier-7b \
  -c 65536 -np 8 -cb -ngl 99 --host 0.0.0.0 --port 5001
```

## LiteLLM route (podium, host file — NOT tracked in this repo)

`~/llm-stack/litellm-config.yaml` (bind-mounted into the `litellm` container):

```yaml
- model_name: local-judge
  litellm_params:
    model: openai/compassverifier-7b
    api_base: http://192.168.68.50:5001/v1
    api_key: "dummy"
    max_input_tokens: 16384
    max_tokens: 2048
```

Fallback (`litellm_settings.fallbacks`): `local-judge: [claude-haiku]` — a judge
outage routes onward to the cheapest cloud judge rather than dropping the gate. The
Tier-2 `cloud-open` (OpenRouter) tail is deferred to its own S5 + provider-spend ruling.

Reload: `docker compose -f ~/llm-stack/docker-compose.yml up -d litellm`.

## Validate

Harness: `scripts/cost-offload/` (`run_verifierbench.py`, `analyze.py`).
Zero provider spend — gold labels are the dataset's own expert annotations.

```sh
cd scripts/cost-offload
curl -sL "https://huggingface.co/datasets/opencompass/VerifierBench/resolve/refs%2Fconvert%2Fparquet/default/test/0000.parquet" -o verifierbench_test.parquet
uv run --with pandas --with pyarrow --with requests \
  python run_verifierbench.py --n 0 --workers 8     # full 2817-item VerifierBench
uv run --with pandas python analyze.py              # F1, Cohen's kappa, conservative skew
```

- **AC4 (quant integrity):** macro-F1 within ±3 of the published CompassVerifier-7B
  number (83.4) confirms Q5_K_M did not degrade the judge.
- **AC3 (agreement vs authoritative reference):** agreement % + Cohen's κ + the
  conservative-skew split against VerifierBench expert gold.

## Promotion gate (shadow → authoritative)

The adapter ships `shadow=True`. Before any gate acts on a local verdict:

1. Run the gate's judge in **shadow** alongside the incumbent (already-paid) judge;
   `shadow_compare(verdict, authoritative_label)` appends pairs to
   `~/.cache/hapax/local-judge-shadow.jsonl` (Langfuse shows **$0 marginal** — the
   incumbent spend was already happening; the local judge adds no cloud tokens).
2. Promote only once the council-distribution log clears **≥150 items, agreement
   ≥90%, Cohen's κ ≥0.8, conservative-skewed** (errors are escalations to the
   incumbent, not false-accepts).

## Operational notes

- **No-co-residency guarantee:** the container is pinned to the 5060 Ti UUID; the
  3090 grounding instance (TabbyAPI `:5000`) is independent. Confirm with `nvidia-smi`.
- **Throughput:** 8 continuous-batch slots × 8192 ctx; ~137 tok/s decode, ~800 tok/s
  prompt. 12/2817 VerifierBench items exceed an 8192-token slot and are reported as
  context-skips by the harness (negligible, <0.5%).
- **Fallback drill:** `docker stop hapax-local-judge`, then a `local-judge` call
  through `:4000` should return a `claude-haiku` answer without a hard error; restart
  with `systemctl --user start hapax-local-judge`.
