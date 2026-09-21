#!/usr/bin/env bash
# Shared launcher identity binding. Resolve before claims, auth probes or spawns.
# This helper belongs to the selected source release and uses its pinned runtime.
bind_codex_execution() {
  local execution_root execution_python
  execution_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || return 9
  execution_python="$execution_root/.venv/bin/python"
  if [[ ! -x "$execution_python" ]]; then
    echo "refusing invocation without descriptor resolver runtime $execution_python; remedy: use a provisioned council release" >&2
    return 9
  fi
  HAPAX_CODEX_EXECUTION_ARGS="$("$execution_python" -I -c \
    'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("shared.capability_execution",run_name="__main__")' \
    "$execution_root" --route "$EXECUTION_ROUTE" -- "${CODEX_EXTRA[@]}")" || return 9
  export HAPAX_CODEX_EXECUTION_ARGS
  local execution_lines
  execution_lines="$("$execution_python" -I -c '
import json,sys
try:
    args = json.loads(sys.argv[1])
    valid = (
        isinstance(args, list) and len(args) >= 2 and len(args) % 2 == 0
        and args[0] == "-c"
        and all(isinstance(arg, str) and arg and not any(c in arg for c in "\n\r\0") for arg in args)
    )
    if not valid:
        raise ValueError("invalid argument list")
except (ValueError, TypeError):
    sys.exit("refusing malformed descriptor arguments; next action: restore the selected release resolver and retry")
print("\n".join(args))
' "$HAPAX_CODEX_EXECUTION_ARGS")" || return 9
  mapfile -t CODEX_EXECUTION_ARGS <<< "$execution_lines"
}
