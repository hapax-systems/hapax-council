#!/usr/bin/env bash
# unguarded-cd-guard.sh — block Bash commands where a bare `cd` failure would
# let subsequent commands run in the WRONG DIRECTORY.
#
# Class history (2026-06-11, twice in one session): a failed `cd` inside a
# compound command ran `git add -A && git commit` in the booby-trapped primary
# tree (recovered via reset --soft), then ran greps in the wrong tree an hour
# later despite a prose rule in memory. Prose is not a mechanism; this is.
#
# BLOCKS: `cd <path>` separated from following commands by `;` or newline,
# without failure-guarding, in a multi-command invocation.
# ALLOWS: `set -e` prefix · `cd X && ...` · `cd X || exit/return/continue` ·
# single-command cd · `git -C` / `make -C` styles (no cd at all).
set -euo pipefail
payload="$(cat)"
cmd="$(HOOK_PAYLOAD="$payload" python3 -c '
import json, os
try:
    print(json.loads(os.environ["HOOK_PAYLOAD"]).get("tool_input",{}).get("command",""))
except Exception:
    pass
')"
[ -z "$cmd" ] && exit 0
# fast allow: set -e discipline covers the whole block
first_line="$(printf '%s' "$cmd" | sed -n '1p')"
case "$first_line" in
  *"set -e"*) exit 0 ;;
esac
python3 - "$cmd" <<'PY'
import re, sys
cmd = sys.argv[1]
# strip quoted strings & heredoc bodies crudely to avoid false hits inside text
stripped = re.sub(r"<<-?'?\"?(\w+)'?\"?.*?\n\1\b", "", cmd, flags=re.S)
stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "", stripped)
lines = re.split(r"[;\n]", stripped)
n = len([l for l in lines if l.strip()])
if n < 2:
    sys.exit(0)
for i, line in enumerate(lines):
    s = line.strip()
    m = re.match(r"(?:builtin\s+)?cd\s+\S+", s)
    if not m:
        continue
    rest = s[m.end():].lstrip()
    # guarded forms on the same statement
    if rest.startswith("&&") or rest.startswith("||"):
        continue
    # cd is the FINAL statement -> nothing runs after a failure
    remaining = [l for l in lines[i+1:] if l.strip()]
    if not remaining:
        continue
    print(
        "BLOCKED: unguarded `cd` in a multi-command invocation — a cd failure "
        "would run the remaining commands in the WRONG directory (2026-06-11 "
        "primary-tree incident class).\n"
        f"  offending: {s[:90]}\n"
        "  use one of: `set -e` as the first line · `cd X && { ... }` · "
        "`cd X || exit 1` · `git -C <path>`",
        file=sys.stderr,
    )
    sys.exit(2)
sys.exit(0)
PY
