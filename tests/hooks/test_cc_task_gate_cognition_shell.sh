#!/usr/bin/env bash
# INV-5 must reach shell writes, not only Edit/Write tool calls.
#
# Before 2026-09-20, is_cognition_path() was consulted only for $edit_path. A bash command has no
# $edit_path, so EVERY shell write was refused unconditionally — including writes to the very paths
# the cognition carve-out exists to keep open. Measured: `cat > <vault note>` with the body `probe`
# was refused, while the identical bytes through the Write tool were allowed. One invariant honoured
# on one surface only.
#
# That refusal was also what taught evasion: if no shell write can succeed, the only way to write
# from a shell is to not look like a shell write.
#
# The decision under test: ALLOW only when at least one target was extracted AND every extracted
# target is a cognition path. Everything else fails closed. The dangerous failure is extracting the
# WRONG target and allowing a write that should be refused, so the cases below include the forms
# most likely to mis-parse.
#
# Run: bash tests/hooks/test_cc_task_gate_cognition_shell.sh   (exit 0 = all assertions hold)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPL="$HERE/../../hooks/scripts/cc-task-gate.impl.sh"
SCRATCH="$(mktemp -d /tmp/hapax-gate-fn.XXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT

# Pull the pure helpers out of the gate so this exercises the SHIPPED text of each function rather
# than a copy that would have to be kept in sync by hand.
sed -n '/^_bash_segments() {/,/^}/p;/^_bash_seg_head() {/,/^}/p;/^_bash_write_targets() {/,/^}/p;/^_bash_writes_cognition_only() {/,/^}/p;/^is_cognition_path() {/,/^}/p' \
  "$IMPL" > "$SCRATCH/fns.sh"
for f in _bash_segments _bash_seg_head _bash_write_targets _bash_writes_cognition_only is_cognition_path; do
  grep -q "^$f() {" "$SCRATCH/fns.sh" || { echo "FATAL: $f not extracted — anchors drifted"; exit 1; }
done
# shellcheck disable=SC1090
. "$SCRATCH/fns.sh"

fail=0
VAULT="$HOME/Documents/Personal/30-areas/hapax/frame/note.md"
SSOT="$HOME/Documents/Personal/20-projects/hapax-cc-tasks/active/t.md"   # explicitly NOT cognition
SRC="$HOME/projects/hapax-council/scripts/x.py"

# Calls the gate's OWN decision function. An earlier version of this test re-implemented the
# decision here instead, and mutation testing caught it: breaking the gate's fail-closed guard and
# breaking its per-target cognition check BOTH left this suite green, because the suite was
# exercising its own copy. A test that compiles its own logic cannot detect changes to the real
# logic. Only the quote-strip is reproduced, because that happens before the call site.
decide() {
  local stripped
  stripped="$(printf '%s' "$1" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g; s/(^|[[:space:]])#[^\n]*//g")"
  if _bash_writes_cognition_only "$stripped"; then echo ALLOW; else echo REFUSE; fi
}

check() { # name expected cmd
  local got; got="$(decide "$3")"
  if [[ "$got" == "$2" ]]; then echo "ok   - $1 ($got)"
  else echo "FAIL - $1: expected $2, got $got"; fail=1; fi
}

echo "== cognition writes are allowed (INV-5 reaches the shell) =="
check "cat > vault note"              ALLOW  "cat > $VAULT"
check "cat >> vault note"             ALLOW  "cat >> $VAULT"
check "cat > vault note with heredoc" ALLOW  "cat > $VAULT <<'EOF'"
check "tee vault note"                ALLOW  "tee $VAULT"
check "cp within vault"               ALLOW  "cp $VAULT ${VAULT}.bak"
check "touch vault note"              ALLOW  "touch $VAULT"

echo
echo "== the harness-assigned session scratchpad is cognition =="
# The agent is TOLD to work here; the gate did not know the surface existed. Measured 2026-09-20: a
# `cp` between two files inside a session's own scratchpad was refused and working data was lost.
SCRATCH_BASE="${TMPDIR:-/tmp}"; SCRATCH_BASE="${SCRATCH_BASE%/}"
SP="$SCRATCH_BASE/claude-1000/-home-user/sess/scratchpad/note.md"
check "cat > session scratchpad"       ALLOW  "cat > $SP"
check "cp within session scratchpad"   ALLOW  "cp $SP ${SP}.bak"
check "legacy /tmp/claude-* form"      ALLOW  "cat > /tmp/claude-1000/s/scratchpad/n.md"
# NARROW on purpose: $TMPDIR at large is not cognition, or an unclaimed lane could write arbitrary
# temp source — the same reasoning the /tmp/hapax-* carve-out is drawn narrowly for.
check "TMPDIR at large is NOT cognition" REFUSE "cat > $SCRATCH_BASE/random-file.sh"
check "sibling tmp dir is NOT cognition" REFUSE "cat > $SCRATCH_BASE/notclaude-1000/x.md"

# DOCUMENTED DEPENDENCY, not a defence against it. The carve-out's own input is a variable set
# upstream. With TMPDIR unset the fallback computes /tmp/claude-<uid>, which matches nothing on a
# host whose scratchpads live elsewhere, and the carve-out SILENTLY STOPS APPLYING. The failure
# direction is safe — more refusals, never fewer — but it is silent, and it would present as exactly
# the symptom this carve-out was added to fix, with a different cause. The next person to see
# scratchpad writes refused will look at the carve-out, see it present, and not think to check the
# variable. This assertion exists so they find it here instead.
#
# The irony is the argument, and it belongs in the record rather than in a fix: the remedy for
# controls whose inputs are set by a layer upstream itself takes an input set by a layer upstream.
# See cc-task-gate-interpreter-blindness-determination-20260920.
( unset TMPDIR
  got="$(decide "cat > /store-fast/tmp/claude-1000/s/scratchpad/n.md")"
  if [[ "$got" == "REFUSE" ]]; then
    echo "ok   - with TMPDIR unset the carve-out does NOT reach a non-/tmp scratchpad (REFUSE — documented, not desired)"
  else
    echo "FAIL - TMPDIR-unset behaviour changed: expected REFUSE, got $got"; exit 1
  fi ) || fail=1

echo
echo "== non-cognition writes still refused =="
check "cat > council source"          REFUSE "cat > $SRC"
check "cp vault -> council source"    REFUSE "cp $VAULT $SRC"
check "cat > task SSOT (carved OUT of cognition on purpose)" REFUSE "cat > $SSOT"
# ALLOW is correct here: `cp SRC DEST` WRITES only to DEST. The council file is READ, not written,
# so the only write is to a cognition path. This case pins the read/write asymmetry — a future
# "simplification" treating every operand as a target would flip it and start refusing note-taking.
check "cp council src -> vault (writes vault only)" ALLOW "cp $SRC $VAULT"

echo
echo "== unreadable or unhandled forms fail CLOSED =="
check "dd of= (not handled)"          REFUSE "dd of=$VAULT"
check "redirect through a variable"   REFUSE 'cat > $SOME_VAR'
check "no write target at all"        REFUSE "rm -rf /some/path"
check "chmod (no target extractor)"   REFUSE "chmod 700 $VAULT"

echo
if (( fail )); then echo "RESULT: FAILURES PRESENT"; exit 1; else echo "RESULT: all assertions hold"; fi
