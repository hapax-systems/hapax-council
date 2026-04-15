# CLAUDE.md rotation scan

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #115)
**Scope:** Run `scripts/check-claude-md-rot.sh --strict` against every CLAUDE.md file in the workspace (excluding alpha/beta/delta/spontaneous worktrees). Identify sections flagged as rot per the rotation policy at `docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`.
**Register:** scientific, neutral

## 1. Headline

**12 CLAUDE.md files scanned, zero rot found.** All workspace CLAUDE.md files pass the strict rotation check (no `fixed YYYY-MM-DD`, no `(PR #NNN)` fingerprints, no `currently non-functional|broken|disabled`, no `TODO|FIXME|XXX|not yet` admissions, no `migration pending`, no `temporary workaround`).

The workspace has high CLAUDE.md hygiene. Recent `claude-md-audit.timer` + the rotation-check script + the monthly audit cycle have kept content-drift minimal.

## 2. Files scanned

| # | Path | Scope | Result |
|---|---|---|---|
| 1 | `~/projects/CLAUDE.md` | Workspace root — symlink to `~/dotfiles/workspace-CLAUDE.md` | ✓ clean |
| 2 | `~/projects/hapax-council/CLAUDE.md` | Council primary (main worktree) | ✓ clean |
| 3 | `~/projects/hapax-council/vscode/CLAUDE.md` | Council VS Code extension | ✓ clean |
| 4 | `~/projects/hapax-officium/CLAUDE.md` | Officium primary | ✓ clean |
| 5 | `~/projects/hapax-officium/vscode/CLAUDE.md` | Officium VS Code extension | ✓ clean |
| 6 | `~/projects/hapax-mcp/CLAUDE.md` | Hapax MCP server | ✓ clean |
| 7 | `~/projects/hapax-constitution/CLAUDE.md` | Governance spec repo | ✓ clean |
| 8 | `~/projects/hapax-watch/CLAUDE.md` | Wear OS companion app | ✓ clean |
| 9 | `~/projects/hapax-phone/CLAUDE.md` | Android companion app | ✓ clean |
| 10 | `~/projects/distro-work/CLAUDE.md` | System maintenance scripts repo | ✓ clean |
| 11 | `~/projects/tabbyAPI/CLAUDE.md` | Upstream clone (local-only via `.git/info/exclude`) | ✓ clean |
| 12 | `~/projects/atlas-voice-training/CLAUDE.md` | Upstream clone (local-only) | ✓ clean |

Excluded from scan:

- `~/projects/hapax-council--beta/`, `hapax-council--lrr-p2-runbook/`, `hapax-council--beta-cherry/` — session worktrees, they share the same CLAUDE.md as their parent repo via git worktree semantics

## 3. Strict-mode patterns checked

The `--strict` flag adds the following patterns to the default rotation check:

| Pattern | Class | Example |
|---|---|---|
| `fixed \d{4}-\d{2}-\d{2}` | Bug-fix retrospective | "fixed 2026-04-14" |
| `\(PR #\d+\)` / `\(<role> PR #\d+\)` | PR fingerprint | "(PR #784)" |
| `currently (non-functional|broken|disabled)` | Transient state | "currently disabled" |
| `\b(not yet|TODO|FIXME|XXX)\b` | In-flight admission | "TODO: refactor" |
| `migration pending` | Deferred work | |
| `temporary workaround` | Stopgap code | |

**None of these patterns matched in any of the 12 files.**

## 4. False-positive edge cases

The rotation-check script intentionally skips "pointer contexts" — sections of CLAUDE.md that cite external documents or commit references in a way that isn't content-drift. Examples:

- `see docs/superpowers/specs/2026-04-15-*.md` — not a PR fingerprint
- `commit SHA abc123` — not a "fixed date"
- Code blocks + inline code are read literally, so `# TODO` inside a code example is still flagged under strict mode

Alpha did NOT find any false positives in this scan — all 12 files came back clean without exclusions.

## 5. Historical context

The `docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md` spec introduced the rotation policy after identifying that several CLAUDE.md files had accumulated bug-fix retrospectives + PR fingerprints + incident narratives that belonged in commit messages or handoff docs. The rotation-check script operationalizes the policy; the monthly `claude-md-audit.timer` runs it automatically.

Today's scan confirms that either:

1. The monthly audit has been catching rot on a cadence that prevents accumulation
2. Recent CLAUDE.md edits (e.g., the `hapax-council/CLAUDE.md` update + the `hapax-officium/CLAUDE.md` working-mode migration) have been disciplined about not introducing rot

Both are positive signals. No remediation needed.

## 6. Non-scanned CLAUDE.md files

The workspace root `~/projects/CLAUDE.md` is a symlink to `~/dotfiles/workspace-CLAUDE.md`. The scan followed the symlink correctly + the underlying file is clean.

The two upstream clones (`tabbyAPI/` and `atlas-voice-training/`) carry local-only CLAUDE.md files via `.git/info/exclude` — they are not pushed to upstream. They're scanned because they live in `~/projects/` and match the rotation convention for the workspace. Both are clean.

## 7. Recommendations

1. **No remediation needed.** All 12 CLAUDE.md files pass strict rotation.
2. **Keep running the monthly `claude-md-audit.timer`** — it's evidently catching rot before it accumulates.
3. **No queue follow-up items needed.** This is a clean-state verification, not a drift-discovery audit.

## 8. Closing

Workspace CLAUDE.md hygiene is healthy. The rotation-check + monthly audit infrastructure is working as designed. Branch-only commit per queue item #115 acceptance criteria.

## 9. Cross-references

- `scripts/check-claude-md-rot.sh` — the operational rotation-check script
- `docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md` — rotation policy spec
- `docs/superpowers/plans/2026-04-13-claude-md-excellence-plan.md` — implementation plan
- `docs/superpowers/audits/2026-04-13-claude-md-excellence-audit.md` — initial audit that drove the policy
- `systemd/units/claude-md-audit.service` + `.timer` — monthly audit timer
- `scripts/monthly-claude-md-audit.sh` — monthly audit runner

— alpha, 2026-04-15T17:55Z
