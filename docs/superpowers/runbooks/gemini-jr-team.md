# Gemini JR Team

Gemini CLI is a packet-only junior support team. It is useful for breadth,
currentness scouting, alternate review, extraction, and test-gap analysis, but
it must not become a production train engine.

## Model Policy

Use the latest highest-capability Gemini CLI selector:

```bash
gemini-3.1-pro-preview
```

This is intentionally strict. The junior team fails closed if the selector is
unavailable rather than silently falling back to Flash or a lower-capability
model. As of 2026-05-01, Google Gemini CLI docs say Gemini 3.1 Pro Preview is
rolling out and can be launched directly with `-m gemini-3.1-pro-preview` when
available; Google API docs identify Gemini 3 Pro as the most intelligent public
model family.

## Authority

Allowed:

- read-only review of supplied diffs, plans, specs, CI logs, or packets
- official-doc currentness scouting
- long-context summarization of supplied material
- test-gap scouting and acceptance-matrix drafting
- bounded extraction and classification
- aesthetic option scouting for senior synthesis

Denied:

- repo edits, vault task mutation, cc-claim, cc-close
- branches, worktrees, PRs, merges, rebases
- deploys, service restarts, `systemctl`, `sudo`, `pass`, secrets
- governance-final decisions, consent/privacy changes, public/private behavior
- any claim that work is implemented, tested, merged, or deployed unless a
  senior lane independently verifies it

## Usage

```bash
scripts/hapax-gemini-jr-team dispatch \
  --role jr-reviewer \
  --task-id pr-2015-review \
  --title "Review PR #2015 for low-risk issues" \
  --prompt-file /tmp/pr-2015-context.md
```

The runner writes packets to:

```text
~/.cache/hapax/gemini-jr-team/packets/
```

It refreshes:

```text
~/.cache/hapax/relay/gemini-jr.yaml
~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/gemini-jr-team.md
```

Codex or Claude must verify and graduate any useful packet into normal
cc-task/branch/PR flow.
