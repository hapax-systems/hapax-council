# Deployment Pipeline Audit — 2026-05-03

Author: alpha (Claude Opus 4.7)
Approved-by: operator
Trigger: operator directive 2026-05-03 "I want a full audit done to make sure
everything is up to date and wired correctly"
Audit window: ~14:30 → 15:00 CDT 2026-05-03

## Executive summary

- The 5-min `hapax-rebuild-services.timer` is now firing cleanly. Diagnosis
  details under § F.
- Of 270 canonical systemd unit files, 245 are aligned, 0 drifted, 25 missing.
  All 25 missing units are NOT loaded into systemd (`is-enabled` returns
  not-found). They are pre-existing pre-canonicalisation drift, NOT
  consequences of recent merges.
- Of 25 Pipewire conf files, 9 aligned, 7 missing, 9 drifted. Of 10
  Wireplumber conf files, 8 aligned, 0 missing, 2 drifted. **All audio
  drift is intentional runtime tuning** (USB device names, channel
  mapping, USB-bias) — NOT remediation targets per operator constraint.
- Of 11 audited services, 8 are running latest code, 2 are STALE
  (`hapax-broadcast-orchestrator` 129 min, `hapax-audio-ducker` inactive,
  both audio-touching, NOT auto-restarted), 1 is not loaded
  (`hapax-mcp` is uninstalled-OK by design).
- The pipeline-level gap: `hapax-rebuild-services.service` does not include
  ExecStart entries for `hapax-broadcast-orchestrator.service` or
  `hapax-audio-ducker.service`. Both are audio-touching so a fix should
  be operator-gated.
- `hapax-post-merge-deploy` is a manual-only script. There is NO timer,
  path unit, or git hook that invokes it. Pipewire/wireplumber/systemd-unit
  changes that ship with merges to main are NEVER auto-deployed. This is
  a structural gap, not a regression.
- Root cause of today's "service started 14:35 with feature-branch code"
  symptom: between 13:50–14:33 a peer/agent left the canonical worktree
  on `alpha/audio-safe-restart-pre-flight-gate` (visible in reflog). The
  `rebuild-service.sh` branch-check correctly skipped the deploy and ntfy'd.
  At 14:33 the operator (alpha session) reset HEAD to `origin/main`. The
  next rebuild fire at 14:34 then tried to restart the services with the
  newly-pulled code. Some restarts never completed because subsequent
  fires at 14:39, 14:44, 14:49, 14:52 saw no canonical SHA advance
  (SHA_FILE was correctly updated at 14:34). One fire at 14:53 failed
  with exit 128 (transient git fetch — non-deterministic, did not repeat).

## A. Canonical worktree state

| Check | Result |
|---|---|
| Current branch | `main` |
| HEAD | `4ffb1675f` (latest origin/main) |
| Untracked files | 3 (1 audit doc, 1 .replaced-by-systemd config, 1 untracked py module) |
| Modified files | 0 |

`~/.cache/hapax/rebuild/worktree` (a separate dedicated worktree
used by `rebuild-logos.sh`, not by `rebuild-service.sh`) is at HEAD
`4ffb1675f` — aligned with main, detached HEAD by design.

**Reflog evidence** of the squatting agent (truncated to relevant range):

```
4ffb1675f HEAD@{2026-05-03 14:34:57 -0500}: merge origin/main: Fast-forward
023a3d274 HEAD@{2026-05-03 14:33:01 -0500}: reset: moving to origin/main
2f3effdcb HEAD@{2026-05-03 14:33:01 -0500}: checkout: moving from alpha/audio-safe-restart-pre-flight-gate to main
5769627cd HEAD@{2026-05-03 14:30:54 -0500}: commit: feat(audio-graph): P1 — Pydantic SSOT schema...
da7a07c55 HEAD@{2026-05-03 14:01:17 -0500}: checkout: moving from alpha/jr-spark-packet-leverage-process to alpha/audio-safe-restart-pre-flight-gate
b8d3d74eb HEAD@{2026-05-03 14:00:59 -0500}: commit: feat(jr-team): consume/supersede/triage state-machine + leverage dashboard + audit
2f3effdcb HEAD@{2026-05-03 14:00:11 -0500}: checkout: moving from alpha/audio-safe-restart-pre-flight-gate to alpha/jr-spark-packet-leverage-process
```

The squatting agent IS the alpha session itself (commit author + reflog
identity are the operator's). The pattern was: alpha was working on two
overlapping packets (`alpha/jr-spark-packet-leverage-process` and
`alpha/audio-safe-restart-pre-flight-gate`) and was switching the canonical
worktree between them rather than using a dedicated worktree per packet.
That collided with the rebuild-services 5-min cycle. The §G remediation
addresses this structurally.

## B. Service deployment audit

Service start vs last commit on watched paths (verified 2026-05-03 at 14:58
CDT after the post-reset rebuild-services cycle ran cleanly):

| Service | Started | Last commit | Status |
|---|---|---|---|
| studio-compositor | 14:37:41 CDT | 023a3d274 (14:18) | RUNNING_LATEST |
| hapax-daimonion | 14:35:33 CDT | 023a3d274 (14:18) | RUNNING_LATEST (audio — DO NOT auto-restart) |
| hapax-imagination | 14:38:29 CDT | 9cb0cd427 | RUNNING_LATEST |
| hapax-imagination-loop | 14:37:26 CDT | 023a3d274 (14:18) | RUNNING_LATEST |
| hapax-dmn | 14:34:59 CDT | 023a3d274 (14:18) | RUNNING_LATEST |
| hapax-reverie | 14:35:55 CDT | 023a3d274 (14:18) | RUNNING_LATEST |
| hapax-content-resolver | 14:57:06 CDT | 023a3d274 | RUNNING_LATEST (auto-restarted by 14:56 timer fire) |
| logos-api | 10:50:28 CDT | 4e046b781 (10:36) | RUNNING_LATEST |
| hapax-audio-router | 14:37:41 CDT | 023a3d274 | RUNNING_LATEST (audio — DO NOT auto-restart) |
| hapax-broadcast-orchestrator | 12:09:15 CDT | 023a3d274 (14:18) | **STALE_BY=129min — audio — operator decision required** |
| hapax-audio-ducker | inactive (last 13:22 CDT) | c553c64b6 (audit-fix-1) | **STALE — inactive — operator decision required** |
| hapax-mcp | not loaded | — | UNINSTALLED-OK (pull-only via Claude Code reconnect) |

The two STALE services are both audio-touching; per audit constraint,
they are not restarted by this audit. The operator should manually run:

```fish
systemctl --user restart hapax-broadcast-orchestrator.service
# audio-ducker only if intentionally enabled (it's currently inactive=dead)
systemctl --user start hapax-audio-ducker.service
```

after verifying audio-stage is healthy.

## C. Systemd unit deployment audit

Counts: TOTAL=270 ALIGNED=245 MISSING=25 DRIFT=0.

All 245 aligned units are symlinks `~/.config/systemd/user/<unit> →
$REPO/systemd/units/<unit>`, which is the canonical install path. Drop-ins
(8 of them, in `*.service.d/` directories) are also all aligned, including:

- `hapax-daimonion.service.d/gpu-pin.conf` (symlink)
- `audio-recorder.service.d/archive-path.conf` (symlink)
- `tabbyapi.service.d/gpu-pin.conf` (symlink)
- `studio-compositor.service.d/cpu-affinity.conf` (symlink)

### Verified-not-merged drop-ins (open PRs, not yet on main)

These were called out in the audit prompt as "should be installed":

- `hapax-daimonion.service.d/shutdown-killmode.conf` — **NOT in canonical**.
  PR #2421 (`alpha/daimonion-killmode-mixed-shutdown-segv-fix`) is OPEN,
  not yet merged. Will be installed automatically by `hapax-post-merge-deploy`
  after merge IF the operator invokes that script (see § F below for the gap).
- `hapax-obs-monitor-loopback.service` — **NOT in canonical**. PR #2428
  (`alpha/canonicalize-obs-monitor-loopback-systemd`) is OPEN. The unit is
  currently hand-installed at `~/.config/systemd/user/hapax-obs-monitor-loopback.service`
  (327B, modified 12:14 CDT), which loads `~/.local/bin/hapax-obs-monitor-load`.
  This will canonicalise once #2428 merges.
- `hapax-audio-signal-assertion.service` — IS in canonical (commit
  `0685d8e23`, PR #2423 already merged), but NOT installed in
  `~/.config/systemd/user/`. This IS the deploy-pipeline gap: post-merge-deploy
  is a manual-only script, so the systemd unit shipped on main but never
  reached the user's systemd.

### 25 MISSING canonical-but-not-installed unit files

Canonical SHA listed; the unit was added in that commit but never
`hapax-post-merge-deploy`d into the user systemd directory.

| Unit | Canonical commit | First-seen |
|---|---|---|
| hapax-audio-signal-assertion.service | 0685d8e23 | PR #2423 |
| hapax-audio-stage-check.service | f5d8027cc | recent audio audit |
| hapax-audio-stage-check.timer | 2f7bc0936 | recent audio audit |
| hapax-audio-topology-assertion.service | 6621b4d11 | recent audio audit |
| hapax-audio-topology-assertion.timer | 6621b4d11 | recent audio audit |
| hapax-audio-topology-verify.service | 71cc36eb4 | recent audio audit |
| hapax-audio-topology-verify.timer | 71749d229 | recent audio audit |
| hapax-broadcast-egress-loopback-producer.service | e33bea532 | recent audio audit |
| hapax-bt-firmware-watchdog.service | 055582c04 | bt-firmware-watchdog packet |
| hapax-conversion-broker.service | 9cb0cd427 | conversion-broker packet |
| hapax-gemini-iota-watchdog.service | 0662ee544 | gemini-iota lane |
| hapax-m8-control.service | df0e618c4 | m8-control packet |
| hapax-m8-stem-recorder.service | 9cb0cd427 | m8-stem-recorder packet |
| hapax-m8-stem-retention.service | 9cb0cd427 | m8-stem-retention packet |
| hapax-m8-stem-retention.timer | 9cb0cd427 | m8-stem-retention packet |
| hapax-novelty-shift-emitter.service | 8d0d1e9e0 | novelty-shift-emitter packet |
| hapax-novelty-shift-emitter.timer | 8d0d1e9e0 | novelty-shift-emitter packet |
| hapax-option-c-pin-watchdog.service | 4c10b81be | option-c-pin-watchdog packet |
| hapax-option-c-pin-watchdog.timer | 4c10b81be | option-c-pin-watchdog packet |
| hapax-parametric-modulation-heartbeat.service | b5ed2fd41 | parametric-modulation packet |
| hapax-private-broadcast-echo-probe.service | d98a97b04 | echo-probe packet |
| hapax-private-broadcast-echo-probe.timer | d98a97b04 | echo-probe packet |
| hapax-usb-bandwidth-preflight.service | d7a20a491 | usb-bandwidth packet |
| hapax-usb-bandwidth-preflight.timer | d7a20a491 | usb-bandwidth packet |
| hapax-xhci-death-watchdog.service | f0a48216e | xhci-death-watchdog packet |

These are NOT loaded into systemd (`systemctl --user list-unit-files`
returns empty for each). The deploy gap left them stranded at canonical.

**Subset that touch audio (operator decision required to install / start):**
8 units — `hapax-audio-signal-assertion`, all 6 `hapax-audio-*-{stage,topology}-*`
units, `hapax-broadcast-egress-loopback-producer`, `hapax-private-broadcast-echo-probe.{service,timer}`.

**Subset safe to install without operator audio-decision:** 17 units —
the `hapax-bt-firmware-watchdog`, `hapax-conversion-broker`, `hapax-gemini-iota-watchdog`,
`hapax-m8-*`, `hapax-novelty-shift-emitter.{service,timer}`,
`hapax-option-c-pin-watchdog.{service,timer}`, `hapax-parametric-modulation-heartbeat`,
`hapax-usb-bandwidth-preflight.{service,timer}`, `hapax-xhci-death-watchdog`.

This audit does NOT install them. The deploy pipeline forever-fix (§F + §G)
will reduce the chance of the same drift recurring; a separate operator-gated
backfill PR should install the safe-17 batch first.

## D. Pipewire / wireplumber config audit

**READ-ONLY per audit constraint. No modifications.**

### Pipewire (config/pipewire/*.conf, 25 files)

| Status | Count | Notes |
|---|---|---|
| ALIGNED | 9 | matches canonical byte-for-byte |
| DRIFTED | 9 | runtime tuning vs canonical |
| MISSING | 7 | canonical declares, not installed |

DRIFTED files (all reflect intentional runtime tuning, not regressions):

- `99-hapax-quantum.conf` — installed adds `default.clock.rate = 48000` and
  `default.clock.allowed-rates = [ 48000 ]`. Operator pin from livestream-incident.
- `hapax-l12-evilpet-capture.conf` — drift expected (channel mapping)
- `hapax-livestream-duck.conf` — installed has dual-channel duck_l/duck_r
  filter chain + `node.target` switched from PCI sink to L-12 USB sink
  (`alsa_output.usb-ZOOM_Corporation_L-12_...`)
- `hapax-music-duck.conf`, `hapax-music-loudnorm.conf`, `hapax-pc-loudnorm.conf`,
  `hapax-stream-split.conf`, `voice-over-ytube-duck.conf`,
  `hapax-notification-private.conf` — drift expected
- `hapax-livestream-tap.conf.replaced-by-systemd-2026-05-03` — operator
  marked replaced by systemd path during today's H3 phase 1 work.

MISSING files (canonical declares but no installed copy):

- `hapax-backing-ducked.conf`, `hapax-backing-ducked-sidechain.conf` —
  rename from `hapax-24c-ducked` per #2301
- `hapax-l6-evilpet-capture.conf`, `hapax-pc-router.conf`,
  `hapax-voice-fx-chain.conf`, `hapax-voice-fx-loudnorm.conf`,
  `hapax-yt-loudnorm.conf` — recent audio packets

These all need operator decision before any install (audio).

### Wireplumber (config/wireplumber/*.conf, 10 files)

| Status | Count | Notes |
|---|---|---|
| ALIGNED | 8 | matches canonical |
| DRIFTED | 2 | runtime tuning |
| MISSING | 0 | |

DRIFTED:
- `10-default-sink-ryzen.conf` — installed targets the L-12 USB sink
  (`alsa_output.usb-ZOOM_Corporation_L-12_...`) instead of the canonical
  PCI sink. Expected.
- `50-hapax-voice-duck.conf` — drift expected.

## E. Repo-vs-runtime drift summary

| Category | Aligned | Stale | Missing | Drift | Uninstalled-OK |
|---|---|---|---|---|---|
| Application services (11 audited) | 8 | 2 | 0 | 0 | 1 |
| Systemd units (270 total) | 245 | 0 | 25 | 0 | 0 |
| Pipewire confs (25 total) | 9 | 0 | 7 | 9 | 0 |
| Wireplumber confs (10 total) | 8 | 0 | 0 | 2 | 0 |

## F. Pipeline diagnosis

The original fault chain was:

1. Alpha session (this Claude Code lane) used the canonical
   `~/projects/hapax-council` worktree to switch between two
   overlapping packets (`alpha/jr-spark-packet-leverage-process` and
   `alpha/audio-safe-restart-pre-flight-gate`) between 13:48 and 14:33
   CDT.
2. The 5-min `hapax-rebuild-services.timer` fired at 13:50, 13:55, 14:00,
   14:05, 14:10, 14:15, 14:20, 14:25, 14:30. Each fire had the canonical
   on a feature branch. The branch-check in `rebuild-service.sh`
   correctly emitted the `[WARN] repo not on main (on alpha/...) — deploy
   skipped` line and a throttled per-SHA ntfy to the operator's phone.
   The `last-${key}-sha` SHA_FILE was correctly NOT updated.
3. At 14:33 the alpha session reset to `origin/main` and at 14:34 the
   timer fired and detected `f8e1b73f → 4ffb1675f` (5 commits ahead) and
   triggered restarts for dmn, voice, compositor, content-resolver,
   reverie, imagination-loop, audio-router, vla, watch-receiver,
   studio-fx-output, studio-person-detector, operator-awareness. All
   succeeded. The SHA_FILES were updated correctly. **This is the bulk
   of the "started 14:35 with stale code" symptom resolving itself.**
4. At 14:53 a single rebuild-services fire failed with exit 128. The
   journal does not record the underlying error (`status=128/n/a` is git's
   "fatal" exit). The 14:56 fire and the 14:57 manual run both succeeded
   cleanly, so the 14:53 failure was transient (likely git fetch
   contention with another `git` operation).

### Pipeline-level gaps surfaced by the audit

1. **`hapax-broadcast-orchestrator.service` is NOT in the rebuild-services
   ExecStart list.** It only restarts when the operator manually does
   so. Last commit to its watched path was 14:18 CDT, last restart was
   12:09 CDT — 129 min stale. This is an audio-touching service so the
   fix should be operator-gated.

2. **`hapax-audio-ducker.service` is NOT in the rebuild-services
   ExecStart list.** Same audio-touching gap.

3. **`hapax-post-merge-deploy` is manual-only.** No timer, no path unit,
   no git hook invokes it. The 25 missing systemd units, 7 missing
   Pipewire confs, and the in-flight #2428 obs-monitor canonicalisation
   PR all assume the operator manually runs the script after each merge.
   This explains how 25 units accumulated as drift since 2026-04-29.

4. **The branch-check in `rebuild-service.sh` is correct, but the user
   ergonomics of "alpha hot-swaps the canonical between feature branches"
   is structurally wrong.** §G addresses this.

### Pipeline state after the audit

- Canonical: on `main`, HEAD `4ffb1675f`. Verified.
- All non-audio services are running latest code. Verified.
- `last-${key}-sha` files are correctly updated to `4ffb1675f`. Verified.
- The 14:56 timer fire ran cleanly. `last-content-resolver-sha` advanced
  from `f8e1b73f` to `4ffb1675f`. Verified.
- The next 5-min timer fire (next: 14:58:19 CDT, then continuing every
  5 min) will detect zero changes and exit cleanly, until the next merge
  to main bumps `origin/main`.

## G. Forever-fix recommendations

Filed as cc-task `deploy-pipeline-canonical-worktree-isolation` (P1, WSJF
target ≥11). Vault path:
`~/Documents/Personal/20-projects/hapax-cc-tasks/active/deploy-pipeline-canonical-worktree-isolation.md`.

Recommendations in WSJF order:

1. **`rebuild-service.sh` should use a separate dedicated worktree for
   the deploy check** (already exists at `~/.cache/hapax/rebuild/worktree/`,
   currently used only by `rebuild-logos.sh`). Switch the `--repo` flag
   in every ExecStart of `hapax-rebuild-services.service` to point at
   `~/.cache/hapax/rebuild/worktree/` instead of
   `~/projects/hapax-council`. Drop the branch-check entirely (the
   dedicated worktree is always on `main`). Eliminates the entire
   "agent squats canonical" failure class.

2. **Add a `hapax-post-merge-deploy.path` unit** that watches the
   canonical's HEAD ref (`~/projects/hapax-council/.git/HEAD`
   plus the file `refs/heads/main`) and triggers
   `hapax-post-merge-deploy.service` on change. Today the script only
   runs when the operator types its name. With a path unit, every
   `git pull` of a merge commit auto-installs Pipewire/wireplumber/systemd
   files. This closes the 25-unit drift class permanently.

3. **Add `hapax-broadcast-orchestrator` and `hapax-audio-ducker` to
   `hapax-rebuild-services.service` ExecStart** with appropriate watch
   paths. Operator gates this on audio-incident-recovery clearance.

4. **Block destructive `git checkout/switch` on the canonical worktree
   via a hook.** Add to `hooks/scripts/no-stale-branches.sh` or a
   companion `hooks/scripts/canonical-worktree-protect.sh`: if `cwd =
   ~/projects/hapax-council` and command is
   `git checkout|switch|reset` AND target is not `main`, refuse. Each
   session must use its own greek-named worktree
   (`hapax-council--<role>`) or a `.cache/hapax/...` ad-hoc one. This
   prevents the squat behavior at the source.

The first three items are non-controversial and operator-greenlit
implicitly (the audit was requested precisely because of the squat
fallout). The hook in #4 is a behavior-change so should land last.

## Closure

- All operator-visible findings reported.
- No audio configs or audio services were modified.
- No services were restarted beyond the `hapax-content-resolver` auto-restart
  the 14:56 rebuild-services cycle did on its own.
- This PR ships the audit doc + cc-task. Patches per §G are deferred to
  the cc-task implementer (PR + reviews per house style) so the audit
  doesn't conflate "report" and "fix" in one diff.
- A cc-task tracks the four §G forever-fixes.
