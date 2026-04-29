# Hapax Council Codex Instructions

Read `~/projects/CLAUDE.md` and this repo's `CLAUDE.md` as the governing system contract. `AGENTS.md` exists to make Codex load the same rules Claude Code already uses, not to fork policy.

Core invariants:

- Single operator only. Do not add auth, user roles, collaboration flows, or multi-user abstractions.
- Obsidian is the canonical work-state surface. CC/Codex work items live in `~/Documents/Personal/20-projects/hapax-cc-tasks/`; use `cc-claim` and the active claim files when the task gate is enabled.
- Use `uv`, not `pip`. Secrets come from `pass` and `hapax-secrets`; do not copy credential values into code or docs.
- Prefer `scripts/hapax-codex --session cx-<color> --slot <alpha|beta|delta|epsilon>` to launch Codex so hooks, MCP, Obsidian context, and no-ask execution are all active. Without `--cd`, non-primary Codex sessions use Codex-native worktrees named `~/projects/hapax-council--cx-<color>`.
- Use `scripts/hapax-codex-send --session cx-<color> --require-ack -- "message"` for load-bearing parent-to-child instructions. The reliable control plane is tmux (`hapax-codex-cx-<color>`); direct `foot` delivery is a legacy fallback and must not be treated as task receipt unless an ACK is observed.
- Screen visibility is required for `cx-red` and protected `cx-violet`. Other worker lanes may run headless in tmux if the Obsidian session dashboard (`hapax-cc-tasks/_dashboard/codex-session-health.md`), relay YAML, active claim file, and PR state stay current.
- Respect relay path claims in `~/.cache/hapax/relay/*.yaml` before touching shared areas.
- Respect protected live-session declarations in `~/.cache/hapax/relay/session-protection.md`; a protected `cx-*` lane must not be killed, replaced, relaunched, or reclaimed unless the operator explicitly overrides it.
- Idle Codex sessions must stay on the coordination timer from `HAPAX_IDLE_UPDATE_SECONDS` (default 270): when blocked, waiting, or otherwise not actively producing, check parent/user/relay updates on that cadence and leave a concise relay/status update if the wait continues.
- Existing Claude hook scripts are also the Codex guardrails through `hooks/scripts/codex-hook-adapter.sh`.

For multi-session work, Codex lane identities use `cx-<color>` and worktree slots remain `alpha`, `beta`, `delta`, `epsilon` as coordination lanes. Greek slot names are not Codex worktree names; do not default Codex work into legacy Claude-era `hapax-council--delta/epsilon/main-red` paths.
