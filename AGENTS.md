# Hapax Council Codex Instructions

Read `~/projects/CLAUDE.md` and this repo's `CLAUDE.md` as the governing system contract. `AGENTS.md` exists to make Codex load the same rules Claude Code already uses, not to fork policy.

Core invariants:

- Single operator only. Do not add auth, user roles, collaboration flows, or multi-user abstractions.
- Obsidian is the canonical work-state surface. CC/Codex work items live in `~/Documents/Personal/20-projects/hapax-cc-tasks/`; use `cc-claim` and the active claim files when the task gate is enabled.
- Use `uv`, not `pip`. Secrets come from `pass` and `hapax-secrets`; do not copy credential values into code or docs.
- Prefer `scripts/hapax-codex --session cx-<color> --slot <alpha|beta|delta|epsilon>` to launch Codex so hooks, MCP, Obsidian context, and no-ask execution are all active. Without `--cd`, non-primary Codex sessions use Codex-native worktrees named `~/projects/hapax-council--cx-<color>`.
- Respect relay path claims in `~/.cache/hapax/relay/*.yaml` before touching shared areas.
- Idle Codex sessions must stay on the coordination timer from `HAPAX_IDLE_UPDATE_SECONDS` (default 180): when blocked, waiting, or otherwise not actively producing, check parent/user/relay updates on that cadence and leave a concise relay/status update if the wait continues.
- Existing Claude hook scripts are also the Codex guardrails through `hooks/scripts/codex-hook-adapter.sh`.

For multi-session work, Codex visible thread names use `cx-<color>` and worktree slots remain `alpha`, `beta`, `delta`, `epsilon` as coordination lanes. Greek slot names are not Codex worktree names; do not default Codex work into legacy Claude-era `hapax-council--delta/epsilon/main-red` paths.
