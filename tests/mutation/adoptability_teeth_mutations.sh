#!/usr/bin/env bash
# tests/mutation/adoptability_teeth_mutations.sh — gate 5 of adoptability-teeth-gates-20260916.
#
# Each mutation removes ONE tooth from a live file; the named tests must go RED; the file is
# restored byte-exact afterwards. A mutation that leaves the tests green means that tooth is
# documentation, not verification — the battery exits 1 and names it.
#
# Two disciplines from the estate's memory notes are built in: the mutant is asserted ON DISK
# before the tests run (a silent no-op replace also "passes"), and __pycache__ is swept before
# and after each run (a same-length restore can re-run stale bytecode).
#
# Run from anywhere:  bash tests/mutation/adoptability_teeth_mutations.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 1
cd "$ROOT" || exit 1
PY="${PYTHON:-$ROOT/.venv/bin/python}"
status=0
killed=0
total=0

sweep_pycache() {
  find "$ROOT/shared" "$ROOT/scripts" "$ROOT/tests" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
}

mutate() {
  local file="$1" old="$2" new="$3" tests="$4" label="$5"
  local backup
  total=$((total + 1))
  backup="$(mktemp)" || { echo "ERROR  $label: mktemp failed"; status=1; return; }
  cp -- "$file" "$backup"
  if ! "$PY" - "$file" "$old" "$new" <<'PYEOF'
import pathlib
import sys

path, old, new = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
hits = text.count(old)
if hits != 1:
    print(f"mutation anchor has {hits} hits in {path} (need exactly 1)", file=sys.stderr)
    sys.exit(9)
path.write_text(text.replace(old, new, 1), encoding="utf-8")
PYEOF
  then
    echo "ERROR     $label: mutation did not apply"
    status=1
    cp -- "$backup" "$file"; rm -f "$backup"
    return
  fi
  if ! grep -qF -- "$new" "$file"; then
    echo "ERROR     $label: mutant not on disk after write"
    status=1
  fi
  sweep_pycache
  # shellcheck disable=SC2086 — $tests is a space-separated list of test node ids on purpose
  if "$PY" -m pytest $tests -q -x -p no:cacheprovider >/dev/null 2>&1; then
    echo "SURVIVED  $label"
    echo "          tests stayed green: $tests"
    status=1
  else
    echo "killed    $label"
    killed=$((killed + 1))
  fi
  cp -- "$backup" "$file"; rm -f "$backup"
  sweep_pycache
  if ! cmp -s -- "$file" "$file"; then :; fi
}

GATE=shared/adoptability_gate.py
MOD=tests/shared/test_adoptability_gate.py

mutate "$GATE" \
  '        refusals.append(STAGE_REFUSED_DEMAND_ABSENT)' \
  '        pass  # mutant: demand refusal removed' \
  "$MOD::test_stage_demand_receipt_absent_alone tests/test_cc_stage_advance_adoptability.py::test_garage_door_row_without_receipts_cannot_leave_s1" \
  "stage: demand-receipt check removed"

mutate "$GATE" \
  'if prior_art in {"absent", "invalid"}:' \
  'if False and prior_art in {"absent", "invalid"}:' \
  "$MOD::test_stage_prior_art_receipt_invalid_reads_as_absent tests/hooks/test_cc_task_gate_adoptability.py::test_hand_advancing_a_garage_door_row_without_receipts_is_blocked" \
  "stage: prior-art check removed"

mutate "$GATE" \
  '        return [STAGE_REFUSED_TAG_REMOVED]' \
  '        return []' \
  "$MOD::test_hook_edit_removing_the_tag_is_refused tests/hooks/test_cc_task_gate_adoptability.py::test_removing_the_garage_door_tag_is_blocked" \
  "stage: tag-removal guard removed"

mutate "$GATE" \
  'if isinstance(value, list) and any(list_item_is_accident(key, item) for item in value):' \
  'if False and isinstance(value, list) and any(list_item_is_accident(key, item) for item in value):' \
  "$MOD::test_lint_unquoted_key_value_inside_list_item_is_refused tests/hooks/test_gate_manifest_check.py::test_rows_dir_lint_refuses_unquoted_key_value_list_item" \
  "lint: non-scalar list-item check removed"

mutate "$GATE" \
  '    if estate_bindings(frontmatter):' \
  '    if False:' \
  "$MOD::test_release_estate_binding_is_independent_of_the_receipt tests/test_avsdlc_release_precheck.py::test_garage_door_row_with_estate_binding_in_install_surface_is_refused" \
  "release: estate-noun scan removed"

mutate "$GATE" \
  '        return [RELEASE_REFUSED_RECEIPT_ABSENT]' \
  '        return []' \
  "$MOD::test_release_receipt_absent tests/test_avsdlc_release_precheck.py::test_garage_door_row_without_adoptability_receipt_is_refused" \
  "release: receipt-absent refusal removed"

mutate "$GATE" \
  '        return [RELEASE_REFUSED_RECEIPT_UNSIGNED]' \
  '        return []' \
  "$MOD::test_release_receipt_signed_with_another_key_is_unsigned" \
  "release: signature check removed"

mutate scripts/hapax-adoptability-receipt \
  '"install": {"passed": install_rc == 0,' \
  '"install": {"passed": True,' \
  "tests/scripts/test_hapax_adoptability_receipt.py::test_install_failure_fails_the_receipt_and_the_rest_is_not_reached" \
  "producer: container install check removed"

mutate scripts/cc-claim \
  '        sys.exit(7)' \
  '        pass  # mutant: refusal no longer exits' \
  "tests/scripts/test_cc_claim.py::test_garage_door_row_without_receipts_cannot_be_claimed" \
  "cc-claim: stage refusal no longer stops the claim"

mutate scripts/cc-stage-advance \
  '        return REFUSED
    if ROW_CONVERTED_CONTRIBUTION in refusals:' \
  '        pass  # mutant: refusal no longer stops the advance
    if ROW_CONVERTED_CONTRIBUTION in refusals:' \
  "tests/test_cc_stage_advance_adoptability.py::test_garage_door_row_without_receipts_cannot_leave_s1" \
  "cc-stage-advance: stage refusal no longer stops the advance"

mutate scripts/cc-scope-widen \
  '[f"  - {_emit_item(path)}" for path in new_items]' \
  '[f"  - {path}" for path in new_items]' \
  "tests/scripts/test_cc_scope_widen.py::test_widen_quotes_items_that_would_not_round_trip_as_scalars" \
  "cc-scope-widen: quote-on-emit removed (the accident's producer)"

mutate "$GATE" \
  '        "kind": KILLSWITCH_LEDGER_KIND,' \
  '        "kind": "mutant-unledgered",' \
  "$MOD::test_killswitch_empties_stage_hook_and_release_refusals_and_ledgers_each tests/hooks/test_cc_task_gate_adoptability.py::test_the_teeth_killswitch_is_honoured_and_ledgered_through_the_hook" \
  "killswitch: bypass no longer ledgered"

mutate hooks/scripts/cc-task-gate.impl.sh \
  '          _teeth_rc=$?' \
  '          _teeth_rc=0' \
  "tests/hooks/test_cc_task_gate_adoptability.py::test_hand_advancing_a_garage_door_row_without_receipts_is_blocked" \
  "hook: predicate verdict ignored"

echo
echo "adoptability teeth mutation battery: $killed/$total mutations killed"
if git -C "$ROOT" status --porcelain -- shared/adoptability_gate.py scripts/hapax-adoptability-receipt scripts/cc-claim scripts/cc-stage-advance hooks/scripts/cc-task-gate.impl.sh | grep -q '^ M'; then
  echo "note: files show as modified — that is this branch's own diff against HEAD, not a leaked mutant (each mutant was restored from its byte-exact backup)"
fi
exit $status
