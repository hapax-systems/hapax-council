#!/usr/bin/env bash
# install-git-hooks.sh — bootstrap the pre-commit framework for this repo.
#
# The pre-commit *framework* (the `pre-commit` CLI) is installed, but the
# per-clone git hook at .git/hooks/pre-commit is NOT version-controlled, so
# it must be installed once per clone/worktree. Until then the whole
# .pre-commit-config.yaml (ruff, conflict-markers, claim-registry,
# experiment-freeze, audio-conf gates, ...) never fires at commit — only
# CI catches violations, minutes later. This script closes that gap.
#
# Usage:  scripts/install-git-hooks.sh
# Safe to re-run (idempotent).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v pre-commit >/dev/null 2>&1; then
  echo "ERROR: pre-commit is not on PATH." >&2
  echo "  Install it first:  uv tool install pre-commit   (or pipx install pre-commit)" >&2
  exit 1
fi

if [ ! -f "$REPO_ROOT/.pre-commit-config.yaml" ]; then
  echo "ERROR: no .pre-commit-config.yaml in $REPO_ROOT" >&2
  exit 1
fi

# pre-commit refuses to install while core.hooksPath is set. Some council
# clones set it (redundantly) to the default .git/hooks; surface this
# rather than failing opaquely.
hooks_path="$(git config --get core.hooksPath || true)"
if [ -n "$hooks_path" ]; then
  echo "NOTE: core.hooksPath is set to '$hooks_path'." >&2
  echo "      pre-commit may refuse to install. If so, clear it and re-run:" >&2
  echo "        git config --unset core.hooksPath" >&2
  echo "      See docs/runbooks/pre-commit-bootstrap.md." >&2
fi

echo "Validating .pre-commit-config.yaml ..."
pre-commit validate-config

echo "Installing git pre-commit hook ..."
pre-commit install --install-hooks

echo "Done. pre-commit is now active for $REPO_ROOT."
echo "Verify with:  pre-commit run --all-files   (first run is slow; it builds tool envs)"
