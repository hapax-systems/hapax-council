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

Every command in this section mutates the appendix runtime and requires separate
runtime authority. A source-only task must stop after preparing the staged package.

```bash
# one-time: confirm the 5060 Ti UUID and update the unit's JUDGE_GPU_UUID if it differs
nvidia-smi --query-gpu=index,name,uuid --format=csv

docker pull ghcr.io/ggml-org/llama.cpp:server-cuda

# Re-emit the authenticated command after runtime authority is granted. Never
# execute RUNBOOK.txt, copy the judge unit, or reproduce the authentication flow.
set -euo pipefail
state="$HOME/.local/state/hapax/root-required"
receipt="$state/desired-receipts/oom-containment.sha"
test -f "$receipt"
test ! -L "$receipt"
test "$(/usr/bin/stat -c %h -- "$receipt")" = 1
test "$(/usr/bin/wc -c < "$receipt")" = 41
IFS= read -r sha < "$receipt"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
stage="$HOME/.cache/hapax/post-merge-root-required/$sha/oom-containment"
runbook="$stage/RUNBOOK.txt"
test -f "$runbook"
test ! -L "$runbook"
test ! -x "$runbook"
grep -Fqx 'DO NOT EXECUTE THIS FILE OR COPY A COMMAND FROM IT. It is caller-owned pending-state' "$runbook"
# Run hapax-post-merge-deploy for "$sha" and execute only its live terminal line
# beginning "next action: run:". The pending RUNBOOK is metadata, not code.
~/.local/bin/hapax-post-merge-deploy "$sha"
/usr/bin/grep -Fqx \
  "hapax-root-required-deferred-install: completed authenticated package=oom-containment sha=$sha" \
  "$stage/AUTHENTICATED-INSTALL.log"

# The package deliberately does not enable or restart the judge. Activation is
# a separate, runtime-authorized step after the exact package verifies.
systemctl --user enable --now hapax-local-judge
# verify model loaded on GPU1 and 3090 VRAM unchanged:
curl -s http://localhost:5001/v1/models | grep compassverifier
nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader
```

The name `hapax-local-judge` is reserved for the systemd unit. It refuses to
delete an unknown same-name container. `After=docker.service` is retained as an
estate convention, but a user manager cannot enforce system-manager ordering;
`Restart=always` with `RestartSec=5s` is the actual Docker-socket readiness path.

The recurring OOM audit requires a present judge container to be `running`. If
it reports that a non-running container holds the name, stop the unit, inspect
the immutable container ID reported by the audit, and confirm it is the stale
judge before removing that exact ID without `-f`:

```sh
systemctl --user stop hapax-local-judge.service
container_id=<immutable-id-from-audit>
docker inspect "$container_id"
test "$(docker inspect --format '{{.Name}}' "$container_id")" = /hapax-local-judge
docker rm "$container_id"
systemctl --user start hapax-local-judge.service
/usr/local/sbin/hapax-oom-policy-audit
```

For an ad-hoc diagnostic run, keep the managed unit stopped and use a distinct
ephemeral name and port:

```sh
docker run --rm --name hapax-local-judge-adhoc \
  --memory 4G --memory-swap 6G \
  --gpus device=<5060Ti-UUID> \
  -v ~/models/compassverifier-7b:/models:ro -p 15001:5001 \
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
- **Candidate host-memory ceiling:** source and manual launches use `--memory 4G
  --memory-swap 6G`: a 4 GiB RAM cap and a 6 GiB combined memory-plus-swap cap,
  permitting at most 2 GiB of swap while leaving the OOM killer enabled. This is
  not runtime-accepted merely because the source tests pass. Before activation or
  runtime closure, deploy `hapax-local-judge.service` only through the manifest-owned
  P0 OOM package; ordinary post-merge deployment stages it without copying or
  restarting the user unit. Then run this 8-worker, 24-request canary and require
  identical container health/restart/OOM state plus unchanged `oom` and
  `oom_kill` counters:

  ```bash
  set -euo pipefail
  repo="${HAPAX_COUNCIL_REPO:-$HOME/.cache/hapax/source-activation/worktree}"
  test -d "$repo/scripts/cost-offload"
  unit=hapax-local-judge.service
  test "$(systemctl --user show "$unit" -p NeedDaemonReload --value)" = no
  test "$(systemctl --user show "$unit" -p FragmentPath --value)" = \
    "$HOME/.config/systemd/user/$unit"
  test -z "$(systemctl --user show "$unit" -p DropInPaths --value)"
  exec_start="$(systemctl --user show "$unit" -p ExecStart --value)"
  [[ "$exec_start" == *"argv[]=/usr/bin/docker run "* ]]
  [[ "$exec_start" == *" --name hapax-local-judge "* ]]
  [[ "$exec_start" == *" --memory 4G "* ]]
  [[ "$exec_start" == *" --memory-swap 6G "* ]]
  container=hapax-local-judge
  oom_kill_disable="$(docker inspect --format '{{json .HostConfig.OomKillDisable}}' "$container")"
  [[ "$oom_kill_disable" == null || "$oom_kill_disable" == false ]]
  pid="$(docker inspect --format '{{.State.Pid}}' "$container")"
  test "$pid" -gt 1
  cgroup="$(awk -F: '$1 == "0" {print $3; exit}' "/proc/$pid/cgroup")"
  events="/sys/fs/cgroup${cgroup}/memory.events"
  test -r "$events"
  before_state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}|{{.RestartCount}}|{{.State.OOMKilled}}' "$container")"
  before_oom="$(awk '$1 == "oom" || $1 == "oom_kill" {print}' "$events")"
  results="${TMPDIR:-/tmp}/local-judge-eight-slot.jsonl"
  (
    cd "$repo/scripts/cost-offload"
    uv run --with pandas --with pyarrow --with requests \
      python run_verifierbench.py --endpoint http://localhost:5001 \
      --n 24 --workers 8 --out "$results"
  )
  jq -e -s 'length == 24 and all(.[]; type == "object" and has("error") and has("pred") and .error == null and (.pred == "A" or .pred == "B" or .pred == "C"))' \
    "$results" >/dev/null
  after_state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}|{{.RestartCount}}|{{.State.OOMKilled}}' "$container")"
  after_oom="$(awk '$1 == "oom" || $1 == "oom_kill" {print}' "$events")"
  test "$before_state" = "$after_state"
  test "$before_oom" = "$after_oom"
  ```
- **Throughput:** 8 continuous-batch slots × 8192 ctx; ~137 tok/s decode, ~800 tok/s
  prompt. 127/2817 (4.5%) VerifierBench items exceed an 8192-token slot and are
  reported as context-skips by the harness — the longest/pathological inputs; raise
  `-c`÷`-np` per slot to score them if a full-coverage number is wanted.
- **Fallback drill:** `docker stop hapax-local-judge`, then a `local-judge` call
  through `:4000` should return a `claude-haiku` answer without a hard error; restart
  with `systemctl --user start hapax-local-judge`.
