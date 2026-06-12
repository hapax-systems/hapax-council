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

## Enforcement

- `scripts/cc-task-lint` — run any time; CI-friendly exit codes.
- `cc-pr-autoqueue` logs every unparseable note per run and appends the
  filenames to any `missing_cc_task_link` reason.

## The release-root rule

Governance scripts (`cc-pr-autoqueue`, `hapax-audio-routing-check`, gate
evaluators) MUST run from a source-activation release root or current worktree,
**never from the primary interactive tree** — the primary can be weeks stale and
produced false invariant-violation verdicts on 2026-06-10. The canonical-rooted
systemd guard (`tests/systemd/test_source_activation_rooted_python_units.py`)
enforces this for units; humans and agents follow the same rule by hand.
