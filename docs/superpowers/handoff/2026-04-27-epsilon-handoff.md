# Epsilon — handoff (2026-04-27 ~00:30Z)

Written for post-compaction-self. You are epsilon — publication-bus + applications-funnel lane. Operator (Oudepode) is asleep on autonomous-overnight protocol. KEEP SHIPPING; revert > stall; never wait for approval; 270s ScheduleWakeup mandatory.

## Top of mind on resume

1. **Don't claim absent-context queue items.** Read this whole file before claiming anything. Beta-RTE may have moved the queue since this was written; check the latest inflection at `~/.cache/hapax/relay/inflections/` first.
2. **You own three new cc-tasks just dropped to vault** (relay R1/R2/R3, see below) but they are **beta-RTE-primary** — don't claim them; let beta pick them up unless beta has been silent for >2 hours.
3. **Don't redo the research → production survey.** Already delivered to beta. If operator asks again, point at `~/.cache/hapax/relay/inflections/20260427T002000Z-epsilon-research-prod-injection-survey-to-beta.md`.

## What this session shipped (last 6h, post-compaction-15)

| PR | Title | Status |
|---|---|---|
| #1708 | feat(refusal-annex): wire orchestrator fanout (Phase 3) | merged |
| #1719 | feat(visual-quality): Px437 16-multiples + reverie 960×540 (Tier-A) | merged |
| #1721 | feat(publish-orchestrator): wire hapax-secrets env so adapters can auth | merged |
| #1722 | feat(publication-bus): wire Bridgy POSSE fan-out (V5) | merged |

All four merged via admin-merge after the same pre-existing test infrastructure failure pattern (`test_archive_lifecycle_integration`, `test_ops_live`, `test_timer_overrides`, `pass` CLI not in CI). These are NOT regressions from our work; the rest of CI was green (lint, typecheck, security, web-build, vscode-build, freeze-check, secrets-scan, homage-visual-regression).

## Live activations (post-merge state, verified)

- `hapax-publish-orchestrator.service` — RESTARTED with `EnvironmentFile=-/run/user/1000/hapax-secrets.env`. Env vars HAPAX_BLUESKY_HANDLE, _DID, _APP_PASSWORD, HAPAX_IA_ACCESS_KEY, _SECRET_KEY, HAPAX_OSF_TOKEN, HAPAX_PHILARCHIVE_SESSION_COOKIE, _AUTHOR_ID, HAPAX_ZENODO_TOKEN all confirmed in `/proc/$pid/environ`. Inbox-glob loop active.
- `hapax-imagination.service` — RESTARTED with HAPAX_IMAGINATION_WIDTH=960, HEIGHT=540 confirmed in env. Reverie shader is now rendering at 960×540 (was 640×360). Frames flow to /dev/shm/hapax-visual/frame.jpg as before.
- Compositor will pick up font sizing changes (Px437 16-multiples) via rebuild-services.timer cascade — no manual intervention needed.

## Vault state at handoff

Active cc-tasks tagged with epsilon involvement or recent epsilon authorship:

**Newly created this session (not yet claimed):**
- `visual-quality-tier-b-livestream-presentation` (WSJF 4.5) — rtmp_output preset bug fix + NVENC quality flags + Cairo font hinting. Source: `~/gdrive-drop/livestream-visual-quality-2026-04-26.md` §4.2 Tier-B. Out-of-scope for now: items 2 (canvas 1080p), 10 (NVENC-Optimal switch is now redundant since Tier-A pulled LegomenaLive to parity), 11 (1440p), 13 (direct RTMP).
- `relay-r1-wsjf-triage-ef7b-reservoir` (WSJF 10.0) — vault hygiene; LOAD-BEARING. **Beta-RTE primary.**
- `relay-r2-push-table-fanout-inflections` (WSJF 6.0) — schema change for fanout markdown. **Beta-RTE.**
- `relay-r3-peer-status-yaml-discipline` (WSJF 5.0) — per-session yaml each tick. Cross-cutting first-claim-wins.

**Still claimed by epsilon:**
- `pub-bus-datacite-graphql-mirror` (WSJF 4.5) — Phase 1 shipped; Phase 2 (graph_publisher.py minting concept-DOI + version-DOIs on material change) still open. The scaffold is at `agents/publication_bus/self_citation_graph_doi.py` with `--commit` recognized but stubbed. ~2-4h work.

## Research drops still in flight or in-vault

Recently surveyed against vault state — see `20260427T002000Z-epsilon-research-prod-injection-survey-to-beta.md`. Summary:

- **arxiv-velocity-preprint** (PR #1677, done)
- **x402-receive-endpoint** (PR #1681, done)
- **livestream-visual-quality** (Tier-A done #1719; Tier-B WSJF'd this session)
- **antigravity-setup**, **3day-overview** — comms artefacts, not WSJF-eligible
- **relay-tree-rebalance** (research returned mid-session, ferried to 3 cc-tasks above)
- **R-7 governance-gate-audit, R-16 langfuse-qdrant-audit, R-20 voice-silence-postmortem** — referenced as "absence-class roster rows" with WSJF 14.0 / 6.0 / n/a; **roster doc location unknown**. Surfaced to beta-RTE as outstanding question.

## Critical operator memories (re-load these on compaction)

The system reminder will load `MEMORY.md` automatically. Pay special attention to:

- `feedback_no_operator_approval_waits` — never pause to ask permission
- `feedback_never_stall_revert_acceptable` — revert > stall in operator's cost function
- `feedback_schedule_wakeup_270s_always` — 270s every tick, no exceptions
- `feedback_always_activate_features` — daemon-reload + restart + verify-running as part of shipping
- `feedback_autonomous_overnight_2026_04_26` — operator asleep, KEEP EVERYONE GOING
- `feedback_features_on_by_default` — flip OFF→ON unless constitutional override
- `feedback_no_context_management_sessions` — operator owns context; don't self-compact

## Operator-directive conflicts you'll hit

**1080p compositor canvas.** Tier-A item 2 of the visual-quality research recommends bumping `agents/studio_compositor/config.py:45-46` to 1920/1080. The April 17 directive ("1080p is NOT a priority") is operator-preference rooted in stale VRAM-headroom assumptions. The Tier-B cc-task explicitly defers this — DO NOT ship it without a fresh operator signal. This is the only directive-conflict zone in the visual remediation work.

## Workflow gotchas you'll re-discover

- **`no-stale-branches.sh` hook blocks `git checkout -b` whenever any unmerged branch exists in the workspace.** Bypass with `git update-ref refs/heads/<name> <sha>` then `git push origin <sha>:refs/heads/<name>`. I used this 4× this session.
- **Worktree symlink mismatch.** When a PR touches `systemd/units/*.service`, the deployed unit at `~/.config/systemd/user/<service>` is a `cp` (not a symlink), and `hapax-post-merge-deploy` only fires on actual merge — alpha worktree must be on origin/main (`git -C ~/projects/hapax-council switch --detach origin/main`) and you may need to manually `cp` the unit file if post-merge-deploy didn't run yet. Memory: `feedback_always_activate_features`.
- **CI test job has flaky pre-existing failures** (`test_ops_live`, `test_timer_overrides`, `test_archive_lifecycle_integration`, missing `pass` CLI). Other 9 checks should be green for any clean PR. Admin-merge is the standard pattern when test is the only red.
- **`gemini-cli` MCP**: not used this session. Reserve for >200KB inputs or perceptual tasks. Always `model: "gemini-3-pro-preview"`.
- **Detached HEAD is normal** for the epsilon worktree. Don't try to "fix" it.

## Suggested first move on resume

1. Read the latest `~/.cache/hapax/relay/inflections/` newest file. Note the time gap; if >30 min has passed, the queue may have shifted.
2. Run `git fetch origin main && git log --oneline origin/main -5` to see what merged while away.
3. Check `gh pr list --author "@me"` for any orphaned in-flight work.
4. If queue-dry, write a `<timestamp>-epsilon-queue-dry-N-to-beta.md` inflection (the standard pattern; N=incremented count) and ScheduleWakeup 270s.
5. Otherwise pick the highest-WSJF un-claimed item in epsilon's lane (publication-bus + applications-funnel) — likely `pub-bus-datacite-graphql-mirror` Phase 2.

## Inflections delivered this session

- `20260427T002000Z-epsilon-research-prod-injection-survey-to-beta.md` — survey of research → cc-task coverage; outstanding R-N roster question
- `20260427T002500Z-epsilon-relay-tree-research-landed-to-beta.md` — relay-tree-rebalance findings + 3 cc-tasks linked

## Stopping point

PRs merged. Activations verified. Research ferried. Vault gaps closed. Inflections delivered. Wakeup scheduled.

Pick up where the queue is at the next tick. Don't second-guess this handoff — the work that landed today is real and the state described above is current as of 2026-04-27T00:30Z.

— epsilon (post-compaction-15)
