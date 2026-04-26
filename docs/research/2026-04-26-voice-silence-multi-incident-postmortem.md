# Voice silence — multi-incident postmortem (2026-04-26)

**Authored:** 2026-04-26 by beta (RTE)
**Source:** R-20 of the absence-class-bug-prevention-and-remediation epic
**Window:** 2026-04-25 ~22:00Z → 2026-04-26 ~16:30Z (≈18.5h with intermittent silence)
**Operator report (verbatim, multiple):** "haven't heard hapax on the stream for a loooong time", "still no hapax voice", "voice not back on stream", "fyi nothing flowing to obs point"

## Why this exists

The 8-hour autonomous-overnight run (2026-04-26 04:20Z → 16:30Z) experienced **four distinct voice-silence root causes** in sequence. Each was diagnosed + remediated by an independent research agent + shipped as a PR. The postmortem is overdue: a single-incident retrospective per cause would lose the cross-cause pattern. The pattern matters — three of the four were absence-class bugs, and the substrate-truth witness gap that would have caught all four is the same substrate gap the absence-class-bug-prevention-and-remediation epic addresses.

This doc consolidates the four causes + the architectural follow-up + the L-12 invariant CI guard task that anchors the postmortem.

## The four root causes

### v1 — orphan `voice_state` health-monitor probe → daimonion restart loop

**Surface:** `hapax-daimonion.service` in continuous restart loop, ~every 15 min for 8+ hours. Operator hears no voice because the cold-start window (80-150 s) plus the inter-restart idle gap exceeds the time between spontaneous-speech triggers.

**Trigger:** `agents/health_monitor/checks/exploration.py` expects 13 components to publish `/dev/shm/hapax-exploration/{component}.json`. 12 are fresh; `voice_state.json` is absent because **no module in `agents/hapax_daimonion/` ever calls `publish_exploration_signal("voice_state", ...)`**. The expected-writer entry was added in PR #1070 (commit ef539334f, 2026-04-18); the producing call was never wired.

The check returns `Status.DEGRADED` with remediation `systemctl --user restart hapax-daimonion` on every tick. The fix-pipeline at `shared/fix_capabilities/pipeline.py` accepts the regex `systemctl --user restart [\w@.\-]+` via `_SAFE_REMEDIATION_PATTERN`, so the restart fires deterministically without LLM gating.

**Fix:** PR #1566 — drop the `voice_state` entry from `COMPONENT_OWNERS`. Detailed diagnosis at `docs/research/2026-04-26-hapax-voice-silence-diagnosis.md`.

**Class:** absence-class — `voice_state` was named in the consumer (health-monitor) but never authored in any producer (daimonion).

### v2 — worktree on stale branch → deployment lag

**Surface:** even after PR #1566 merged, the operator's broadcast machine ran the pre-merge code because the primary worktree's `git branch` was a feature branch, not `main`. The post-merge deploy chain (`scripts/rebuild-service.sh`) refuses to deploy when the worktree is off `main` and emits a throttled ntfy.

**Trigger:** alpha had detached the worktree mid-cycle (per the FU-6 documented tension where alpha's worktree doubles as dev branch + production deploy target). Operator missed the ntfy.

**Fix:** operator detached to `origin/main` manually; rebuild-services.timer picked up on next 5-min tick. Then PR #1566's fix actually reached the deployed daimonion.

**Class:** drift, not absence. The deploy chain *is* designed to fail-safe; the failure mode is operator-attention.

### v3 — TTS chain wired to L-12 only, not livestream-tap

**Surface:** daimonion's TTS audio reached the L-12 console (operator could monitor) but never reached the broadcast (OBS source = silent).

**Trigger:** `config/pipewire/hapax-tts-duck.conf` had a single `libpipewire-module-filter-chain` that fed `hapax-tts-duck` → L-12 USB output. The 2026-04-25 channel-narrow on `hapax-l12-evilpet-capture.conf` (14 channels → AUX1/3/4/5) protected the inverse direction (broadcast must not loop back into capture) but also dropped the USB-return pair where TTS landed. **No path from TTS to `hapax-livestream-tap`** existed.

The L-12 invariant (`feedback_l12_equals_livestream_invariant`): every audio source in L-12 must reach broadcast, AND non-broadcast audio must leave L-12 entirely. v3 was a violation of the *forward* direction.

**Fix:** PR #1572 — add a second `libpipewire-module-loopback` to the same conf that taps `hapax-tts-duck` monitor → `hapax-livestream-tap`. Parallel to L-12 USB output; both fire on every TTS clip.

**Class:** absence-class — the broadcast forward path was named in the invariant but never authored in the conf.

### v4 — wireplumber `role.assistant` `preferred-target = hapax-private`

**Surface:** broadcast TTS silenced for ~6 hours after the morning leak fix.

**Trigger:** operator complained on 2026-04-26 morning that private hapax cognition was leaking onto broadcast. The fix in `config/wireplumber/50-hapax-voice-duck.conf` retargeted `role.assistant` from `hapax-voice-fx-capture` → `hapax-private`. This closed the leak — but it also blocked the broadcast TTS path, because daimonion uses `media.role = Assistant` for *all* TTS, not distinguishing private from broadcast destinations.

The `destination_channel.classify_destination` classifier in daimonion intends a private/livestream split via `pw-cat --target`, but **role-based policy silently overrides `--target`**. `--target` is a hint to wireplumber; `policy.role-based.preferred-target` is the binding selector.

**Fix:** PR #1575 reverted the morning fix (preferred-target back to `hapax-voice-fx-capture`) to restore broadcast voice. PR #1581 then shipped the architectural fix: a separate `Broadcast` media-role parallel to `Assistant`, with `daimonion.cpal.destination_channel.resolve_role(destination)` mapping LIVESTREAM→Broadcast and PRIVATE→Assistant. Per-call `--media-role` override threaded through `generate_spontaneous_speech` → `_speak_sentence` → `_write_audio`.

The actual flip (Assistant → hapax-private; Broadcast pinned at hapax-voice-fx-capture) was deferred to operator follow-up because the daimonion classifier rules need verification before the leak-protection lands.

**Class:** wireplumber-policy-coarseness — single role can't carry private/broadcast split. Architectural fix is correct; the deferred flip is pending operator decision.

## v5 (architectural follow-up, not strictly an incident)

PR #1608 (alpha-now-gamma's pitch implementation) — set `node.passive = false` on the `hapax-l12-evilpet-playback` filter-chain output. Without this, the playback node defaulted to passive and stalled after a wireplumber restart until something downstream actively claimed it. The 11:09 wireplumber double-restart triggered exactly this orphan state — broadcast went silent again.

**Class:** absence-class — `node.passive = false` was needed but never authored. Permanent fix.

## Cross-cause pattern

| # | Root cause | Bug class | Surface absent | Fix PR |
|---|---|---|---|---|
| v1 | orphan `voice_state` probe | absence-class | producing call in daimonion | #1566 |
| v2 | worktree on stale branch | deployment-drift | operator-attention to ntfy | (manual) |
| v3 | TTS → L-12 only | absence-class | forward-path loopback to livestream-tap | #1572 |
| v4 | role.assistant → hapax-private | policy-coarseness | per-destination media-role split | #1575 + #1581 |
| v5 | playback node passive | absence-class | `node.passive = false` declaration | #1608 |

Three of the five root causes (v1, v3, v5) are absence-class. They share a single failure mode:

> The substrate (consumer / loopback / pull-claim) was wired correctly per its own logic, the unit tests passed against the fixture the author imagined, the audit yamls said the right words, and yet the production data-path did not connect because the *other* end of the wiring never authored the symbol the substrate expected.

This is exactly the bug class the absence-class-bug-prevention-and-remediation epic addresses. The audit-yaml schema (P-1, beta-direct), the substrate smoke test (P-3, per-substrate), the post-merge trace service (P-5, alpha lane), and the cross-session audit invariant (P-7, beta-direct) all attack this surface from complementary angles.

## L-12 invariant CI guard

The R-20 task includes the L-12 invariant CI guard test. The invariant's two halves:

1. **Forward:** every audio source feeding the L-12 must reach broadcast.
2. **Inverse:** any non-broadcast audio must leave the L-12 entirely (private must not be capturable).

A CI guard for the FORWARD direction is the natural complement to the existing inverse-direction guard (the channel-narrow on `hapax-l12-evilpet-capture.conf`). It would:

- Parse all wireplumber rules + pipewire confs that target L-12 nodes.
- For each producer pointed at L-12, assert there exists ALSO a downstream path to `hapax-livestream-tap`.
- Fail CI if any L-12 producer lacks a livestream-tap reachability path.

The full guard is sketched but not shipped in this PR (~3-4h of static-graph parsing). It's a follow-up to this postmortem.

## Lessons + lookbacks

- **Substrate-runtime smoke tests would have caught v1 + v3 + v5.** The audit-yaml schema (P-1) requires `data_flow_traced` and `production_path_verified` fields exactly to surface this class at PR time.
- **The L-12 invariant should have a CI guard.** Inverse-direction is structurally enforced by the channel-narrow; forward-direction is enforced by per-conf inspection only. R-20's CI guard closes the asymmetry.
- **Wireplumber role-based policy needs taxonomy depth.** v4 surfaced the limitation that one media.role can't carry orthogonal destinations. PR #1581's per-destination split is the right architectural answer; the pending operator decision is when to flip Assistant→hapax-private (now safe with the Broadcast role available).
- **Operator-attention to ntfy is fragile in autonomous-overnight mode.** v2's resolution required operator-physical action that didn't happen for ~6 hours. The post-merge-deploy --report-coverage CI workflow (P-4 #1649) catches the structural half of this; the worktree-state surface is a separate operator-visibility concern.

## Cross-references

- v1: `docs/research/2026-04-26-hapax-voice-silence-diagnosis.md`
- v3: `docs/research/2026-04-26-hapax-voice-silence-diagnosis-v3.md`
- L-12 invariant rule: `feedback_l12_equals_livestream_invariant` in `~/.claude/projects/-home-hapax-projects/memory/`
- Absence-class epic: `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md`
- 8-hour audit (the seed): `~/.cache/hapax/relay/research/2026-04-26-8hr-audit.md`
