#!/usr/bin/env bash
# Shared launcher construction. Resolve identity before claims, auth probes or spawns.
# This helper belongs to the selected source release and uses its pinned runtime.
# Qualified rust-v0.160.1 package archive SHA256:
# 340801565906a7028f6baaa9ab6853addaef221f0016a1417a7c1ffdd96c21f0  # pragma: allowlist secret
# One source contract is transported with both SSH programs; PATH is not authority.
CODEX_PIN_PY='import hashlib,os,pwd,stat,subprocess
def _resolve_codex_bin(hint=""):
    try:
        account_home=pwd.getpwuid(os.getuid()).pw_dir
        if not isinstance(account_home,str) or not os.path.isabs(account_home) or os.path.realpath(account_home) != account_home or not os.path.isdir(account_home):
            raise ValueError("invalid account home")
    except (KeyError,OSError,TypeError,ValueError,AttributeError) as exc:
        return None,"codex_pin_account_home_unavailable:"+type(exc).__name__+"; next action: repair the executing Unix account home binding through governed maintenance"
    path=os.path.join(account_home,".codex/packages/standalone/releases/0.160.1-x86_64-unknown-linux-musl/bin/codex")
    expected="f34a4d2301892ae96c90097786bfe5dc269f187b6f69faf42a7b357b8c081e35"  # pragma: allowlist secret
    remedy="; next action: restore the provenance-qualified Codex 0.160.1 package at "+path+" through governed maintenance"
    try:
        if (hint and hint != path) or os.path.realpath(path) != path:
            return None,"codex_pin_path_mismatch"+remedy
        before=os.stat(path)
        if not stat.S_ISREG(before.st_mode) or not os.access(path,os.X_OK):
            return None,"codex_pin_not_executable"+remedy
        with open(path,"rb") as binary:
            digest=hashlib.file_digest(binary,"sha256").hexdigest()
        if digest != expected:
            return None,"codex_pin_hash_mismatch"+remedy
        result=subprocess.run([path,"--version"],capture_output=True,text=True,timeout=5)
        if result.returncode or result.stdout != "codex-cli 0.160.1\n" or result.stderr:
            return None,"codex_pin_version_mismatch"+remedy
        after=os.stat(path)
        if any(getattr(before,k) != getattr(after,k) for k in ("st_dev","st_ino","st_mode","st_size","st_mtime_ns","st_ctime_ns")):
            return None,"codex_pin_changed_during_check"+remedy
    except (OSError,subprocess.SubprocessError,UnicodeError) as exc:
        return None,"codex_pin_unavailable:"+type(exc).__name__+remedy
    return path,""'

resolve_governed_codex_bin() {
  python3 -c "$CODEX_PIN_PY
import sys
path,error=_resolve_codex_bin(sys.argv[1])
if error:
    print(error,file=sys.stderr)
    sys.exit(78)
print(path)
" "${HAPAX_CODEX_BIN_PATH:-}"
}

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
    -c 'check_for_update_on_startup=false'
    -c "projects.\"$load_home/projects\".trust_level=\"trusted\""
    -c "projects.\"$load_workdir\".trust_level=\"trusted\""
    -c "hooks.SessionStart=[{hooks=[{type=\"command\",command=\"$load_hook\",timeout=20,statusMessage=\"Loading Hapax context\"}]}]"
    -c "hooks.PreToolUse=[{hooks=[{type=\"command\",command=\"$load_hook\",timeout=20,statusMessage=\"Hapax guardrails\"}]}]"
    -c "hooks.PostToolUse=[{hooks=[{type=\"command\",command=\"$load_hook\",timeout=20,statusMessage=\"Hapax audit\"}]}]"
    -c "hooks.Stop=[{hooks=[{type=\"command\",command=\"$load_hook\",timeout=20,statusMessage=\"Writing Hapax session summary\"}]}]"
    -c "mcp_servers.hapax.command=\"$load_home/.local/bin/uv\""
    -c "mcp_servers.hapax.args=[\"--directory\",\"$load_home/projects/hapax-mcp\",\"run\",\"hapax-mcp\"]"
    -c "mcp_servers.hapax.env.LOGOS_BASE_URL=\"$load_logos_url\""
  )
}
