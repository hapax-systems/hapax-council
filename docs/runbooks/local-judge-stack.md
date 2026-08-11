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

Before requesting runtime authority, perform this read-only source/live identity
recheck. It hashes and measures the protected target without staging, starting,
stopping, or replacing anything:

```bash
account_home="$(/usr/bin/getent passwd "$(/usr/bin/id -u)" | /usr/bin/cut -d: -f6)"
"$account_home/.cache/hapax/source-activation/worktree/scripts/hapax-post-merge-deploy" \
  --measure-protected-local-judge-model \
  /store-fast/hapax-models/sha256/d6d6fba56c25d2d0f1b2cc8ee261b209b77729510b3d770d43ccb6e741dff0db/CompassVerifier-7B.Q5_K_M.gguf
```

Every command below mutates the appendix runtime and requires a task note whose
frontmatter explicitly grants `runtime_mutation_authorized: true`. A source-only
task stops here. The disposable canary uses the exact proposed `4G/6G` limits and
must pass before the authenticated package command is requested.

Protected model staging is the first separately measured phase of that mandatory
canary, not an activation side effect. The block below runs
`--measure-protected-local-judge-model` against the root-owned content address
before starting the disposable container and writes the candidate cap receipt
only after both staging and the workload pass. Authenticated installation and
activation each verify that exact-SHA receipt before their first mutation, so a
skipped or incomplete staging canary is rejected before the durable unit can be
started.

The active task must authorize every semantic effect listed in the candidate
`config/root-required/oom-containment.effects`, plus the canary, activation, and
managed-recheck effects used below. The authenticated helper reads that exact-SHA
descriptor and validates the complete set in one task parse before sudo, after
sudo, and after live verification immediately before receipt advancement and
deferral drain.
Source-file paths are package inventory, not runtime authority.
This is a cooperative single-operator boundary: the active task and cap receipt
are caller-owned evidence, while root-owned model staging and installed artifacts
prevent later account-level substitution.

### Required pre-deploy cap canary

This canary temporarily stops the managed judge if it is active, starts an
immutable-ID-tracked disposable container on port 15001, and restores the prior
unit state before package installation. It never removes a container by name.
Its fixed 8 workers match the unit's `-np 8` parallelism, and 24 requests exercise
three complete concurrency waves. The workload is deliberately synthetic: the
deploy gate favors deterministic candidate-bound evidence over representative
traffic, while the separate VerifierBench workflow below remains the quality
benchmark.

```bash
account_uid="$(/usr/bin/id -u)"
account_name="$(/usr/bin/id -un)"
account_home="$(/usr/bin/getent passwd "$account_uid" | /usr/bin/cut -d: -f6)"
test -n "$account_home"
test "$account_home" = "$(/usr/bin/realpath -e -- "$account_home")"
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
/usr/bin/env -i \
  HOME="$account_home" \
  USER="$account_name" \
  LOGNAME="$account_name" \
  PATH=/usr/bin:/bin \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  XDG_RUNTIME_DIR="/run/user/$account_uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$account_uid/bus" \
  HAPAX_RUNTIME_AUTHORITY_TASK="$runtime_task" \
  /usr/bin/bash --noprofile --norc -p -s <<'HAPAX_LOCAL_JUDGE_CAP_CANARY'
set -euo pipefail
PATH=/usr/bin:/bin
export PATH
DOCKER_HOST=unix:///var/run/docker.sock
export DOCKER_HOST
test -S /var/run/docker.sock
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
repo_alias="$HOME/.cache/hapax/source-activation/worktree"
repo="$(/usr/bin/realpath -e -- "$repo_alias")"
release_root="$HOME/.cache/hapax/source-activation/releases"
test "${repo%/*}" = "$release_root"
[[ "${repo##*/}" =~ ^[0-9a-f]{40}$ ]]
test "$(/usr/bin/stat -c %u -- "$repo")" = "$(/usr/bin/id -u)"
candidate_sha="${repo##*/}"
candidate_git() {
  /usr/bin/env -i \
    HOME=/nonexistent \
    PATH=/usr/bin:/bin \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_NO_REPLACE_OBJECTS=1 \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git -C "$repo" "$@"
}
test "$(candidate_git rev-parse --verify 'HEAD^{commit}')" = "$candidate_sha"
verifier_oid="$(candidate_git rev-parse --verify "$candidate_sha:scripts/hapax-post-merge-deploy")"
[[ "$verifier_oid" =~ ^[0-9a-f]{40}$ ]]
candidate_verify() {
  candidate_git cat-file blob "$verifier_oid" | \
    /usr/bin/env -i \
      HOME="$HOME" \
      USER="$USER" \
      LOGNAME="$LOGNAME" \
      PATH=/usr/bin:/bin \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
      DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
      DOCKER_HOST="$DOCKER_HOST" \
      HAPAX_RUNTIME_AUTHORITY_TASK="$runtime_task" \
      REPO="$repo" \
      /usr/bin/bash --noprofile --norc -p -s -- "$@"
}
canary_scopes=(
  runtime:docker:pull:ghcr.io/ggml-org/llama.cpp@sha256:841b199aed2649a748875b043b32fed2e8c2d4d87e1d563556817fb7fa44b72b
  runtime:docker:run-remove:hapax-local-judge-cap-canary
  runtime:root-directory:ensure-root-0755:/store-fast/hapax-models
  runtime:root-directory:ensure-root-0755:/store-fast/hapax-models/sha256
  runtime:root-directory:ensure-root-0755:/store-fast/hapax-models/sha256/d6d6fba56c25d2d0f1b2cc8ee261b209b77729510b3d770d43ccb6e741dff0db
  runtime:root-file:stage-content-addressed:/store-fast/hapax-models/sha256/d6d6fba56c25d2d0f1b2cc8ee261b209b77729510b3d770d43ccb6e741dff0db/CompassVerifier-7B.Q5_K_M.gguf
  runtime:state:write-local-judge-cap-receipt
  runtime:state:write-remove-canary-scratch:/store-fast/tmp
  runtime:systemd-user:stop-restore:hapax-local-judge.service
)
candidate_verify --verify-runtime-authority-for-release \
  "$candidate_sha" "$runtime_task" "${canary_scopes[@]}"

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
source_unit_text="$(candidate_git show "$candidate_sha:systemd/units/hapax-local-judge.service")"
for key in JUDGE_GPU_UUID JUDGE_MODEL JUDGE_MODEL_SHA256 JUDGE_MODEL_SIZE_BYTES JUDGE_MODEL_HOST_DIR JUDGE_MODEL_HOST JUDGE_IMAGE; do
  test "$(printf '%s\n' "$source_unit_text" | grep -c "^Environment=$key=")" -eq 1
done
judge_gpu_uuid="$(printf '%s\n' "$source_unit_text" | sed -n 's/^Environment=JUDGE_GPU_UUID=//p')"
judge_model="$(printf '%s\n' "$source_unit_text" | sed -n 's/^Environment=JUDGE_MODEL=//p')"
expected_model_sha256="$(printf '%s\n' "$source_unit_text" | sed -n 's/^Environment=JUDGE_MODEL_SHA256=//p')"
expected_model_size_bytes="$(printf '%s\n' "$source_unit_text" | sed -n 's/^Environment=JUDGE_MODEL_SIZE_BYTES=//p')"
model_host_dir="$(printf '%s\n' "$source_unit_text" | sed -n 's/^Environment=JUDGE_MODEL_HOST_DIR=//p')"
declared_model_host="$(printf '%s\n' "$source_unit_text" | sed -n 's/^Environment=JUDGE_MODEL_HOST=//p')"
image="$(printf '%s\n' "$source_unit_text" | sed -n 's/^Environment=JUDGE_IMAGE=//p')"
[[ "$judge_model" =~ ^/models/[A-Za-z0-9._-]+\.gguf$ ]]
[[ "$expected_model_sha256" =~ ^[0-9a-f]{64}$ ]]
[[ "$expected_model_size_bytes" =~ ^[0-9]{1,20}$ ]]
test "$model_host_dir" = "/store-fast/hapax-models/sha256/$expected_model_sha256"
test "$declared_model_host" = "$model_host_dir/${judge_model##*/}"
[[ "$image" =~ ^ghcr\.io/ggml-org/llama\.cpp@sha256:[0-9a-f]{64}$ ]]
nvidia-smi --query-gpu=uuid --format=csv,noheader | grep -Fqx "$judge_gpu_uuid"
workload_oid="$verifier_oid"
candidate_workload() {
  candidate_verify "$@"
}
model_source_path="$HOME/models/compassverifier-7b/${judge_model##*/}"
model_host_path="$model_host_dir/${judge_model##*/}"

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

if [ ! -e "$model_host_path" ] && [ ! -L "$model_host_path" ]; then
  test -f "$model_source_path"
  test ! -L "$model_source_path"
  test "$(stat -c %u -- "$model_source_path")" = "$(id -u)"
  test "$(stat -c %h -- "$model_source_path")" = 1
  test "$(stat -c %s -- "$model_source_path")" = "$expected_model_size_bytes"
  source_mode="$(stat -c %a -- "$model_source_path")"
  (( (8#$source_mode & 022) == 0 ))
  sudo /usr/bin/install -d -o root -g root -m 0755 \
    /store-fast/hapax-models /store-fast/hapax-models/sha256 "$model_host_dir"
  model_stage="$model_host_dir/.${judge_model##*/}.partial.$$"
  if ! /usr/bin/dd if="$model_source_path" bs=4M iflag=fullblock,nofollow status=none | \
      sudo /usr/bin/dd of="$model_stage" bs=4M oflag=excl,nofollow status=none; then
    sudo /usr/bin/rm -f -- "$model_stage"
    echo "protected model staging failed; rerun after checking source stability" >&2
    exit 1
  fi
  sudo /usr/bin/chmod 0444 "$model_stage"
  stage_evidence="$(candidate_workload --measure-protected-local-judge-model "$model_stage")"
  stage_sha256="$(printf '%s\n' "$stage_evidence" | sed -n 's/^model_sha256=//p')"
  stage_size_bytes="$(printf '%s\n' "$stage_evidence" | sed -n 's/^model_size_bytes=//p')"
  if [ "$stage_sha256" != "$expected_model_sha256" ] \
      || [ "$stage_size_bytes" != "$expected_model_size_bytes" ]; then
    sudo /usr/bin/rm -f -- "$model_stage"
    echo "protected model staging did not match the candidate digest and size" >&2
    echo "next action: quarantine the partial staged file, verify the source model, and rerun this exact-SHA canary" >&2
    exit 1
  fi
  sudo /usr/bin/mv -T -- "$model_stage" "$model_host_path"
fi
model_evidence="$(candidate_workload --measure-protected-local-judge-model "$model_host_path")"
model_sha256="$(printf '%s\n' "$model_evidence" | sed -n 's/^model_sha256=//p')"
model_size_bytes="$(printf '%s\n' "$model_evidence" | sed -n 's/^model_size_bytes=//p')"
model_identity="$(printf '%s\n' "$model_evidence" | sed -n 's/^model_identity=//p')"
if [ "$model_sha256" != "$expected_model_sha256" ] \
    || [ "$model_size_bytes" != "$expected_model_size_bytes" ]; then
  echo "protected model does not match the candidate digest and size" >&2
  echo "next action: stop activation, quarantine $model_host_path, and rerun the authorized exact-SHA staging canary" >&2
  exit 1
fi
[[ "$model_identity" =~ ^[0-9]+:[0-9]+:[0-9]+$ ]]

was_active="$(systemctl --user show "$unit" -p ActiveState --value)"
case "$was_active" in
  active|inactive|failed) ;;
  *)
    echo "refusing transitional or unknown $unit state: $was_active" >&2
    echo "next action: inspect systemctl --user status $unit, let transitions settle, and rerun preflight" >&2
    exit 1
    ;;
esac
if ! port_probe="$(/usr/bin/ss -H -ltn 'sport = :15001')"; then
  echo "cannot prove canary port 15001 availability" >&2
  echo "next action: restore /usr/bin/ss network inspection, then rerun preflight" >&2
  exit 1
elif [ -n "$port_probe" ]; then
  echo "refusing occupied canary port 15001" >&2
  echo "next action: identify and stop only the known listener on 127.0.0.1:15001, then rerun preflight" >&2
  exit 1
fi
printf 'local-judge cap canary preflight passed: candidate=%s unit_state=%s model=%s\n' \
  "$candidate_sha" "$was_active" "$model_identity"
canary_id_absent() {
  local matches=""
  if ! matches="$(docker ps -aq --no-trunc --filter "id=$1")"; then
    return 2
  fi
  [ -z "$matches" ]
}
cleanup_done=0
cleanup_status=0
cleanup_signal_rc=0
cleanup_canary() {
  if [ "$cleanup_done" -eq 1 ]; then
    return "$cleanup_status"
  fi
  cleanup_status=0
  local id="" observed_name="" remaining="" removed=0 restored_state=""
  if [ -n "$canary_id" ]; then
    if [[ "$canary_id" =~ ^[0-9a-f]{64}$ ]]; then
      id="$canary_id"
    else
      echo "unsafe bound canary ID; refusing container stop" >&2
      cleanup_status=1
    fi
  elif [ -e "$canary_cidfile" ] || [ -L "$canary_cidfile" ]; then
    if [ -f "$canary_cidfile" ] && [ ! -L "$canary_cidfile" ]; then
      id="$(< "$canary_cidfile")"
      if ! [[ "$id" =~ ^[0-9a-f]{64}$ ]]; then
        id=""
      fi
    fi
    if [ -z "$id" ]; then
      echo "unsafe or invalid canary cidfile: $canary_cidfile" >&2
      cleanup_status=1
    fi
  fi
  if [ -n "$id" ]; then
    if observed_name="$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null)"; then
      if [ "$observed_name" != "/$canary_name" ]; then
        echo "canary ID/name mismatch; refusing container stop: id=$id name=$observed_name" >&2
        cleanup_status=1
      else
        canary_id="$id"
        if docker stop "$id" >/dev/null; then
          for _ in $(seq 1 30); do
            if canary_id_absent "$id"; then
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
    elif ! canary_id_absent "$id"; then
      echo "cannot prove canary ID absence after inspect failure: $id" >&2
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
    if ! rm -f -- "$canary_cidfile"; then
      echo "cannot remove owned canary cidfile: $canary_cidfile" >&2
      cleanup_status=1
    elif [ "$was_active" = active ]; then
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
  fi
  if [ "$cleanup_status" -ne 0 ]; then
    echo "next action: inspect $canary_name and the bound ID ${canary_id:-unavailable}; stop only that exact ID after confirming its name, remove owned canary files, then restore $unit if it was previously active" >&2
  fi
  if [ "$cleanup_status" -eq 0 ]; then
    cleanup_done=1
  fi
  return "$cleanup_status"
}
record_cleanup_signal() {
  cleanup_signal_rc="$1"
}
on_exit() {
  local rc=$? attempts=0
  trap - EXIT
  trap 'record_cleanup_signal 130' INT
  trap 'record_cleanup_signal 143' TERM
  while ! cleanup_canary; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 3 ]; then
      rc=1
      break
    fi
    if ! sleep 1; then
      : # A trapped signal is recorded and cleanup still retries.
    fi
  done
  if [ "$cleanup_done" -eq 1 ] && [ "$cleanup_signal_rc" -ne 0 ]; then
    rc="$cleanup_signal_rc"
  fi
  trap - INT TERM
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

docker run --pull=never --cidfile "$canary_cidfile" -d --rm --name "$canary_name" \
  --memory 4G --memory-swap 6G \
  --gpus "device=$judge_gpu_uuid" \
  --mount "type=bind,src=$model_host_dir,dst=/models,readonly" \
  -p 127.0.0.1:15001:5001 \
  "$image_id" \
  -m "$judge_model" -a compassverifier-7b \
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
candidate_workload \
  --run-local-judge-cap-workload "$endpoint" "$results"
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
  "image_ref=$image" \
  "image_id=$image_id" \
  "model_sha256=$model_sha256" \
  "model_size_bytes=$model_size_bytes" \
  "model_host_dir=$model_host_dir" \
  "model_identity=$model_identity" \
  "workload_oid=$workload_oid" \
  'memory_bytes=4294967296' \
  'memory_swap_bytes=6442450944' \
  'requests=24' \
  'workers=8' \
  "memory_peak_bytes=$memory_peak" \
  "swap_peak_bytes=$swap_peak" \
  "completed_at_epoch=$completed_at_epoch" > "$receipt_tmp"
mv -fT -- "$receipt_tmp" "$canary_receipt"
echo "local-judge cap canary accepted: $canary_receipt"
HAPAX_LOCAL_JUDGE_CAP_CANARY
```

### Authenticated package installation

```bash
# Re-emit the authenticated command after runtime authority is granted. Never
# execute RUNBOOK.txt, copy the judge unit, or reproduce the authentication flow.
# The emitted helper validates every scope in the exact release's
# oom-containment.effects. No source-file path is accepted as runtime authority.
set -euo pipefail
account_uid="$(/usr/bin/id -u)"
account_name="$(/usr/bin/id -un)"
account_home="$(/usr/bin/getent passwd "$account_uid" | /usr/bin/cut -d: -f6)"
test -n "$account_home"
test "$account_home" = "$(/usr/bin/realpath -e -- "$account_home")"
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
/usr/bin/env -i \
  HOME="$account_home" \
  USER="$account_name" \
  LOGNAME="$account_name" \
  PATH=/usr/bin:/bin \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  XDG_RUNTIME_DIR="/run/user/$account_uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$account_uid/bus" \
  HAPAX_RUNTIME_AUTHORITY_TASK="$runtime_task" \
  /usr/bin/bash --noprofile --norc -p -s <<'HAPAX_LOCAL_JUDGE_AUTHENTICATED_INSTALL'
set -euo pipefail
PATH=/usr/bin:/bin
export PATH
inner_account_home="$(/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  /usr/bin/python3 -I -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
if [ "$HOME" != "$inner_account_home" ]; then
  echo "local-judge authenticated install: HOME does not match the passwd-backed account home; next action: rerun the complete outer fence rather than the heredoc body" >&2
  exit 2
fi
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
repo_alias="$HOME/.cache/hapax/source-activation/worktree"
repo="$(/usr/bin/realpath -e -- "$repo_alias")"
release_root="$HOME/.cache/hapax/source-activation/releases"
test "${repo%/*}" = "$release_root"
[[ "${repo##*/}" =~ ^[0-9a-f]{40}$ ]]
test "$(/usr/bin/stat -c %u -- "$repo")" = "$(/usr/bin/id -u)"
release_sha="${repo##*/}"
release_git() {
  /usr/bin/env -i \
    HOME=/nonexistent \
    PATH=/usr/bin:/bin \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_NO_REPLACE_OBJECTS=1 \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git -C "$repo" "$@"
}
test "$(release_git rev-parse --verify 'HEAD^{commit}')" = "$release_sha"
verifier_oid="$(release_git rev-parse --verify "$release_sha:scripts/hapax-post-merge-deploy")"
[[ "$verifier_oid" =~ ^[0-9a-f]{40}$ ]]
release_verify() {
  release_git cat-file blob "$verifier_oid" | \
    /usr/bin/env -i \
      HOME="$HOME" \
      USER="$USER" \
      LOGNAME="$LOGNAME" \
      PATH=/usr/bin:/bin \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
      DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
      HAPAX_RUNTIME_AUTHORITY_TASK="$runtime_task" \
      REPO="$repo" \
      /usr/bin/bash --noprofile --norc -p -s -- "$@"
}
state="$HOME/.local/state/hapax/root-required"
receipt="$state/desired-receipts/oom-containment.sha"
test -f "$receipt"
test ! -L "$receipt"
test "$(/usr/bin/stat -c %h -- "$receipt")" = 1
test "$(/usr/bin/wc -c < "$receipt")" = 41
IFS= read -r sha < "$receipt"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
test "$sha" = "$release_sha"
release_verify --verify-local-judge-cap-receipt "$sha" candidate
stage="$HOME/.cache/hapax/post-merge-root-required/$sha/oom-containment"
runbook="$stage/RUNBOOK.txt"
test -f "$runbook"
test ! -L "$runbook"
test ! -x "$runbook"
grep -Fqx 'DO NOT EXECUTE THIS FILE OR COPY A COMMAND FROM IT. It is caller-owned pending-state' "$runbook"
# Run hapax-post-merge-deploy for "$sha" and execute only its live terminal line
# beginning "next action: run:". The pending RUNBOOK is metadata, not code.
release_verify "$sha"
HAPAX_LOCAL_JUDGE_AUTHENTICATED_INSTALL
```

Execute only the live terminal `next action: run:` line emitted by that command.
After it returns successfully, verify the authenticated completion and installed
receipt in a new shell:

```bash
set -euo pipefail
account_uid="$(/usr/bin/id -u)"
account_name="$(/usr/bin/id -un)"
account_home="$(/usr/bin/getent passwd "$account_uid" | /usr/bin/cut -d: -f6)"
test -n "$account_home"
test "$account_home" = "$(/usr/bin/realpath -e -- "$account_home")"
/usr/bin/env -i \
  HOME="$account_home" \
  USER="$account_name" \
  LOGNAME="$account_name" \
  PATH=/usr/bin:/bin \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  /usr/bin/bash --noprofile --norc -p -s <<'HAPAX_LOCAL_JUDGE_INSTALLED_VERIFY'
set -euo pipefail
PATH=/usr/bin:/bin
export PATH
repo_alias="$HOME/.cache/hapax/source-activation/worktree"
repo="$(/usr/bin/realpath -e -- "$repo_alias")"
release_root="$HOME/.cache/hapax/source-activation/releases"
test "${repo%/*}" = "$release_root"
[[ "${repo##*/}" =~ ^[0-9a-f]{40}$ ]]
test "$(/usr/bin/stat -c %u -- "$repo")" = "$(/usr/bin/id -u)"
release_sha="${repo##*/}"
release_git() {
  /usr/bin/env -i \
    HOME=/nonexistent \
    PATH=/usr/bin:/bin \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_NO_REPLACE_OBJECTS=1 \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git -C "$repo" "$@"
}
test "$(release_git rev-parse --verify 'HEAD^{commit}')" = "$release_sha"
verifier_oid="$(release_git rev-parse --verify "$release_sha:scripts/hapax-post-merge-deploy")"
[[ "$verifier_oid" =~ ^[0-9a-f]{40}$ ]]
release_verify() {
  release_git cat-file blob "$verifier_oid" | \
    /usr/bin/env -i \
      HOME="$HOME" \
      USER="$USER" \
      LOGNAME="$LOGNAME" \
      PATH=/usr/bin:/bin \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      REPO="$repo" \
      /usr/bin/bash --noprofile --norc -p -s -- "$@"
}
state="$HOME/.local/state/hapax/root-required"
receipt="$state/desired-receipts/oom-containment.sha"
test -f "$receipt"
test ! -L "$receipt"
test "$(/usr/bin/wc -c < "$receipt")" = 41
IFS= read -r sha < "$receipt"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
test "$sha" = "$release_sha"
release_verify --verify-local-judge-cap-receipt "$sha" installed
stage="$HOME/.cache/hapax/post-merge-root-required/$sha/oom-containment"
/usr/bin/grep -Fqx \
  "hapax-root-required-deferred-install: completed authenticated package=oom-containment sha=$sha" \
  "$stage/AUTHENTICATED-INSTALL.log"
/usr/bin/grep -Fqx "$sha" "$state/installed-receipts/oom-containment.sha"
HAPAX_LOCAL_JUDGE_INSTALLED_VERIFY
```

### Separate activation and recheck

The package deliberately does not enable or restart the judge. This separately
authorized fence reloads the exact installed unit, then rechecks the effective
limits and the recurring audit.

```bash
set -euo pipefail
account_uid="$(/usr/bin/id -u)"
account_name="$(/usr/bin/id -un)"
account_home="$(/usr/bin/getent passwd "$account_uid" | /usr/bin/cut -d: -f6)"
test -n "$account_home"
test "$account_home" = "$(/usr/bin/realpath -e -- "$account_home")"
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
/usr/bin/env -i \
  HOME="$account_home" \
  USER="$account_name" \
  LOGNAME="$account_name" \
  PATH=/usr/bin:/bin \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  XDG_RUNTIME_DIR="/run/user/$account_uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$account_uid/bus" \
  HAPAX_RUNTIME_AUTHORITY_TASK="$runtime_task" \
  /usr/bin/bash --noprofile --norc -p -s -- \
    /usr/bin/systemctl \
    /usr/bin/curl \
    /usr/bin/nvidia-smi \
    /usr/local/sbin/hapax-oom-policy-audit <<'HAPAX_LOCAL_JUDGE_ACTIVATION'
set -euo pipefail
PATH=/usr/bin:/bin
export PATH
systemctl_bin="$1"
curl_bin="$2"
nvidia_smi_bin="$3"
oom_audit_bin="$4"
for executable in "$systemctl_bin" "$curl_bin" "$nvidia_smi_bin" "$oom_audit_bin"; do
  test -x "$executable"
  test ! -L "$executable"
done
runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
repo_alias="$HOME/.cache/hapax/source-activation/worktree"
repo="$(/usr/bin/realpath -e -- "$repo_alias")"
release_root="$HOME/.cache/hapax/source-activation/releases"
test "${repo%/*}" = "$release_root"
[[ "${repo##*/}" =~ ^[0-9a-f]{40}$ ]]
test "$(/usr/bin/stat -c %u -- "$repo")" = "$(/usr/bin/id -u)"
sha="${repo##*/}"
release_git() {
  /usr/bin/env -i \
    HOME=/nonexistent \
    PATH=/usr/bin:/bin \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_NO_REPLACE_OBJECTS=1 \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git -C "$repo" "$@"
}
test "$(release_git rev-parse --verify 'HEAD^{commit}')" = "$sha"
verifier_oid="$(release_git rev-parse --verify "$sha:scripts/hapax-post-merge-deploy")"
[[ "$verifier_oid" =~ ^[0-9a-f]{40}$ ]]
release_verify() {
  release_git cat-file blob "$verifier_oid" | \
    /usr/bin/env -i \
      HOME="$HOME" \
      USER="$USER" \
      LOGNAME="$LOGNAME" \
      PATH=/usr/bin:/bin \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
      DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
      REPO="$repo" \
      /usr/bin/bash --noprofile --norc -p -s -- "$@"
}
activation_scopes=(
  runtime:systemd-user:daemon-reload
  runtime:systemd-user:enable:hapax-local-judge.service
  runtime:systemd-user:restart:hapax-local-judge.service
  runtime:state:write-local-judge-activation-result
)
release_verify --verify-runtime-authority-for-release \
  "$sha" "$runtime_task" "${activation_scopes[@]}"
release_verify --verify-local-judge-cap-receipt "$sha" installed

result_dir="$HOME/.local/state/hapax/local-judge-activation"
result="$result_dir/latest.env"
/usr/bin/mkdir -p -- "$result_dir"
test -d "$result_dir"
test ! -L "$result_dir"
test "$(/usr/bin/stat -c %u -- "$result_dir")" = "$(/usr/bin/id -u)"
result_mode="$(/usr/bin/stat -c %a -- "$result_dir")"
(( (8#$result_mode & 022) == 0 ))
write_activation_result() {
  local status="$1" phase="$2" service_mutation_started="$3" tmp
  tmp="$(/usr/bin/mktemp -p "$result_dir" .latest.env.XXXXXX)"
  /usr/bin/chmod 0600 "$tmp"
  /usr/bin/printf '%s\n' \
    'schema=1' \
    "candidate_sha=$sha" \
    "status=$status" \
    "phase=$phase" \
    "service_mutation_started=$service_mutation_started" \
    "recorded_at_epoch=$(/usr/bin/date +%s)" \
    'next_action=inspect-service-and-journal-then-rerun-authorized-fence' > "$tmp"
  /usr/bin/mv -fT -- "$tmp" "$result"
}
activation_phase=authorized
service_mutation_started=false
on_activation_exit() {
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    return
  fi
  set +e
  status=failed_pre_mutation
  if [ "$service_mutation_started" = true ]; then
    status=partial_success
  fi
  write_activation_result "$status" "$activation_phase" "$service_mutation_started"
  /usr/bin/printf '%s\n' \
    "local-judge activation $status: phase=$activation_phase candidate_sha=$sha service_mutation_started=$service_mutation_started receipt=$result; next action: inspect '$systemctl_bin --user status hapax-local-judge.service' and 'journalctl --user -u hapax-local-judge.service', repair the failed phase, then rerun this separately authorized fence" >&2
  exit "$rc"
}
trap on_activation_exit EXIT
write_activation_result in_progress "$activation_phase" "$service_mutation_started"

activation_phase=daemon_reload
write_activation_result in_progress "$activation_phase" "$service_mutation_started"
service_mutation_started=true
"$systemctl_bin" --user daemon-reload
activation_phase=effective_unit
write_activation_result in_progress "$activation_phase" "$service_mutation_started"
exec_start="$("$systemctl_bin" --user show hapax-local-judge.service -p ExecStart --value)"
[[ "$exec_start" == *"argv[]=/usr/bin/env -i "* ]]
[[ "$exec_start" == *" /usr/bin/docker --host=unix:///var/run/docker.sock --config="* ]]
[[ "$exec_start" == *"/hapax-local-judge/docker-config run "* ]]
[[ "$exec_start" == *" --memory 4G "* ]]
[[ "$exec_start" == *" --memory-swap 6G "* ]]
activation_phase=enable
write_activation_result in_progress "$activation_phase" "$service_mutation_started"
"$systemctl_bin" --user enable hapax-local-judge.service
activation_phase=restart
write_activation_result in_progress "$activation_phase" "$service_mutation_started"
"$systemctl_bin" --user restart hapax-local-judge.service
activation_phase=model_api
write_activation_result in_progress "$activation_phase" "$service_mutation_started"
models="$("$curl_bin" --fail --silent --show-error --max-time 30 \
  http://127.0.0.1:5001/v1/models)"
/usr/bin/grep -Fq compassverifier <<<"$models"
activation_phase=gpu_inventory
write_activation_result in_progress "$activation_phase" "$service_mutation_started"
"$nvidia_smi_bin" --query-gpu=index,name,memory.used --format=csv,noheader
activation_phase=oom_audit
write_activation_result in_progress "$activation_phase" "$service_mutation_started"
"$oom_audit_bin"
activation_phase=complete
write_activation_result accepted "$activation_phase" "$service_mutation_started"
trap - EXIT
/usr/bin/printf 'local-judge activation accepted: candidate_sha=%s receipt=%s\n' "$sha" "$result"
HAPAX_LOCAL_JUDGE_ACTIVATION
```

Every authorized attempt updates
`~/.local/state/hapax/local-judge-activation/latest.env` atomically. A failure
before `daemon-reload` records `failed_pre_mutation`; any later failure records
`partial_success` with the exact failed phase. Treat `partial_success` as a live
runtime change: inspect the service and journal named by the terminal diagnostic,
repair that phase, and rerun this separately authorized fence rather than assuming
the failed command rolled activation back.

The name `hapax-local-judge` is reserved for the systemd unit. Docker writes the
unit-owned full ID to `%t/hapax-local-judge/container.cid`; stop and restart use
only that ID and retain the cidfile whenever absence cannot be proven. The unit
refuses to delete an unknown same-name container. A user manager cannot order the system
manager's `docker.service`, so the unit deliberately declares no inert
cross-manager dependency. Its first `ExecStartPre` instead polls the pinned local
Docker daemon for at most 60 seconds; `Restart=always` with `RestartSec=5s`
retries persistent unavailability after that bounded start attempt. If readiness
failures continue after `systemctl is-active docker.service` reports `active`, inspect
`journalctl --user -u hapax-local-judge.service` for the socket, image, model, or
same-name-container refusal before restarting anything. Its preflight also requires the exact digest image
to be locally staged and the root-owned content-addressed model to match the
candidate size before `docker run --pull=never`. A same-name collision therefore
causes an intentional, audit-visible restart loop until reconciled.

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
  ghcr.io/ggml-org/llama.cpp@sha256:841b199aed2649a748875b043b32fed2e8c2d4d87e1d563556817fb7fa44b72b \
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
  account_uid="$(/usr/bin/id -u)"
  account_name="$(/usr/bin/id -un)"
  account_home="$(/usr/bin/getent passwd "$account_uid" | /usr/bin/cut -d: -f6)"
  test -n "$account_home"
  test "$account_home" = "$(/usr/bin/realpath -e -- "$account_home")"
  runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
  /usr/bin/env -i \
    HOME="$account_home" \
    USER="$account_name" \
    LOGNAME="$account_name" \
    PATH=/usr/bin:/bin \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    XDG_RUNTIME_DIR="/run/user/$account_uid" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$account_uid/bus" \
    DOCKER_HOST=unix:///var/run/docker.sock \
    HAPAX_RUNTIME_AUTHORITY_TASK="$runtime_task" \
    /usr/bin/bash --noprofile --norc -p -s <<'HAPAX_LOCAL_JUDGE_MANAGED_RECHECK'
  set -euo pipefail
  PATH=/usr/bin:/bin
  export PATH
  runtime_task="${HAPAX_RUNTIME_AUTHORITY_TASK:?set to the authorized cc-task note}"
  test -S /var/run/docker.sock
  repo_alias="$HOME/.cache/hapax/source-activation/worktree"
  repo="$(/usr/bin/realpath -e -- "$repo_alias")"
  release_root="$HOME/.cache/hapax/source-activation/releases"
  test "${repo%/*}" = "$release_root"
  [[ "${repo##*/}" =~ ^[0-9a-f]{40}$ ]]
  test "$(/usr/bin/stat -c %u -- "$repo")" = "$(/usr/bin/id -u)"
  sha="${repo##*/}"
  release_git() {
    /usr/bin/env -i \
      HOME=/nonexistent \
      PATH=/usr/bin:/bin \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      GIT_CONFIG_GLOBAL=/dev/null \
      GIT_CONFIG_NOSYSTEM=1 \
      GIT_NO_REPLACE_OBJECTS=1 \
      GIT_OPTIONAL_LOCKS=0 \
      /usr/bin/git -C "$repo" "$@"
  }
  test "$(release_git rev-parse --verify 'HEAD^{commit}')" = "$sha"
  verifier_oid="$(release_git rev-parse --verify "$sha:scripts/hapax-post-merge-deploy")"
  [[ "$verifier_oid" =~ ^[0-9a-f]{40}$ ]]
  release_verify() {
    release_git cat-file blob "$verifier_oid" | \
      /usr/bin/env -i \
        HOME="$HOME" \
        USER="$USER" \
        LOGNAME="$LOGNAME" \
        PATH=/usr/bin:/bin \
        LANG=C.UTF-8 \
        LC_ALL=C.UTF-8 \
        XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
        DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
        DOCKER_HOST=unix:///var/run/docker.sock \
        REPO="$repo" \
        /usr/bin/bash --noprofile --norc -p -s -- "$@"
  }
  managed_recheck_scopes=(
    runtime:state:write-remove-managed-recheck:/store-fast/tmp
    runtime:workload:run-local-judge-managed-recheck:requests-24:workers-8
  )
  release_verify --verify-runtime-authority-for-release \
    "$sha" "$runtime_task" "${managed_recheck_scopes[@]}"
  release_verify --verify-local-judge-cap-receipt "$sha" installed
  unit=hapax-local-judge.service
  test "$(/usr/bin/systemctl --user show "$unit" -p NeedDaemonReload --value)" = no
  test "$(/usr/bin/systemctl --user show "$unit" -p FragmentPath --value)" = \
    "$HOME/.config/systemd/user/$unit"
  test -z "$(/usr/bin/systemctl --user show "$unit" -p DropInPaths --value)"
  exec_start="$(/usr/bin/systemctl --user show "$unit" -p ExecStart --value)"
  [[ "$exec_start" == *"argv[]=/usr/bin/env -i "* ]]
  [[ "$exec_start" == *" /usr/bin/docker --host=unix:///var/run/docker.sock --config="* ]]
  [[ "$exec_start" == *"/hapax-local-judge/docker-config run "* ]]
  [[ "$exec_start" == *" --name hapax-local-judge "* ]]
  [[ "$exec_start" == *" --memory 4G "* ]]
  [[ "$exec_start" == *" --memory-swap 6G "* ]]
  container=hapax-local-judge
  oom_kill_disable="$(/usr/bin/docker inspect --format '{{json .HostConfig.OomKillDisable}}' "$container")"
  [[ "$oom_kill_disable" == null || "$oom_kill_disable" == false ]]
  pid="$(/usr/bin/docker inspect --format '{{.State.Pid}}' "$container")"
  test "$pid" -gt 1
  cgroup="$(/usr/bin/awk -F: '$1 == "0" {print $3; exit}' "/proc/$pid/cgroup")"
  events="/sys/fs/cgroup${cgroup}/memory.events"
  memory_peak_path="/sys/fs/cgroup${cgroup}/memory.peak"
  swap_peak_path="/sys/fs/cgroup${cgroup}/memory.swap.peak"
  test -r "$events"
  test -r "$memory_peak_path"
  test -r "$swap_peak_path"
  before_state="$(/usr/bin/docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}|{{.RestartCount}}|{{.State.OOMKilled}}' "$container")"
  before_oom="$(/usr/bin/awk '$1 == "oom" || $1 == "oom_kill" {print}' "$events")"
  results="/store-fast/tmp/local-judge-managed-recheck-$$.jsonl"
  test -d /store-fast/tmp
  test ! -e "$results"
  trap '/usr/bin/rm -f "$results"' EXIT
  release_verify --run-local-judge-cap-workload http://127.0.0.1:5001 "$results"
  /usr/bin/jq -e -s 'length == 24 and all(.[]; type == "object" and has("error") and has("pred") and .error == null and (.pred == "A" or .pred == "B" or .pred == "C"))' \
    "$results" >/dev/null
  after_state="$(/usr/bin/docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}|{{.RestartCount}}|{{.State.OOMKilled}}' "$container")"
  after_oom="$(/usr/bin/awk '$1 == "oom" || $1 == "oom_kill" {print}' "$events")"
  memory_peak="$(/usr/bin/cat "$memory_peak_path")"
  swap_peak="$(/usr/bin/cat "$swap_peak_path")"
  test "$before_state" = "$after_state"
  test "$before_oom" = "$after_oom"
  test "$memory_peak" -le 3221225472
  test "$swap_peak" -le 1073741824
  /usr/bin/rm -f "$results"
  trap - EXIT
HAPAX_LOCAL_JUDGE_MANAGED_RECHECK
  ```
- **Throughput:** 8 continuous-batch slots × 8192 ctx; ~137 tok/s decode, ~800 tok/s
  prompt. 127/2817 (4.5%) VerifierBench items exceed an 8192-token slot and are
  reported as context-skips by the harness — the longest/pathological inputs; raise
  `-c`÷`-np` per slot to score them if a full-coverage number is wanted.
- **Fallback drill:** stop the lifecycle owner with
  `systemctl --user stop hapax-local-judge.service`; require
  `systemctl --user show hapax-local-judge.service -p ActiveState --value` to
  return `inactive`, require
  `$XDG_RUNTIME_DIR/hapax-local-judge/container.cid` to be absent,
  and require `docker ps -aq --no-trunc --filter 'name=^/hapax-local-judge$'`
  to return no ID. Only then send a `local-judge`
  request through `:4000` and require a `claude-haiku` answer without a hard
  error. Restore the lifecycle owner with
  `systemctl --user start hapax-local-judge.service`; never stop or remove this
  container by mutable name during the drill.
