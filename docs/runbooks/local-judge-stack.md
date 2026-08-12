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

Every command below mutates the appendix runtime and requires a task note whose
frontmatter explicitly grants `runtime_mutation_authorized: true`. A source-only
task stops here. The disposable canary uses the exact proposed `4G/6G` limits and
must pass before the authenticated package command is requested.

Protected model staging is the first separately measured phase of that mandatory
canary, not an activation side effect. The block below runs
`--measure-protected-local-judge-model` against the root-owned content address
before starting the disposable container and writes the candidate cap receipt
only after both staging and the workload pass. A future root-owned package broker
and the separate activation fence must each verify that exact-SHA receipt before their
first mutation, so a skipped or incomplete staging canary is rejected before the
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
model_root_keys=(mount store_fast models sha256 digest)
measure_model_root() {
  candidate_workload --measure-protected-local-judge-model-root "$model_host_dir"
}
model_root_identity() {
  local evidence="$1" key="$2" value=""
  local -a matches=()
  mapfile -t matches < <(printf '%s\n' "$evidence" | sed -n "s/^${key}_identity=//p")
  if [ "${#matches[@]}" -ne 1 ]; then
    echo "protected model root evidence has no unique ${key} identity" >&2
    echo "next action: stop staging and rerun the exact candidate root measurement" >&2
    return 1
  fi
  value="${matches[0]}"
  if [[ "$value" != missing && ! "$value" =~ ^[0-9]+:[0-9]+$ ]]; then
    echo "protected model root evidence has an invalid ${key} identity" >&2
    echo "next action: stop staging and inspect the candidate helper output" >&2
    return 1
  fi
  printf '%s\n' "$value"
}
validate_model_root_evidence() {
  local evidence="$1" key=""
  for key in "${model_root_keys[@]}"; do
    model_root_identity "$evidence" "$key" >/dev/null
  done
}
require_complete_model_root() {
  local evidence="$1" key="" value=""
  validate_model_root_evidence "$evidence"
  for key in "${model_root_keys[@]}"; do
    value="$(model_root_identity "$evidence" "$key")"
    if [ "$value" = missing ]; then
      echo "protected model root remains incomplete after directory creation: $key" >&2
      echo "next action: stop staging and inspect the exact root-owned directory chain" >&2
      return 1
    fi
  done
}
verify_model_root_transition() {
  local before="$1" after="$2" key="" before_id="" after_id=""
  validate_model_root_evidence "$before"
  validate_model_root_evidence "$after"
  for key in "${model_root_keys[@]}"; do
    before_id="$(model_root_identity "$before" "$key")"
    after_id="$(model_root_identity "$after" "$key")"
    if [ "$before_id" != missing ] && [ "$before_id" != "$after_id" ]; then
      echo "protected model root ancestor changed during staging: $key" >&2
      echo "next action: stop publication, preserve the partial file, and inspect the root path" >&2
      return 1
    fi
  done
}

# Authenticate and bind the governed /store-fast mount plus every existing
# physical root-owned ancestor before the first sudo or Docker mutation.
# Missing descendants may be created only below that bound chain, then every
# newly complete ancestor is rebound before content writes.
model_root_before="$(measure_model_root)"
validate_model_root_evidence "$model_root_before"

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
  model_root_after_create="$(measure_model_root)"
  require_complete_model_root "$model_root_after_create"
  verify_model_root_transition "$model_root_before" "$model_root_after_create"
  model_root_bound="$model_root_after_create"
  model_stage="$model_host_dir/.${judge_model##*/}.partial.$$"
  if ! sudo /usr/bin/python3 -I - "$model_stage" <<'LOCAL_JUDGE_MODEL_STAGE_CREATE_PY'
from __future__ import annotations

import os
import stat
import sys

path = sys.argv[1]
if os.geteuid() != 0:
    print(
        "protected model stage creator is not root; "
        "next action: restore the authorized sudo boundary before staging",
        file=sys.stderr,
    )
    raise SystemExit(2)
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
try:
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        inode = os.fstat(fd)
    finally:
        os.close(fd)
except OSError as exc:
    print(
        f"cannot atomically create protected model stage: {exc}; "
        "next action: quarantine any stale partial and rerun the exact-SHA canary",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc
if (
    not stat.S_ISREG(inode.st_mode)
    or inode.st_uid != 0
    or inode.st_nlink != 1
    or stat.S_IMODE(inode.st_mode) != 0o600
    or inode.st_size != 0
):
    print(
        "protected model stage did not retain root ownership, one link, mode 0600, and zero size; "
        "next action: remove only this partial and inspect the target filesystem",
        file=sys.stderr,
    )
    raise SystemExit(2)
LOCAL_JUDGE_MODEL_STAGE_CREATE_PY
  then
    echo "protected model stage creation refused; no pre-existing path was removed" >&2
    exit 1
  fi
  if ! /usr/bin/dd if="$model_source_path" bs=4M iflag=fullblock,nofollow status=none | \
      sudo /usr/bin/dd of="$model_stage" bs=4M oflag=nofollow status=none; then
    sudo /usr/bin/rm -f -- "$model_stage"
    echo "protected model staging failed; rerun after checking source stability" >&2
    exit 1
  fi
  read -r stage_uid stage_mode stage_links stage_size stage_extra \
    <<<"$(/usr/bin/stat -c '%u %a %h %s' -- "$model_stage")"
  if [ -n "$stage_extra" ] || [ "$stage_uid" != 0 ] || [ "$stage_mode" != 600 ] \
      || [ "$stage_links" != 1 ] || [ "$stage_size" != "$expected_model_size_bytes" ]; then
    sudo /usr/bin/rm -f -- "$model_stage"
    echo "protected model stage changed before sealing" >&2
    echo "next action: stop publication, inspect the protected filesystem, and rerun the exact-SHA canary" >&2
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
  model_root_before_publish="$(measure_model_root)"
  require_complete_model_root "$model_root_before_publish"
  verify_model_root_transition "$model_root_bound" "$model_root_before_publish"
  sudo /usr/bin/mv -T -- "$model_stage" "$model_host_path"
  model_root_bound="$model_root_before_publish"
else
  require_complete_model_root "$model_root_before"
  model_root_bound="$model_root_before"
fi
model_root_after_publish="$(measure_model_root)"
require_complete_model_root "$model_root_after_publish"
verify_model_root_transition "$model_root_bound" "$model_root_after_publish"
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
docker pull "$image"
image_id="$(docker image inspect --format '{{.Id}}' "$image")"
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]

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

### Broker-gated package installation

This source revision deliberately cannot perform package installation. Do not
attempt the live command merely because
`/usr/local/sbin/hapax-root-required-package-apply` exists or appears root-owned:
those properties are forgeable in nested namespaces. Stop and dispatch separately
authorized broker/cryptographic-attestation design and implementation work. The
desired receipt and `RUNBOOK.txt` must remain pending; do not restore the retired
Bash production path for continuity. A future broker must treat package and SHA
as requests to compare against its own derivation, hold a root-owned transaction
lock across revalidation, effects, readback, publication, and drain, and return
source-verifiable host-root attestation. Caller-owned `RUNBOOK.txt`/`DRAINED.txt`,
logs, snapshots, and receipts are workflow bookkeeping, never durable completion
proof.

```bash
# Reference fence only: this exact source revision must fail closed before sudo.
# Runtime authority or an apparently root-owned broker does not enable it. Never
# execute RUNBOOK.txt, copy the judge unit, or reproduce the authentication flow.
# The emitted helper may narrow or refuse. Only the root-owned broker can apply,
# and it independently validates the exact release and effect transaction.
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
# Run hapax-post-merge-deploy for "$sha" only to restage pending metadata. This
# revision's emitted helper command must refuse before sudo. Never execute RUNBOOK.
release_verify "$sha"
HAPAX_LOCAL_JUDGE_AUTHENTICATED_INSTALL
```

Do not execute the emitted `next action: run:` line expecting deployment in this
revision; the helper must refuse with the cryptographic-attestation next action.
There is intentionally no successful installed-verification recipe. The rejection
block below shows that caller-owned logs and receipts cannot close this predicate:

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
echo "installed verification unavailable: require an exact request ID and matching cryptographically attested per-request and current host-root records" >&2
exit 1
HAPAX_LOCAL_JUDGE_INSTALLED_VERIFY
```

### Activation and recheck unavailable

The package does not enable or restart the judge. This source revision has no
runnable activation fence: caller-owned desired, installed, canary, activation,
or managed-recheck records cannot attest that host root applied the exact
package. `--verify-local-judge-cap-receipt <sha> installed` therefore fails
unconditionally before reading those records.

Activation and the managed post-activation workload recheck remain blocked until
a separately authorized successor binds one exact request ID, package, release
SHA, and effect set to cryptographically attested per-request and current
host-root completion records. That successor must verify both attestations from
a source-pinned trust anchor before any `systemctl --user daemon-reload`,
enable, restart, result-state write, or managed workload command.
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
  pre-deploy canary above gates source candidacy only. The managed 8-worker,
  24-request post-activation recheck is intentionally unavailable in this
  revision for the same reason as activation: no cryptographically attested
  installed package generation exists. Its health, restart, OOM, and peak-memory
  predicates remain required for runtime closure after the attested protocol is
  implemented; caller-owned workload output is not closure evidence.
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
