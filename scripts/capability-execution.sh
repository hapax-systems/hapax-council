#!/usr/bin/env bash
# Shared launcher identity binding. Resolve before claims, auth probes or spawns.
# This helper belongs to the selected source release and uses its pinned runtime.
bind_codex_execution() {
  local execution_root execution_python
  execution_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || return 9
  execution_python="$execution_root/.venv/bin/python"
  if [[ ! -x "$execution_python" ]]; then
    echo "refusing invocation without the descriptor resolver runtime; remedy: use a provisioned council release" >&2
    return 9
  fi
  HAPAX_CODEX_EXECUTION_ARGS="$(PYTHONPATH="$execution_root${PYTHONPATH:+:$PYTHONPATH}" \
    "$execution_python" -m shared.capability_execution --route "$EXECUTION_ROUTE" -- "${CODEX_EXTRA[@]}")" || return 9
  export HAPAX_CODEX_EXECUTION_ARGS
  local execution_lines
  execution_lines="$("$execution_python" -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "$HAPAX_CODEX_EXECUTION_ARGS")" || return 9
  mapfile -t CODEX_EXECUTION_ARGS <<< "$execution_lines"
}
