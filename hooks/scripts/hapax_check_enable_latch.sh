#!/usr/bin/env bash
# hapax_check_enable_latch.sh — shared governed enable-latch check (capability-adapter glue).
#
# Sourced by interactive worker launchers (scripts/hapax-antigrav) so they honor the same
# DEFAULT_DENY_ENABLE_LATCH posture as the headless launchers (hapax-claude-headless /
# hapax-codex-headless, which use ENABLE_FILE/DISABLE_FILE/headless_allowed): a runtime may launch
# only when explicitly enabled, and never when explicitly disabled.
#
#   hapax_check_enable_latch <runtime>
#
# Returns 0 (launch allowed) / 1 (refused; reason on stderr). For <runtime> it reads, with env
# overrides keyed by the upper-cased runtime (hyphens -> underscores):
#   disable file: $HOME/.cache/hapax/disable-<runtime>   (override HAPAX_<RUNTIME>_DISABLE_FILE)
#   enable  file: $HOME/.cache/hapax/enable-<runtime>     (override HAPAX_<RUNTIME>_ENABLE_FILE)
#   bypass  env:  HAPAX_<RUNTIME>_ALLOW=1
#
# Semantics (FAIL-CLOSED, mirrors hapax-claude-headless headless_allowed): a present disable file
# refuses unconditionally; otherwise launch is allowed iff (ALLOW=1 OR the enable file exists);
# otherwise refused (default-deny). The deploy step seeds the enable file once so the live lane is
# not bricked — the posture is default-deny but the rollout is enable-present.

hapax_check_enable_latch() {
  local runtime="$1"
  local upper disable_var enable_var allow_var disable_file enable_file allow
  upper="$(printf '%s' "$runtime" | tr '[:lower:]-' '[:upper:]_')"
  disable_var="HAPAX_${upper}_DISABLE_FILE"
  enable_var="HAPAX_${upper}_ENABLE_FILE"
  allow_var="HAPAX_${upper}_ALLOW"
  disable_file="${!disable_var:-$HOME/.cache/hapax/disable-$runtime}"
  enable_file="${!enable_var:-$HOME/.cache/hapax/enable-$runtime}"
  allow="${!allow_var:-}"

  if [ -e "$disable_file" ]; then
    echo "hapax-enable-latch: $runtime refused — disable latch present ($disable_file)" >&2
    return 1
  fi
  if [ "$allow" = "1" ] || [ -e "$enable_file" ]; then
    return 0
  fi
  echo "hapax-enable-latch: $runtime refused — governed enable-latch absent (create $enable_file or set ${allow_var}=1)" >&2
  return 1
}
