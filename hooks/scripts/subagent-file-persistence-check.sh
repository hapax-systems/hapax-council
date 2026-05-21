#!/usr/bin/env bash
# subagent-file-persistence-check.sh — PostToolUse hook for Agent tool.
#
# After a subagent completes, extracts file paths mentioned in its result
# text and stat()-checks each one exists and is non-empty. Logs missing
# files to ~/.claude/work-loss.log.
#
# Advisory (exit 0) — warns on stderr without blocking.

set -euo pipefail

LOSS_LOG="${HOME}/.claude/work-loss.log"
INPUT="$(cat)"

TOOL="$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_name', ''))
except: print('')
" 2>/dev/null || true)"

[ "$TOOL" = "Agent" ] || exit 0

RESULT="$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_result', d.get('output', '')))
except: print('')
" 2>/dev/null || true)"

[ -n "$RESULT" ] || exit 0

FILES="$(printf '%s' "$RESULT" | python3 -c "
import re, sys
text = sys.stdin.read()
paths = set()
exts = r'\.(?:py|sh|md|yaml|yml|json|toml|rs|tsx?|jsx?|css|html|wgsl|conf)'
for pattern in [
    r'(?:wrote|created|modified|edited|saved|added)\s+[\"'\'']*(/[^\s\"'\'']+' + exts + r')',
    r'(?:File|Written|Created|New file):\s*[\"'\'']*(/[^\s\"'\'']+' + exts + r')',
    r'create mode \d+ (\S+' + exts + r')',
]:
    for m in re.finditer(pattern, text, re.IGNORECASE):
        p = m.group(1)
        if not p.startswith('/tmp') and not p.startswith('/dev'):
            paths.add(p)
for p in sorted(paths):
    print(p)
" 2>/dev/null || true)"

[ -n "$FILES" ] || exit 0

missing=0
while IFS= read -r fpath; do
    [ -z "$fpath" ] && continue
    if [ ! -f "$fpath" ]; then
        echo "subagent-file-persistence: MISSING: $fpath" >&2
        echo "$(date -Iseconds) MISSING $fpath tool=Agent" >> "$LOSS_LOG" 2>/dev/null || true
        missing=$((missing + 1))
    elif [ ! -s "$fpath" ]; then
        echo "subagent-file-persistence: EMPTY: $fpath" >&2
        echo "$(date -Iseconds) EMPTY $fpath tool=Agent" >> "$LOSS_LOG" 2>/dev/null || true
        missing=$((missing + 1))
    fi
done <<< "$FILES"

if [ "$missing" -gt 0 ]; then
    echo "subagent-file-persistence: WARNING: $missing file(s) missing/empty after subagent" >&2
fi

exit 0
