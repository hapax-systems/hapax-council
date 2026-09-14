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

   Recheck — the close gate alone does not pin all of the above. The boolean
   spellings are pinned by the schema-parity suite and the admission/minting
   behaviour by the autoqueue and dispatch suites, so a reader re-running only
   the first command could see green while parity had drifted:

   ```
   uv run pytest tests/scripts/test_cc_close_acceptance_receipt_check.py \
                 tests/shared/test_sdlc_lifecycle.py \
                 tests/shared/test_frontmatter.py \
                 tests/shared/test_sdlc_close.py \
                 tests/test_cc_pr_autoqueue.py \
                 tests/test_cc_pr_review_dispatch.py -q
   ```

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

   Every row below was applied and measured; the counts are what the run
   actually reported, not estimates.

   | Mutate in `shared/sdlc_lifecycle.py` | Expect red |
   |---|---|
   | `is_frontmatter_fence`: return `line.rstrip() == "---"` | 8, incl. `TestFenceGrammar::test_recognized[--- # task metadata]` and `test_a_commented_opening_fence_still_arms_the_gate` |
   | `is_frontmatter_fence`: drop the `rstrip("\r")` | 3, incl. `test_crlf_notes_parse_identically_to_lf` and `TestFenceGrammar::test_recognized[---\r]` |
   | `frontmatter_block_text`: drop `lines[0][3:]` from the join | 2, incl. `test_opening_line_yaml_content_is_preserved` |
   | `frontmatter_block_text`: return `FRONTMATTER_ABSENT` for a bad opener | 5, incl. `test_an_attempted_but_invalid_opening_marker_is_unreadable` and autoqueue's `test_invalid_opening_fence_is_diagnosed_not_silently_empty` |
   | `_independent_review_state`: test `raw is True` instead of `_schema_bool` | 33 in `TestSchemaParity` |
   | `acceptance_receipt_triggers`: `elif` the malformed branch | 2, incl. `test_demand_plus_malformed_reports_both` |

   The writer's guards, same discipline, same command plus
   `tests/shared/test_sdlc_close.py`:

   | Mutate | Expect red |
   |---|---|
   | `frontmatter_write_partition`: match a fence with `startswith("---")` | 1 — `test_terminal_close_projects_a_note_that_parses_as_closed[dash_prefixed_key]` |
   | `_frontmatter_set`: `re.sub(..., count=1)` | 2, incl. the `duplicated_keys` round trip |
   | `_frontmatter_set`: pattern back to `^key:\s*.*$` | 9, incl. `test_setting_a_key_does_not_consume_the_line_beneath_it` and three pre-existing close tests |
   | `_frontmatter_set`: drop the append path's `\r` | 1 — `test_frontmatter_set_keeps_a_crlf_note_wholly_crlf[append_absent_key]` |
   | `_frontmatter_set`: `re.sub(pattern, line, head)` (string, not function) | 1 — `test_frontmatter_set_writes_a_value_containing_regex_backreferences` |
   | `_frontmatter_set`: drop the `_require_exact_frontmatter_write` call | 2 |
   | drop the `write_ineffective` clause | 1 — `quoted_duplicate_wins_the_parse` |
   | drop the `collateral` clause | 1 — `flow_collection_member` |
   | weaken the one-entry rule to `key not in intent` | 2, both newline-injection cases |
   | drop the preimage-state check | 1 — `test_frontmatter_set_blames_a_note_that_was_already_unparseable` |

   A tenth mutation is absent because the guard is: an attempt to restore the
   matched line's CR inside the replacement **reddened nothing**, because the
   `[^\r\n]*` pattern never includes the CR in the match. It was a second guard
   for one hazard and was deleted rather than given a test — the same
   correction as the row below.

   An earlier version of this table carried a seventh row — dropping a per-line
   `rstrip("\r")` inside `frontmatter_block_text` — and claimed it reddened the
   CRLF test. **It did not: that mutation reddened nothing**, because the fence
   helper already tolerates CR and PyYAML accepts CRLF. The row was a second
   guard for one hazard, so neither guard had an oracle. It was deleted rather
   than given a test, and the CR guard that remains is now genuinely
   load-bearing — which is why row 2 above reds where it previously would not.

   **Frontmatter fence grammar** (one rule, `shared.sdlc_lifecycle.is_frontmatter_fence`):
   `---` at column 0, followed by end-of-line or whitespace. So `---`,
   `--- `, and `--- # task metadata` are fences; `---extra: abc` (a legal
   mapping key), an indented `  ---` inside a literal scalar, and `----` are
   not. A mis-detected fence truncates the block and silently drops every field
   below it, including the review declarations above.
4. Reason codes must name the true failure: an unparseable note is reported as
   such by `cc-pr-autoqueue`, never as a generic missing link.
5. **The same grammar governs writing.** Terminal close rewrites the note's
   `stage`, `status`, `completed_at`, `updated_at` and `pr` in place — it edits
   lines rather than re-serialising the mapping, so hand-written notes keep
   their comments, key order and quoting. `shared.sdlc_close._frontmatter_set`
   therefore takes its boundaries from the same fence grammar the readers use
   (`shared.sdlc_lifecycle.frontmatter_write_partition`) and states its
   post-condition over the parsed mapping:

   > after the write, the frontmatter parses equal to the frontmatter before
   > it with that one key set to the intended value — exactly.

   Stating it as one equality is what makes it cover shapes nobody enumerated.
   It has to be enforced rather than assumed because close is destructive: it
   projects the postimage into `closed/` **and** deletes the active note and
   every claim lease in the same transaction, so a note that parses back wrong
   is unrecoverable — the task reads as unclosed and the lease that would let
   anyone close it is gone.

   | Reason in the refusal | What is wrong | Repair |
   |---|---|---|
   | `terminal_close_frontmatter_malformed` | the note has no closed frontmatter mapping, or setting the key would leave it unparseable (e.g. the key's value is a nested block). The detail says which, and whether the note was already broken | close the frontmatter, or give that key a single-line value |
   | `terminal_close_frontmatter_value_unrepresentable` | the value does not render as exactly one mapping entry — a newline in it declares a second field, and `--pr` reaches this as an unvalidated string | pass a single-line value |
   | `terminal_close_frontmatter_write_ineffective` | the key was rewritten but the note still parses as the old value, because another spelling of the same key (`"stage":`, `? stage`) occurs later and wins | remove the conflicting entry |
   | `terminal_close_frontmatter_write_collateral` | setting the key also changed a different field — the key occurs at column 0 inside a multi-line flow collection | move the key out of the nested structure |

   Four defects were measured on the previous writer, all one cause — it
   reasoned about character offsets instead of about the document:

   | Shape | What the old writer did |
   |---|---|
   | `---extra: abc` (a legal mapping key) | read as the closing fence; the update was inserted **above** it and the originals below won the parse, so a close recorded S11 onto a note that still said S10 |
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

## The release-root rule

Governance scripts (`cc-pr-autoqueue`, `hapax-audio-routing-check`, gate
evaluators) MUST run from a source-activation release root or current worktree,
**never from the primary interactive tree** — the primary can be weeks stale and
produced false invariant-violation verdicts on 2026-06-10. The canonical-rooted
systemd guard (`tests/systemd/test_source_activation_rooted_python_units.py`)
enforces this for units; humans and agents follow the same rule by hand.
