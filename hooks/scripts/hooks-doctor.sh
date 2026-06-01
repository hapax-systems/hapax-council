#!/usr/bin/env bash
# hooks-doctor.sh — gate-drift detector + canonical deployer (reform FM-6).
#
# The cc-task-gate used to be physically copied into every worktree, so the fleet
# carried SIX gate versions (427/651/779/786/832/905 lines) and the oldest lanes
# silently violated INV-5 (cognition-always-writable) because their 427-line gate
# predates is_cognition_path. The fix is one canonical impl + thin shims; this
# tool is the drift detector the design promised, plus the deployer/fanout that
# makes "update the gate" a one-file change.
#
# Modes:
#   --session            (default) advisory fleet report; ALWAYS exit 0 (never
#                        wedges a SessionStart); prints CRITICAL/WARN drift lines.
#   --check | --strict   strict: exit 1 on CRITICAL drift (CI + manual). The
#                        committed cc-task-gate.sh MUST be a shim and the impl
#                        MUST carry is_cognition_path, else CI refuses.
#   --deploy-canonical   copy the gate closure (impl + agent-role + escape-grant +
#                        this doctor) to $HAPAX_CANONICAL_HOOKS and write a
#                        sha256 MANIFEST; symlink ~/.local/bin/hapax-hooks-doctor.
#   --fanout             rewrite every lane worktree's cc-task-gate.sh to the
#                        canonical shim (the one-shot that fixes INV-5 on stale
#                        lanes immediately, without waiting for them to rebase).
#   --classify FILE      print a single gate file's classification; exit nonzero
#                        if it is drifted (used by the test-suite + ad-hoc).
#
# Options: --from DIR (deploy source, default this repo), --root DIR (override the
# repo/worktree root for --check/fleet, for tests), --dry-run, --verbose|-v,
# --notify (best-effort ntfy on drift, for the timer/service).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANONICAL_DIR="${HAPAX_CANONICAL_HOOKS:-$HOME/.local/lib/hapax/hooks}"
SHIM_MARKER="HAPAX-GATE-SHIM"
COGNITION_MARKER="is_cognition_path()"

MODE=session
FROM=""
ROOT_OVERRIDE=""
DRY=0
VERBOSE=0
NOTIFY=0
CLASSIFY_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session)                 MODE=session ;;
    --check|--strict)          MODE=check ;;
    --deploy-canonical|--deploy) MODE=deploy ;;
    --fanout)                  MODE=fanout ;;
    --classify)                MODE=classify; CLASSIFY_FILE="${2:?--classify needs a FILE}"; shift ;;
    --from)                    FROM="${2:?--from needs a DIR}"; shift ;;
    --root)                    ROOT_OVERRIDE="${2:?--root needs a DIR}"; shift ;;
    --dry-run)                 DRY=1 ;;
    --verbose|-v)              VERBOSE=1 ;;
    --notify)                  NOTIFY=1 ;;
    -h|--help)                 grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "hooks-doctor: unknown argument: $1" >&2; exit 64 ;;
  esac
  shift
done

# Repo/worktree root: --root wins (tests), else this file's repo, else its dir.
if [[ -n "$ROOT_OVERRIDE" ]]; then
  REPO_ROOT="$ROOT_OVERRIDE"
else
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." 2>/dev/null && pwd || echo "$SCRIPT_DIR")"
fi

# classify_gate <gate-file> — echo a label; return 0 shim, 2 warn-drift,
# 3 critical-drift, 4 missing. A "shim" carries the HAPAX-GATE-SHIM marker and
# resolves to canonical (so it inherits INV-5). A non-shim full gate copy is
# drift; it is CRITICAL when it also lacks is_cognition_path (the stale-lane
# INV-5 violation), else a WARN (drifted but carve-out present).
classify_gate() {
  local f="$1"
  if [[ ! -e "$f" ]]; then echo "missing"; return 4; fi
  if grep -q "$SHIM_MARKER" "$f" 2>/dev/null; then echo "shim"; return 0; fi
  if grep -q "$COGNITION_MARKER" "$f" 2>/dev/null; then echo "drift-warn"; return 2; fi
  echo "drift-critical"; return 3
}

# check_canonical — the deployed impl all shims resolve to must exist, be the impl
# (not a shim), and carry INV-5. Echoes a status line; return 0 ok, 3 critical.
check_canonical() {
  local c="$CANONICAL_DIR/cc-task-gate.sh" s
  if [[ ! -r "$c" ]]; then echo "CRITICAL canonical impl missing: $c"; return 3; fi
  if grep -q "$SHIM_MARKER" "$c" 2>/dev/null; then echo "CRITICAL canonical is a shim, not the impl: $c"; return 3; fi
  if ! grep -q "$COGNITION_MARKER" "$c" 2>/dev/null; then echo "CRITICAL canonical impl lacks INV-5 is_cognition_path: $c"; return 3; fi
  for s in agent-role.sh escape-grant.sh; do
    [[ -r "$CANONICAL_DIR/$s" ]] || { echo "CRITICAL canonical closure missing sibling: $CANONICAL_DIR/$s"; return 3; }
  done
  echo "ok canonical healthy: $c"; return 0
}

# check_repo_self — the committed gate in REPO_ROOT must be a shim, and the impl
# must exist with INV-5. This is the CI regression guard: nobody commits a full
# gate copy back into cc-task-gate.sh. Echoes findings; return 0 ok, 3 critical.
check_repo_self() {
  local rc=0
  local shim="$REPO_ROOT/hooks/scripts/cc-task-gate.sh"
  local impl="$REPO_ROOT/hooks/scripts/cc-task-gate.impl.sh"
  if [[ ! -e "$shim" ]]; then
    echo "CRITICAL $shim missing"; rc=3
  elif ! grep -q "$SHIM_MARKER" "$shim" 2>/dev/null; then
    echo "CRITICAL $shim is NOT a shim (regressed to a physical gate copy)"; rc=3
  fi
  if [[ ! -r "$impl" ]]; then
    echo "CRITICAL $impl missing"; rc=3
  elif ! grep -q "$COGNITION_MARKER" "$impl" 2>/dev/null; then
    echo "CRITICAL $impl lacks INV-5 is_cognition_path"; rc=3
  fi
  return "$rc"
}

# list_lane_worktrees — lane worktrees only (basename hapax-council[--*]); the
# SHA-named source-activation release snapshots and the rebuild/worktree (which
# self-heals on rebuild) are intentionally excluded.
list_lane_worktrees() {
  git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree /{sub(/^worktree /,""); print}' \
    | while IFS= read -r wt; do
        case "$(basename "$wt")" in
          hapax-council|hapax-council--*) printf '%s\n' "$wt" ;;
        esac
      done
}

# check_fleet — classify each lane worktree's gate. Echoes WARN/CRITICAL lines
# (and ok lines when --verbose). Return 0 clean, 2 warn-only, 3 any-critical.
check_fleet() {
  local rc=0 wt gate label crc
  while IFS= read -r wt; do
    [[ -n "$wt" ]] || continue
    gate="$wt/hooks/scripts/cc-task-gate.sh"
    [[ -e "$gate" ]] || continue
    label="$(classify_gate "$gate")"; crc=$?
    case "$crc" in
      0) [[ "$VERBOSE" = 1 ]] && echo "ok       $wt [$label]" ;;
      2) echo "WARN     $wt [$label] — drifted full gate (INV-5 carve-out present)"; (( rc < 2 )) && rc=2 ;;
      3) echo "CRITICAL $wt [$label] — stale full gate WITHOUT INV-5 carve-out"; rc=3 ;;
      4) [[ "$VERBOSE" = 1 ]] && echo "ok       $wt [no gate]" ;;
    esac
  done < <(list_lane_worktrees)
  return "$rc"
}

_notify() {
  [[ "$NOTIFY" = 1 ]] || return 0
  local msg="$1"
  if command -v hapax-notify >/dev/null 2>&1; then
    hapax-notify "hooks-doctor" "$msg" >/dev/null 2>&1 && return 0
  fi
  ( cd "$REPO_ROOT" 2>/dev/null \
    && python3 -c 'import sys
try:
    from shared.notify import send_notification
    send_notification("hooks-doctor: gate drift", sys.argv[1], priority="high", tags=["warning"])
except Exception:
    pass' "$msg" ) >/dev/null 2>&1 || true
}

deploy_canonical() {
  local from="${FROM:-$REPO_ROOT}" src
  src="$from/hooks/scripts"
  if [[ ! -r "$src/cc-task-gate.impl.sh" ]]; then
    echo "deploy: source impl missing: $src/cc-task-gate.impl.sh" >&2
    return 1
  fi
  if ! grep -q "$COGNITION_MARKER" "$src/cc-task-gate.impl.sh" 2>/dev/null; then
    echo "deploy: REFUSING to deploy an impl that lacks INV-5 is_cognition_path: $src/cc-task-gate.impl.sh" >&2
    return 1
  fi
  if [[ "$DRY" = 1 ]]; then
    echo "[dry-run] would deploy gate closure: $src -> $CANONICAL_DIR"
    return 0
  fi
  mkdir -p "$CANONICAL_DIR"
  # impl deploys AS cc-task-gate.sh (the name shims + settings.json resolve to).
  install -m 0755 "$src/cc-task-gate.impl.sh" "$CANONICAL_DIR/cc-task-gate.sh"
  local s
  for s in agent-role.sh escape-grant.sh hooks-doctor.sh; do
    [[ -r "$src/$s" ]] && install -m 0755 "$src/$s" "$CANONICAL_DIR/$s"
  done
  ( cd "$CANONICAL_DIR" && sha256sum cc-task-gate.sh agent-role.sh escape-grant.sh hooks-doctor.sh 2>/dev/null ) \
    > "$CANONICAL_DIR/MANIFEST.sha256" 2>/dev/null || true
  local bindir="${HAPAX_LOCAL_BIN:-$HOME/.local/bin}"
  mkdir -p "$bindir"
  ln -sf "$CANONICAL_DIR/hooks-doctor.sh" "$bindir/hapax-hooks-doctor"
  echo "deployed gate closure -> $CANONICAL_DIR (from $src)"
  check_canonical
}

fanout() {
  local shim_src="$REPO_ROOT/hooks/scripts/cc-task-gate.sh" wt gate n=0
  if ! grep -q "$SHIM_MARKER" "$shim_src" 2>/dev/null; then
    echo "fanout: $shim_src is not the shim; aborting" >&2
    return 1
  fi
  while IFS= read -r wt; do
    [[ -n "$wt" ]] || continue
    gate="$wt/hooks/scripts/cc-task-gate.sh"
    [[ -d "$wt/hooks/scripts" ]] || continue
    if grep -q "$SHIM_MARKER" "$gate" 2>/dev/null; then
      [[ "$VERBOSE" = 1 ]] && echo "skip     $gate (already shim)"
      continue
    fi
    if [[ "$DRY" = 1 ]]; then
      echo "[dry-run] would shim $gate"; n=$((n + 1)); continue
    fi
    install -m 0755 "$shim_src" "$gate"
    echo "shimmed  $gate"
    n=$((n + 1))
  done < <(list_lane_worktrees)
  echo "fanout: $n gate(s) updated$([[ "$DRY" = 1 ]] && echo ' (dry-run)')"
}

case "$MODE" in
  classify)
    classify_gate "$CLASSIFY_FILE"
    exit $?
    ;;
  deploy)
    deploy_canonical
    exit $?
    ;;
  fanout)
    fanout
    exit $?
    ;;
  check)
    rc=0
    if out="$(check_repo_self)"; then :; else rc=3; fi
    [[ -n "${out:-}" ]] && echo "$out"
    if [[ -e "$CANONICAL_DIR/cc-task-gate.sh" ]]; then
      if cout="$(check_canonical)"; then :; else rc=3; fi
      echo "$cout"
    else
      echo "note: no deployed canonical at $CANONICAL_DIR (ok in CI / pre-deploy)"
    fi
    if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
      fout="$(check_fleet)"; fc=$?
      [[ -n "$fout" ]] && echo "$fout"
      (( fc >= 3 )) && rc=3
    fi
    if (( rc >= 3 )); then
      echo "hooks-doctor: CRITICAL gate drift — REFUSE"
      _notify "CRITICAL gate drift detected"
      exit 1
    fi
    echo "hooks-doctor: gate fleet clean (no critical drift)"
    exit 0
    ;;
  session)
    # Advisory: never wedge a session. Print canonical + fleet drift, exit 0.
    crit=0
    if [[ -e "$CANONICAL_DIR/cc-task-gate.sh" ]]; then
      cout="$(check_canonical)" || crit=1
      [[ "$VERBOSE" = 1 || "$crit" = 1 ]] && echo "$cout"
    else
      echo "hooks-doctor: no deployed canonical gate at $CANONICAL_DIR — run 'hapax-hooks-doctor --deploy-canonical'"
      crit=1
    fi
    if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
      fout="$(check_fleet)"; fc=$?
      [[ -n "$fout" ]] && echo "$fout"
      (( fc >= 3 )) && crit=1
    fi
    if (( crit == 1 )); then
      echo "hooks-doctor: gate drift present (advisory) — run 'hapax-hooks-doctor --check' / '--fanout' / '--deploy-canonical'"
      _notify "gate drift present (advisory)"
    fi
    exit 0
    ;;
esac
