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

Every command below mutates the appendix runtime and requires a task note whose
frontmatter explicitly grants `runtime_mutation_authorized: true`. A source-only
task stops here. The disposable canary uses the exact proposed `4G/6G` limits and
must pass before the authenticated package command is requested.

### Required pre-deploy cap canary

This canary temporarily stops the managed judge if it is active, starts an
immutable-ID-tracked disposable container on port 15001, and restores the prior
unit state before package installation. It never removes a container by name.

```bash
set -euo pipefail
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
authority_check="$HOME/.local/bin/hapax-post-merge-deploy"
test -f "$authority_check"
test ! -L "$authority_check"
"$authority_check" --verify-runtime-authority \
  "$runtime_task" systemd/units/hapax-local-judge.service

repo_alias="$HOME/.cache/hapax/source-activation/worktree"
repo="$(/usr/bin/realpath -e -- "$repo_alias")"
release_root="$HOME/.cache/hapax/source-activation/releases"
test "${repo%/*}" = "$release_root"
[[ "${repo##*/}" =~ ^[0-9a-f]{40}$ ]]
test "$(/usr/bin/stat -c %u -- "$repo")" = "$(/usr/bin/id -u)"
candidate_sha="${repo##*/}"
state="$HOME/.local/state/hapax/root-required"
desired_receipt="$state/desired-receipts/oom-containment.sha"
test -f "$desired_receipt"
test ! -L "$desired_receipt"
test "$(/usr/bin/stat -c %u -- "$desired_receipt")" = "$(/usr/bin/id -u)"
test "$(/usr/bin/stat -c %h -- "$desired_receipt")" = 1
receipt_mode="$(/usr/bin/stat -c %a -- "$desired_receipt")"
(( (8#$receipt_mode & 022) == 0 ))
test "$(/usr/bin/wc -c < "$desired_receipt")" = 41
IFS= read -r desired_sha < "$desired_receipt"
test "$desired_sha" = "$candidate_sha"
source_unit="$repo/systemd/units/hapax-local-judge.service"
test -f "$source_unit"
test ! -L "$source_unit"
test "$(grep -c '^Environment=JUDGE_GPU_UUID=' "$source_unit")" -eq 1
judge_gpu_uuid="$(sed -n 's/^Environment=JUDGE_GPU_UUID=//p' "$source_unit")"
test -n "$judge_gpu_uuid"
nvidia-smi --query-gpu=uuid --format=csv,noheader | grep -Fqx "$judge_gpu_uuid"

image=ghcr.io/ggml-org/llama.cpp:server-cuda
unit=hapax-local-judge.service
canary_name="hapax-local-judge-cap-canary-$$"
canary_id=""
endpoint=http://127.0.0.1:15001
results="/store-fast/tmp/local-judge-cap-canary-$$.jsonl"
canary_cidfile="/store-fast/tmp/local-judge-cap-canary-$$.cid"
canary_receipt_root="$state/local-judge-cap-canary"
canary_receipt="$canary_receipt_root/$candidate_sha.env"
test -d /store-fast/tmp
test ! -e "$results"
test ! -e "$canary_cidfile"
docker pull "$image"
image_id="$(docker image inspect --format '{{.Id}}' "$image")"
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
host="$(hostname)"
test "$host" = hapax-appendix

was_active="$(systemctl --user show "$unit" -p ActiveState --value)"
case "$was_active" in
  active|inactive|failed) ;;
  *) echo "refusing transitional or unknown $unit state: $was_active" >&2; exit 1 ;;
esac
cleanup_done=0
cleanup_status=0
cleanup_canary() {
  if [ "$cleanup_done" -eq 1 ]; then
    return "$cleanup_status"
  fi
  cleanup_done=1
  local id="" remaining="" removed=0 restored_state="" cidfile_safe=0
  if [ -e "$canary_cidfile" ] || [ -L "$canary_cidfile" ]; then
    if [ -f "$canary_cidfile" ] && [ ! -L "$canary_cidfile" ]; then
      id="$(< "$canary_cidfile")"
      if [[ "$id" =~ ^[0-9a-f]{64}$ ]]; then
        cidfile_safe=1
      fi
    fi
    if [ "$cidfile_safe" -eq 1 ]; then
      if docker inspect "$id" >/dev/null 2>&1; then
        if docker stop "$id" >/dev/null; then
          for _ in $(seq 1 30); do
            if ! docker inspect "$id" >/dev/null 2>&1; then
              removed=1
              break
            fi
            sleep 1
          done
          if [ "$removed" -ne 1 ]; then
            echo "canary container did not terminate and remove: $id" >&2
            cleanup_status=1
          fi
        else
          echo "failed to stop canary container by immutable ID: $id" >&2
          cleanup_status=1
        fi
      fi
    else
      echo "unsafe or invalid canary cidfile: $canary_cidfile" >&2
      cleanup_status=1
    fi
  fi
  if ! remaining="$(docker ps -aq --filter "name=^/${canary_name}$")"; then
    echo "cannot prove canary-name absence during cleanup: $canary_name" >&2
    cleanup_status=1
  elif [ -n "$remaining" ]; then
    echo "canary container remains after cleanup: $remaining" >&2
    cleanup_status=1
  fi
  if ! rm -f -- "$results"; then
    echo "cannot remove owned canary result file: $results" >&2
    cleanup_status=1
  fi
  if [ "$cleanup_status" -eq 0 ]; then
    rm -f -- "$canary_cidfile"
    if [ "$was_active" = active ]; then
      if ! systemctl --user start "$unit"; then
        echo "failed to restore $unit after proven canary termination" >&2
        cleanup_status=1
      else
        restored_state="$(systemctl --user show "$unit" -p ActiveState --value)"
        if [ "$restored_state" != active ]; then
          echo "restored $unit did not reach active state: $restored_state" >&2
          cleanup_status=1
        fi
      fi
    fi
  elif [ "$was_active" = active ]; then
    echo "not restoring $unit because disposable-container absence is unproven" >&2
    echo "next action: inspect $canary_cidfile and $canary_name, stop the immutable ID, then restore the unit" >&2
  fi
  return "$cleanup_status"
}
on_exit() {
  local rc=$?
  trap - EXIT INT TERM
  if ! cleanup_canary; then
    rc=1
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [ "$was_active" = active ]; then
  systemctl --user stop "$unit"
  test "$(systemctl --user show "$unit" -p ActiveState --value)" = inactive
fi
managed_ids="$(docker ps -aq --filter 'name=^/hapax-local-judge$')"
test -z "$managed_ids"

docker run --cidfile "$canary_cidfile" -d --rm --name "$canary_name" \
  --memory 4G --memory-swap 6G \
  --gpus "device=$judge_gpu_uuid" \
  -v "$HOME/models/compassverifier-7b:/models:ro" \
  -p 127.0.0.1:15001:5001 \
  "$image" \
  -m /models/CompassVerifier-7B.Q5_K_M.gguf -a compassverifier-7b \
  -c 65536 -np 8 -cb -ngl 99 --host 0.0.0.0 --port 5001 >/dev/null
test -f "$canary_cidfile"
test ! -L "$canary_cidfile"
test "$(/usr/bin/wc -c < "$canary_cidfile")" = 64
canary_id="$(< "$canary_cidfile")"
[[ "$canary_id" =~ ^[0-9a-f]{64}$ ]]
test "$(docker inspect --format '{{.Name}}' "$canary_id")" = "/$canary_name"
limit_fields="$(docker inspect --format \
  '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{json .HostConfig.OomKillDisable}}' \
  "$canary_id")"
read -r memory memory_swap oom_kill_disable extra <<< "$limit_fields"
test -z "${extra:-}"
test "$memory" = 4294967296
test "$memory_swap" = 6442450944
[[ "$oom_kill_disable" == null || "$oom_kill_disable" == false ]]

ready=0
for _ in $(seq 1 90); do
  if curl -fsS "$endpoint/v1/models" | jq -e \
    '.data | any(.id == "compassverifier-7b")' >/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
test "$ready" -eq 1

pid="$(docker inspect --format '{{.State.Pid}}' "$canary_id")"
test "$pid" -gt 1
cgroup="$(awk -F: '$1 == "0" {print $3; exit}' "/proc/$pid/cgroup")"
events="/sys/fs/cgroup${cgroup}/memory.events"
memory_peak_path="/sys/fs/cgroup${cgroup}/memory.peak"
swap_peak_path="/sys/fs/cgroup${cgroup}/memory.swap.peak"
test -r "$events"
test -r "$memory_peak_path"
test -r "$swap_peak_path"
before_state="$(docker inspect --format '{{.State.Status}}|{{.RestartCount}}|{{.State.OOMKilled}}' "$canary_id")"
before_oom="$(awk '$1 == "oom" || $1 == "oom_kill" {print}' "$events")"
(
  cd "$repo/scripts/cost-offload"
  uv run --with pandas --with pyarrow --with requests \
    python run_verifierbench.py --endpoint "$endpoint" \
    --n 24 --workers 8 --out "$results"
)
jq -e -s 'length == 24 and all(.[]; type == "object" and has("error") and has("pred") and .error == null and (.pred == "A" or .pred == "B" or .pred == "C"))' \
  "$results" >/dev/null
after_state="$(docker inspect --format '{{.State.Status}}|{{.RestartCount}}|{{.State.OOMKilled}}' "$canary_id")"
after_oom="$(awk '$1 == "oom" || $1 == "oom_kill" {print}' "$events")"
memory_peak="$(cat "$memory_peak_path")"
swap_peak="$(cat "$swap_peak_path")"
test "$before_state" = "$after_state"
test "$before_oom" = "$after_oom"
test "$memory_peak" -le 3221225472  # retain at least 1 GiB RAM headroom
test "$swap_peak" -le 1073741824    # retain at least 1 GiB swap headroom

test "$(/usr/bin/realpath -e -- "$repo_alias")" = "$repo"
IFS= read -r desired_sha_after < "$desired_receipt"
test "$desired_sha_after" = "$candidate_sha"
cleanup_canary
trap - EXIT INT TERM

test ! -L "$canary_receipt_root"
mkdir -p "$canary_receipt_root"
chmod 0700 "$canary_receipt_root"
receipt_tmp="$(mktemp "$canary_receipt_root/.${candidate_sha}.tmp.XXXXXX")"
chmod 0600 "$receipt_tmp"
completed_at_epoch="$(date +%s)"
printf '%s\n' \
  'schema=1' \
  "candidate_sha=$candidate_sha" \
  "host=$host" \
  "gpu_uuid=$judge_gpu_uuid" \
  "image_id=$image_id" \
  'memory_bytes=4294967296' \
  'memory_swap_bytes=6442450944' \
  'requests=24' \
  'workers=8' \
  "memory_peak_bytes=$memory_peak" \
  "swap_peak_bytes=$swap_peak" \
  "completed_at_epoch=$completed_at_epoch" > "$receipt_tmp"
mv -fT -- "$receipt_tmp" "$canary_receipt"
echo "local-judge cap canary accepted: $canary_receipt"
```

### Authenticated package installation

```bash
# Re-emit the authenticated command after runtime authority is granted. Never
# execute RUNBOOK.txt, copy the judge unit, or reproduce the authentication flow.
set -euo pipefail
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
authority_check="$HOME/.local/bin/hapax-post-merge-deploy"
test -f "$authority_check"
test ! -L "$authority_check"
"$authority_check" --verify-runtime-authority \
  "$runtime_task" systemd/units/hapax-local-judge.service
state="$HOME/.local/state/hapax/root-required"
receipt="$state/desired-receipts/oom-containment.sha"
test -f "$receipt"
test ! -L "$receipt"
test "$(/usr/bin/stat -c %h -- "$receipt")" = 1
test "$(/usr/bin/wc -c < "$receipt")" = 41
IFS= read -r sha < "$receipt"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
"$authority_check" --verify-local-judge-cap-receipt "$sha" candidate
stage="$HOME/.cache/hapax/post-merge-root-required/$sha/oom-containment"
runbook="$stage/RUNBOOK.txt"
test -f "$runbook"
test ! -L "$runbook"
test ! -x "$runbook"
grep -Fqx 'DO NOT EXECUTE THIS FILE OR COPY A COMMAND FROM IT. It is caller-owned pending-state' "$runbook"
# Run hapax-post-merge-deploy for "$sha" and execute only its live terminal line
# beginning "next action: run:". The pending RUNBOOK is metadata, not code.
~/.local/bin/hapax-post-merge-deploy "$sha"
```

Execute only the live terminal `next action: run:` line emitted by that command.
After it returns successfully, verify the authenticated completion and installed
receipt in a new shell:

```bash
set -euo pipefail
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
authority_check="$HOME/.local/bin/hapax-post-merge-deploy"
test -f "$authority_check"
test ! -L "$authority_check"
"$authority_check" --verify-runtime-authority \
  "$runtime_task" systemd/units/hapax-local-judge.service
state="$HOME/.local/state/hapax/root-required"
receipt="$state/desired-receipts/oom-containment.sha"
test -f "$receipt"
test ! -L "$receipt"
test "$(/usr/bin/wc -c < "$receipt")" = 41
IFS= read -r sha < "$receipt"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
"$authority_check" --verify-local-judge-cap-receipt "$sha" installed
stage="$HOME/.cache/hapax/post-merge-root-required/$sha/oom-containment"
/usr/bin/grep -Fqx \
  "hapax-root-required-deferred-install: completed authenticated package=oom-containment sha=$sha" \
  "$stage/AUTHENTICATED-INSTALL.log"
/usr/bin/grep -Fqx "$sha" "$state/installed-receipts/oom-containment.sha"
```

### Separate activation and recheck

The package deliberately does not enable or restart the judge. This separately
authorized fence reloads the exact installed unit, then rechecks the effective
limits and the recurring audit.

```bash
set -euo pipefail
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
authority_check="$HOME/.local/bin/hapax-post-merge-deploy"
test -f "$authority_check"
test ! -L "$authority_check"
"$authority_check" --verify-runtime-authority \
  "$runtime_task" systemd/units/hapax-local-judge.service
state="$HOME/.local/state/hapax/root-required"
receipt="$state/desired-receipts/oom-containment.sha"
test -f "$receipt"
test ! -L "$receipt"
test "$(/usr/bin/stat -c %h -- "$receipt")" = 1
test "$(/usr/bin/wc -c < "$receipt")" = 41
IFS= read -r sha < "$receipt"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
"$authority_check" --verify-local-judge-cap-receipt "$sha" installed
systemctl --user daemon-reload
exec_start="$(systemctl --user show hapax-local-judge.service -p ExecStart --value)"
[[ "$exec_start" == *" --memory 4G "* ]]
[[ "$exec_start" == *" --memory-swap 6G "* ]]
systemctl --user enable hapax-local-judge.service
systemctl --user restart hapax-local-judge.service
# verify model loaded on GPU1 and 3090 VRAM unchanged:
curl -s http://localhost:5001/v1/models | grep compassverifier
nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader
/usr/local/sbin/hapax-oom-policy-audit
```

The name `hapax-local-judge` is reserved for the systemd unit. It refuses to
delete an unknown same-name container. `After=docker.service` is retained as an
estate metadata parity token. The recheck is
`systemctl --user show hapax-local-judge.service -p After`; it does not create a
cross-manager Docker job. `Restart=always` with
`RestartSec=5s` is the actual Docker-socket readiness path. A same-name collision
therefore causes an intentional, audit-visible restart loop until reconciled.

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
  intentionally looser than the canary's 1 GiB accepted swap peak, preserving
  another 1 GiB inside the hard limit rather than treating the limit as a target.
  The cap is not runtime-accepted merely because the source tests pass. The required
  pre-deploy canary above gates installation of the candidate. After activation,
  repeat the same 8-worker, 24-request load against the managed container before
  runtime closure and require unchanged health/restart/OOM state, unchanged `oom`
  counters, and the same peak-memory headroom:

  ```bash
  set -euo pipefail
  runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
  authority_check="$HOME/.local/bin/hapax-post-merge-deploy"
  test -f "$authority_check"
  test ! -L "$authority_check"
  "$authority_check" --verify-runtime-authority \
    "$runtime_task" systemd/units/hapax-local-judge.service
  repo_alias="$HOME/.cache/hapax/source-activation/worktree"
  repo="$(/usr/bin/realpath -e -- "$repo_alias")"
  release_root="$HOME/.cache/hapax/source-activation/releases"
  test "${repo%/*}" = "$release_root"
  [[ "${repo##*/}" =~ ^[0-9a-f]{40}$ ]]
  test "$(/usr/bin/stat -c %u -- "$repo")" = "$(/usr/bin/id -u)"
  sha="${repo##*/}"
  "$authority_check" --verify-local-judge-cap-receipt "$sha" installed
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
  memory_peak_path="/sys/fs/cgroup${cgroup}/memory.peak"
  swap_peak_path="/sys/fs/cgroup${cgroup}/memory.swap.peak"
  test -r "$events"
  test -r "$memory_peak_path"
  test -r "$swap_peak_path"
  before_state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}|{{.RestartCount}}|{{.State.OOMKilled}}' "$container")"
  before_oom="$(awk '$1 == "oom" || $1 == "oom_kill" {print}' "$events")"
  results="/store-fast/tmp/local-judge-managed-recheck-$$.jsonl"
  test -d /store-fast/tmp
  test ! -e "$results"
  trap 'rm -f "$results"' EXIT
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
  memory_peak="$(cat "$memory_peak_path")"
  swap_peak="$(cat "$swap_peak_path")"
  test "$before_state" = "$after_state"
  test "$before_oom" = "$after_oom"
  test "$memory_peak" -le 3221225472
  test "$swap_peak" -le 1073741824
  rm -f "$results"
  trap - EXIT
  ```
- **Throughput:** 8 continuous-batch slots × 8192 ctx; ~137 tok/s decode, ~800 tok/s
  prompt. 127/2817 (4.5%) VerifierBench items exceed an 8192-token slot and are
  reported as context-skips by the harness — the longest/pathological inputs; raise
  `-c`÷`-np` per slot to score them if a full-coverage number is wanted.
- **Fallback drill:** `docker stop hapax-local-judge`, then a `local-judge` call
  through `:4000` should return a `claude-haiku` answer without a hard error; restart
  with `systemctl --user start hapax-local-judge`.
