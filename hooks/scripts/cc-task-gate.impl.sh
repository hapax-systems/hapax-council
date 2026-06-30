#!/usr/bin/env bash
# cc-task-gate.impl.sh — canonical cc-task-gate implementation (the REAL gate).
#
# This file holds the gate logic. It is invoked through a thin stable-abs-path
# SHIM (hooks/scripts/cc-task-gate.sh) that resolves to ONE deployed copy of this
# file at $HAPAX_CANONICAL_HOOKS (default ~/.local/lib/hapax/hooks/cc-task-gate.sh),
# so "update the gate" is a one-file change instead of a 26-worktree physical
# fan-out (reform FM-6 collapse). The deployed closure carries this file plus its
# sourced siblings agent-role.sh + escape-grant.sh. Drift between any worktree's
# shim and the canonical copy is detected by hooks-doctor.sh (SessionStart + CI +
# timer); the canonical copy is refreshed by hapax-post-merge-deploy on merge.
#
# PreToolUse hook (D-30 Phase 3)
#
# Blocks file-mutating tool calls unless the current CC session has
# CLAIMED a task in the Obsidian vault SSOT and that task is in
# `in_progress` (or about to transition there from `claimed`).
#
# Operator-facing surface for all CC work lives at:
#   ~/Documents/Personal/20-projects/hapax-cc-tasks/
#
# Each session writes its current claim to:
#   ~/.cache/hapax/cc-active-task-{role}
# (one line: the vault task_id, e.g. "ef7b-020")
#
# MANDATORY for all interfaces. Claude Code fires this hook directly;
# Codex fires it via codex-hook-adapter.sh (unconditionally since the
# 2026-05-19 codex-lane-crashout-prevention fix).
#
# Bypass: HAPAX_CC_TASK_GATE_OFF=1 disables the hook (incident response).
#
# Failure mode: FAIL-CLOSED on infrastructure errors for protected
# mutations (Edit/Write/Bash-destructive). Amendment 1 (HAZ-006):
# fail-open permitted unauthorized protected mutations. Protected
# surfaces now block; emergency bypass via HAPAX_METHODOLOGY_EMERGENCY=1
# with audit receipt.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/agent-role.sh" ]]; then
  # shellcheck source=agent-role.sh
  . "$SCRIPT_DIR/agent-role.sh"
fi

# Daemon-independent escape-grant substrate (reform Phase 4, NEW-2/INV-4). Gives
# this shim `escape_grant_allows <gate>`: a pure file read that honors a signed
# EscapeGrant when the gate would otherwise fail closed — no RPC, works with the
# kernel down.
if [[ -f "$SCRIPT_DIR/escape-grant.sh" ]]; then
  # shellcheck source=escape-grant.sh
  . "$SCRIPT_DIR/escape-grant.sh"
fi

# This gate's scope name for escape grants (a grant must cover this exact gate,
# or "*"). One gate, not a global off-switch.
GATE_NAME="cc-task-gate"

# _emit_block — every BLOCK routes its existing message through here on stdin.
# Before failing closed it honors a signed EscapeGrant covering this gate (a pure
# file read, daemon-independent: NEW-2/INV-4). When no grant is present the
# original operator-facing text is printed unchanged and the shim exits 2. The
# trailing `exit 2` at each call site is an unreachable fail-closed backstop.
_emit_block() {
  local _msg
  _msg="$(cat)"
  if declare -F escape_grant_allows >/dev/null 2>&1 && escape_grant_allows "$GATE_NAME"; then
    echo "cc-task-gate: escape grant honored for '$GATE_NAME' — allowed (logged, daemon-independent)." >&2
    exit 0
  fi
  printf '%s\n' "$_msg" >&2
  exit 2
}

# _record_retro_grant_obligation — deprecation backstop for the unconditional
# HAPAX_METHODOLOGY_EMERGENCY off-switch (master design §4.4 / §7 NEW-2: the
# emergency switch is incident-only and now incurs a MANDATORY signed EscapeGrant
# within 1h). Writes a pending obligation that scripts/coord-retro-grant-watch
# escalates (ntfy) if no covering grant lands before the deadline. Best-effort.
_record_retro_grant_obligation() {
  local role="${1:-unknown}" task="${2:-unknown}" case_id="${3:-unknown}"
  local tool="${4:-unknown}" trigger="${5:-HAPAX_METHODOLOGY_EMERGENCY}"
  local obligations="${HOME}/.cache/hapax/coord-retro-grant-obligations.jsonl"
  local ledger="${HAPAX_METHODOLOGY_LEDGER:-${HOME}/.cache/hapax/methodology-emergency-ledger.jsonl}"
  local now_s deadline_s
  now_s="$(date +%s 2>/dev/null || echo 0)"
  deadline_s=$((now_s + 3600))
  mkdir -p "$(dirname "$obligations")" 2>/dev/null || true
  printf '{"ts":"%s","ts_s":%s,"deadline_s":%s,"status":"pending","gate":"%s","trigger":"%s","role":"%s","task":"%s","case":"%s","tool":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$now_s" "$deadline_s" "$GATE_NAME" "$trigger" "$role" "$task" "$case_id" "$tool" \
    >>"$obligations" 2>/dev/null || true
  printf '{"ts":"%s","kind":"retro_grant_obligation","role":"%s","task":"%s","case":"%s","tool":"%s","deadline_s":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task" "$case_id" "$tool" "$deadline_s" \
    >>"$ledger" 2>/dev/null || true
  echo "cc-task-gate: retro-grant obligation recorded (1h deadline). HAPAX_*_OFF is DEPRECATED —" >&2
  echo "  sign a scoped escape instead: scripts/coord-grant-mint --scope $GATE_NAME --reason '<incident>'." >&2
}

# --- 1. Read tool invocation from stdin ---
input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")"

bash_cmd=""
mutation_surface_hint="source"

# --- Argument-aware bash classifier (FM-16) -----------------------------------
# The legacy classifier grep-scanned the WHOLE command line, so a mutation verb
# that appeared only inside a quoted ARGUMENT (e.g. a `grep -E 'git reset|x'`
# pattern — whose interior `|` was even read as a command separator) or a purely
# read-only `systemctl is-active` was misclassified as a mutation, blocking the
# very inspection a blocked/roleless lane needs to report state (the gate's own
# comment promised "read-only shell remains available" — FM-16 broke that).
#
# These helpers classify the EXECUTED COMMAND HEAD of each simple command: quoted
# spans + comments are stripped (so verbs/separators inside them are inert), the
# line is split on shell separators (; | & ( )), and each segment's leading
# command word is matched against known families. Pure readers (grep/cat/ls/find/
# awk, git log/show/diff/status/rev-list/ls-tree/branch/merge-base, systemctl
# is-active/status/show/list-*, journalctl without --vacuum) match nothing and
# pass. This mirrors the argument-aware classifier in shared/policy_decide.py
# (`_bash_is_mutating`/`_bash_is_runtime`/`_bash_is_source_scope`) so the Phase-3b
# shadow→cutover is verdict-stable on this corpus.

# systemctl subcommands that mutate runtime state. Mirrors journalctl's
# --vacuum-only pattern: everything else (is-active/is-enabled/is-failed/status/
# show/cat/list-*/get-default/…) is a read and stays available without a claim.
_systemctl_subcmd_mutates() {
  case "$1" in
    start|stop|restart|try-restart|reload|reload-or-restart|force-reload \
      | enable|disable|reenable|preset|preset-all|mask|unmask|link|revert \
      | set-property|set-default|isolate|kill|clean|freeze|thaw \
      | daemon-reload|daemon-reexec|edit|switch-root|default \
      | reboot|poweroff|halt|kexec|suspend|hibernate|hybrid-sleep|emergency|rescue) return 0 ;;
  esac
  return 1
}

# docker subcommands that mutate container/image/runtime state (docker ps/logs/
# inspect/images/version remain reads). Covers `docker compose <verb>` too.
_docker_subcmd_mutates() {
  case "$1" in
    up|down|start|stop|restart|kill|rm|rmi|run|exec|create|build|pull|push|load|import|prune|compose) return 0 ;;
  esac
  return 1
}

# `git branch` lists/shows by default (a read); it mutates only when it deletes,
# renames, copies, force-updates, (re)sets upstream, or names a (new) branch to
# create. Plain `git branch [-a|-r|-v|--show-current|--list|--contains X]` stays
# readable. (FM-16 reader whitelist — branch creation is also governed by the
# dedicated no-stale-branches hook.)
_git_branch_mutates() { # args AFTER the `branch` subcommand
  local a prev_value_flag=0
  for a in "$@"; do
    case "$a" in
      -d | -D | --delete | -m | -M | --move | -c | -C | --copy | -f | --force \
        | --edit-description | -u | --set-upstream-to | --set-upstream-to=* | --unset-upstream) return 0 ;;
      --contains | --no-contains | --merged | --no-merged | --points-at | --sort | --format | --list | --column)
        prev_value_flag=1 ;;
      -*) prev_value_flag=0 ;;
      *)
        [[ "$prev_value_flag" == 1 ]] && { prev_value_flag=0; continue; }
        return 0 ;;
    esac
  done
  return 1
}

# Emit each simple command (one per line) with quoted spans + comments removed.
# Mirrors the proven strip at the source-scope call site (sed -z spans newlines,
# so multi-line "$(cat <<'EOF'…)" payloads collapse) and additionally splits on
# the shell command separators ; | & ( ) so a verb inside a quoted arg can no
# longer read as its own command. `||`/`&&` collapse to blank segments (skipped).
_bash_segments() {
  # Trailing newline is REQUIRED: `while read` skips a final line with no newline,
  # which would drop the (sole) segment of every un-piped command.
  printf '%s\n' "$1" \
    | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g; s/(^|[[:space:]])#[^\n]*//g" \
    | tr ';|&()' '\n'
}

# Resolve a segment's executed command HEAD into _HEAD, with the remaining tokens
# in _ARGS. Skips leading VAR=val assignments and wrapper words (sudo/env/nohup/…)
# so `sudo systemctl restart x` still classifies on `systemctl`. _HEAD is "" when
# the segment has no command word.
_bash_seg_head() {
  _HEAD=""
  _ARGS=()
  local -a _toks=()
  # `read` hits EOF on the here-string and returns 1; tolerate under `set -e`.
  read -r -a _toks <<<"$1" || true
  local i=0 n=${#_toks[@]}
  while ((i < n)); do
    case "${_toks[i]}" in
      *=* | sudo | doas | env | command | builtin | nohup | time | exec | nice | ionice | stdbuf | setsid) i=$((i + 1)) ;;
      -*) i=$((i + 1)) ;;
      *) break ;;
    esac
  done
  if ((i < n)); then
    _HEAD="${_toks[i]}"
    _ARGS=("${_toks[@]:i+1}")
  fi
}

# True if a sed/perl segment carries an in-place-edit flag (the only mutating
# form). The segment is already quote-stripped, so an `i`/`-i` inside a quoted
# script/pattern cannot trip this — only a real `-i`/`--in-place`/`-pi` flag does.
_seg_has_inplace() {
  local head="$1" seg="$2"
  case "$head" in
    sed) [[ "$seg" =~ (^|[[:space:]])(-i|--in-place) ]] && return 0 ;;
    perl) [[ "$seg" =~ (^|[[:space:]])-[[:alpha:]]*i ]] && return 0 ;;
  esac
  return 1
}

# True if a python command line writes the filesystem. `cmd` is passed verbatim
# from the caller (RAW for is_mutating, pre-stripped for the scope check) so the
# raw-vs-stripped asymmetry holds: `python3 -c "open(...)"` is a claim-gated
# mutation (raw has the marker) but is NOT source-scope-blocked (the stripped
# form drops the quoted payload), while a bare heredoc writer still blocks.
_py_writes() {
  local cmd="$1"
  [[ "$cmd" == *"<<"* ]] && return 0
  case "$cmd" in
    *.write_text* | *.write_bytes* | *"open("* | *"shutil."* \
      | *"os.remove"* | *"os.unlink"* | *"os.rename"* | *"os.replace"* | *"Path("*) return 0 ;;
  esac
  return 1
}

# True iff a `cat` SEGMENT redirects its STDOUT to a file (`> f` / `>> f` / `1> f`)
# — a real write. A '>' inside a stderr/fd redirection (`2>&1`, `2>/dev/null`, `&>`)
# is NOT a stdout-to-file write, so those redirect tokens are stripped before the
# `*">"*` test; otherwise a read-only `cat file 2>/dev/null` is misread as a writer
# and source-blocked, locking a roleless lane out of its own diagnostics
# (fix-cc-gate-fps Fix 1). The segment is already quote-stripped. Mirrors
# shared/policy_decide._cat_writes_to_file.
_cat_writes_file() {
  local seg="$1"
  # Drop fd-dup (N>&M / >&M / N>&-), both-streams (&> / &>>), and stderr-or-higher-fd
  # to-file (2>, 2>>, 3>, …) redirections; what remains carries a '>' only on a real
  # stdout-to-file redirect (bare `>`/`>>`/`1>` keep their '>').
  seg="$(printf '%s' "$seg" | sed -E 's/[0-9]*>&[0-9-]+/ /g; s/&>>?/ /g; s/[2-9][0-9]*>>?/ /g')"
  [[ "$seg" == *">"* ]]
}

# Runtime/system-state mutations (need runtime_mutation_authorized): package
# installs, remote shells, process signals, container/service lifecycle. systemctl
# and docker are subcommand-gated; journalctl only on --vacuum.
bash_is_runtime_mutation() {
  local cmd="$1" seg a
  while IFS= read -r seg; do
    [[ -z "${seg// /}" ]] && continue
    _bash_seg_head "$seg"
    [[ -z "$_HEAD" ]] && continue
    case "$_HEAD" in
      ssh | scp | rsync | kill | pkill | pacman | paru | apt | dnf) return 0 ;;
      systemctl) for a in "${_ARGS[@]}"; do _systemctl_subcmd_mutates "$a" && return 0; done ;;
      docker) for a in "${_ARGS[@]}"; do _docker_subcmd_mutates "$a" && return 0; done ;;
      journalctl) for a in "${_ARGS[@]}"; do [[ "$a" == --vacuum* ]] && return 0; done ;;
      uv) [[ " ${_ARGS[*]} " == *" pip "* && " ${_ARGS[*]} " == *" install "* ]] && return 0 ;;
      pip | pip3) [[ " ${_ARGS[*]} " == *" install "* ]] && return 0 ;;
    esac
  done < <(_bash_segments "$cmd")
  return 1
}

# True for any claim-gated mutation: a runtime mutation OR a source/VCS write.
# npm/pnpm/yarn stay claim-gated-but-not-runtime (matching the legacy gate, so a
# claimed `pnpm tauri build` is not newly forced to carry runtime authorization).
bash_is_mutating() {
  local cmd="$1" seg
  bash_is_runtime_mutation "$cmd" && return 0
  while IFS= read -r seg; do
    [[ -z "${seg// /}" ]] && continue
    _bash_seg_head "$seg"
    [[ -z "$_HEAD" ]] && continue
    case "$_HEAD" in
      npm | pnpm | yarn) return 0 ;;
      tee | cp | install | touch | truncate | chmod | chown | mkdir | rm | mv | dd) return 0 ;;
      sed | perl) _seg_has_inplace "$_HEAD" "$seg" && return 0 ;;
      cat) _cat_writes_file "$seg" && return 0 ;;
      git)
        case "${_ARGS[0]:-}" in
          branch) _git_branch_mutates "${_ARGS[@]:1}" && return 0 ;;
          apply | reset | merge | rebase | restore | commit | push | checkout | switch | tag | add | stash | rm | mv) return 0 ;;
        esac ;;
      gh)
        case "${_ARGS[0]:-}" in
          api | repo | release) return 0 ;;
          pr) case "${_ARGS[1]:-}" in create | merge | edit | close | reopen) return 0 ;; esac ;;
        esac ;;
      python*) _py_writes "$cmd" && return 0 ;;
    esac
  done < <(_bash_segments "$cmd")
  return 1
}

# True for source-tree writes that must fall inside the task's mutation_scope_refs.
# Excludes git ref ops (checkout/switch/branch write no source — the FM-16 fix,
# matching policy_decide's _GIT_SOURCE_SUBCMDS); per-segment splitting means a
# `sed -i` cannot borrow its flag from a downstream piped command.
bash_source_mutation_requires_scope() {
  local cmd="$1" seg
  while IFS= read -r seg; do
    [[ -z "${seg// /}" ]] && continue
    _bash_seg_head "$seg"
    [[ -z "$_HEAD" ]] && continue
    case "$_HEAD" in
      tee | cp | install | touch | truncate | chmod | chown | mkdir | rm | mv | dd) return 0 ;;
      sed | perl) _seg_has_inplace "$_HEAD" "$seg" && return 0 ;;
      cat) _cat_writes_file "$seg" && return 0 ;;
      git) case "${_ARGS[0]:-}" in apply | reset | merge | rebase | restore) return 0 ;; esac ;;
      python*) _py_writes "$cmd" && return 0 ;;
    esac
  done < <(_bash_segments "$cmd")
  return 1
}

connector_tool_is_mutating() {
  local name="$1"
  local repo_root rc
  repo_root="$(cd "$SCRIPT_DIR/../.." && pwd)"
  if command -v python3 >/dev/null 2>&1; then
    set +e
    PYTHONPATH="$repo_root:${PYTHONPATH:-}" \
      python3 -m shared.mcp_connector_policy is-side-effecting "$name" >/dev/null 2>&1
    rc=$?
    set -e
    case "$rc" in
      0) return 0 ;;
      10) return 1 ;;
      *)
        echo "cc-task-gate: WARNING — connector classifier failed for '$name'; treating as mutating." >&2
        return 0
        ;;
    esac
  fi
  printf '%s' "$name" | grep -Eiq \
    '(create|update|delete|merge|push|commit|branch|tag|release|pull_request|issue_comment|send|archive|label|modify|share|upload|respond|dismiss|confirm|disable|flush|decide|nudge_act|set)'
}

# Cognition / diagnostic surfaces are never release-risk: operator auto-memory,
# the personal vault (notes, relay receipts), and ephemeral scratch (/dev/shm,
# project /tmp diagnostics). Edits to these are allowed regardless of claim,
# authority, stage, or scope — a blocked lane must still be able to think, take
# notes, and report state. Their integrity is enforced by content-validating
# writers, not the claim gate. (FR-SCOPE-GATES-COGNITION)
#
# Deliberately NARROW vs the design's bare "/tmp": only /tmp/hapax-* diagnostic
# scratch is carved out, so an unclaimed lane cannot write arbitrary /tmp source.
# Repo docs/*.md are deliberately NOT carved here — they keep the existing
# docs_mutation_authorized gate below; broadening cognition to repo docs is a
# separate, explicit follow-on (it would change the docs-authorization invariant).
is_cognition_path() {
  local p="$1"
  [[ -z "$p" ]] && return 1
  # operator auto-memory at any depth under ~/.claude/**/memory/
  if [[ "$p" == "$HOME"/.claude/* && ( "$p" == */memory/* || "$p" == */memory ) ]]; then
    return 0
  fi
  case "$p" in
    # The governance SSOT (cc-task + request notes) is NOT cognition: it keeps its
    # dedicated content-validated bootstrap/claim path so notes cannot be forged or
    # edited unclaimed. Must precede the general vault rule below.
    "$HOME"/Documents/Personal/20-projects/hapax-cc-tasks/*) return 1 ;;
    "$HOME"/Documents/Personal/20-projects/hapax-requests/*) return 1 ;;
    "$HOME"/Documents/Personal/*) return 0 ;;  # personal vault (cognition / PARA notes)
    /dev/shm/*) return 0 ;;                     # ephemeral diagnostic scratch
    /tmp/hapax-*|/tmp/hapax/*) return 0 ;;      # project diagnostic scratch
  esac
  return 1
}

# --- 2. Only gate file-mutating tools ---
# Covers Claude Code (Edit/Write/Bash) AND Codex (apply_patch/exec_command_pty)
# tool names. The codex-hook-adapter normalizes before calling this script, but
# defense-in-depth: if this hook is invoked directly, Codex tool names still match.
case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit|apply_patch|ApplyPatch|functions.apply_patch|patch)
    ;;
  Bash|exec_command_pty|exec_command|shell|shell_command|unified_exec)
    bash_cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // .tool_input.cmd // .tool_input.shell_command // empty' 2>/dev/null || echo "")"
    if ! bash_is_mutating "$bash_cmd"; then
      exit 0
    fi
    if bash_is_runtime_mutation "$bash_cmd"; then
      mutation_surface_hint="runtime"
    fi
    ;;
  mcp__*)
    if ! connector_tool_is_mutating "$tool_name"; then
      exit 0
    fi
    ;;
  *)
    exit 0
    ;;
esac

# --- 2b. Extract edit path for docs-vs-source classification (section 10) ---
edit_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // empty' 2>/dev/null || echo "")"

# --- 2c. Cognition / diagnostic surfaces: always-allow (FR-SCOPE-GATES-COGNITION) ---
# Placed BEFORE the claim/authority/stage/scope blocks so memory, vault notes,
# and ephemeral scratch are never gated — a blocked lane can still think, take
# notes, and report state. Fail-open-WITH-ledger: an advisory + a ledger line
# are emitted (never silent), but no operator gate stands in the way.
if [[ -n "$edit_path" ]] && is_cognition_path "$edit_path"; then
  _cog_role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-unknown}}}"
  _cog_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_cog_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"cognition_allow","role":"%s","tool":"%s","path":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$_cog_role" "$tool_name" "$edit_path" \
    >> "$_cog_ledger" 2>/dev/null || true
  echo "cc-task-gate: cognition surface — allowed (advisory, logged): $edit_path" >&2
  exit 0
fi

# --- 3. Bypass for incident response (DEPRECATED — incident-only, now ledgered) ---
# Historically a silent, unconditional, unscoped off-switch — the audit's core
# complaint was that it logged NOTHING. It still works for incident response but
# is now recorded to the methodology ledger (the digest counts it) and points the
# operator at the scoped, signed, daemon-independent escape-grant path instead.
if [[ "${HAPAX_CC_TASK_GATE_OFF:-0}" == "1" ]]; then
  _gate_off_role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-unknown}}}"
  _gate_off_ledger="${HAPAX_METHODOLOGY_LEDGER:-$HOME/.cache/hapax/methodology-emergency-ledger.jsonl}"
  mkdir -p "$(dirname "$_gate_off_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"cc_task_gate_off_bypass","role":"%s","tool":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$_gate_off_role" "$tool_name" \
    >>"$_gate_off_ledger" 2>/dev/null || true
  echo "cc-task-gate: HAPAX_CC_TASK_GATE_OFF bypass used — LEDGERED. This switch is DEPRECATED" >&2
  echo "  (incident-only). Prefer a scoped signed escape: scripts/coord-grant-mint --scope $GATE_NAME." >&2
  exit 0
fi
# Methodology emergency bypass (logged in section 10 when case_id is present;
# here as early-out when infrastructure prevents reaching section 10).
if [[ "${HAPAX_METHODOLOGY_EMERGENCY:-0}" == "1" ]]; then
  _emergency_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_emergency_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","role":"unknown","task":"unknown","case":"unknown","tool":"%s","reason":"early_infra_bypass"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$tool_name" \
    >> "$_emergency_ledger" 2>/dev/null || true
  echo "cc-task-gate: EMERGENCY BYPASS (early) — logged" >&2
  _record_retro_grant_obligation "unknown" "unknown" "unknown" "$tool_name" "HAPAX_METHODOLOGY_EMERGENCY"
  exit 0
fi

# --- 3b. Unclaimed governance-intake bootstrap allowance ---
# The task gate must not deadlock the lifecycle it enforces. A session without
# a claim may create a new request or offered cc-task note, but only through a
# path-scoped, content-validated Write event. Ordinary source/runtime/system
# mutation and manual claim-file writes still fail closed below.
#
# FAIL-OPEN ON INFRA ERROR (reform — bootstrap-failopen-atomic-swap). This is the
# roleless session's ONLY sanctioned write path, so it MUST mirror the shim's
# INV-5 posture (master design §2.2 / FM-15 / NEW-2): when the validator helper
# itself cannot run — unreadable, mid atomic-swap, or it crashes — a bootstrap
# CANDIDATE write fails OPEN (advisory + ledger) instead of fail-closed-blocking,
# and any other mutation falls through to the normal claim/authority gate. ONLY a
# genuine BLOCKED verdict (rc==12) from a helper that actually ran blocks; python's
# own "can't open file" rc==2 and every other non-{0,10} code are infra signals,
# never a deny. Before this fix the case mapped EVERY non-{0,10} code to exit 2, so
# a redeploy that briefly unlinked the helper fail-closed even a properly CLAIMED
# session (the S2 incident).
_bootstrap_helper="$SCRIPT_DIR/cc-task-gate-bootstrap.py"

# _bootstrap_is_candidate_target — mirror the helper's candidate test in pure bash
# so the fail-OPEN stays narrow: only a Write of a .md note under the governance
# intake roots (hapax-requests/active or hapax-cc-tasks/active) fails open when the
# helper can't run. Any other mutation falls through to the normal gate — an infra
# error must never widen what a non-bootstrap mutation may do.
_bootstrap_is_candidate_target() {
  [[ "$tool_name" == "Write" ]] || return 1
  local p="${edit_path/#\~/$HOME}"
  [[ -n "$p" && "$p" == *.md ]] || return 1
  case "$p" in
    "$HOME"/Documents/Personal/20-projects/hapax-requests/active/*) return 0 ;;
    "$HOME"/Documents/Personal/20-projects/hapax-cc-tasks/active/*) return 0 ;;
  esac
  return 1
}

# _bootstrap_infra_failopen — shared "the validator could not run" handler: emit a
# loud ledger line + stderr advisory, then mirror INV-5 — fail OPEN (exit 0) for a
# candidate, else return so the caller falls through to the normal claim gate.
_bootstrap_infra_failopen() {
  local reason="$1" detail="$2" is_cand="false"
  if _bootstrap_is_candidate_target; then is_cand="true"; fi
  local _bs_role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-unknown}}}"
  local _bs_ledger="${HAPAX_METHODOLOGY_LEDGER:-$HOME/.cache/hapax/methodology-emergency-ledger.jsonl}"
  mkdir -p "$(dirname "$_bs_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"bootstrap_helper_infra_failopen","reason":"%s","detail":"%s","role":"%s","tool":"%s","path":"%s","candidate":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$reason" "$detail" "$_bs_role" "$tool_name" "${edit_path:-}" "$is_cand" \
    >> "$_bs_ledger" 2>/dev/null || true
  if [[ "$is_cand" == "true" ]]; then
    echo "cc-task-gate: bootstrap validator unavailable ($reason) — FAILING OPEN for governance-intake write (advisory, ledgered, INV-5): ${edit_path:-}" >&2
    exit 0
  fi
  echo "cc-task-gate: bootstrap validator unavailable ($reason) — non-candidate mutation falls through to the normal gate (advisory, ledgered)." >&2
  return 0
}

if [[ ! -r "$_bootstrap_helper" ]]; then
  # Absent/unreadable (e.g. a concurrent hooks-doctor redeploy briefly unlinked
  # it). Don't exec python on it — that would surface as rc==2 and historically
  # fail closed. Go straight to the INV-5 fail-open handler.
  _bootstrap_infra_failopen "helper_unreadable" "$_bootstrap_helper"
else
  set +e
  _bootstrap_output="$(
    printf '%s' "$input" | python3 "$_bootstrap_helper" 2>&1
  )"
  _bootstrap_rc=$?
  set -e
  case "$_bootstrap_rc" in
    0)
      [[ -n "$_bootstrap_output" ]] && printf '%s\n' "$_bootstrap_output" >&2
      exit 0
      ;;
    10)
      # NOT_CANDIDATE — fall through to the normal claim/authority gate.
      ;;
    12)
      # The ONLY blocking verdict: the helper ran and judged the bootstrap note
      # invalid. A genuine deny.
      [[ -n "$_bootstrap_output" ]] && printf '%s\n' "$_bootstrap_output" >&2
      exit 2
      ;;
    *)
      # Any other code (python rc 2 = can't open file, 1 = uncaught exception,
      # 127 = python missing, …) is an INFRA signal, never a deny. Mirror INV-5:
      # fail OPEN for a candidate, else fall through. Sanitize the captured output
      # before it enters the JSONL ledger.
      _bs_det="$(printf '%s' "${_bootstrap_output:-}" | tr '\n\r\t"\\' '     ' | cut -c1-160)"
      _bootstrap_infra_failopen "helper_rc_${_bootstrap_rc}" "$_bs_det"
      ;;
  esac
fi

# --- 3c. Shadow decision log (reform 3b PRODUCER source) ---------------------
# From here on every exit is a genuine GATED decision (the non-mutating / cognition
# / bypass / bootstrap early-outs above are NOT logged). Append this gate's REAL
# exit code + the resolved state it decided on to a cache JSONL so
# scripts/policy-decide-shadow-replay can diff it against shared.policy_decide.
# The legacy verdict recorded here is THIS gate's own exit code — never a
# re-derivation via _LEGACY_*_RE, which is exactly the drift the 3b-cutover unit
# must eliminate. Advisory only: `set +e` in the trap guarantees the logging can
# never change the verdict, and HAPAX_GATE_DECISION_LOG_OFF=1 kills it outright.
_shadow_decision_log="${HAPAX_GATE_DECISION_LOG:-$HOME/.cache/hapax/cc-task-gate-decisions.jsonl}"
_emit_gate_decision() {
  local rc=$?
  trap - EXIT
  set +e
  if [[ "${HAPAX_GATE_DECISION_LOG_OFF:-0}" == "1" ]]; then
    return 0
  fi
  if command -v jq >/dev/null 2>&1 && command -v flock >/dev/null 2>&1; then
    mkdir -p "$(dirname "$_shadow_decision_log")" 2>/dev/null
    # Single-writer-safe append: capture the record, then write it under an
    # exclusive flock on the SAME sidecar Python uses (<name>.lock). flock(1) and
    # fcntl.flock(2) both take a kernel LOCK_EX on the inode, so this bash writer
    # and the Python writers never interleave — the decision log carries records
    # >PIPE_BUF (max ~9KB live). flock is hard-required (no raw >> fallback); the
    # sidecar is pre-created 0600 to match shared.jsonl_append._lock_path
    # (dn-ledger-flock).
    _decision_lock="${_shadow_decision_log}.lock"
    (umask 077; : >>"$_decision_lock") 2>/dev/null
    _decision_rec="$(jq -cn \
      --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --argjson legacy_exit "$rc" \
      --arg role "${role:-}" \
      --arg session_id "${session_id:-}" \
      --arg task_id "${task_id:-}" \
      --arg tool_name "${tool_name:-}" \
      --arg command "${bash_cmd:-}" \
      --arg file_path "${edit_path:-}" \
      --arg mutation_surface "${mutation_surface_hint:-source}" \
      --arg status "${status:-}" \
      --arg assigned_to "${assigned:-}" \
      --arg authority_case "${authority_case:-}" \
      --arg parent_spec "${parent_spec:-}" \
      --arg stage "${case_stage:-}" \
      --arg implementation_authorized "${impl_authorized:-}" \
      --arg source_mutation_authorized "${src_authorized:-}" \
      --arg docs_mutation_authorized "${docs_authorized:-}" \
      --arg runtime_mutation_authorized "${runtime_authorized:-}" \
      --arg mutation_scope_refs "${mutation_scope_refs:-}" \
      '{ts:$ts, legacy_exit:$legacy_exit, role:$role, session_id:$session_id, task_id:$task_id, tool_name:$tool_name, command:$command, file_path:$file_path, mutation_surface:$mutation_surface, status:$status, assigned_to:$assigned_to, authority_case:$authority_case, parent_spec:$parent_spec, stage:$stage, implementation_authorized:$implementation_authorized, source_mutation_authorized:$source_mutation_authorized, docs_mutation_authorized:$docs_mutation_authorized, runtime_mutation_authorized:$runtime_mutation_authorized, mutation_scope_refs:$mutation_scope_refs}' 2>/dev/null)"
    if [ -n "$_decision_rec" ]; then
      printf '%s\n' "$_decision_rec" \
        | flock "$_decision_lock" tee -a "$_shadow_decision_log" >/dev/null 2>&1
    fi
  fi
  return 0
}
trap '_emit_gate_decision' EXIT

# --- 4. Determine session identity (coordination reform Phase 1, cluster 6) ---
# Single source of truth in agent-role.sh (sourced above): explicit env →
# agent-role recovery → relay presence → role-less-but-claimable fallback
# ("roleless"). Branch-prefix inference was REMOVED (FM-1): a worktree's git
# branch is not identity — it produced phantom roles (usually alpha) that
# clobbered the role's shared claim file. The role-less degraded mode (audit B)
# lives inside hapax_effective_role: a session with a session id but no role
# resolves to "roleless" and stays fully governed (authority/stage/scope still
# enforced below) rather than being hard-blocked. "No role" never means "no
# escape."
session_id=""
if declare -F hapax_session_id >/dev/null 2>&1; then
  session_id="$(hapax_session_id 2>/dev/null || true)"
fi
if declare -F hapax_effective_role >/dev/null 2>&1; then
  role="$(hapax_effective_role 2>/dev/null || true)"
else
  role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
fi
if [[ -z "$role" ]]; then
  # No identity at all (no role AND no session id) — genuinely unkeyable.
  _emit_block <<EOF
cc-task-gate: BLOCKED — cannot determine session role (set HAPAX_AGENT_ROLE, CODEX_ROLE, or CLAUDE_ROLE).
  Protected mutations require a role or a session id. Bypass: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

# Session-keyed claim lookup with legacy fallback. cc-claim keys a claim to
# <role>-<session_id> so two same-role sessions never collide (FM-2); a pre-reform
# claim at the legacy <role> path is still honoured through the cutover.
claim_file=""
if [[ -n "$session_id" ]] && [[ -f "$HOME/.cache/hapax/cc-active-task-$role-$session_id" ]]; then
  claim_file="$HOME/.cache/hapax/cc-active-task-$role-$session_id"
elif [[ -f "$HOME/.cache/hapax/cc-active-task-$role" ]]; then
  claim_file="$HOME/.cache/hapax/cc-active-task-$role"
fi
if [[ -z "$claim_file" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — no claimed task for role '$role'.

  Claim a task before mutating files:
    cc-claim <task_id>

  To start new work without bypassing the gate, use the Write tool to create
  one of these validated, audited bootstrap notes:
    20-projects/hapax-requests/active/REQ-<timestamp>-<slug>.md
    20-projects/hapax-cc-tasks/active/<task_id>.md

  Then run request-intake-consumer / cc-claim through the normal lifecycle.
  Do not write ~/.cache/hapax/cc-active-task-* by hand.

  Browse the offered queue in Obsidian:
    20-projects/hapax-cc-tasks/_dashboard/cc-offered.md
EOF
  exit 2
fi

# Lease heartbeat (reform Phase 1, cluster 6): refresh the resolved claim file's
# mtime — this session is demonstrably alive (it is making a gated call against a
# valid claim). cc-claim treats a claim older than the lease TTL as free, so this
# keeps a live session's lease from aging out and being reaped while a dead
# session's lease still expires. Best-effort; never blocks the decision below.
touch "$claim_file" 2>/dev/null || true

task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
if [[ -z "$task_id" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — claim file is empty for role '$role'.
  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

# --- 6. Locate task note in vault ---
vault_root="$HOME/Documents/Personal/20-projects/hapax-cc-tasks"
note_path=""
for candidate in "$vault_root/active/$task_id-"*.md; do
  if [[ -f "$candidate" ]]; then
    note_path="$candidate"
    break
  fi
done
if [[ -z "$note_path" && -f "$vault_root/active/$task_id.md" ]]; then
  note_path="$vault_root/active/$task_id.md"
fi
if [[ -z "$note_path" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — claimed task '$task_id' not found in vault.

  Claim file:    $claim_file (says '$task_id')
  Vault search:  $vault_root/active/$task_id-*.md or $vault_root/active/$task_id.md

  Either the task was moved to closed/ (no longer claimable) or the
  claim file is stale. Re-claim a fresh task:
    cc-claim <task_id>
EOF
  exit 2
fi

# --- 6b. Own claimed-task note: always editable by its claimer (fix-cc-gate-fps
# Fix 2). A session's OWN claimed cc-task note is governance bookkeeping (session
# log, AC checkboxes, stage) and is rarely listed in its own mutation_scope_refs, so
# the fully-authorized owner was scope-DENIED editing it. Allow it here, matched
# against the RESOLVED note_path for THIS claimed task only — a DIFFERENT task's note
# stays fully gated. Mirrors policy_decide's _is_own_task_note allow (section 5b) and
# precedes status/authority/scope so a claimer can maintain its own note even across
# a reconciler-unassign race or a terminal status.
if [[ -n "$edit_path" ]]; then
  _edit_real="$(realpath -m -- "$edit_path" 2>/dev/null || echo "$edit_path")"
  _note_real="$(realpath -m -- "$note_path" 2>/dev/null || echo "$note_path")"
  if [[ "$_edit_real" == "$_note_real" ]]; then
    echo "cc-task-gate: own claimed-task note — allowed (governance bookkeeping): $edit_path" >&2
    exit 0
  fi
fi

# --- 7. Parse frontmatter via python (jq doesn't do YAML) ---
if ! command -v python3 &>/dev/null; then
  echo "cc-task-gate: BLOCKED — python3 missing; cannot validate AuthorityCase." >&2
  echo "  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1" >&2
  exit 2
fi

# Use a tiny inline python to extract status + assignment + AuthorityCase
# fields. `authority_case` is canonical; `case_id` is accepted only as a
# backwards-compatible alias.
# Output format:
# status assigned blocked authority parent_spec route_schema stage impl src docs runtime scope_refs
parse_output="$(python3 - "$note_path" <<'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if not text.startswith("---"):
    print("\t\t\t\t\t\t\t")
    sys.exit(0)
end = text.find("\n---", 4)
if end < 0:
    print("\t\t\t\t\t\t\t")
    sys.exit(0)
front = text[4:end]
fields = {}
lines = front.splitlines()
idx = 0
def normalize_value(key, val):
    val = val.strip().strip('"').strip("'")
    if key == "mutation_scope_refs" and val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return ""
        items = [
            part.strip().strip('"').strip("'")
            for part in inner.split(",")
            if part.strip()
        ]
        return "\x1f".join(items)
    return val
while idx < len(lines):
    raw = lines[idx]
    line = raw.strip()
    idx += 1
    if not line or line.startswith("#") or ":" not in line:
        continue
    key, _, val = line.partition(":")
    key = key.strip()
    val = normalize_value(key, val)
    if val:
        fields[key] = val
        continue
    items = []
    while idx < len(lines):
        child = lines[idx].strip()
        if child.startswith("- "):
            items.append(child[2:].strip().strip('"').strip("'"))
            idx += 1
            continue
        if not child:
            idx += 1
            continue
        break
    fields[key] = "\x1f".join(items)
status = fields.get("status", "")
assigned = fields.get("assigned_to", "")
blocked_reason = fields.get("blocked_reason", "")
blocked_witness = fields.get("blocked_witness", "") or fields.get("blocked_witness_path", "")
authority_case = fields.get("authority_case") or fields.get("case_id", "")
parent_spec = fields.get("parent_spec", "")
route_schema = fields.get("route_metadata_schema", "")
stage = fields.get("stage", "")
impl_auth = fields.get("implementation_authorized", "")
src_auth = fields.get("source_mutation_authorized", "")
docs_auth = fields.get("docs_mutation_authorized", "")
runtime_auth = fields.get("runtime_mutation_authorized", "")
scope_refs = fields.get("mutation_scope_refs", "")
print(
    f"{status}\t{assigned}\t{blocked_reason}\t{blocked_witness}\t"
    f"{authority_case}\t{parent_spec}\t{route_schema}\t{stage}\t"
    f"{impl_auth}\t{src_auth}\t{docs_auth}\t{runtime_auth}\t{scope_refs}"
)
PYEOF
)"

status="$(printf '%s' "$parse_output" | cut -f1)"
assigned="$(printf '%s' "$parse_output" | cut -f2)"
blocked_reason="$(printf '%s' "$parse_output" | cut -f3)"
blocked_witness="$(printf '%s' "$parse_output" | cut -f4)"
authority_case="$(printf '%s' "$parse_output" | cut -f5)"
parent_spec="$(printf '%s' "$parse_output" | cut -f6)"
route_schema="$(printf '%s' "$parse_output" | cut -f7)"
case_stage="$(printf '%s' "$parse_output" | cut -f8)"
impl_authorized="$(printf '%s' "$parse_output" | cut -f9)"
src_authorized="$(printf '%s' "$parse_output" | cut -f10)"
docs_authorized="$(printf '%s' "$parse_output" | cut -f11)"
runtime_authorized="$(printf '%s' "$parse_output" | cut -f12)"
mutation_scope_refs="$(printf '%s' "$parse_output" | cut -f13-)"

# --- 8. Check assigned_to ---
if [[ "$assigned" != "$role" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' is assigned to '$assigned', not '$role'.

  Note: $note_path
  Either this session has the wrong role, or the operator reassigned
  the task. Refresh the claim file or update the task's assigned_to.
EOF
  exit 2
fi

# --- 9. Check status ---
_transition_claimed=false
case "$status" in
  in_progress)
    # Status OK — fall through to AuthorityCase validation (section 10).
    ;;
  claimed)
    # Defer claimed → in_progress until after AuthorityCase/scope validation.
    # A denied first mutation must not leave the task note marked active.
    _transition_claimed=true
    ;;
  blocked)
    _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' is in BLOCKED state.

  Reason:  ${blocked_reason:-(no reason set)}
  Witness: ${blocked_witness:-(no witness set)}
  Note:    $note_path

  Operator must edit the task to status: in_progress (or claimed) to resume.
EOF
    exit 2
    ;;
  pr_open|merge_queue|ci_green|ready|ready_for_review|review_ready|ready_for_merge)
    # PR-open / merge-queue / ready-family: the owning lane may still mutate
    # files (CI fixes, review feedback, queue/closeout maintenance). The
    # ready-family was previously unhandled here and fell to *) → BLOCK,
    # stranding the ~88 active `ready` tasks (the gate blocked exactly the
    # statuses the autoqueue admits). SSOT: shared/sdlc_lifecycle.py
    # TASK_MUTABLE_STATUSES, pinned by
    # tests/hooks/test_cc_task_gate.py::TestStatusVocabularyDrift.
    # Fall through to AuthorityCase validation (section 10).
    ;;
  done|withdrawn|superseded|completed|complete|closed|fulfilled|resolved|withdrawn_stale|closed_superseded|rejected|refused|not_applicable|deferred|closed_poisoned)
    _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' is terminal ('$status').

  Note: $note_path

  This task has shipped or been withdrawn. Claim a fresh task:
    cc-claim <task_id>
EOF
    exit 2
    ;;
  offered|"")
    _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' is in '$status' state, not claimed.

  Note: $note_path

  Run \`cc-claim $task_id\` to claim it before mutating files.
EOF
    exit 2
    ;;
  *)
    _emit_block <<EOF
cc-task-gate: BLOCKED — unknown status '$status' for task '$task_id'.
  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
    exit 2
    ;;
esac

# --- 10. AuthorityCase validation (SDLC Reform Slice 2) ---
# `authority_case` is canonical for current cc-tasks. Missing authority on a
# mutating tool is a hard block; migration compatibility belongs in explicit
# read-only/intake paths, not source/runtime mutation.
is_nullish() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$value" in
    ""|null|none|"~"|"[]") return 0 ;;
    *) return 1 ;;
  esac
}

# Idempotently set a single frontmatter key in a cc-task note: replace the key
# if present, else insert it before the closing '---'. Atomic (tmp + rename).
# Used to stamp a derived/defaulted field durably so downstream release/packet
# checks read it consistently. Best-effort: returns non-zero on any failure.
_stamp_frontmatter_field() {
  local note="$1" key="$2" value="$3"
  python3 - "$note" "$key" "$value" <<'PYEOF' 2>/dev/null || return 1
import sys
from pathlib import Path

path, key, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
if not text.startswith("---"):
    sys.exit(1)
end = text.find("\n---", 4)
if end < 0:
    sys.exit(1)
front, body = text[4:end], text[end:]
out, found = [], False
for line in front.splitlines():
    stripped = line.strip()
    if stripped.startswith(f"{key}:") or stripped.startswith(f"{key} :"):
        out.append(f"{key}: {value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}: {value}")
new = "---\n" + "\n".join(out) + body
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(new, encoding="utf-8")
tmp.replace(path)
PYEOF
}

# authority_case and parent_spec remain HARD requirements: they are the verified
# root of authority, not derivable defaults. Error messages point at in-session
# repair (cc-task-repair, next cluster) rather than a dead end.
if is_nullish "$authority_case"; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — mutating task '$task_id' has no authority_case.

  Task: $note_path
  Current field may be missing or legacy-only. Modern mutating work requires
  authority_case plus a non-null parent_spec before any source/runtime change.
  Repair in place (next cluster): cc-task-repair $task_id --backfill-authority
EOF
  exit 2
fi

if is_nullish "$parent_spec"; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — mutating task '$task_id' has no non-null parent_spec.

  AuthorityCase: $authority_case
  Task: $note_path

  Create or attach the parent request/spec first. Read-only diagnosis and
  governed bootstrap note creation remain allowed; source/runtime mutation does not.
  Repair in place (next cluster): cc-task-repair $task_id --attach-parent-spec
EOF
  exit 2
fi

# route_metadata_schema has exactly one legal value (1). A nullish value is a
# template/migration gap, not an authority defect — default it in-memory and log
# a ledger line (fail-open-WITH-ledger) instead of bricking authorized work.
# (FR-AUTHORITY-FIELDS-FIRST-MUTATION-BLOCK)
if is_nullish "$route_schema"; then
  route_schema=1
  _route_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_route_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"route_schema_defaulted","role":"%s","task":"%s","case":"%s","value":1}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task_id" "$authority_case" \
    >> "$_route_ledger" 2>/dev/null || true
  echo "cc-task-gate: route_metadata_schema missing — defaulted to 1 (logged for review)." >&2
fi

# Direct docs/report mutations are allowed to happen before implementation
# when the task explicitly authorizes docs mutation. Source/runtime mutation
# still requires S6 + implementation authorization below.
_is_docs_edit=false
if [[ -n "$edit_path" ]]; then
  case "$edit_path" in
    */docs/*|*/CLAUDE.md|*/README.md|*.md) _is_docs_edit=true ;;
  esac
fi

# Emergency bypass with audit logging
if [[ "${HAPAX_METHODOLOGY_EMERGENCY:-0}" == "1" ]]; then
  _emergency_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_emergency_ledger")"
  printf '{"ts":"%s","role":"%s","task":"%s","case":"%s","tool":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task_id" "$authority_case" "$tool_name" \
    >> "$_emergency_ledger"
  echo "cc-task-gate: EMERGENCY BYPASS — logged to $_emergency_ledger" >&2
  _record_retro_grant_obligation "$role" "$task_id" "$authority_case" "$tool_name" "HAPAX_METHODOLOGY_EMERGENCY"
  exit 0
fi

# Stage must be S6 or later for implementation
_stage_num=""
if [[ "$case_stage" =~ ^S([0-9]+) ]]; then
  _stage_num="${BASH_REMATCH[1]}"
fi
# FR-STAGE-S6-TRAP: a blank/unparseable stage on a fully-authorized task
# (authority_case + parent_spec already verified non-null above, plus
# implementation_authorized: true) is a template gap, not a stage deficiency.
# Derive S6 AND stamp an explicit numeric stage into the note so downstream
# release/packet checks read it consistently (closes the shadow-denial brick
# where stage_num=-1 tripped a release-time denial). Fail-open-WITH-ledger.
# Source mutation still requires impl auth + scope below.
if [[ "$_is_docs_edit" != "true" && -z "$_stage_num" && "$impl_authorized" == "true" ]] \
   && ! is_nullish "$authority_case" && ! is_nullish "$parent_spec"; then
  _orig_stage="${case_stage:-<blank>}"
  case_stage="S6_IMPLEMENTATION"
  _stage_num=6
  _stamp_frontmatter_field "$note_path" "stage" "S6_IMPLEMENTATION" || true
  _stage_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_stage_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"stage_derived","role":"%s","task":"%s","case":"%s","from":"%s","to":"S6_IMPLEMENTATION"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task_id" "$authority_case" "$_orig_stage" \
    >> "$_stage_ledger" 2>/dev/null || true
  echo "cc-task-gate: blank stage on authorized task — derived + stamped S6_IMPLEMENTATION (logged)." >&2
fi
if [[ "$_is_docs_edit" != "true" && ( -z "$_stage_num" || "$_stage_num" -lt 6 ) ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' has invalid or insufficient stage '$case_stage' (< S6).

  Implementation requires stage >= S6 with implementation_authorized: true.
  Task: $note_path

  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

# implementation_authorized must be true
if [[ "$_is_docs_edit" != "true" && "$impl_authorized" != "true" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' does not have implementation_authorized: true.

  Current value: implementation_authorized: $impl_authorized
  Task: $note_path

  Create an Implementation Slice Authorization Packet (S5) first.
  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

if [[ "$_is_docs_edit" == "true" && "$docs_authorized" != "true" ]]; then
  # Source mutation auth subsumes docs if source is authorized
  if [[ "$src_authorized" != "true" ]]; then
    _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' does not authorize docs mutation.

  docs_mutation_authorized: $docs_authorized
  source_mutation_authorized: $src_authorized
  File: $edit_path
  Task: $note_path

  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
    exit 2
  fi
fi

if [[ "$mutation_surface_hint" == "runtime" && "$runtime_authorized" != "true" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' does not authorize runtime mutation.

  runtime_mutation_authorized: $runtime_authorized
  Command: ${bash_cmd:0:160}
  Task: $note_path

  Read-only runtime inspection remains allowed; restart/install/remote/process
  mutation requires an explicit runtime task.
EOF
  exit 2
fi

if [[ "$_is_docs_edit" != "true" && "$mutation_surface_hint" != "runtime" && "$src_authorized" != "true" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' does not authorize source mutation.

  source_mutation_authorized: $src_authorized
  File: ${edit_path:-"(shell/mcp mutation)"}
  Task: $note_path
EOF
  exit 2
fi

if [[ -z "$edit_path" && -n "$bash_cmd" && "$mutation_surface_hint" != "runtime" ]]; then
  # Strip single/double-quoted spans + trailing comments before the source-scope
  # check so mutation tokens that appear only inside a message/echo payload (e.g.
  # `git commit -m "remove the rm and mv helpers"`) don't false-trigger the guard.
  # The quote-strip mirrors the proven no-stale-branches.sh:75 line (sed -z spans
  # newlines, so multi-line "$(cat <<'EOF'…)" payloads are stripped too); the
  # comment-strip only removes '#' at a word boundary so `${v#x}` / URL fragments
  # survive. NOT applied to bash_is_mutating / bash_is_runtime_mutation — those
  # stay raw so a quoted `systemctl` or python-write inside a heredoc still fails
  # closed. (FR-BASH-MUTATION-FALSE-POSITIVES)
  _cmd_stripped="$(printf '%s' "$bash_cmd" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g; s/(^|[[:space:]])#[^\n]*//g")"
  if bash_source_mutation_requires_scope "$_cmd_stripped"; then
    _emit_block <<EOF
cc-task-gate: BLOCKED — cannot verify mutation_scope_refs for shell source mutation.

  Command: ${bash_cmd:0:160}
  Task: $note_path
EOF
    exit 2
  fi
fi

if [[ -n "$edit_path" ]]; then
  # Anchor RELATIVE scope refs/targets to the git repo toplevel AND the personal
  # vault root (in addition to the live cwd), so a vault cc-task's own
  # `20-projects/hapax-cc-tasks/` scope resolves to the absolute note path and a bare
  # repo-relative ref resolves even from a repo subdirectory (fix-cc-gate-fps Fix 2).
  # git toplevel anchors: the hook-cwd toplevel (the session worktree) AND the
  # edited file's OWN repo/worktree toplevel. The file's toplevel is the
  # canonical anchor for the file's relative path — without it, an in-scope edit
  # to a SIBLING worktree's file cannot match: the cwd/primary-worktree toplevel
  # resolves the scope ref to a DIFFERENT worktree's copy of the same relative
  # path (e.g. a session rooted at the meta-workspace or the primary council
  # worktree editing a --review-witness / --cns lane worktree). A non-repo
  # cwd/file yields "" and only the remaining anchors apply.
  # Harden BOTH git discovery calls against GIT_DIR/GIT_WORK_TREE env vars:
  # if set in the hook environment they override -C/cwd discovery, resolving the
  # toplevel to an unrelated repo (review finding on PR #4280). `env -u` strips
  # them for the call so discovery proceeds from the intended path.
  _scope_repo_top="$(env -u GIT_DIR -u GIT_WORK_TREE git rev-parse --show-toplevel 2>/dev/null || true)"
  _scope_file_top="$(env -u GIT_DIR -u GIT_WORK_TREE git -C "$(dirname "$edit_path")" rev-parse --show-toplevel 2>/dev/null || true)"
  _scope_vault_root="$HOME/Documents/Personal"
  scope_check="$(python3 - "$edit_path" "$mutation_scope_refs" "$_scope_repo_top" "$_scope_vault_root" "$_scope_file_top" <<'PYEOF'
import os
import sys
from pathlib import Path

target_raw = sys.argv[1]
scope_blob = sys.argv[2]
repo_top = sys.argv[3] if len(sys.argv) > 3 else ""
vault_root = sys.argv[4] if len(sys.argv) > 4 else ""
file_top = sys.argv[5] if len(sys.argv) > 5 else ""
if not scope_blob.strip():
    print("missing")
    sys.exit(0)

# Candidate anchor roots for a RELATIVE path: the live cwd (legacy behavior), the git
# repo toplevel (so a bare `shared/x` / `tests/` ref resolves even when the session
# cwd is a subdirectory), and the personal vault root (so a vault cc-task's own
# `20-projects/hapax-cc-tasks/` scope resolves to the absolute note path, not a
# nonexistent repo-relative path). Absolute paths ignore the anchors.
anchor_roots = [Path.cwd()]
for _root in (repo_top, vault_root, file_top):
    if _root:
        anchor_roots.append(Path(_root))


def _resolved_candidates(raw):
    p = Path(os.path.expanduser(raw))
    raws = [p] if p.is_absolute() else [root / p for root in anchor_roots]
    out = []
    for cand in raws:
        try:
            out.append(cand.resolve(strict=False))
        except Exception:
            out.append(cand.absolute())
    return out


target_candidates = _resolved_candidates(target_raw)

allowed = False
for raw in scope_blob.split("\x1f"):
    item = raw.strip()
    if not item or item.startswith(("cc-task:", "request:")):
        continue
    dir_suffix = item.endswith("/") or item.endswith(os.sep)
    for scope_resolved in _resolved_candidates(item):
        prefix = str(scope_resolved).rstrip(os.sep) + os.sep
        for target_resolved in target_candidates:
            if target_resolved == scope_resolved:
                allowed = True
                break
            if dir_suffix and str(target_resolved).startswith(prefix):
                allowed = True
                break
            if scope_resolved.is_dir():
                try:
                    target_resolved.relative_to(scope_resolved)
                    allowed = True
                    break
                except ValueError:
                    pass
        if allowed:
            break
    if allowed:
        break

print("allowed" if allowed else "denied")
PYEOF
)"
  case "$scope_check" in
    allowed) ;;
    missing)
      _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' has no mutation_scope_refs for direct file mutation.

  File: $edit_path
  Task: $note_path
EOF
      exit 2
      ;;
    *)
      _emit_block <<EOF
cc-task-gate: BLOCKED — file is outside this task's declared mutation_scope_refs.

  File: $edit_path
  Task: $note_path
EOF
      exit 2
      ;;
  esac
fi

if [[ "$_transition_claimed" == "true" ]]; then
  python3 - "$note_path" <<'PYEOF'
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
text2 = re.sub(
    r"^updated_at:.*$",
    f"updated_at: {now}",
    text,
    count=1,
    flags=re.MULTILINE,
)
text3 = text2.replace(
    "status: claimed", "status: in_progress", 1
).replace(
    "## Session log\n",
    f"## Session log\n- {now} hook transitioned claimed → in_progress on first mutation\n",
    1,
)
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(text3, encoding="utf-8")
tmp.replace(path)
PYEOF
fi

exit 0
