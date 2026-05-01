#!/usr/bin/env bash
# run-with-test-substrate.sh — capture a long test/build run into a durable
# substrate directory so session handoffs can cite a path instead of fragile
# scrollback or terminal copy-paste.
#
# Per cc-task full-test-output-substrate. The substrate layout is:
#
#   ~/.cache/hapax/relay/test-runs/<iso-timestamp>-<short-cwd>/
#     cmd                  # the exact command line
#     cwd                  # absolute working directory
#     git_head             # `git rev-parse HEAD` if in a git tree
#     git_branch           # `git rev-parse --abbrev-ref HEAD`
#     git_dirty.txt        # `git status --short` snapshot (empty if clean)
#     stdout.log           # captured stdout
#     stderr.log           # captured stderr
#     exit_code            # numeric exit code
#     start_time           # ISO 8601 UTC
#     end_time             # ISO 8601 UTC
#     pytest_lastfailed    # `.pytest_cache/v/cache/lastfailed` snapshot if present
#     env.txt              # filtered env vars (HAPAX_*, CLAUDE_*, USER, HOME, PATH, PWD)
#
# Usage:
#   scripts/run-with-test-substrate.sh -- <cmd> [args...]
#   scripts/run-with-test-substrate.sh --label <slug> -- <cmd> [args...]
#
# The optional --label appends a kebab-case slug to the directory name
# so a session can find its own runs quickly:
#   ~/.cache/hapax/relay/test-runs/20260501T050000Z-hapax-council-pre-merge-pr1952/
#
# Exit code: the wrapper exits with the wrapped command's exit code so it
# is drop-in safe in CI / subagent contexts.

set -uo pipefail

LABEL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --label)
            LABEL="${2:-}"
            shift 2
            ;;
        --label=*)
            LABEL="${1#--label=}"
            shift
            ;;
        --help|-h)
            sed -n '2,/^# Exit code/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

if [ $# -eq 0 ]; then
    echo "run-with-test-substrate: no command given" >&2
    echo "usage: $0 [--label SLUG] -- <cmd> [args...]" >&2
    exit 2
fi

substrate_root="${HAPAX_TEST_SUBSTRATE_ROOT:-$HOME/.cache/hapax/relay/test-runs}"
mkdir -p "$substrate_root"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
cwd_short="$(basename "$PWD")"

dir_name="${ts}-${cwd_short}"
[ -n "$LABEL" ] && dir_name="${dir_name}-${LABEL}"

run_dir="${substrate_root}/${dir_name}"
mkdir -p "$run_dir"

# Capture invariants up-front so we always have them, even if the wrapped
# command crashes mid-execution or the wrapper itself is killed.
printf '%s\n' "$@" > "$run_dir/cmd"
printf '%s\n' "$PWD" > "$run_dir/cwd"

if git -C "$PWD" rev-parse --git-dir >/dev/null 2>&1; then
    git -C "$PWD" rev-parse HEAD > "$run_dir/git_head" 2>/dev/null || true
    git -C "$PWD" rev-parse --abbrev-ref HEAD > "$run_dir/git_branch" 2>/dev/null || true
    git -C "$PWD" status --short > "$run_dir/git_dirty.txt" 2>/dev/null || true
fi

env | grep -E '^(HAPAX_|CLAUDE_|USER=|HOME=|PATH=|PWD=)' > "$run_dir/env.txt" 2>/dev/null || true

date -u +%Y-%m-%dT%H:%M:%SZ > "$run_dir/start_time"

set +e
"$@" > "$run_dir/stdout.log" 2> "$run_dir/stderr.log"
rc=$?
set -e

date -u +%Y-%m-%dT%H:%M:%SZ > "$run_dir/end_time"
printf '%d\n' "$rc" > "$run_dir/exit_code"

# Snapshot pytest's lastfailed cache if present — captures which tests are
# currently failing so a follow-up session can re-run just them.
if [ -f "$PWD/.pytest_cache/v/cache/lastfailed" ]; then
    cp "$PWD/.pytest_cache/v/cache/lastfailed" "$run_dir/pytest_lastfailed" 2>/dev/null || true
fi

# Tee a one-liner summary on stderr so a human / parent agent can spot the
# substrate path without parsing JSON.
{
    echo
    echo "[run-with-test-substrate] exit=${rc} substrate=${run_dir}"
} >&2

exit "$rc"
