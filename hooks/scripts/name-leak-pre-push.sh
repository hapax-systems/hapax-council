#!/bin/bash
# Pre-push gate: block a push that introduces an operator legal name or a registered
# principal given name into tracked files. This is the BLOCKING --diff half of the
# household-name guard (seat ruling 2026-10-04, #5024 re-round): it runs against the
# LOCAL principal-name registry, which every estate lane has, so it covers every push.
#
# Names are NEVER sent to a third party: there is no name registry in CI secrets. The
# CI step (.github/workflows/household-name-leak-guard.yml) SKIPS with an explicit
# reason when no local registry is present, by design. The repo-wide --all mode is an
# audit tool for the legacy-corpus scrub, not a push gate (the existing corpus would
# block every push).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# pre-commit's pre-push stage supplies the remote and local refs; fall back to the
# merge-base with origin/main for a new branch or a direct invocation.
base="${PRE_COMMIT_FROM_REF:-}"
head="${PRE_COMMIT_TO_REF:-HEAD}"
zero="0000000000000000000000000000000000000000"
if [ -z "$base" ] || [ "$base" = "$zero" ]; then
    base="$(git merge-base origin/main HEAD 2>/dev/null || true)"
fi
if [ -n "$base" ]; then
    range="${base}..${head}"
else
    # No comparable base (first commit / no origin/main): diff against the empty tree
    # so nothing new escapes.
    range="$(git hash-object -t tree /dev/null)..${head}"
fi

exec scripts/check-legal-name-leaks.sh --diff "$range"
