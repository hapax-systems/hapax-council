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

echo "== the MINIMAL carve-out admits ordinary note-taking (seat's exit condition, 2026-09-28) =="
# Four rounds of enumerating (and then allowlisting) option spellings each produced another admit path, so
# the carve-out was CUT instead of patched again: only `echo`, `printf`, `cat` and `tee` with NO option
# token at all, writing through `>`/`>>`/`tee` into a cognition path, with an optional leading `cd`.
check "cat > vault note"              ALLOW  "cat > $VAULT"
check "cat >> vault note"             ALLOW  "cat >> $VAULT"
check "cat > vault note with heredoc" ALLOW  "cat > $VAULT <<'EOF'"
check "tee vault note"                ALLOW  "tee $VAULT"
check "echo x > vault note"           ALLOW  "echo x > $VAULT"
check "printf >> vault note"          ALLOW  "printf '%s\\n' x >> $VAULT"
check "cat SOURCE > vault note"       ALLOW  "cat $SRC > $VAULT"
check "echo | tee vault note"         ALLOW  "echo x | tee $VAULT"
check "cd then cat > vault"           ALLOW  "cd /tmp && cat > $VAULT"

echo
echo "== the harness-assigned session scratchpad is cognition =="
SCRATCH_BASE="${TMPDIR:-/tmp}"; SCRATCH_BASE="${SCRATCH_BASE%/}"
SP="$SCRATCH_BASE/claude-1000/-home-user/sess/scratchpad/note.md"
check "cat > session scratchpad"       ALLOW  "cat > $SP"
check "echo > session scratchpad"      ALLOW  "echo x > $SP"
check "legacy /tmp/claude-* form"      ALLOW  "cat > /tmp/claude-1000/s/scratchpad/n.md"
check "TMPDIR at large is NOT cognition" REFUSE "cat > $SCRATCH_BASE/random-file.sh"
check "sibling tmp dir is NOT cognition" REFUSE "cat > $SCRATCH_BASE/notclaude-1000/x.md"

( unset TMPDIR
  got="$(decide "cat > /store-fast/tmp/claude-1000/s/scratchpad/n.md")"
  if [[ "$got" == "REFUSE" ]]; then
    echo "ok   - with TMPDIR unset the carve-out does NOT reach a non-/tmp scratchpad (REFUSE — documented, not desired)"
  else
    echo "FAIL - TMPDIR-unset behaviour changed: expected REFUSE, got $got"; exit 1
  fi ) || fail=1

echo
echo "== everything else refuses: other heads, every option, unresolved tokens =="
check "cat > council source"          REFUSE "cat > $SRC"
check "cat > task SSOT"               REFUSE "cat > $SSOT"
REQ="$HOME/Documents/Personal/20-projects/hapax-requests/active/r.md"
check "cat > request SSOT"            REFUSE "cat > $REQ"
check "redirect through a variable"   REFUSE 'cat > $SOME_VAR'
check "cat > command substitution"    REFUSE 'cat > $(cmd)'
check "rm of a source alone"          REFUSE "rm -f $SRC"
check "rm then cat > vault"           REFUSE "rm -f $SRC; cat > $VAULT"
check "dd then echo > vault"          REFUSE "dd if=/dev/zero of=$SRC; echo x > $VAULT"
check "chmod then tee vault"          REFUSE "chmod 700 $SRC && tee $VAULT"
check "mv into the vault"             REFUSE "mv $VAULT ${VAULT}.bak"
check "sort -o into a source"         REFUSE "sort -o$SRC $VAULT; cat > $VAULT"
check "uniq with an OUT operand"      REFUSE "uniq $VAULT $SRC"
check "cp -t into a source dir"       REFUSE "cp -t$SRC $VAULT"
check "mv -t into a source dir"       REFUSE "mv -t $SRC $VAULT"
check "mv -- discards operands"       REFUSE "mv -- $SRC $VAULT; cat > $VAULT"
check "cp -- discards operands"       REFUSE "cp -- $VAULT $SRC"
check "cat -n (an option)"            REFUSE "cat -n $SRC > $VAULT"
check "cat -- (an option token)"      REFUSE "cat -- $SRC > $VAULT"
check "grep then cat > vault"         REFUSE "grep -q x /dev/null; cat > $VAULT"

echo
echo "== dynamic forms refuse BEFORE the strip (full gate; review of #4704, 2026-09-28) =="
# The quote-strip removes quoted content, but the shell still EXECUTES it, so a substitution inside
# quotes reached the early allow with only the vault target visible. The refusal is at the gate's call
# site, on the RAW command — which is why these cases run the whole hook rather than the helper.
mkdir -p /store-fast/tmp/hapax-wt/grok-sonar-tmp2
HOME_DYN="$(mktemp -d /store-fast/tmp/hapax-wt/grok-sonar-tmp2/gate-home.XXXXXX)"
trap 'rm -rf "$SCRATCH" "$HOME_DYN"' EXIT
DYNNOTE="$HOME_DYN/Documents/Personal/30-areas/hapax/frame/note.md"
DYNLEDGER="$HOME_DYN/.cache/hapax/methodology-emergency-ledger.jsonl"
mkdir -p "$(dirname "$DYNNOTE")" "$(dirname "$DYNLEDGER")"

run_gate_dyn() {
  local cmd="$1" rc=0
  jq -n --arg c "$cmd" '{tool_name:"Bash", tool_input:{command:$c}}' \
    | env -u HAPAX_AGENT_ROLE -u HAPAX_AGENT_NAME -u HAPAX_WORKTREE_ROLE \
        -u CODEX_ROLE -u CLAUDE_ROLE -u CODEX_THREAD_NAME \
        -u HAPAX_CC_TASK_GATE_OFF -u HAPAX_METHODOLOGY_EMERGENCY \
        HOME="$HOME_DYN" bash "$IMPL" >"$SCRATCH/out" 2>"$SCRATCH/err" || rc=$?
  printf '%s' "$rc"
}

for dyn in "echo \"\$(rm $SRC)\" > $DYNNOTE" "echo \`rm $SRC\` > $DYNNOTE" "cat <(rm $SRC) > $DYNNOTE" \
           "eval \"cat > $DYNNOTE\"" "source x.sh; cat > $DYNNOTE" ". x.sh; cat > $DYNNOTE"; do
  : >"$DYNLEDGER" 2>/dev/null || true
  rc="$(run_gate_dyn "$dyn")"
  if [[ "$rc" == "2" ]] && ! grep -q '"kind":"cognition_allow"' "$DYNLEDGER" 2>/dev/null; then
    echo "ok   - refused end to end, no cognition_allow: $dyn"
  else
    echo "FAIL - dynamic form admitted or ledgered: rc=$rc $dyn"; fail=1
  fi
done

echo
echo "== witnessed full gate: the old admit paths now refuse, note-taking still allows =="
mkdir -p /store-fast/tmp/hapax-wt/grok-sonar-tmp
HOME_FX="$(mktemp -d /store-fast/tmp/hapax-wt/grok-sonar-tmp/gate-home.XXXXXX)"
trap 'rm -rf "$SCRATCH" "$HOME_FX"' EXIT
NOTE="$HOME_FX/Documents/Personal/30-areas/hapax/frame/note.md"
DONE="$HOME_FX/Documents/Personal/00-inbox/quack/done"
LEDGER="$HOME_FX/.cache/hapax/methodology-emergency-ledger.jsonl"
mkdir -p "$(dirname "$NOTE")" "$DONE" "$(dirname "$LEDGER")"

run_gate() {
  local cmd="$1" rc=0
  jq -n --arg c "$cmd" '{tool_name:"Bash", tool_input:{command:$c}}' \
    | env -u HAPAX_AGENT_ROLE -u HAPAX_AGENT_NAME -u HAPAX_WORKTREE_ROLE \
        -u CODEX_ROLE -u CLAUDE_ROLE -u CODEX_THREAD_NAME \
        -u HAPAX_CC_TASK_GATE_OFF -u HAPAX_METHODOLOGY_EMERGENCY \
        HOME="$HOME_FX" bash "$IMPL" >"$SCRATCH/out" 2>"$SCRATCH/err" || rc=$?
  printf '%s' "$rc"
}

ledger_allows() {
  [[ -f "$LEDGER" ]] || return 1
  grep -q '"kind":"cognition_allow"' "$LEDGER"
}

for case in "cat > $NOTE" "cat > $NOTE <<'EOF'" "echo x | tee $NOTE"; do
  : >"$LEDGER"
  rc="$(run_gate "$case")"
  if [[ "$rc" == "0" ]] && ledger_allows; then
    echo "ok   - $case allowed and ledgered cognition_allow"
  else
    echo "FAIL - $case: rc=$rc ledger=$(cat "$LEDGER" 2>/dev/null || echo missing)"; fail=1
  fi
done
# `echo x > <path>` and `printf … > <path>` are admitted by the gate's SEPARATE non-mutating
# early-out, which never reaches this carve-out and writes no cognition_allow line. Asserting the
# ledger here would test that other mechanism; measured 2026-09-28 and reported to the seat as its
# own finding (it admits a redirect to ANY path, not only a cognition one).
for case in "echo x > $NOTE" "printf '%s\n' x > $NOTE"; do
  : >"$LEDGER"
  rc="$(run_gate "$case")"
  if [[ "$rc" == "0" ]]; then
    echo "ok   - $case allowed (by the non-mutating early-out, no ledger line)"
  else
    echo "FAIL - $case: rc=$rc"; fail=1
  fi
done

for case in "rm -f $HOME_FX/projects/x; cat > $NOTE" "sort -o $HOME_FX/projects/x $NOTE; cat > $NOTE" \
            "uniq $NOTE $HOME_FX/projects/x; cat > $NOTE" "cp -t $HOME_FX/projects/x $NOTE; cat > $NOTE" \
            "mv -- $HOME_FX/projects/x $NOTE; cat > $NOTE" "cat -n $NOTE > $HOME_FX/projects/x" \
            "mv $NOTE $DONE/" "cat > $HOME_FX/Documents/Personal/20-projects/hapax-cc-tasks/active/t.md"; do
  : >"$LEDGER"
  rc="$(run_gate "$case")"
  if [[ "$rc" == "2" ]] && ! ledger_allows; then
    echo "ok   - refused end to end, no cognition_allow: $case"
  else
    echo "FAIL - expected rc=2 with no cognition_allow: rc=$rc $case"; fail=1
  fi
done

echo
if (( fail )); then echo "RESULT: FAILURES PRESENT"; exit 1; else echo "RESULT: all assertions hold"; fi
