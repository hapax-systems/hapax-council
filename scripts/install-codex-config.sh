#!/usr/bin/env bash
# Install the Hapax Codex config into CODEX_HOME without embedding secrets.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_COUNCIL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
SOURCE_CONFIG="${1:-$DEFAULT_COUNCIL_DIR/config/codex/config.toml}"
TARGET_CONFIG="$CODEX_HOME_DIR/config.toml"
PROJECT_CODEX="$HOME/projects/.codex"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
COUNCIL_DIR="${HAPAX_COUNCIL_DIR:-$(cd "$(dirname "$SOURCE_CONFIG")/../.." && pwd)}"
PROJECTS_DIR="${HAPAX_PROJECTS_DIR:-$HOME/projects}"
MCP_DIR="${HAPAX_MCP_DIR:-$HOME/projects/hapax-mcp}"

sed_replacement_escape() {
  printf '%s' "$1" | sed -e 's/[\\&#]/\\&/g'
}

if [ ! -f "$SOURCE_CONFIG" ]; then
  echo "install-codex-config: source config missing: $SOURCE_CONFIG" >&2
  exit 2
fi

mkdir -p "$CODEX_HOME_DIR"

if [ -e "$PROJECT_CODEX" ] && [ ! -d "$PROJECT_CODEX" ]; then
  mv "$PROJECT_CODEX" "$PROJECT_CODEX.file-backup-$STAMP"
  mkdir -p "$PROJECT_CODEX"
  echo "install-codex-config: replaced file $PROJECT_CODEX with directory; backup has .file-backup-$STAMP suffix"
fi

if [ -f "$TARGET_CONFIG" ]; then
  cp "$TARGET_CONFIG" "$TARGET_CONFIG.backup-$STAMP"
fi

tmp_config="$(mktemp)"
trap 'rm -f "$tmp_config"' EXIT

sed \
  -e "s#__HAPAX_HOME__#$(sed_replacement_escape "$HOME")#g" \
  -e "s#__HAPAX_PROJECTS__#$(sed_replacement_escape "$PROJECTS_DIR")#g" \
  -e "s#__HAPAX_COUNCIL_DIR__#$(sed_replacement_escape "$COUNCIL_DIR")#g" \
  -e "s#__HAPAX_MCP_DIR__#$(sed_replacement_escape "$MCP_DIR")#g" \
  "$SOURCE_CONFIG" >"$tmp_config"

install -m 0600 "$tmp_config" "$TARGET_CONFIG"

echo "install-codex-config: wrote $TARGET_CONFIG"
echo "Use hapax-codex --session cx-red --slot alpha|beta|delta|epsilon for no-ask, role-aware launches."
echo "Non-primary Codex sessions default to ~/projects/hapax-council--cx-<color> worktrees."
