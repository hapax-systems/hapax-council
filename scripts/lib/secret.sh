# shellcheck shell=bash
# scripts/lib/secret.sh — the shell half of the estate secret resolver. Never pass.
#
# Operator ruling 2026-09-16, verbatim: "Pass and gopass should never be used going forward
# to manage secrets." `shared/secrets.py` is the Python half; this is the shell half, and the
# two resolve in the same order so a launcher and an agent reading the same name get the same
# value.
#
# Source it, then:
#
#   . "$(dirname "$0")/lib/secret.sh"
#   hapax_secret_into GITHUB_PERSONAL_ACCESS_TOKEN github/personal-access-token || ...
#   token="$(hapax_secret_or_fail tavily/api-key)"
#
# Resolution order, narrowest first, matching the Python resolver:
#   1. the named environment variable, when NON-EMPTY (an exported-but-empty variable is not
#      a value — that is the silent empty-credential bug, where a service starts,
#      authenticates as nobody, and fails far from the cause);
#   2. `hapax-secret <name>`, which reads the FileStore and does its own name mapping, so
#      there is exactly one implementation of `name_of` on every path.
#
# There is no pass path and there must never be one. A helper with a pass fallback is what
# keeps pass installed, and that fallback would be reached exactly when the FileStore is
# having a bad day — the worst moment to widen what a launcher will read.
#
# Values never reach argv, a log line, or an error message. Only NAMES are ever printed.

_hapax_secret_cli() {
  command -v hapax-secret >/dev/null 2>&1
}

# hapax_secret_read NAME
#   Print whatever was stored, trailing newline stripped — INCLUDING an empty value — and
#   return 0. Returns non-zero only when the secret could not be READ at all.
#
#   The distinction matters to callers that report differently for the two cases: "there is
#   no secret here" and "there is one and it is empty" need different operator actions (look
#   for a secret that was never put, versus re-put one that was put wrong). Collapsing them
#   sends an operator to the wrong place; `hapax-glmcp-claude` exits 5 and 6 respectively,
#   and lost that distinction the first time this helper was wired in.
hapax_secret_read() {
  local name="${1:?hapax_secret_read: a secret name is required}"
  local value
  if ! _hapax_secret_cli; then
    return 1
  fi
  # No `local value=$(...)` — that form swallows the exit status into `local`'s own, which
  # would report success for every failed read.
  value="$(hapax-secret "$name" 2>/dev/null)" || return 1
  value="${value%$'\n'}"
  value="${value%$'\r'}"
  printf '%s' "$value"
}

# hapax_secret_get NAME
#   Print the value on stdout, trailing newline stripped. Returns non-zero and prints nothing
#   when the secret is not resolvable here OR is empty — an empty credential is not a usable
#   one, and most callers only ever want a usable value. Callers that need a diagnostic use
#   the _or_fail form; this one stays quiet so it composes inside `||` chains. Callers that
#   must tell empty from absent use `hapax_secret_read`.
hapax_secret_get() {
  local name="${1:?hapax_secret_get: a secret name is required}"
  local value
  value="$(hapax_secret_read "$name")" || return 1
  [ -n "$value" ] || return 1
  printf '%s' "$value"
}

# hapax_secret_or_fail NAME [ENV_VAR]
#   Print the value, or exit 2 with a named next action. ENV_VAR, when given, is consulted
#   first and must be non-empty to count.
hapax_secret_or_fail() {
  local name="${1:?hapax_secret_or_fail: a secret name is required}"
  local env_name="${2:-}"
  local value
  if [ -n "$env_name" ] && [ -n "${!env_name:-}" ]; then
    printf '%s' "${!env_name}"
    return 0
  fi
  if value="$(hapax_secret_get "$name")"; then
    printf '%s' "$value"
    return 0
  fi
  if ! _hapax_secret_cli; then
    echo "${0##*/}: hapax-secret is not on PATH; cannot resolve '${name}'." \
         "Next action: install the reins CLI on this host, or export ${env_name:-the variable}." >&2
    exit 2
  fi
  echo "${0##*/}: secret unavailable: ${name}." \
       "Next action: put it with \`hapax-secret\` (TTY dialogue via reins)${env_name:+, or export ${env_name}}." >&2
  exit 2
}

# hapax_secret_into ENV_VAR NAME [NAME...]
#   Export ENV_VAR from the first NAME that resolves. Already-set non-empty ENV_VAR wins and
#   no store read happens. Returns non-zero if nothing resolved, so callers keep their own
#   `|| fallback || exit` chains — this replaces `load_first_available_pass_secret` exactly,
#   minus pass.
hapax_secret_into() {
  local env_name="${1:?hapax_secret_into: an environment variable name is required}"
  shift
  [ -n "${!env_name:-}" ] && return 0
  local name value
  for name in "$@"; do
    if value="$(hapax_secret_get "$name")"; then
      export "${env_name}=${value}"
      return 0
    fi
  done
  return 1
}
