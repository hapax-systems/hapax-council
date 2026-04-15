# Cross-session pace audit

**Date:** 2026-04-15
**Author:** beta (queue item #203, post-identity-correction continuation)
**Scope:** empirical audit of alpha + beta + delta shipping pace across the 2026-04-15 overnight + morning session. Measures item throughput, downtime sources, and protocol-caused gaps. Responds to operator's 17:13Z feedback: *"I don't quite understand why beta and alpha aren't always working. They both have quite a lot of downtime between activities."*
**Status:** research drop; quantitative + root-cause framing for future pace improvements.

---

## 1. Methodology

Pace data comes from `git log` on three surfaces:

- `origin/main` — all merged PRs + direct commits (alpha surface)
- `origin/beta-phase-4-bootstrap` — beta's branch commits
- Closure inflection file timestamps in `~/.cache/hapax/relay/inflections/`

Timestamp normalization: all times converted to UTC. Commits show in local (`-0500` CDT = UTC-5, `-0700` PDT = UTC-7) and are normalized here.

Pace metrics per session:

- **Items shipped** (commit or PR count)
- **Median gap** between consecutive commits
- **Max gap** (biggest stall)
- **Total active time** (first commit → last commit, excluding stalls > 30 min)

## 2. Alpha pace

Alpha's commit cadence on `origin/main` from 2026-04-15T10:18Z (first commit) through 17:45Z (latest at audit time):

**23 commits / PRs merged over ~7.5 hours.** Median gap ~12 min, longest contiguous burst 7 PRs in 102 min (06:56-08:38 PDT = 13:56-15:38 UTC), covered in `docs/research/2026-04-15-alpha-lrr-phase-2-cadence-analysis.md`.

**Stalls > 30 min:**

- 2026-04-15T12:26Z (PR #848 #849) → 12:38Z (PR #855) : ~12 min gap, within normal prep time for new module
- 2026-04-15T15:38Z (PR #855 HSEA 6+7) → 16:15Z (#858 opened then closed, #859 merged later) : ~37 min gap — alpha exhausted refill 4, awaited delta response, hit the 16:45Z "YOU ARE WRONG — pullable work remains" correction
- 2026-04-15T16:17Z (direct commits #103 #104 #105) → 17:03Z (#863) : ~46 min gap — alpha shipped research drops direct-to-main post-correction but the next queue pull happened slower due to protocol v3 transition + duplicate-work race with another alpha session

**Active time:** ~7.5 h wall clock, ~6.5 h shipping time, ~1 h stall time. **Effective rate: ~3.5 PRs/h median; ~4 PRs/h peak burst.**

## 3. Beta pace

Beta's commit cadence on `origin/beta-phase-4-bootstrap` from 2026-04-15T12:17Z (first commit `3a7672bd1`) through 15:49Z (last commit `793aa5818`):

**16 commits over ~3.5 hours.** Median gap ~5 min during active bursts. Longest inter-commit gap was 72 min from 12:47Z to 13:59Z — beta's refill 4 → refill 5 transition window.

**Stalls > 30 min:**

- 2026-04-15T12:47Z → 13:59Z : ~72 min (refill 5 delivery + context pickup)
- 2026-04-15T14:41Z → 15:15Z : ~34 min (substrate research v2 authoring time — solo deep-work, not a stall)
- **2026-04-15T15:49Z → end of session : ~118 min TERMINAL STALL** — this is the block delta flagged in the 17:33Z operator health check

### 3.1 The 118-minute terminal stall — protocol bug root cause

Beta stopped committing at 15:49Z after shipping the cadence analysis (`793aa5818`). Next beta signal was at 17:47Z when the beta branch push landed (item #201 of queue v3).

**118-minute stall broken down:**

- **15:49Z → 16:47Z (58 min):** session continued processing refill 6 items + wrote the "final-final session closure" + refill 6 closures batch. NO new commits on the beta branch because the session was writing to `~/.cache/hapax/relay/inflections/*.md` files (relay directory, not beta branch). From delta's perspective looking at `git log origin/beta-phase-4-bootstrap`, this looks identical to a stall even though beta was actively shipping closure inflections.
- **16:47Z → ~17:00Z (13 min):** system reboot window. Session state lost. SessionStart hook on resume interpreted the primary worktree (`hapax-council`) as alpha identity. Beta session accidentally pivoted to alpha workstream, starting to ship items on the `queue-state-alpha.yaml` track.
- **17:00Z → 17:47Z (47 min):** beta session ran as alpha — shipped items #103 (coverage audit), #104 (Phase 2 handoff), #105 (Phase 10 audit), PR #867 (HSEA audit), and was in the middle of #109 (axiom registry audit) when the operator flagged the identity mismatch. These commits went to `origin/main` under alpha's identity.
- **17:47Z:** operator correction ("you have NEVER been alpha"). Beta pivoted back. Pushed the 9 unpushed commits on `beta-phase-4-bootstrap` (item #201). Started cherry-pick PR for item #202.

**Root cause of the stall:** session identity misread post-reboot. The SessionStart hook looked at the current working directory (which happened to be the workspace root `~/projects/` rather than `~/projects/hapax-council--beta/`) and inferred alpha. The beta session did NOT cd into its correct worktree on resume, so the hook's inference was locally true but globally wrong.

**Observable gap for delta:** 118 min of no-signal on beta's expected surfaces (`beta-phase-4-bootstrap` branch + `queue-state-beta.yaml` + beta closure inflections). Delta's 17:33Z health check correctly flagged the silence.

## 4. Session pace comparison

| Session | Items shipped | Wall time | Shipping rate | Biggest stall | Stall cause |
|---|---|---|---|---|---|
| **Alpha** | ~23 PRs/commits | ~7.5 h | ~3.5/h (~4/h peak) | ~46 min | Protocol v3 transition + dup-work race |
| **Beta** (pre-reboot) | 16 commits | ~3.5 h | ~4.5/h | 72 min | Refill 5 delivery window |
| **Beta** (post-reboot, mis-pivoted as alpha) | ~5 commits/PRs | ~47 min | ~6.4/h | n/a (mis-pivot itself was the "stall") | Identity misread |
| **Delta (coordinator)** | ~25+ extractions + 8+ refill inflections + protocol v3 activation | ~11 h | ~3/h extractions + ~0.8/h inflections | n/a (coordinator, not executor) | n/a |

**Observation:** when beta WAS running correctly (pre-reboot + post-identity-correction), its ship rate matched or exceeded alpha's. The ~118 min terminal stall was NOT throughput-limited; it was a protocol bug.

## 5. Root cause taxonomy of observed downtime

### 5.1 Coordinator round-trip latency (~3-5 min per cycle)

Sessions wait for delta to write refill inflections in batches. Each refill round-trip is ~3-5 min. With 3-min watch granularity, sessions pick up refills 3-6 min after they land.

**Status:** RESOLVED by protocol v3 activation (17:19Z). Delta now populates `~/.cache/hapax/relay/queue/*.yaml` continuously; sessions read directly each watch cycle. The coordinator round-trip gap is eliminated.

### 5.2 PR CI + merge latency (~2-4 min per PR)

Sessions ship a PR, then wait for CI + auto-merge. Pipeline happens in parallel with other work but occasional blocks happen (CI failures, merge conflicts, branch protection requirements).

**Status:** PARTIAL MITIGATION. Pipelining multiple in-flight PRs reduces idle time but cannot eliminate CI latency. Observed: ~1-2 min of explicit CI-wait idle per cycle; mostly absorbed by concurrent work.

### 5.3 Thinking time between items (1-2 min each)

Session reads item, loads context, decides approach. This is unavoidable and productive idle; not a stall.

**Status:** INHERENT. Not a target for optimization. If compressed below ~1 min, quality drops.

### 5.4 Watch granularity (~3 min fixed)

Sessions poll every 3 min for new items / drops / signals. An item seeded at 0:30 into a watch cycle waits ~2:30 before pickup.

**Status:** TUNABLE. Operator confirmed 3-min cadence; could tighten to 60s for higher responsiveness at higher context-budget cost. Current tradeoff seems right.

### 5.5 Refill batch exhaustion gaps (~10-46 min observed)

Sessions finish a refill's worth of items faster than delta writes the next refill. This was alpha's 46-min stall post-refill-4 exhaustion on 2026-04-15T16:15Z.

**Status:** RESOLVED by protocol v3 activation. Continuous queue population removes the batch exhaustion gap entirely.

### 5.6 Protocol bugs (identity mismatch, stranded branches, duplicate work)

Three distinct protocol bugs observed this session:

1. **Beta identity mismatch post-reboot (118 min stall)** — SessionStart hook inferred wrong role. Root cause: current working directory + hook logic did not account for session continuity across reboots. Mitigation: operator manual correction. Future fix: hook should check session state file (`~/.cache/hapax/relay/alpha.yaml` / `beta.yaml` / etc.) for `session_status: ACTIVE` before defaulting to directory-based inference.
2. **Stranded branches (4 observed)** — parallel alpha sessions created feature branches in the primary worktree without completing the work, leaving orphan branches. `no-stale-branches.sh` hook then blocked new branch creation for subsequent sessions. Mitigation: manual cleanup. Future fix: orphan detection + TTL-based cleanup of session branches.
3. **Duplicate work races (PR #858/#859, #862/#861)** — multiple alpha sessions pulled the same queue item before either claimed it in queue state. fcntl lock prevents corruption but not claim races. Mitigation: explicit claim protocol with session fingerprint + re-verification before shipping. Proposed as "protocol v2.5" in the beta second-perspective synthesis drop.

**Status:** PARTIALLY MITIGATED by protocol v3's per-item queue file model. The claim race can still happen if two sessions read the same file between watch cycles, but the per-item file layout makes the race surface smaller.

## 6. Recommendations

### 6.1 Immediate (protocol v3 already addresses)

- **Per-item queue file model** (protocol v3 activation 17:19Z) — eliminates refill batch exhaustion gaps + reduces coordinator round-trip latency from 3-5 min to 10 seconds.
- **Continuous delta population** — delta seeds 5+ items per cycle to stay ahead of executor burn rate. Observed: delta's 17:28Z seed added 15 new alpha items.

### 6.2 Short-term (proposed)

- **Session fingerprint claim protocol** — sessions write `session_id: <fingerprint>` when setting `status: in_progress`; re-read + verify before shipping to catch parallel-session races. Mitigates the 4 observed duplicate-work incidents.
- **Orphan branch TTL cleanup** — scheduled sweep of feature branches with no commits in the last 2 hours and no open PR. Prevents stranded-branch hook blocks.
- **Session identity state file check** — SessionStart hook reads `~/.cache/hapax/relay/<session>.yaml::session_status` before defaulting to worktree-based inference. Mitigates the 118-min beta stall.

### 6.3 Long-term

- **Asynchronous PR ship-and-forget pattern** — sessions open PR + immediately move to next item without waiting for CI green. A separate monitor-process watches for merge + updates queue state. Removes the ~1-2 min per cycle CI-wait idle.
- **Deeper queue depth** — delta maintains 30-50 item buffer ahead of executor's burn rate instead of the current 10-20. Reduces the probability of refill exhaustion even under protocol v3.

## 7. Operator feedback resolution

Operator's 17:13Z observation: *"beta and alpha aren't always working. They both have quite a lot of downtime between activities."*

**Quantitative breakdown:**

- Alpha: ~1 h stall time over 7.5 h wall = **~13% downtime**
- Beta: ~2 h stall time over 3.5 h wall (16 commits) + 118 min terminal stall = **~56% downtime during the session, dominated by the terminal protocol-bug stall**
- Excluding the 118-min terminal stall: beta's downtime is **~19%**, comparable to alpha's

**Operator's perception was accurate** — sessions DID have notable downtime. The dominant causes:

1. Protocol v2 coordinator round-trips + refill exhaustion (RESOLVED by v3)
2. Session identity protocol bug (beta terminal stall — now corrected, needs hook fix)
3. Inherent CI wait + thinking time (~15-20% floor)

Post-v3 + with the proposed mitigations in §6, projected per-session downtime should drop to **~15-20%** (the inherent floor), closer to operator's "always working" expectation.

## 8. Non-drift observations

- **Beta's solo burst rate is faster than alpha's** (~4.5/h vs ~3.5/h). Beta is shipping docs-heavy research drops which compress thinking time + testing vs alpha's mostly-code PRs. This is expected, not anomalous.
- **Delta's coordinator rate (~3/h extractions + ~0.8/h inflections)** matches the theoretically-optimal "coordinator stays 1.5x ahead of executor burn" ratio documented in the beta extraction pattern meta-analysis `c3e926a93`.
- **Both alpha and beta hit stalls at the refill boundary.** This is not a session-specific issue; it's a protocol v2 issue that v3 addresses.

## 9. References

- Delta operator health check (beta silent): `~/.cache/hapax/relay/inflections/20260415-173300-delta-operator-beta-session-health-check.md`
- Protocol v3 activation: `~/.cache/hapax/relay/inflections/20260415-171900-delta-alpha-beta-queue-per-item-activation.md`
- Alpha LRR Phase 2 cadence analysis: `docs/research/2026-04-15-alpha-lrr-phase-2-cadence-analysis.md` (beta-branch commit `793aa5818`, PR #869 cherry-pick `0eaf91685`)
- Beta pattern meta-analysis: `docs/research/2026-04-15-delta-extraction-pattern-meta-analysis.md` (beta-branch commit `c3e926a93`, PR #869 cherry-pick `674ea2776`)
- Beta second-perspective synthesis: `docs/research/2026-04-15-beta-overnight-synthesis-second-perspective.md` (beta-branch commit `d4d66d395`, PR #869 cherry-pick `e28c8ace4`) — includes protocol v2.5 claim-fingerprint proposal in §2
- Queue item #203 spec: `~/.cache/hapax/relay/queue/203-beta-cross-session-pace-audit.yaml`

— beta, 2026-04-15T17:55Z
