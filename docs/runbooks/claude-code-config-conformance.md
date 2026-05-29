# Claude Code config conformance

This runbook records the post-merge activation state for
`REQ-20260528-claude-code-config-sdlc-conformance`.

## Current state

As of 2026-05-29:

- P0/P1/P2 are merged on `main`:
  - P0: PR #3736, merge `cf4d6e44`
  - P1: PR #3737, merge `f66c7e00`
  - P2: PR #3738, merge `80efa76e0601001dc88c5c8db3433f52bd084c95`
- `~/.claude/settings.json` registers the shipped Claude Code guardrails:
  - `pr-release-gate.sh`
  - `visual-audio-evidence-reflex.sh`
  - `hook-presence-verify.sh`
  - `subagent-git-safety.sh`
- Existing Claude hook command paths point at the clean merged source path:
  `$HOME/.cache/hapax/rebuild/worktree/hooks/scripts/`.
- The governance-path deny-list is active for high-risk council surfaces:
  `axioms/**`, `CLAUDE.md`, and `config/pipewire/**`.
- `pre-commit` hooks are installed in the current council and constitution
  clones. New clones still need `docs/runbooks/pre-commit-bootstrap.md`.
- `.github/CODEOWNERS` documents governance-protected path ownership, but
  GitHub branch protection for `hapax-systems/hapax-council/main` does not
  require PR review in this single-user repo. Required approving review and
  required Code Owner review both deadlock PRs authored by the sole operator
  account because GitHub forbids self-approval.
- The constitution-package drift surfaced by this audit is a separate
  constitution-lane request:
  `~/Documents/Personal/20-projects/hapax-requests/active/REQ-20260529-constitution-package-sdlc-engine-drift.md`.

Activation receipt:
`~/.cache/hapax/relay/2026-05-29-claude-code-config-postmerge-activation-receipt.md`.

## Verify Claude settings

```bash
jq empty ~/.claude/settings.json

jq -r '
  .hooks
  | to_entries[] as $event
  | $event.value[]?
  | .hooks[]?.command
  | select(startswith("/"))
' ~/.claude/settings.json \
  | while IFS= read -r script; do
      test -x "$script" || echo "MISSING $script"
    done

printf '{}' \
  | HAPAX_SETTINGS_FILE=~/.claude/settings.json \
    ~/.cache/hapax/rebuild/worktree/hooks/scripts/hook-presence-verify.sh
```

Expected result: `jq` exits zero, the executable-path loop prints nothing, and
`hook-presence-verify.sh` prints nothing.

## Verify local git hooks

```bash
test -x ~/projects/hapax-council/.git/hooks/pre-commit
test -x ~/projects/hapax-constitution/.git/hooks/pre-commit
```

If either hook is missing, follow `docs/runbooks/pre-commit-bootstrap.md` in
that clone. If council has a redundant local `core.hooksPath`, clear it with:

```bash
git config --unset-all core.hooksPath
```

## Verify CODEOWNERS posture

```bash
gh api \
  repos/hapax-systems/hapax-council/branches/main/protection/required_pull_request_reviews \
  --jq '{require_code_owner_reviews, required_approving_review_count}'
```

Expected result includes:

```json
{"require_code_owner_reviews":false,"required_approving_review_count":0}
```

Governance paths are listed in `.github/CODEOWNERS` for advisory ownership and
review routing. In a single-user repository, blocking PR review should stay
disabled unless a non-author reviewer identity exists.

## Governing new Claude Code sessions

Normal Claude Code lanes may create governed intake requests and drive work
only through the dispatch/task path:

1. Capture operator prose as a request or cc-task intake artifact.
2. Use `hapax-methodology-dispatch` or a wrapper that delegates to it for lane
   assignment.
3. Ensure the dispatched task has `authority_case`, non-null `parent_spec`,
   route metadata, stage, mutation scope, and quality gates before mutation.
4. Claim exactly one task with `cc-claim`.
5. Release through PR; the in-session PR gate blocks missing AVSDLC/test
   evidence where the active task requires it.

Do not self-select generic "highest WSJF" work, force-claim a peer lane, or use
`HAPAX_METHODOLOGY_EMERGENCY=1` for ordinary convenience.

## Known follow-up

`hapax-sdlc` package drift belongs to the constitution lane, not the Claude
Code config-conformance lane. Track it through:

`REQ-20260529-constitution-package-sdlc-engine-drift`.
