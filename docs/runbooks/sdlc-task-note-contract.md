# SDLC task-note contract (legibility triad)

Operator directive 2026-06-10: *any confusion in the SDLC is a FAILURE of the
SDLC — it must be corrected programmatically, through formality, or through
reliable legibility (ideally all three).*

## The contract

1. Task notes live in `~/Documents/Personal/20-projects/hapax-cc-tasks/{active,closed}/`.
2. Frontmatter is fenced YAML and MUST parse. **No ANSI escape sequences** —
   on 2026-06-10 a checker's colored output pasted into a witness field made a
   task invisible and admission reported `missing_cc_task_link`, which was a lie.
   Shell-captured values must be stripped (`sed 's/\x1b\[[0-9;]*m//g'`) before
   landing in frontmatter.
3. Required fields for `type: cc-task`: `task_id`, `status`, `authority_case`,
   `parent_spec`. PR-linked tasks additionally need a current
   `<task_id>.review-dossier.yaml` with review-team quorum before merge
   admission. **Receipt-armed** closes additionally need `<task_id>.acceptance.yaml`
   (see PR #4049) and AVSDLC axes/witness fields where media surfaces are touched.

   **A row is receipt-armed by either of two declarations** — the floor alone is
   not the test (PR #4669):

   | Declaration | Where it is read |
   |---|---|
   | `quality_floor: frontier_review_required` | top-level, and the `route_metadata` mirror |
   | `review_requirement.independent_review_required` | top-level, and the `route_metadata` mirror |

   A row may demand independent review under **any** quality floor, and a
   `verification_receipt` row that did exactly that closed unreviewed on
   2026-09-13 before this was enforced. A demand in either location arms
   (fail-closed on disagreement). Only an explicit, schema-valid `false`
   declines.

   **Present but unreadable also arms, and the reason names which level failed**
   — an unknown review requirement may not read as no requirement. Match the
   refusal to the repair:

   | Reason in the refusal | What is wrong | Repair |
   |---|---|---|
   | `review_requirement.independent_review_required:malformed` | the flag value is not a boolean the route schema accepts | set it to `true` or `false` |
   | `review_requirement:malformed_container` | `review_requirement` — or the `route_metadata` holding it — is a list or scalar where a mapping is required | fix the **shape**; the flag value may already be correct, do not change it |
   | `frontmatter_unreadable:<state>` | the note's own YAML does not parse — `invalid_opening_fence` (the first line starts with dashes but is not a document marker), `unterminated`, `parse_error`, `not_a_mapping` | repair the frontmatter block |

   The last one is fail-closed on *content*, not on I/O: the file read fine and
   its YAML is malformed. A note too broken to read cannot be shown to require
   no review, so it is refused rather than admitted.

   Recheck — the close gate alone does not pin all of the above. **One command,
   copy-pasteable, no companion block to forget:**

   ```
   uv run pytest tests/scripts/test_cc_close_acceptance_receipt_check.py \
                 tests/shared/test_sdlc_note_contract.py \
                 tests/shared/test_sdlc_lifecycle.py \
                 tests/shared/test_frontmatter.py \
                 tests/shared/test_sdlc_close.py \
                 tests/test_sdlc_closed_loop_e2e.py \
                 tests/test_release_auto_arm.py \
                 tests/test_cc_pr_autoqueue.py \
                 tests/test_cc_pr_review_dispatch.py \
                 tests/shared/test_session_context_canon.py \
                 packages/hapax-context-canon/tests -q
   ```

   Why each is in the list, because a reader re-running a subset could see green
   while the claim it dropped had drifted:

   | Suite | Pins |
   |---|---|
   | `test_sdlc_note_contract.py` | the leaf's import direction, and that nothing imports the canon module's frozen copies |
   | `test_sdlc_lifecycle.py` | the boolean spellings, via `TestSchemaParity` |
   | `test_cc_pr_autoqueue.py`, `test_cc_pr_review_dispatch.py` | admission and minting |
   | `test_sdlc_closed_loop_e2e.py` | `test_both_close_gates_share_one_receipt_predicate` and `test_the_close_path_snapshot_sees_the_review_demand` — the derivation and snapshot claims this section's prose makes |
   | `test_sdlc_close.py`, `test_release_auto_arm.py` | the two note writers |
   | `test_session_context_canon.py`, `packages/hapax-context-canon/tests` | that the canon bundle hash has not moved — see [the Gate 0A section](#sharedsdlc_lifecyclepy-is-a-gate-0a-canon-hashed-source) below. **No targeted selection reaches this**, and it is one assertion among 262 |

   The boolean spellings above are a **reimplementation** of the route schema's
   coercion (the close gate runs under a bare `python3` and must not import
   pydantic). Their agreement with the real model is pinned by test, not by
   inspection — recheck it directly after any pydantic upgrade:

   ```
   uv run pytest tests/shared/test_sdlc_lifecycle.py::TestSchemaParity -q
   ```

   Residual risk, stated: a pydantic upgrade merged without rerunning that suite
   could briefly reopen the parser-boundary gap the parity test exists to close.

   **Reproducing the mutation evidence.** The claims above are pinned by tests,
   but a passing suite only proves the tests run — not that they would catch a
   regression. Each guard below has a one-line mutation and a named expected
   failure, so the evidence is reproducible rather than a transcript claim.
   Apply the mutation, run the command, confirm the named test reds, revert.

   **Every row was applied and measured against the shipped code**, in one run
   per row, with the recheck command above minus the two canon suites (which no
   mutation here touches). The counts are what the runs reported. Mutate in
   `shared/sdlc_note_contract.py`; `git checkout -- shared/sdlc_note_contract.py`
   reverts.

   | Mutate | Red |
   |---|---|
   | `is_frontmatter_fence`: return `line.rstrip() == "---"` | 8 — incl. `TestFenceGrammar::test_recognized`, `test_a_commented_opening_fence_still_arms_the_gate` |
   | `is_frontmatter_fence`: drop the `rstrip("\r")` | 6 — incl. `test_crlf_notes_parse_identically_to_lf`, `test_frontmatter_set_keeps_a_crlf_note_wholly_crlf` |
   | `frontmatter_block_text`: drop `lines[0][3:]` from the join | 3 — incl. `test_block_text_includes_opening_line_content` |
   | `frontmatter_block_text`: read a bad opener as `FRONTMATTER_ABSENT` | 5 — incl. autoqueue's `test_invalid_opening_fence_is_diagnosed_not_silently_empty` |
   | `frontmatter_state_from_text`: an empty block reads as `FRONTMATTER_OK` | 2 — `test_an_empty_fence_pair_is_its_own_state_not_absent`, `test_adjacent_and_blank_separated_empty_fences_agree` |
   | `frontmatter_state_from_text`: an empty block reads as `FRONTMATTER_ABSENT` | 3 — the two above plus autoqueue's `test_empty_frontmatter_between_real_fences_is_not_an_error` |
   | `_independent_review_state`: identity test instead of `_schema_bool` | 41 — incl. all of `TestSchemaParity` |
   | `acceptance_receipt_triggers`: `elif` the malformed branch | 2 — `test_demand_plus_malformed_reports_both` and its reverse |
   | `frontmatter_write_partition`: match a fence with `startswith("---")` | 3 — the close round trip **and both release-arm round trips** |
   | `frontmatter_set_exactly`: `re.sub(..., count=1)` | 2 — incl. the `duplicated_keys` close round trip |
   | `frontmatter_set_exactly`: pattern back to `^key:\s*.*$` | 12 — incl. four pre-existing close tests |
   | `frontmatter_set_exactly`: drop the append path's `\r` | 1 — `test_frontmatter_set_keeps_a_crlf_note_wholly_crlf[append_absent_key]` |
   | `frontmatter_set_exactly`: `re.sub(pattern, line, head)` (string, not function) | 1 — `test_frontmatter_set_writes_a_value_containing_regex_backreferences` |
   | `frontmatter_set_exactly`: return the postimage without the post-condition | 5 — incl. release-arm's refusal test |
   | `frontmatter_set_exactly`: drop the `write_ineffective` clause | 1 — `quoted_duplicate_wins_the_parse` |
   | `frontmatter_set_exactly`: drop the `collateral` clause | 1 — `flow_collection_member` |
   | `frontmatter_set_exactly`: weaken one-entry to `key not in intent` | 2 — both newline-injection cases |
   | `frontmatter_set_exactly`: drop the preimage-state check | 1 — `test_frontmatter_set_separates_a_broken_note_from_a_broken_write` |
   | `apply_release_auto_arm`: ignore the writer's refusal | 1 — `test_apply_release_auto_arm_refuses_with_a_reason_and_records_no_progress` |

   **Two rows are absent because their guards were deleted, not tested.** Each
   time, a mutation survived and the cause was the same: two guards for one
   hazard, so neither could have an oracle.

   - An attempt to restore the matched line's CR inside the replacement function
     reddened nothing — `[^\r\n]*` never includes the CR in the match, so the
     branch could not fire.
   - Returning `FRONTMATTER_EMPTY_BLOCK` from `frontmatter_block_text` reddened
     nothing — the parser reaches the same verdict through `yaml.safe_load`
     returning `None`, and has to, because a comment-only block has a non-empty
     region and still declares nothing. Deleting it is what makes the two
     `frontmatter_state_from_text` rows above red.

   An earlier version of this table also carried a row for a per-line
   `rstrip("\r")` inside `frontmatter_block_text`, claiming it reddened the CRLF
   test. **It did not — that mutation reddened nothing**, for the same reason.
   It was found by a reviewer checking the table, not by me. That is why every
   row here is now run rather than reasoned about: a table of N assertions is N
   assertions, not one deliverable.

   **Frontmatter fence grammar** (one rule, `shared.sdlc_note_contract.is_frontmatter_fence`):
   `---` at column 0, followed by end-of-line or whitespace. So `---`,
   `--- `, and `--- # task metadata` are fences; `---extra: abc` (a legal
   mapping key), an indented `  ---` inside a literal scalar, and `----` are
   not. A mis-detected fence truncates the block and silently drops every field
   below it, including the review declarations above.
4. Reason codes must name the true failure: an unparseable note is reported as
   such by `cc-pr-autoqueue`, never as a generic missing link.
5. **The same grammar governs writing, and there is one writer.** Two surfaces
   rewrite a note's frontmatter in place — terminal close (`stage`, `status`,
   `completed_at`, `updated_at`, `pr`) and release auto-arm
   (`release_authorized`, the authorized head, `stage`, `updated_at`). Both edit
   lines rather than re-serialising the mapping, so hand-written notes keep
   their comments, key order and quoting. Both now go through
   **`shared.sdlc_note_contract.frontmatter_set_exactly`**, which takes its
   boundaries from the same fence grammar the readers use
   (`frontmatter_write_partition`) and states its post-condition over the
   parsed mapping:

   > after the write, the frontmatter parses equal to the frontmatter before
   > it with that one key set to the intended value — exactly.

   Stating it as one equality is what makes it cover shapes nobody enumerated.
   It has to be enforced rather than assumed because both callers act on the
   result: close projects the postimage into `closed/` **and** deletes the
   active note and every claim lease in the same transaction, so a note that
   parses back wrong is unrecoverable — the task reads as unclosed while the
   lease that would let anyone close it is gone. Release auto-arm writes the
   note and appends an audit line, so a postimage that parses back unarmed
   records work that did not happen, once per retry.

   The primitive is policy-free: it returns `(text, state, detail)` and hands
   back its INPUT unchanged on any state but `ok`. Each caller supplies the
   policy — close raises a typed refusal, release auto-arm returns the note
   unchanged, which `arm_release_for_task` already reads as a refusal.

   | Reason in close's refusal | What is wrong | Repair |
   |---|---|---|
   | `terminal_close_frontmatter_malformed` | the note has no closed frontmatter mapping, or setting the key would leave it unparseable (e.g. the key's value is a nested block). The detail says which, and whether the note was already broken | close the frontmatter, or give that key a single-line value |
   | `terminal_close_frontmatter_value_unrepresentable` | the value does not render as exactly one mapping entry — a newline in it declares a second field, and `--pr` reaches this as an unvalidated string | pass a single-line value |
   | `terminal_close_frontmatter_write_ineffective` | the key was rewritten but the note still parses as the old value, because another spelling of the same key (`"stage":`, `? stage`) occurs later and wins | remove the conflicting entry |
   | `terminal_close_frontmatter_write_collateral` | setting the key also changed a different field — the key occurs at column 0 inside a multi-line flow collection | move the key out of the nested structure |

   Four defects were measured on the previous writers — **both of them, the
   same four** — all one cause: they reasoned about character offsets instead
   of about the document. That is why the contract is written once here rather
   than mirrored per caller.

   | Shape | What the old writers did |
   |---|---|
   | `---extra: abc` (a legal mapping key) | read as the closing fence; the update was inserted **above** it and the originals below won the parse. Close recorded S11 onto a note that still said S10; release auto-arm logged "release_authorized -> true" onto a note that still said `false`, once per retry |
   | a duplicated key | `count=1` rewrote the first; YAML resolves to the last, so the note parsed exactly as before |
   | an empty-valued key (`pr:`) | `^key:\s*.*$` — `\s*` crosses the newline — ate the line beneath it; closing with `--pr` dropped `implementation_authorized` |
   | a value containing `\1` | substituted as a regex replacement, so `re.sub` raised `error: invalid group reference` out of a governed path |

## Enforcement

- `scripts/cc-task-lint` — run any time; CI-friendly exit codes.
- `uv run python scripts/cc-pr-review-dispatch.py --pr <PR> --repo hapax-systems/hapax-council`
  — recheck the review-team constitution plan and linked task note without
  mutating reviewer artifacts.
- `uv run python scripts/cc-pr-review-dispatch.py --pr <PR> --repo hapax-systems/hapax-council --apply`
  — produce or refresh the review-team dossier through automation; acceptance
  receipts are written only by this path after quorum acceptance and gate-valid
  dossier scope.
- `uv run python scripts/cc-pr-autoqueue.py --repo hapax-systems/hapax-council --limit 100`
  — recheck merge admission; PR-linked tasks without a current quorum dossier
  report `missing_review_dossier`, stale dossiers report
  `review_dossier_stale_head:*`, and unavailable changed-file scope reports
  `review_dossier_changed_files_unknown`,
  `review_dossier_changed_files_count_unknown`, or
  `review_dossier_changed_files_truncated:<seen>/<total>`.
- `cc-pr-autoqueue` logs every unparseable note per run and appends the
  filenames to any `missing_cc_task_link` reason.

## `shared/sdlc_lifecycle.py` is a Gate 0A canon-hashed source

Its sha256 is a member of `_SOURCE_HASH_REFS` in
`shared/session_context_canon.py`, so **any** edit to it — a comment included —
moves `bundle_hash`, then `position_ref`, then `frame_hash`, and
`tests/shared/test_session_context_canon.py::test_contract_semantic_supersession_binds_current_and_predecessor`
fails against the frozen fixtures in
`packages/hapax-context-canon/tests/fixtures/`. `shared/release_gate.py:816`
records the same fact and the estate's standing workaround: land extensions
outside the hashed surface until Gate 0B folds them in with the fixture
supersession ceremony.

The failure is easy to miss, because it is **one assertion** and the other 261
canon tests stay green — they check each fixture against its own recorded hash
rather than against a freshly built bundle. Targeted suites will not show it.
Before editing that file, and again before pushing:

```
uv run pytest tests/shared/test_session_context_canon.py packages/hapax-context-canon/tests -q
```

Its last edit on `main` was `158e746bf`, the commit that also froze the
fixtures.

**This is why the note contract lives in `shared/sdlc_note_contract.py`.** The
corrections that this runbook documents — the fence grammar, the receipt
triggers, the exact writer — could not land in the canon module without a
supersession, so they landed in a leaf beside it. The canon module still defines
`frontmatter_from_text`, `requires_acceptance_receipt`,
`acceptance_receipt_blockers` and `apply_release_auto_arm` with their
**pre-correction** behaviour. Those copies are frozen, not current. Import from
`shared.sdlc_note_contract`; `tests/shared/test_sdlc_note_contract.py` fails if
anything imports them from the canon module, and also asserts they are still
defined there so the guard cannot pass vacuously.

One consumer the move could not reach: `task_closure_validity` is defined inside
the canon module and calls the parser next to it, so it still reads notes with
the old grammar — unchanged from `main`, tracked as
`sdlc-task-closure-validity-old-fence-grammar-20260914`. When Gate 0B folds
extensions back into the canon-hashed map, the whole split retires: delete the
frozen copies and the no-import guard with them.

## The release-root rule

Governance scripts (`cc-pr-autoqueue`, `hapax-audio-routing-check`, gate
evaluators) MUST run from a source-activation release root or current worktree,
**never from the primary interactive tree** — the primary can be weeks stale and
produced false invariant-violation verdicts on 2026-06-10. The canonical-rooted
systemd guard (`tests/systemd/test_source_activation_rooted_python_units.py`)
enforces this for units; humans and agents follow the same rule by hand.
