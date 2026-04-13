# CLAUDE.md Excellence — Post-Execution Audit

**Date:** 2026-04-13
**Author:** beta
**Spec:** [`../specs/2026-04-13-claude-md-excellence-design.md`](../specs/2026-04-13-claude-md-excellence-design.md)
**Plan:** [`../plans/2026-04-13-claude-md-excellence-plan.md`](../plans/2026-04-13-claude-md-excellence-plan.md)

Audit performed against the 5 PRs that shipped earlier the same day. Verifies the design doc's success criterion ("every existing CLAUDE.md scores ≥ 90 on the rubric") and surfaces gaps the original execution missed.

## Re-grades (post-Phase-D, 100-point rubric)

Updated by Phase E1. The Phase D round added cross-references, dropped duplicated content from constitution, and propagated rotation-policy trailers to most siblings — improvements bake into the scores below.

| File | Cmd | Arch | Pattern | Concise | Current | Action | Total | Grade | Δ from Phase D |
|---|---|---|---|---|---|---|---|---|---|
| `hapax-council/CLAUDE.md` | 18 | 20 | 14 | 12 | 14 | 14 | **92** | A | +2 |
| `hapax-council/vscode/CLAUDE.md` | 18 | 18 | 13 | 14 | 14 | 14 | **91** | A− | +2 |
| `hapax-officium/CLAUDE.md` | 18 | 20 | 14 | 14 | 15 | 14 | **95** | A+ | +1 |
| `hapax-officium/vscode/CLAUDE.md` | 18 | 17 | 13 | 14 | 14 | 13 | **89** | B+ | 0 (E2 will lift) |
| `hapax-mcp/CLAUDE.md` | 19 | 19 | 14 | 15 | 15 | 14 | **96** | A+ | +1 |
| `hapax-constitution/CLAUDE.md` | 18 | 18 | 13 | 14 | 15 | 14 | **92** | A | +6 |
| `hapax-watch/CLAUDE.md` | 19 | 19 | 13 | 15 | 14 | 14 | **94** | A | +2 |
| `hapax-phone/CLAUDE.md` | 19 | 19 | 14 | 14 | 15 | 14 | **95** | A+ | 0 |
| `distro-work/CLAUDE.md` | 19 | 19 | 13 | 14 | 15 | 14 | **94** | A | 0 |
| `atlas-voice-training/CLAUDE.md` | 19 | 19 | 14 | 14 | 15 | 15 | **96** | A+ | 0 |
| `tabbyAPI/CLAUDE.md` | 19 | 18 | 14 | 14 | 15 | 15 | **95** | A+ | 0 |
| `~/projects/CLAUDE.md` (symlink) | 18 | 18 | 13 | 13 | 14 | 13 | **89** | B+ | 0 (E4 will lift) |

**Average: 93 (A).** Median: 94. Min: 89 (officium vscode + workspace root — both addressed by E2 + E4).

## Gaps vs the success criterion

The spec's success criterion is **every file ≥ 90**. After Phase D, two files remain below:

1. `hapax-officium/vscode/CLAUDE.md` — 89 (B+). Council added a `> Sister surface: hapax-mcp …` callout in PR #728 that wasn't propagated to officium. Asymmetric drift introduced by the audit itself, missed by the broken D1 drift checker (F1). **E2 fixes by propagating the callout.**
2. `~/projects/CLAUDE.md` — 89 (B+). Workspace root is a symlink into dotfiles; nothing in the file documents this. **E4 adds a one-line provenance note.**

The constitution and council vscode files reached A-tier in Phase D (constitution dropped duplicates → 92; council vscode gained sister-surface callout → 91).

## Findings

Findings are tagged: 🔴 high, 🟡 medium, 🟢 low.

### Consistency

| ID | Severity | Finding | Remediation |
|---|---|---|---|
| C-1 | 🔴 | `hapax-phone/CLAUDE.md` is invisible in the local working tree — `main` is 2 ahead, 1 behind `origin/main` because the operator has unmerged local commits. | Operator must rebase or merge their local commits onto `origin/main`. Not safe to fix autonomously. |
| C-2 | 🟡 | `distro-work` primary worktree was 1 behind `origin/main`. | Fixed in Phase A by `git merge --ff-only origin/main`. |
| C-3 | 🟡 | Sister vscode warning understates intentional differences (claims port-only; constitution-path style also differs). | Phase C2 normalizes the constitution-path style. |
| C-4 | 🟢 | `hapax-watch` and `hapax-phone` use different sister-app callout styles. | Defer; cosmetic. |
| C-5 | 🟢 | `hapax-mcp/CLAUDE.md` line 39 lists `cycle_mode` in the read-only tool list. | Phase C3 verifies against `server.py` and reconciles. |
| C-6 | 🟢 | `hapax-constitution/CLAUDE.md` duplicates workspace-root conventions. | Phase C4 drops the duplicates. |

### Completeness

| ID | Severity | Finding | Remediation |
|---|---|---|---|
| Co-1 | 🔴 | The success criterion ("every CLAUDE.md ≥ 90") was never measured. | This audit. |
| Co-2 | 🔴 | No automated enforcement existed. | Phase B wires `pre-commit` hook + GHA workflow + PR template clause. |
| Co-3 | 🟡 | Workspace-root CLAUDE.md is a symlink to dotfiles; not documented. | Phase C adds a one-line provenance note. |
| Co-4 | 🟡 | `.git/info/exclude` is per-clone state; portability fragile. | Defer to Phase D — not blocking. |
| Co-5 | 🟡 | Only council mentions the rotation policy by name. | Phase C adds a one-line trailer to every other workspace CLAUDE.md. |
| Co-6 | 🟢 | Spec/plan didn't link the implementing PRs. | Phase B5 adds the Status appendix to the plan. |

### Robustness

| ID | Severity | Finding | Remediation |
|---|---|---|---|
| R-1 | 🟡 | Rot script v1 had 8 known weak spots (silent skip, narrow patterns, no auto-discovery, no test coverage). | Phase B1 ships v2: auto-discovery via `find`, wider patterns (`not yet`, `migration pending`, `temporary workaround`, `--strict` for `TODO`/`FIXME`/`XXX`), error on missing target, 9 smoke tests. |
| R-2 | 🟡 | `hapax-watch/CLAUDE.md` line 49 has "battery percentage not yet captured — TODO" — a rot pattern v1 missed. | Caught by v2 in-flight pattern. Phase C1 removes it. |
| R-3 | 🟡 | Alpha worktree has uncommitted state — files marked deleted by rebuild-logos timer. | Documented behavior; alpha session recovers via `git restore .` on resume. Not addressed here. |
| R-4 | 🟢 | Workspace-root symlink isn't sanity-checked. | Defer. |

### Dead code / leftovers

| ID | Severity | Finding | Remediation |
|---|---|---|---|
| D-1 | 🟢 | No leftover branches across any owned repo. | ✓ Verified. |
| D-2 | 🟢 | No leftover worktrees outside the canonical alpha/beta/delta. | ✓ Verified. |
| D-3 | 🟢 | `git remote prune` revealed 6 stale remote-tracking branches across 4 repos. | Cleaned in Phase A4. |

### Missed opportunities

| ID | Severity | Finding | Remediation |
|---|---|---|---|
| M-1 | 🟡 | Rot script could be a hook. | Wired in Phase B2. |
| M-2 | 🟡 | No CLAUDE.md grade reporting. | This audit doc IS the report; future audits regenerate it. |
| M-3 | 🟢 | Sister-extension files could be deduplicated entirely. | Defer; duplication is currently bounded by sync warning + Phase C2 normalization. |
| M-4 | 🟢 | No CONTRIBUTING.md or onboarding pointer. | Defer; single-operator system, lower priority. |
| M-5 | 🟢 | Plan doc missing reverse links to PRs. | Phase B5 adds Status appendix. |
| M-6 | 🟢 | Quarterly review reminder not scheduled. | Defer; weekly-review system already exists and rotation-policy check runs on every PR via Phase B3. |

## Phase B deliverables landed in this audit

- ✓ B1 — `scripts/check-claude-md-rot.sh` rewritten as v2 (auto-discovery, wider patterns, modes, typo guard)
- ✓ B1 — `tests/test_check_claude_md_rot.sh` covers 9 fixtures (clean, fix-date, PR fingerprint, beta-PR, currently-broken, in-flight, TODO non-strict, TODO strict, missing target)
- ✓ B2 — `claude-md-rot` pre-commit hook entry on files matching `CLAUDE\.md$`
- ✓ B3 — `.github/workflows/claude-md-rot.yml` triggered on `**/CLAUDE.md` paths (the regular CI workflow's `paths-ignore` skips these)
- ✓ B4 — `.github/pull_request_template.md` carries a CLAUDE.md hygiene checkbox
- ✓ B5 — Plan doc Status appendix; spec doc carries plan + audit cross-links
- ✓ B6 — This audit doc
- ✓ B7 — Phase C remediation list (below)

## Phase C work (sibling repos, one PR each)

| # | Repo | Change |
|---|---|---|
| C1 | `hapax-watch` | Remove "battery percentage not yet captured" gotcha (R-2). Add rotation-policy trailer (Co-5). |
| C2 | `hapax-officium` | Normalize constitution-path style across both vscode CLAUDE.mds (C-3). Add rotation-policy trailer to main CLAUDE.md (Co-5). |
| C3 | `hapax-mcp` | Verify `cycle_mode` tool name against `server.py` and reconcile (C-5). Add rotation-policy trailer (Co-5). |
| C4 | `hapax-constitution` | Drop duplicated workspace conventions (C-6). Add rotation-policy trailer (Co-5). |
| C5 | `distro-work` | Add rotation-policy trailer (Co-5). |

## Deferred (Phase D)

- D1 — Generate-vs-duplicate decision for the two vscode CLAUDE.mds.
- D2 — Move atlas + tabbyAPI local files into a tracked dotfiles location.
- D3 — Sister-something cross-references for mcp ↔ vscode-extensions, constitution ↔ council ↔ officium.
- D4 — Quarterly audit calendar entry / `/weekly-review` integration.
- D5 — Operator's hapax-phone divergence reconciliation (C-1).

## Phase D execution (shipped 2026-04-13 06:32–06:53)

All five D items shipped. PR-by-PR map:

- **D5** — phone divergence rebased + pushed (`6c00c57..0ec3052`). No PR; operator's local commits.
- **D2** — atlas + tabbyAPI CLAUDE.md content relocated to `~/dotfiles/upstream-claude-md/`. New `install.sh` re-creates the symlinks. Pushed to dotfiles main.
- **D1+D4** — [council #728](https://github.com/ryanklee/hapax-council/pull/728) — `scripts/check-vscode-sister-extensions.sh`, `scripts/monthly-claude-md-audit.sh`, `systemd/units/claude-md-audit.{service,timer}`, `systemd/README.md` audit subsection. Bundled with council-side D3.
- **D3** — five PRs:
  - [mcp #30](https://github.com/ryanklee/hapax-mcp/pull/30) sister Tier 1 surfaces
  - [officium #65](https://github.com/ryanklee/hapax-officium/pull/65) sister surfaces + sdlc spec dependency
  - [constitution #45](https://github.com/ryanklee/hapax-constitution/pull/45) downstream consumers
  - council #728 (bundled) — sister surfaces + spec dependency in council CLAUDE.md, `Sister surface` callout in council vscode/CLAUDE.md
- **MCP cycle_mode → working_mode aliases** — [mcp #31](https://github.com/ryanklee/hapax-mcp/pull/31) — added canonical `working_mode()`/`working_mode_set()` tools, fixed `cycle_mode_set` literal type bug, kept deprecated aliases routed to `/working-mode`.

## Phase D regressions caught by Phase E audit

The Phase D execution introduced four issues that the Phase E audit surfaced. All four are tracked as **F1–F4** below and remediated by Phase E PRs.

- **F1 🔴** — `scripts/check-vscode-sister-extensions.sh` used `diff -u` (which produces `-`/`+` prefixes) but the case statement matched `< `/`> ` (plain `diff` format). The loop never matched anything; the script was a permanent no-op. **Fixed in E1**: switched to plain `diff`, added 6 test fixtures.
- **F2 🔴** — Council added a `> Sister surface: hapax-mcp …` callout in PR #728 that wasn't propagated to officium/vscode/CLAUDE.md. Real asymmetric drift, hidden by F1's no-op. **E1 makes the checker catch it; E2 propagates the callout.**
- **F3 🔴** — Officium has not actually migrated `cycle_mode` → `working_mode`. C2's removal of "migration pending" was based on the workspace memory but the migration is genuinely pending in officium per [`officium-design-language.md §9`](../../officium-design-language.md). **E2 executes the §9 migration.**
- **F4 🔴** — MCP's working_mode fix (PR #31) routes to `/working-mode` which doesn't exist on officium. Council backends are correct; officium-pointing MCP instances would 404. **E2 makes F4 moot by giving officium `/working-mode`.**

## Phase E remediation map

E1 ships as a single council PR; E2/E3/E4 follow serially.

| Finding | Severity | Remediation phase |
|---|---|---|
| F1 — drift checker no-op | 🔴 high | E1: switch `diff -u` → `diff`, add `tests/test_check_vscode_sister_extensions.sh`, default to beta canonical |
| F2 — vscode asymmetric drift | 🔴 high | E1 makes it visible; E2 propagates the council callout to officium |
| F3 — officium hasn't migrated | 🔴 high | E2: execute `officium-design-language.md §9` (6-file migration) |
| F4 — MCP fix breaks officium pointing | 🔴 high | E2 makes F4 moot (officium gets `/working-mode`) |
| F5 — no test coverage for sister-drift | 🟡 medium | E1: 6 fixtures in new test file |
| F6 — alpha worktree path fragility | 🟡 medium | E1: `git show origin/main:` for council files; absolute path in service unit |
| F7 — beta canonical hardcode | 🟡 medium | E1: validate `$COUNCIL_CANONICAL` exists at startup |
| F8 — systemd unit missing PATH/HOME | 🟡 medium | E1: add `Environment=PATH=` + `Environment=HOME=` |
| F9 — path style inconsistency | 🟡 medium | E1: switch from `%h` to the convention used by other council units |
| F10 — timer not auto-enabled | 🟡 medium | E1: `install-units.sh` enables newly installed timers (with `SKIP_TIMER_ENABLE=1` escape hatch) |
| F11 — stale model docstring | 🟡 medium | E3: drop "/ cycle mode endpoint" half |
| F12 — status key compat break | 🟡 medium | E3: include both `working_mode` and `cycle_mode` keys |
| F13 — dead runtime mode-validation | 🟡 medium | E3: remove the `if mode not in (...)` checks |
| F14 — Tier 1 framing inaccuracy | 🟢 low | E3: rephrase to "three Logos-API consumers" |
| F15 — tool/data category confusion | 🟢 low | E3: rephrase the framing |
| F16 — sister-surface line officium framing | 🟢 low | E2: parameterize when propagating |
| F17 — audit re-grade table stale | 🟢 low | E1: this very edit |
| F18 — D-PR commit body claim | 🟢 low | Documented here; no fix needed |
| F19 — no caller-visible deprecation | 🟢 low | E3: prepend `[deprecated:]` to deprecated tool responses (optional) |
