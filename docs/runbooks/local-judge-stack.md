# Local Judge Stack — CompassVerifier-7B (cost-offload Tier-1)

**Authority:** ISAP `S5-CAPACITY-ROUTING-COST-OFFLOAD-TIER1` · REQ `REQ-20260613-sdlc-cost-offload-program` · case `CASE-CAPACITY-ROUTING-001`.
**Status:** parked and decommissioning. Activation is unavailable until a
separately runtime-authorized, host-root-signed broker contract exists.

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
- **Former serving path:** `ghcr.io/ggml-org/llama.cpp:server-cuda` on `:5001`.
  The mutable tag, mutable model bind, name-based cleanup, and unlimited memory
  policy are retired and must not be recreated.
- **Gateway:** podium LiteLLM (`:4000`) exposes it as the `local-judge` route, reached
  cross-rig at `http://192.168.68.50:5001/v1`.

## Retirement (appendix)

The source unit is deleted. Post-merge deployment classifies that exact
historical path before consulting old or current package manifests and records
runtime deferral; it never sends the path to generic user-unit, system-unit, or
OOM deployment. The canonical user-unit installer treats
`hapax-local-judge.service` as
decommissioned and leaves an installed `/dev/null` mask as its tombstone. Its
retirement transaction runs before environment sync:

1. Enumerate the exact local Docker daemon and capture a matching container's
   full immutable ID.
2. Disable the historical unit, remove wants links and drop-ins, replace its
   installed unit with a `/dev/null` mask, and reload the user manager.
3. Remove only the captured immutable container ID, signal the masked unit's
   main process without invoking its historical name-based `ExecStop`, and
   reject any replacement identity.

A retry that begins with the `/dev/null` mask already installed still re-enters
immutable-ID Docker reconciliation, so interruption between masking and removal
does not leave the transaction permanently half-retired.

This source task does not authorize running that transaction on Appendix. The
deployed historical unit remains a runtime gap until the normal user-unit
deployment is separately authorized. The observational OOM audit requires both
container absence and `LoadState=masked`, `UnitFileState=masked`,
`ActiveState=inactive`, and `FragmentPath=/dev/null`. Read-only inspection:

```sh
systemctl --user is-enabled hapax-local-judge.service
systemctl --user is-active hapax-local-judge.service
docker --host=unix:///var/run/docker.sock ps -a --no-trunc \
  --filter 'name=^/hapax-local-judge$' --format '{{.ID}} {{.Image}} {{.Names}}'
```

Future activation requires host-root signatures over the exact request ID,
generation, unit bytes, immutable image digest, content-addressed model digest
and size, cap values, and completion result. The complete threat input is
`docs/security/root-authority-hazard-register.md`. Same-UID receipts or local
health responses are not activation authority.

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

## Historical performance notes

- **No-co-residency guarantee:** the container is pinned to the 5060 Ti UUID; the
  3090 grounding instance (TabbyAPI `:5000`) is independent. Confirm with `nvidia-smi`.
- **Throughput:** 8 continuous-batch slots × 8192 ctx; ~137 tok/s decode, ~800 tok/s
  prompt. 127/2817 (4.5%) VerifierBench items exceed an 8192-token slot and are
  reported as context-skips by the harness — the longest/pathological inputs; raise
  `-c`÷`-np` per slot to score them if a full-coverage number is wanted.
- **Routing while parked:** calls must use the existing cloud fallback. A local
  responder on `:5001` is not proof that the retired service is safe or current.
- **Healthcheck caveat:** the historical container's image healthcheck probed a
  different port than the configured service. Treat its prior unhealthy status
  as non-diagnostic; immutable identity and the configured endpoint must be
  bound together in any future health contract.
