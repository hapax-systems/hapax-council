#!/usr/bin/env bash
set -euo pipefail

# Retention-only install boundary. Live activation requires its separate seat ruling.
# Hooks and plugin registration are owned elsewhere; never merge legacy hooks here.
usage() {
  echo "Usage: install-claude-code.sh --config-dir EXISTING_CLAUDE_PROFILE"
  echo "Set only cleanupPeriodDays=3650 in an existing settings.json. No default profile."
}

fail() {
  echo "install-claude-code: $*" >&2
  exit 1
}

config_dir=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-dir)
      [[ $# -ge 2 && -n "$2" && -z "$config_dir" ]] || fail "provide --config-dir exactly once with an existing directory"
      config_dir="$2"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown argument: $1; use --config-dir EXISTING_CLAUDE_PROFILE" ;;
  esac
done
[[ -n "$config_dir" && -d "$config_dir" ]] || fail "an explicit existing --config-dir is required"
config_dir="$(realpath -e -- "$config_dir")"
settings="$config_dir/settings.json"
[[ -f "$settings" && ! -L "$settings" ]] || fail "settings.json must already be a regular file, not a symlink"

# Include identity, mode and nanosecond timestamps as well as bytes: a replaced
# file or chmod during preparation also invalidates the captured preimage.
fingerprint() {
  [[ -f "$settings" && ! -L "$settings" ]] || return 1
  stat -c '%d:%i:%f:%u:%g:%s:%y:%z' -- "$settings" || return 1
  sha256sum -- "$settings"
}
preimage="$(fingerprint)" || fail "cannot read settings preimage"
mode="$(stat -c '%a' -- "$settings")"
temporary="$(mktemp -- "$config_dir/.settings.json.XXXXXXXX")"
trap 'rm -f -- "$temporary"' EXIT

# Slurp also rejects multiple top-level JSON documents. Only this one key is
# authorized; all remote-control, hooks, permissions and other settings survive.
jq -s '
  if length != 1 or (.[0] | type) != "object"
  then error("settings.json must contain exactly one JSON object")
  else .[0] | .cleanupPeriodDays = 3650
  end
' "$settings" > "$temporary" || fail "invalid settings JSON; original preserved"
jq -e 'type == "object" and .cleanupPeriodDays == 3650' "$temporary" > /dev/null \
  || fail "invalid prepared settings; original preserved"
chmod "$mode" "$temporary"

already_set=false
if jq -e '.cleanupPeriodDays == 3650' "$settings" > /dev/null; then
  already_set=true
fi
current="$(fingerprint)" || fail "settings changed during preparation; retry after the writer finishes"
[[ "$current" == "$preimage" ]] || fail "settings changed during preparation; original preserved, retry after the writer finishes"
if [[ "$already_set" == true ]]; then
  echo "Retention already set; settings unchanged: $settings"
  exit 0
fi

# One same-directory rename publishes a validated, mode-preserving postimage.
mv -f -- "$temporary" "$settings"
echo "Retention set to 3650 days: $settings"
