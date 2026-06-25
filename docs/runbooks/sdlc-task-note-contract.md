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
   admission. Review-floor closes additionally need `<task_id>.acceptance.yaml`
   (see PR #4049) and AVSDLC axes/witness fields where media surfaces are touched.
4. Reason codes must name the true failure: an unparseable note is reported as
   such by `cc-pr-autoqueue`, never as a generic missing link.

## Verification Contract

`verification_surface` distinguishes required closure/admission checks from
baseline safety nets:

- `focused_checks`: commands that directly exercise the changed behavior.
- `touched_checks`: commands for touched files or modules.
- `adjacent_checks`: nearby regression checks justified by the route envelope.
- `required_ci_checks`: GitHub required contexts that must be observed green.
- `full_safety_net_checks`: broad local/manual/weekly checks such as full
  `uv run pyright` or full `uv run pytest tests/ -q`.
- `baseline_waivers`: dated evidence for known full-safety-net failures outside
  the mutation scope.

Full safety-net failures are advisory only when the task declares the safety-net
check as nonblocking and attaches a current waiver with all of:
`waiver_id`, `check_name`, `witness`, `observed_at`, `expires_at`,
`tracking_ref`, non-empty `affected_scope`, and `rationale`. The waiver admits
only failures outside the PR's touched paths. A missing, future-dated, expired,
malformed, unknown-scope, or touched-scope waiver is blocking. Unknown failed
checks remain blocking.

Verification blocker repair actions:

- `verification_failed_check:<check>`: rerun/fix the failed check, or declare it
  as a full safety-net check only if it is truly broad baseline coverage.
- `verification_safety_net_unwaived:<check>:missing`: add a current baseline
  waiver with witness, tracking reference, affected scope, and rationale.
- `verification_safety_net_unwaived:<check>:not_yet_observed:<waiver>`: replace
  the future-dated waiver with observed evidence collected at or before the
  admission/closure decision time.
- `verification_safety_net_unwaived:<check>:expired:<waiver>`: refresh the
  witness and expiry window or fix the baseline.
- `verification_safety_net_opted_in:<check>`: the task explicitly made this
  full safety-net check blocking; fix the check or change the task contract only
  with fresh route justification and review.
- `verification_safety_net_scope_unknown:<check>`: attach touched-path evidence
  before treating the safety-net failure as advisory.
- `verification_safety_net_implicated:<check>:<waiver>`: fix the failure or
  split the work so the touched paths no longer overlap the waived baseline.
- `verification_contract_malformed:<error>`: repair the task-note frontmatter;
  the error text names the missing field or invalid window.

Acceptance-oracle observations should include `checked_at`; if it is missing or
unparseable, the oracle evaluates waiver currentness against the evaluator's
current UTC time. The finding payload preserves the original `checked_at`
observation field alongside the verification surface and touched paths so the
decision can be reconstructed.

Emergency stops do not waive evidence. `HAPAX_ACCEPTANCE_ORACLE_OFF=1` makes the
acceptance oracle return an indeterminate shadow result instead of running
clean-tree probes. `HAPAX_CC_PR_AUTOQUEUE_OFF=1`/`HAPAX_CC_HYGIENE_OFF=1` stop
autoqueue mutation. Neither variable converts a failed or unaudited safety-net
failure into an accepted check; use a task/PR fix or explicit operator hold for
incident handling.

Recheck the verification-contract path with:

```bash
uv run pytest tests/shared/test_route_metadata_schema.py tests/test_acceptance_oracle.py tests/test_cc_pr_review_dispatch.py tests/test_review_team.py tests/test_cc_pr_autoqueue.py -q
uv run ruff check shared/route_metadata_schema.py scripts/hapax-acceptance-oracle scripts/cc-pr-review-dispatch.py scripts/review_team.py scripts/cc-pr-autoqueue.py tests/shared/test_route_metadata_schema.py tests/test_acceptance_oracle.py tests/test_cc_pr_review_dispatch.py tests/test_review_team.py tests/test_cc_pr_autoqueue.py
git diff --check
```

Routing-derived verification intensity belongs in
`verification_surface.allocation` (`request_hardening`, `review_intensity`,
`verifier_intensity`, `opportunity_cost`, `rationale_refs`). CCTV, request
hardening, review, and verifier work are allocated work with opportunity cost,
not a fixed intake or review tax.

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
