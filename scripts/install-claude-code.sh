#!/usr/bin/env bash
set -euo pipefail

# hapax-system install — uses native Claude Code directories (commands, hooks, rules, agents)
# The hapax-system repo stays the source of truth. This script creates symlinks.

PLUGIN_SRC="$(cd "$(dirname "$0")" && pwd)"
COMMANDS_DIR="$HOME/.claude/commands"
AGENTS_DIR="$HOME/.claude/agents"
RULES_DIR="$HOME/.claude/rules"
INSTALLED_PLUGINS="$HOME/.claude/plugins/installed_plugins.json"
SETTINGS="$HOME/.claude/settings.json"

echo "Installing hapax-system (native directories)..."

# 1. Skills → ~/.claude/commands/<name>.md (symlinks)
mkdir -p "$COMMANDS_DIR"
for skill_dir in "$PLUGIN_SRC/skills/"*/; do
  if [ -d "$skill_dir" ]; then
    SKILL_NAME="$(basename "$skill_dir")"
    SKILL_FILE="${skill_dir}SKILL.md"
    TARGET="$COMMANDS_DIR/$SKILL_NAME.md"
    if [ -f "$SKILL_FILE" ]; then
      [ -L "$TARGET" ] && rm "$TARGET"
      [ -f "$TARGET" ] && { echo "  SKIP: $TARGET exists (not a symlink). Remove it first."; continue; }
      ln -s "$SKILL_FILE" "$TARGET"
      echo "  Skill: /$SKILL_NAME -> $SKILL_FILE"
    fi
  fi
done

# 2. Agents → ~/.claude/agents/<name>.md (symlinks)
mkdir -p "$AGENTS_DIR"
for agent_file in "$PLUGIN_SRC/agents/"*.md; do
  if [ -f "$agent_file" ]; then
    BASENAME="$(basename "$agent_file")"
    TARGET="$AGENTS_DIR/$BASENAME"
    [ -L "$TARGET" ] && rm "$TARGET"
    [ -f "$TARGET" ] && { echo "  SKIP: $TARGET exists (not a symlink). Remove it first."; continue; }
    ln -s "$agent_file" "$TARGET"
    echo "  Agent: $BASENAME -> $agent_file"
  fi
done

# 3. Rules → ~/.claude/rules/hapax-<name>.md (symlinks, same as before)
mkdir -p "$RULES_DIR"
for rule_file in "$PLUGIN_SRC/rules/"*.md; do
  if [ -f "$rule_file" ]; then
    BASENAME="$(basename "$rule_file")"
    TARGET="$RULES_DIR/hapax-$BASENAME"
    [ -L "$TARGET" ] && rm "$TARGET"
    ln -s "$rule_file" "$TARGET"
    echo "  Rule: hapax-$BASENAME -> $rule_file"
  fi
done

# 4. Hooks → merge into ~/.claude/settings.json (correct Claude Code location)
# Claude Code reads hooks from settings.json, not a separate hooks.json.
# Format: nested {"matcher": "...", "hooks": [{"type": "command", "command": "..."}]}
# All hook commands point to absolute paths in hapax-system repo.
# This enables clean uninstall by filtering on the repo path.
if [ ! -f "$SETTINGS" ]; then
  echo '{}' > "$SETTINGS"
elif ! jq . "$SETTINGS" > /dev/null 2>&1; then
  echo "  ERROR: $SETTINGS is not valid JSON. Fix it before installing."
  exit 1
fi

# Build hapax hook entries as JSON (nested format for Claude Code)
HAPAX_HOOKS=$(cat <<HEREDOC
{
  "SessionStart": [
    {"hooks": [{"type": "command", "command": "$PLUGIN_SRC/hooks/scripts/session-context.sh"}]}
  ],
  "PreToolUse": [
    {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "$PLUGIN_SRC/hooks/scripts/axiom-scan.sh"}]},
    {"matcher": "Bash", "hooks": [{"type": "command", "command": "$PLUGIN_SRC/hooks/scripts/axiom-commit-scan.sh"}]}
  ],
  "PostToolUse": [
    {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "$PLUGIN_SRC/hooks/scripts/axiom-audit.sh"}]}
  ],
  "Stop": [
    {"hooks": [{"type": "command", "command": "$PLUGIN_SRC/hooks/scripts/session-summary.sh"}]}
  ]
}
HEREDOC
)

# Merge: for each event type, remove existing hapax entries (idempotent re-install).
# Filter by checking nested hooks[].command for our repo path.
jq --arg path "$PLUGIN_SRC" '
  .hooks //= {} |
  .hooks |= with_entries(
    .value |= map(select(
      (.hooks // []) | all(.command | contains($path) | not)
    ))
  )
' "$SETTINGS" > "${SETTINGS}.tmp" && mv "${SETTINGS}.tmp" "$SETTINGS"

# Now add hapax entries
jq --argjson hapax "$HAPAX_HOOKS" '
  .hooks //= {} |
  reduce ($hapax | to_entries[]) as $entry (
    .;
    .hooks[$entry.key] = ((.hooks[$entry.key] // []) + $entry.value)
  )
' "$SETTINGS" > "${SETTINGS}.tmp" && mv "${SETTINGS}.tmp" "$SETTINGS"

echo "  Hooks: merged into $SETTINGS"

# Clean up obsolete hooks.json if it exists
OLD_HOOKS="$HOME/.claude/hooks.json"
if [ -f "$OLD_HOOKS" ]; then
  rm "$OLD_HOOKS"
  echo "  Cleaned up obsolete $OLD_HOOKS"
fi

# 5. Clean up old plugin registration (from failed cache approach)
if [ -f "$INSTALLED_PLUGINS" ]; then
  if jq -e '.plugins["hapax-system@hapax-local"]' "$INSTALLED_PLUGINS" > /dev/null 2>&1; then
    jq 'del(.plugins["hapax-system@hapax-local"])' "$INSTALLED_PLUGINS" > "${INSTALLED_PLUGINS}.tmp" \
      && mv "${INSTALLED_PLUGINS}.tmp" "$INSTALLED_PLUGINS"
    echo "  Cleaned up old plugin registration"
  fi
fi

if [ -f "$SETTINGS" ]; then
  if jq -e '.enabledPlugins["hapax-system@hapax-local"]' "$SETTINGS" > /dev/null 2>&1; then
    jq 'del(.enabledPlugins["hapax-system@hapax-local"])' "$SETTINGS" > "${SETTINGS}.tmp" \
      && mv "${SETTINGS}.tmp" "$SETTINGS"
    echo "  Cleaned up old plugin settings"
  fi
fi

# Clean up old cache directory if it exists
rm -rf "$HOME/.claude/plugins/cache/hapax-local" 2>/dev/null || true

echo ""
echo "Installed. Restart Claude Code to activate."
echo "Verify: /status, /briefing, /axiom-check should be available as slash commands."
