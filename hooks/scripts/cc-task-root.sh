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
#   . "$(dirname "$0")/cc-task-root.sh"
#   cc_task_root_resolve || return $?   # sets CC_TASK_ROOT, or returns 2 with a next action

_cc_task_root_reject_named_user_tilde() {
  # ~user is expanduser() on Python and a literal here. Refuse, do not expand.
  case "$1" in
    "~"|"~/"*) return 0 ;;
    "~"*)
      echo "cc-task-root: ${2} uses a named-user tilde (${1}). The shell resolver cannot expand ~user forms, so both sides refuse them rather than silently disagree. Next: set ${2} to an absolute path or a ~/ form" >&2
      return 2
      ;;
  esac
  return 0
}

_cc_task_root_require_absolute() {
  # A relative value is not a location, it is a location PER PROCESS. Both resolvers accept
  # it and agree textually, and every consumer still reads a different vault depending on
  # where it was launched -- the split SSOT this file exists to prevent, arriving with no
  # disagreement anywhere to detect. Refused rather than anchored: cwd is the defect, and
  # $HOME or the repo root would invent a meaning nobody configured.
  case "$1" in
    /*) return 0 ;;
  esac
  echo "cc-task-root: ${2} is relative (${1}). A relative root resolves against each consumer's working directory, so a gate and a writer started from different directories would use different task vaults and both would succeed. Next: set ${2} to an absolute path" >&2
  return 2
}

cc_task_root_resolve() {
  local override personal knob
  override="${HAPAX_CC_TASKS_ROOT:-}"
  # Trim surrounding whitespace, so a stray space in a unit file is not a different path.
  override="${override#"${override%%[![:space:]]*}"}"
  override="${override%"${override##*[![:space:]]}"}"
  # TILDE EXPANSION IS NOT AUTOMATIC INSIDE A VARIABLE. Python's `expanduser` turns `~/tasks`
  # into an absolute path; the shell leaves it literal, so `-d` fails on a root that exists and
  # the two resolvers disagree about the SSOT. Expanded here so both sides mean the same thing.
  _cc_task_root_reject_named_user_tilde "$override" "HAPAX_CC_TASKS_ROOT" || return $?
  case "$override" in
    "~") override="$HOME" ;;
    "~/"*) override="$HOME/${override#\~/}" ;;
  esac

  if [ -n "$override" ]; then
    # Absolute BEFORE the -d probe. `.` IS a directory, so probing first would accept it
    # and anchor the SSOT on whatever cwd the consumer happened to have.
    _cc_task_root_require_absolute "$override" "HAPAX_CC_TASKS_ROOT" || return $?
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
  # Which knob the value came from, so a refusal names the one the operator can actually
  # change. Python decides this the same way, on the STRIPPED value, so an all-whitespace
  # PERSONAL_VAULT_PATH is reported as HOME on both sides rather than one each.
  knob="PERSONAL_VAULT_PATH"
  if [ -z "$personal" ]; then
    personal="$HOME/Documents/Personal"
    knob="HOME"
  fi
  _cc_task_root_reject_named_user_tilde "$personal" "$knob" || return $?
  case "$personal" in
    "~") personal="$HOME" ;;
    "~/"*) personal="$HOME/${personal#\~/}" ;;
  esac
  # Checked on the default branch too: the default is built from $HOME, so a relative HOME
  # would produce a relative root here exactly as a relative knob would.
  _cc_task_root_require_absolute "$personal" "$knob" || return $?
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

# A `cc_task_root_require` belongs here — resolve, then refuse the genesis state with a message
# distinguishing "not created yet" from "broken install". It is deliberately NOT in this commit,
# for the same reason its Python twin is withheld (shared/cc_task_root.py, end of file): it would
# have no caller. It had one here and not there, which made the two surfaces stop being one rule —
# a future consumer written against the shell would have had no Python equivalent to agree with,
# and the parity pin would have covered `resolve` only. Both land with the first consumer that
# needs them, in the same change, so function and call site are reviewed together. Nothing is lost
# meanwhile: CC_TASK_ROOT_EXISTS already carries the distinction any such caller would read.
