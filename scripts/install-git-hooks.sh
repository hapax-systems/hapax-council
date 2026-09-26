#!/usr/bin/env bash
# install-git-hooks.sh — bootstrap the pre-commit and pre-push hooks for this repo.
#
# The pre-commit *framework* (the `pre-commit` CLI) is installed, but the
# per-clone git hooks under the common git directory are NOT version-controlled,
# so they must be installed once per clone. Until then the whole
# .pre-commit-config.yaml (ruff, conflict-markers, claim-registry,
# experiment-freeze, audio-conf gates, ...) never fires at commit and the
# scan-before-push rule never fires at push — only CI catches violations later.
# This script installs both hooks into the same shared directory.
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

if [ ! -f "$REPO_ROOT/scripts/pre-push" ]; then
  echo "ERROR: no scripts/pre-push in $REPO_ROOT" >&2
  echo "Remedy: restore scripts/pre-push in this checkout and re-run scripts/install-git-hooks.sh." >&2
  exit 1
fi

# core.hooksPath replaces Git's entire hook lookup directory, and pre-commit refuses to install
# while it is set. Require one common hook directory so pre-commit and pre-push cannot mask each
# other. The explicit failure also repairs clones configured by the superseded pre-push runbook.
if hooks_path="$(git config --get core.hooksPath)"; then
  echo "ERROR: core.hooksPath is set to '$hooks_path'; it would mask the shared hooks." >&2
  echo "  Clear it and re-run: git config --unset-all core.hooksPath" >&2
  echo "  See docs/runbooks/pre-commit-bootstrap.md." >&2
  exit 1
fi

COMMON_GIT_DIR="$(git rev-parse --path-format=absolute --git-common-dir)"
HOOKS_DIR="$COMMON_GIT_DIR/hooks"

echo "Validating .pre-commit-config.yaml ..."
pre-commit validate-config

echo "Installing git pre-commit hook ..."
pre-commit install --install-hooks

echo "Installing git pre-push hook ..."
install -d "$HOOKS_DIR"
install -m 0755 "$REPO_ROOT/scripts/pre-push" "$HOOKS_DIR/pre-push"

if [ ! -x "$HOOKS_DIR/pre-commit" ] || [ ! -x "$HOOKS_DIR/pre-push" ]; then
  echo "ERROR: hook installation did not produce executable pre-commit and pre-push hooks." >&2
  echo "Remedy: check hook-directory permissions and the pre-commit/install tools, then re-run scripts/install-git-hooks.sh." >&2
  exit 1
fi

echo "Done. pre-commit and pre-push are now active for $REPO_ROOT."
echo "Verify with:  pre-commit run --all-files   (first run is slow; it builds tool envs)"
