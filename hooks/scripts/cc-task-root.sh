# shellcheck shell=bash
# The cc-task root, for shell consumers. Mirrors shared/cc_task_root.py exactly.
#
# The hook gates (work-resolution-gate, pr-release-gate, cc-task-pr-link, session-context) each
# rebuild the vault path from a literal today. They cannot import Python cheaply — a hook runs on
# every tool event and an interpreter start per event is not free — so the rules live twice.
#
# Two implementations of one rule is a hazard, and the mitigation is a test that runs both and
# compares (tests/hooks/test_cc_task_root_sh.py). Without that pin the failure mode is not a crash
# but a SPLIT SSOT: the gate consults one vault while the writer updates another, both succeed,
# and nothing anywhere reports a disagreement.
#
# Sourced, not executed: it defines a variable in its caller's scope and has no shebang.
#
# Usage:
#   . "$(dirname "$0")/cc-task-root.sh"   # sets CC_TASK_ROOT, or exits 2 with a next action

cc_task_root_resolve() {
  local override personal
  override="${HAPAX_CC_TASKS_ROOT:-}"
  # Trim surrounding whitespace, so a stray space in a unit file is not a different path.
  override="${override#"${override%%[![:space:]]*}"}"
  override="${override%"${override##*[![:space:]]}"}"
  # TILDE EXPANSION IS NOT AUTOMATIC INSIDE A VARIABLE. Python's `expanduser` turns `~/tasks`
  # into an absolute path; the shell leaves it literal, so `-d` fails on a root that exists and
  # the two resolvers disagree about the SSOT. Expanded here so both sides mean the same thing.
  case "$override" in
    "~") override="$HOME" ;;
    "~/"*) override="$HOME/${override#\~/}" ;;
  esac

  if [ -n "$override" ]; then
    # Precedence, not fallback. An override that names nothing usable REFUSES; resolving to the
    # vault default here would write cc-tasks into a different SSOT than the operator configured,
    # and every write would succeed.
    if [ ! -d "$override" ]; then
      echo "cc-task-root: HAPAX_CC_TASKS_ROOT names ${override}, which is not a directory. Refusing rather than falling back to the vault default. Next: create ${override}, or unset HAPAX_CC_TASKS_ROOT to use the personal vault" >&2
      return 2
    fi
    CC_TASK_ROOT="$override"
    CC_TASK_ROOT_SOURCE="override"
    CC_TASK_ROOT_EXISTS=1
    return 0
  fi

  # `:-` already treats set-but-empty as unset, which is the behaviour both sides now share --
  # Python previously returned "" here and built a RELATIVE path while the shell used $HOME.
  personal="${PERSONAL_VAULT_PATH:-$HOME/Documents/Personal}"
  personal="${personal#"${personal%%[![:space:]]*}"}"
  personal="${personal%"${personal##*[![:space:]]}"}"
  [ -n "$personal" ] || personal="$HOME/Documents/Personal"
  case "$personal" in
    "~") personal="$HOME" ;;
    "~/"*) personal="$HOME/${personal#\~/}" ;;
  esac
  CC_TASK_ROOT="$personal/20-projects/hapax-cc-tasks"
  CC_TASK_ROOT_SOURCE="personal_vault"
  # A missing default is genesis, not a fault: R4.1's third clause is that first-init CREATES the
  # task vault. Reported, never fatal here; callers that need it present check the flag.
  if [ -d "$CC_TASK_ROOT" ]; then
    CC_TASK_ROOT_EXISTS=1
  else
    CC_TASK_ROOT_EXISTS=0
  fi
  return 0
}

cc_task_root_require() {
  cc_task_root_resolve || return $?
  if [ "$CC_TASK_ROOT_EXISTS" -ne 1 ]; then
    echo "cc-task-root: no cc-task vault at ${CC_TASK_ROOT} (resolved from ${CC_TASK_ROOT_SOURCE}). This is the pre-first-init state, not a broken install. Next: run first-init to create the task vault, or set HAPAX_CC_TASKS_ROOT to an existing one" >&2
    return 2
  fi
  return 0
}
