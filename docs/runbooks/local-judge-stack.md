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
- **Serving:** `ghcr.io/ggml-org/llama.cpp@sha256:841b199aed2649a748875b043b32fed2e8c2d4d87e1d563556817fb7fa44b72b` (natively Blackwell-capable:
  `ARCHS=...,1200`, `BLACKWELL_NATIVE_FP4=1`) on `:5001`, OpenAI-compatible `/v1`.
- **Gateway:** podium LiteLLM (`:4000`) exposes it as the `local-judge` route, reached
  cross-rig at `http://192.168.68.50:5001/v1`.

## Deploy (appendix)

Model source (already present):
`~/models/compassverifier-7b/CompassVerifier-7B.Q5_K_M.gguf` (5.4 GB; GGUF
Q5_K_M). The authorized canary copies it once into a root-owned SHA-addressed
directory on the existing `/store-fast` NVMe and serves only that protected copy.
Preflight pins the Samsung volume's XFS UUID
`5934e619-0f38-4285-8556-5fed21ef7b9a` and carries its live mount ID through
every staging transition, so a `nofail` mount miss cannot fall through to SATA.

After the merged release containing this protected-model measurement helper is
the canonical source-activation worktree, and before requesting runtime authority,
perform this read-only source/live identity recheck. It hashes and measures the
protected target without staging, starting, stopping, or replacing anything. An
unrecognized option means source activation is stale, not that the model is invalid:
A missing protected path means the model has not yet been staged; that is expected
before an authorized canary and is not an integrity failure.

```bash
account_home="$(/usr/bin/getent passwd "$(/usr/bin/id -u)" | /usr/bin/cut -d: -f6)"
"$account_home/.cache/hapax/source-activation/worktree/scripts/hapax-post-merge-deploy" \
  --measure-protected-local-judge-model \
  /store-fast/hapax-models/sha256/d6d6fba56c25d2d0f1b2cc8ee261b209b77729510b3d770d43ccb6e741dff0db/CompassVerifier-7B.Q5_K_M.gguf
```

Every mutation described below is unavailable in this source revision. Runtime
work requires a task note whose frontmatter explicitly grants
`runtime_mutation_authorized: true`, but that grant alone is not executable
authority and does not make a source-published command safe.

Protected model staging remains the first separately measured phase of the future
mandatory canary, not an activation side effect. A future root-owned package
broker and activation fence must each verify an attested exact-SHA result before
their first mutation, so skipped or incomplete staging is rejected before the
durable unit can be started.

The active task must authorize every semantic effect listed in the candidate
`config/root-required/oom-containment.effects` plus the canary. Activation and
managed-recheck scopes are intentionally absent because this revision provides
no runnable fence for either. The exact-SHA helper validates that task only as
advisory narrowing. It cannot grant production effects and never executes the
interpreted installer in production. A future independently installed root-owned
package broker must derive authority, package bytes, destinations, and the fixed
effect transaction again at the privileged boundary.
Source-file paths, caller-owned task rows, cap receipts, sealed descriptors, and
helper results are evidence, not bearer authority.

The future broker interface also carries a helper-generated 256-bit correlation
ID. It is not authority. Plain root ownership is namespace-relative and cannot
authenticate host root to a same-UID caller that can create user and mount
namespaces. This revision therefore contains no executable production broker path
and refuses before state locking or package validation. A successor may add such a path only
after a separately reviewed protocol signs or MACs request ID, package, SHA, and
completion generation with a host-root-held key and verifies that attestation
against a source-pinned trust anchor. File-level per-request and current mode-`0444`
receipts remain useful shape requirements, not authority. Caller-owned installed
receipts never drain pending work before the broker runs. The broker, attestation
key lifecycle, exact `NOSETENV` sudo rule, retention, and blanket-`NOPASSWD: ALL`
retirement are separate runtime-authorized work; none is implemented here.

### Required pre-deploy cap canary unavailable

The prior canary recipe performed model publication, service transitions, image
pulls, and container lifecycle mutations directly from caller-controlled shell
state. It is intentionally removed. No canary or protected-model publication is
runnable in this source revision. A successor must bind the exact request ID,
package SHA, model digest, image digest, effect set, and result to a
cryptographically attested host-root transaction before exposing any command.
Until then, retain the read-only protected-path measurement above and keep the
canary, installation, activation, and managed recheck predicates open.

### Broker-gated package installation unavailable

This source revision has no executable package broker or helper command. Current
and historical Git helper blobs are data only and must never be streamed into an
interpreter. Caller-owned desired receipts, pending packages, task notes, logs,
and apparent root ownership do not enable installation or prove completion.
Preserve pending exact-SHA packages while separately runtime-authorized broker
and cryptographic-attestation work is designed and reviewed.

There is intentionally no installed-verification recipe. Production verification
must fail until a source-pinned verifier can validate matching per-request and
current-generation host-root attestations for one exact request ID, package, SHA,
and effect transaction.

### Activation and recheck unavailable

The package does not enable or restart the judge. This source revision has no
runnable activation, stale-container cleanup, ad hoc container, or managed
recheck procedure. Caller-owned desired, installed, canary, activation, or
managed-recheck records cannot attest that host root applied the exact package.
The installed receipt verifier therefore fails before reading those records.

A separately authorized successor must verify matching cryptographically
attested per-request and current-generation records from a source-pinned trust
anchor before any service-manager, container, result-state, or workload
mutation. Until that protocol exists, inspect diagnostics read-only and leave
activation and recheck blocked.

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

LiteLLM reload remains a separately governed runtime action; this runbook does
not provide a direct mutation command.

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
- **Candidate host-memory ceiling:** source and manual launches use `--memory 4G
  --memory-swap 6G`: a 4 GiB RAM cap and a 6 GiB combined memory-plus-swap cap,
  permitting at most 2 GiB of swap while leaving the OOM killer enabled. This is
  intentionally looser than the canary's 1 GiB accepted swap peak, preserving
  another 1 GiB inside the hard limit rather than treating the limit as a target.
  The cap is not runtime-accepted merely because the source tests pass. The future
  pre-deploy canary will gate source candidacy only. The managed 8-worker,
  24-request post-activation recheck is intentionally unavailable in this
  revision for the same reason as activation: no cryptographically attested
  installed package generation exists. Its health, restart, OOM, and peak-memory
  predicates remain required for runtime closure after the attested protocol is
  implemented; caller-owned workload output is not closure evidence.
- **Throughput:** 8 continuous-batch slots × 8192 ctx; ~137 tok/s decode, ~800 tok/s
  prompt. 127/2817 (4.5%) VerifierBench items exceed an 8192-token slot and are
  reported as context-skips by the harness — the longest/pathological inputs; raise
  `-c`÷`-np` per slot to score them if a full-coverage number is wanted.
- **Fallback drill:** unavailable until the attested activation protocol can bind
  lifecycle transitions and restoration to one governed request. Read-only state
  inspection may continue, but this runbook publishes no stop, start, or container
  removal command.
