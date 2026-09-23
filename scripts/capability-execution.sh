#!/usr/bin/env bash
# Shared launcher construction. Resolve identity before claims, auth probes or spawns.
# This helper belongs to the selected source release and uses its pinned runtime.
bind_codex_execution() {
  local execution_root execution_python
  execution_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || return 9
  execution_python="$execution_root/.venv/bin/python"
  if [[ ! -x "$execution_python" ]]; then
    echo "refusing invocation without descriptor resolver runtime $execution_python; remedy: use a provisioned council release" >&2
    return 9
  fi
  local execution_binding
  local -a execution_fields
  execution_binding="$("$execution_python" -I -c \
    'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("shared.capability_execution",run_name="__main__")' \
    "$execution_root" --with-descriptor --route "$EXECUTION_ROUTE" -- "${CODEX_EXTRA[@]}")" || return 9
  local execution_lines
  execution_lines="$("$execution_python" -I -c '
import json,sys
try:
    binding = json.loads(sys.argv[1])
    args = binding["argv"]
    descriptor = binding["descriptor"]
    valid = (
        isinstance(args, list) and len(args) == 4 and args[::2] == ["-c", "-c"]
        and all(isinstance(arg, str) and arg and not any(c in arg for c in "\n\r\0") for arg in args)
    )
    if not valid:
        raise ValueError("invalid argument list")
    values = {key: json.loads(value) for key, value in (arg.split("=", 1) for arg in args[1::2])}
    if not all(
        isinstance(value, str) and value for value in values.values()
    ):
        raise ValueError("missing concrete identity arguments")
    if not isinstance(descriptor, dict) or descriptor.get("model_id") != values["model"] or descriptor.get("effort") != values["model_reasoning_effort"]:
        raise ValueError("descriptor and invocation disagree")
except (ValueError, TypeError, KeyError):
    sys.exit("refusing malformed descriptor arguments; next action: restore the selected release resolver and retry")
print(json.dumps(args))
print(json.dumps(descriptor))
print("\n".join(args))
' "$execution_binding")" || return 9
  mapfile -t execution_fields <<< "$execution_lines"
  export HAPAX_CODEX_EXECUTION_ARGS="${execution_fields[0]}"
  export HAPAX_CODEX_EXECUTION_DESCRIPTOR="${execution_fields[1]}"
  CODEX_EXECUTION_ARGS=("${execution_fields[@]:2}")
}

# Common native configuration; mode-specific tools and invocation flags stay at callers.
bind_codex_common_config() {
  local load_home="$1" load_workdir="$2" load_hook="$3" load_logos_url="$4"
  CODEX_COMMON_CONFIG_ARGS=(
    -c 'approval_policy="never"'
    -c 'sandbox_mode="danger-full-access"'
    -c "projects.\"$load_home/projects\".trust_level=\"trusted\""
    -c "projects.\"$load_workdir\".trust_level=\"trusted\""
    -c "hooks.SessionStart=[{command=\"$load_hook\",timeout=20,statusMessage=\"Loading Hapax context\"}]"
    -c "hooks.PreToolUse=[{command=\"$load_hook\",timeout=20,include_apply_patch_tool=true,statusMessage=\"Hapax guardrails\"}]"
    -c "hooks.PostToolUse=[{command=\"$load_hook\",timeout=20,include_apply_patch_tool=true,statusMessage=\"Hapax audit\"}]"
    -c "hooks.Stop=[{command=\"$load_hook\",timeout=20,statusMessage=\"Writing Hapax session summary\"}]"
    -c "mcp_servers.hapax.command=\"$load_home/.local/bin/uv\""
    -c "mcp_servers.hapax.args=[\"--directory\",\"$load_home/projects/hapax-mcp\",\"run\",\"hapax-mcp\"]"
    -c "mcp_servers.hapax.env.LOGOS_BASE_URL=\"$load_logos_url\""
  )
}
