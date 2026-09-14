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
   (fail-closed on disagreement). A `review_requirement` that is present but
   unreadable — not a mapping, or a flag value the route schema rejects — also
   arms, reported as `…:malformed`: an unknown review requirement may not read
   as no requirement. Only an explicit, schema-valid `false` declines.

   Recheck — the close gate alone does not pin all of the above. The boolean
   spellings are pinned by the schema-parity suite and the admission/minting
   behaviour by the autoqueue and dispatch suites, so a reader re-running only
   the first command could see green while parity had drifted:

   ```
   uv run pytest tests/scripts/test_cc_close_acceptance_receipt_check.py \
                 tests/shared/test_sdlc_lifecycle.py \
                 tests/test_cc_pr_autoqueue.py \
                 tests/test_cc_pr_review_dispatch.py -q
   ```
4. Reason codes must name the true failure: an unparseable note is reported as
   such by `cc-pr-autoqueue`, never as a generic missing link.

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

## The release-root rule

Governance scripts (`cc-pr-autoqueue`, `hapax-audio-routing-check`, gate
evaluators) MUST run from a source-activation release root or current worktree,
**never from the primary interactive tree** — the primary can be weeks stale and
produced false invariant-violation verdicts on 2026-06-10. The canonical-rooted
systemd guard (`tests/systemd/test_source_activation_rooted_python_units.py`)
enforces this for units; humans and agents follow the same rule by hand.
