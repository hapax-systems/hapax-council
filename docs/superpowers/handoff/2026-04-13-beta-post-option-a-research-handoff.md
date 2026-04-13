# Beta Session Retirement Handoff — Post-Option-A Research (Queue 023)

**Session:** beta
**Worktree:** `hapax-council--beta` @ `research/post-option-a` (off main `b57c12d28`)
**Date:** 2026-04-13, 16:48–17:25 CDT
**Queue item:** 023 — post-option-a-stability
**Depends on:** Queue 022 (PR #752 merged)
**Inflection:** `20260413-214200-alpha-beta-post-option-a-research-brief.md`
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## One-paragraph summary

Beta completed a six-phase post-Option-A stability + observability
deep-dive research pass. All six phases shipped deliverables. Three
convergence-critical findings were filed live during the session:

1. **PR #751 TTS UDS delegation is a 100 % failure path on the
   compositor side** — 15 consecutive 30-second synthesize timeouts
   observed across two PIDs, with zero inbound-request log lines on
   the daimonion side. The "speak-react at parity latency" claim in
   the finding doc is refuted. Regression alert logged to
   `convergence.log` at 17:16:45 CDT.
2. **The full-stack Prometheus metric surface has two major
   blackhole patches** — `studio_compositor :9482` is not in any
   scrape job (`series_count({__name__=~"studio_.*"})=0`) and
   `node-exporter :9100` scrape is broken. The entire
   `studio-cameras.json` Grafana dashboard is end-to-end dead; host
   OS metrics are entirely absent.
3. **The budget_signal dead path is wider than PR #752 reported** —
   `BudgetTracker` itself is instantiated nowhere in production, so
   both `publish_costs` and `publish_degraded_signal` are
   wired-but-never-called (not just missing a consumer). The whole
   Phase 7 budget enforcement layer is dormant. Recommendation:
   formal retirement (Option B).

Option A itself (PR #751 libtorch removal) is confirmed effective —
libtorch mappings 35 → 0 and stayed at 0 on every post-fix PID.
The compositor address space shrank by >14 GB. Secondary memory
growth is present at ~3.3 MB/min but not dominant.

## Phase ship record

| phase | doc | status | acceptance |
|---|---|---|---|
| 1 — long-duration stability | `phase-1-long-duration-stability.md` | **shipped (partial)** | met for libtorch-gone confirmation, secondary-leak characterization, three-process trajectory; NOT met for 2-hour uninterrupted window (external restarts at 17:01 + 17:16 prevented it) |
| 2 — cameras_healthy gauge | `phase-2-cameras-healthy-gauge.md` | **shipped** | met — reproduction + line-level fix diff + consumer survey + severity re-rating |
| 3 — budget_signal dead path | `phase-3-budget-signal-dead-path.md` | **shipped** | met — git archaeology + two wiring options + recommendation |
| 4 — fault injection | `phase-4-fault-injection-timings.md` | **shipped (class A via natural experiment, B/C/D documented plan)** | met for class A; B/C/D require live coordination deferred to next session |
| 5 — audio + A/V latency | `phase-5-audio-av-latency.md` | **shipped (partial)** | met for live TTS regression evidence + Kokoro + pipewire + RTMP state; A/V latency deferred (MediaMTX + operator action) |
| 6 — metric surface audit | `phase-6-metric-surface-audit.md` | **shipped** | met — 19 endpoints enumerated, classified, ranked gap list |

Supporting data:

- `data/baseline/t0-snapshot.txt` — smaps_rollup + lib family counts + cgroup state at baseline
- `data/repro_cameras_healthy.py` — minimal reproduction harness for the Phase 2 bug
- `data/repro_cameras_healthy.out` — observed output (all 6 scenarios reporting `cameras_healthy=0.0`)
- alpha-owned sampler: `~/.cache/hapax/compositor-leak-2026-04-13/memory-samples-post-fix.csv` (40 rows, 3 PID spans)

## Convergence-critical findings

### BETA-FINDING-G: PR #751 TTS UDS delegation has a 100 % failure rate on the compositor side

**Severity:** HIGH — blocks the main operator-value claim of PR #751.
**Observed window:** 17:00:17 → 17:16:02 CDT (16 minutes).
**Evidence:** 15 consecutive `tts client: synthesize timed out after
30.0s` warnings across PIDs 2913194 and 3145327. Zero `tts_server` or
`tts client` log lines on the daimonion side since startup at
16:38:59. UDS socket at `/run/user/1000/hapax-daimonion-tts.sock`
exists with mtime 16:38 and has not been touched since. Daimonion
CPAL is alive and producing `process_impingement` logs throughout
the window.

**Root cause hypotheses** (ordered by likelihood):
1. asyncio lock contention between CPAL's voice loop and the new
   TtsServer UDS handler on the shared `TTSManager` singleton
2. socket-accept loop wedged by a dead-client coroutine
3. JSON-header parse hanging on partial reads

**Consequence.** The compositor's director_loop logs REACT text
continuously but produces no audio output. Downstream viewers see
shader state changes without narration. The finding-doc
verification condition "speak-react preserved at parity latency" is
refuted — parity latency is currently infinite.

**Convergence log:** `2026-04-13T17:16:45-05:00 | REGRESSION_ALERT`.

### BETA-FINDING-H: `studio-compositor :9482` is not in the Prometheus scrape config

**Severity:** HIGH — all 15 compositor metric series are invisible
to the monitoring stack. The `studio-cameras.json` Grafana dashboard
is end-to-end dead.

**Evidence:**
```text
$ curl -s 'http://127.0.0.1:9090/api/v1/label/__name__/values' | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print(sum(1 for n in d['data'] if n.startswith('studio_')))"
0
```
`prometheus.yml` enumerated in Phase 6 has 8 scrape jobs, none
targeting port 9482. `studio-cameras.json` has 12 panels querying
`studio_*` metrics, all of which return empty series vectors.

**Secondary consequence**: queue 022's BETA-FINDING-E ("Grafana panel
0 displays wrong number") is half-wrong. Panel 0 queries
`sum(studio_camera_state{state="healthy"})`, not the broken
`studio_compositor_cameras_healthy` gauge. With no scrape, panel 0
shows "No data" regardless. The bug is real but has zero operational
impact today because the gauge has zero consumers. See Phase 2 for
the re-rating.

**Fix:** add a `studio-compositor` scrape job (5 lines of yaml +
prometheus restart). Phase 6 provides the config snippet.

### BETA-FINDING-I: `BudgetTracker` itself is dormant, not just `publish_degraded_signal`

**Severity:** MEDIUM (correctness) — the scope of the half-merge is
larger than queue 022 reported.

**Evidence:** `grep -rn 'BudgetTracker(' agents/` returns production
call sites only in `cairo_source.py:27` (TYPE_CHECKING import) and
`cairo_source.py:94` (kwarg with default `None`). The three
production sites that construct CairoSourceRunner
(`source_registry.py:103`, `overlay_zones.py:373`,
`sierpinski_renderer.py:349`) all omit `budget_tracker=`, so every
runner gets the default `None`. Therefore `tracker.record()` is
never called outside tests, `tracker.snapshot()` returns empty, and
both `publish_costs` and `publish_degraded_signal` would write
empty JSON if they were called — which they are not, because they
have no production callers either.

**Consequence.** The entire Phase 7 budget-enforcement layer is
dormant in production. Alpha's PR #754 adds `FreshnessGauge` wrappers
that surface the dead-path state to Prometheus but does not wire
it. Phase 3 recommends Option B (formal retirement) over Option A
(resurrect).

### BETA-FINDING-J: Compositor post-fix steady-state RSS is not ~1.09 GB

**Severity:** INFORMATIONAL — reframes the post-fix baseline.

**Evidence:** Three post-fix processes observed. PID 2913194
stabilized at ~1.15 GB. PID 3145327 stabilized at ~4.44 GB — a 4×
difference driven by different graph plan activation paths. The
1.09 GB value alpha reported is the first sample of PID 2913194 at
T+2 minutes before warmup completed. Secondary linear growth at
~3.3 MB/min is present on both processes but below the brief's
5 MB/min leak threshold.

**Consequence.** Option A is confirmed working (libtorch = 0) but
the "1.09 GB post-fix baseline" headline should be revised to
"1.1–4.4 GB post-fix steady state, depending on graph plan and
warmup path, with ~3.3 MB/min residual growth." See Phase 1.

## Ranked fix backlog (extends PR #752's 16-item list)

Ordered by operator impact, continuing the numbering from PR #752's
retirement handoff (which ended at item 16):

### High

17. **`fix(daimonion): TTS UDS server hangs on every compositor
    request (PR #751 regression)`** [Phase 5] — 15/15 failure rate.
    Most load-bearing fix in the post-Option-A backlog. See
    BETA-FINDING-G for hypothesis ordering.
18. **`fix(monitoring): add studio-compositor scrape job to
    prometheus.yml`** [Phase 6] — 5 lines of yaml, zero risk, fixes
    the entire studio-cameras dashboard end-to-end.
19. **`fix(monitoring): diagnose + fix node-exporter scrape gap`**
    [Phase 6] — likely a host-side firewall (nftables) rule for
    port 9100 from docker bridge interfaces. Diagnostic command:
    `sudo nft list ruleset | grep -E '(9100|9835|8051)'`.
20. **`feat(daimonion): in-process Prometheus exporter`** [Phase 6]
    — port 9483, ~300 lines. Covers CPAL state, TTS latency, STT
    latency, watchdog, VRAM, affordance counts. Would also have
    made BETA-FINDING-G observable within 30 s instead of needing
    a half-hour speculative trace.
21. **`feat(vla): in-process Prometheus exporter`** [Phase 6] — port
    9484. Per-dimension values, stance transitions, per-backend
    freshness.
22. **`feat(imagination): Prometheus exporter via Rust prometheus
    crate`** [Phase 6] — this is alpha's task #10 already; phase 6
    strengthens the case. Pool metrics + shader compile timing +
    frame-time histogram.

### Medium

23. **`chore(compositor): Phase 3 retire — delete budget_signal.py,
    budget.py (retain atomic_write_json helper only),
    test_budget.py, test_budget_signal.py, remove
    CairoSourceRunner budget_tracker kwarg`** [Phase 3] — Option B
    recommended. Coordinates with alpha's PR #754 rebase to drop
    the `_PUBLISH_DEGRADED_FRESHNESS` wrapper before merge.
24. **`fix(metrics): studio_compositor_cameras_healthy accumulator`**
    [Phase 2] — six-line diff with `_healthy_roles: set[str]`
    accumulator + tests + `shutdown()` refresh. Severity re-rated
    LOW because no downstream consumer; worth shipping for
    correctness.
25. **`feat(compositor): `studio_compositor_memory_footprint_bytes{kind}`
    gauge`** [Phase 1, Phase 6] — in-process replacement for
    alpha's external sampler CSV. Polls `/proc/self/status` every
    30 s. Removes PID-tracking race during restarts. Carried
    forward from PR #752 backlog.
26. **`feat(monitoring): initial Prometheus alert rules`** [Phase 6]
    — at minimum `up == 0 for 2m`, compositor watchdog freshness,
    GPU/system memory, budget_freshness (if not retired).
27. **`fix(monitoring): change litellm scrape path to /metrics/`**
    [Phase 6] — one-line yaml change; current config relies on 307
    redirect follow.
28. **`feat(logos-api): application-level metrics beyond process_*`**
    [Phase 6] — agent runs, LLM call counts, consent-gate denials,
    affordance recruitment counts.
29. **`feat(officium-api): application-level metrics`** [Phase 6] —
    same gap as logos-api.
30. **`research(compositor): Phase 1 uninterrupted 2-hour window
    re-run once #17 lands and the compositor is not being
    restarted externally`** [Phase 1] — linear regression needs
    continuous data to disambiguate "leak" vs "asymptotic plateau"
    on the 3.3 MB/min slope.
31. **`fix(compositor): per-shader-slot memory accounting during
    graph-plan activation`** [Phase 1] — PID 2913194's +792 MB step
    at graph activation and PID 3145327's +1.35 GB step both
    correlate with shader recompilation events. Each slot appears
    to cost ~100 MB. Investigate `effect_graph.pipeline.activate_plan`.

### Low

32. **`feat(compositor): `compositor_tts_client_timeout_total`
    counter`** [Phase 5, Phase 6] — 15/15 failures went unobserved
    by Prometheus. A one-line Counter in `tts_client.py` would
    have surfaced the regression via dashboard rate rules.
33. **`feat(compositor): TTS fallback path when daimonion UDS fails
    3 consecutive requests`** [Phase 5] — a shallow retry budget +
    fallback that preserves silence-with-log rather than
    silence-with-timeout-stall. Preserves stream quality during
    daimonion restarts.
34. **`fix(compositor): expose `studio_rtmp_bin_state` gauge with
    values {unbuilt, connecting, connected, failed}`** [Phase 5] —
    currently `studio_rtmp_connected` has no value line at all
    (Gauge never `.set()`). A state gauge documents the "native
    RTMP bin never constructed" case explicitly.
35. **`fix(compositor): rename "Failed to allocate a buffer" error
    message`** [Phase 4] — the v4l2 error is actually a device
    disappear, not a memory exhaustion. Renaming prevents future
    sessions from chasing the wrong hypothesis.
36. **`research(compositor): microsecond-precision fault recovery
    timing`** [Phase 4] — current natural-experiment dwell times
    are all below the 1 ms journal resolution floor. `time.monotonic_ns()`
    instrumentation + a histogram is needed to see how much below.
37. **`fix(compositor): expose `BACKOFF_CEILING_S` as a per-role
    parameter`** [Phase 4] — brio-room (physical reset is slow)
    could use a longer ceiling than fast C920s.
38. **`feat(vla): compositor_degraded stimmung backend`** [Phase 3,
    conditional on Option A] — only if Option A is chosen over
    Option B for the Phase 3 decision. Reads degraded.json,
    exposes a `compositor_degraded` dimension. 50 lines following
    the ir_presence.py backend pattern.
39. **`research(compositor): reproduce class B/C/D fault injection
    under alpha coordination`** [Phase 4] — USBDEVFS_RESET,
    watchdog trip, MediaMTX kill/restart. Plan documented in
    Phase 4.
40. **`research(compositor): reproduce Phase 5 A/V latency
    measurements once #17 lands and MediaMTX is up`** [Phase 5] —
    commands fully documented in Phase 5 reproduction plan.
41. **`fix(daimonion): structured log at TtsServer._handle_client
    entry`** [Phase 5] — one `log.info` line would have made
    BETA-FINDING-G a 5-minute trace instead of a 30-minute
    speculative session.

## Convergence log entries (this session)

Reproduced from `~/.cache/hapax/relay/convergence.log` for handoff
continuity:

- `17:08:35 SESSION_START | beta: queue 023 post-Option-A research, branch research/post-option-a`
- `17:07:14 OBSERVATION | beta: compositor PID 2913194 was SIGTERM'd at 17:01:23 (not by beta). New PID 3145327...`
- `17:11:12 PHASE_4_REQUEST | beta: have captured a complete natural fault-class-A event for brio-room...`
- `17:16:45 REGRESSION_ALERT | beta: PR #751 TTS UDS delegation is producing tts_client timeouts on the compositor side...`

## What the next session should read first

1. **`docs/research/2026-04-13/post-option-a-stability/phase-5-audio-av-latency.md`** § "Daimonion TTS UDS regression" — the highest-priority fix in the backlog. The hypotheses are listed; someone needs to verify (1) by adding a `log.info` and (2) by checking the `TTSManager` lock type.
2. **`docs/research/2026-04-13/post-option-a-stability/phase-6-metric-surface-audit.md`** § "Deep dive: the studio-compositor scrape-gap" — the Grafana dashboard is end-to-end dead. 5 lines of yaml fixes it.
3. **`docs/research/2026-04-13/post-option-a-stability/phase-3-budget-signal-dead-path.md`** § "Option B — Retire" — the recommendation that affects alpha's in-flight PR #754.
4. **`docs/research/2026-04-13/post-option-a-stability/phase-1-long-duration-stability.md`** § "Direct answer to the brief's cardinal question" — the post-fix steady-state reframe (not 1.09 GB).

## Coordination notes

- **Alpha is active on `chore/compositor-small-fixes` (PR #754 open,
  CI running)**. Phase 3's Option B recommendation affects that PR's
  scope. Alpha should decide retire-or-keep before merge.
- **Alpha's live sampler** at
  `~/.cache/hapax/compositor-leak-2026-04-13/memory-samples-post-fix.csv`
  is still running, now with 40 rows spanning three PIDs. Do not
  start a second sampler.
- **Beta's research branch** `research/post-option-a` is local-only
  (not pushed to origin). Next commit + push + PR should be a
  docs-only PR mirroring PR #752's shape.
- **The compositor has been restarting externally every ~15
  minutes** during this session (17:01:23, 17:16:22). Source
  unknown; not rebuild-services timer (5 min cadence, not covering
  compositor). Most likely operator or alpha testing PR #754
  locally. Phase 1 needs this to stop for the 2-hour re-run.

## Open questions left for alpha + operator

1. **(alpha)** What triggered the compositor SIGTERMs at 17:01:23
   and 17:16:22 today? Neither was a rebuild-services timer (that
   does not cover compositor per alpha.yaml). Manual test? Some
   other path?
2. **(alpha)** Does the daimonion TtsServer share an `asyncio.Lock`
   or a `threading.Lock` with CPAL's TTSManager use? The lock type
   is the most likely cause of the 100 % timeout rate (Phase 5).
3. **(alpha)** Should PR #754 be rebased to drop the
   `_PUBLISH_DEGRADED_FRESHNESS` wrapper? Phase 3 recommends
   Option B (retire entire budget_signal layer); if agreed, PR
   #754's scope narrows to just the token_pole golden-image
   change.
4. **(operator)** Is the stimmung-gated "compositor degraded under
   load" signal a real need? 30+ days have passed since F3 shipped
   without it and no gap has been felt. If the answer is "not
   needed", Phase 3's Option B (delete) is clear. If "needed",
   Option A (resurrect) is the path.
5. **(operator)** Should beta execute fault classes B/C/D with
   alpha coordination before retiring? Brief says yes, but queue
   023's other phases took all of the session budget.

## Beta retirement status

Beta considers queue 023 substantively complete. All six phase
docs exist. Phases 1, 4, 5 shipped partial deliverables (as the
original brief explicitly allowed for deferrals on MediaMTX +
operator-gate items), with reproduction plans for the deferred
parts. Phase 2, 3, 6 shipped full deliverables. The retirement
handoff (this doc) captures the convergence-critical findings,
ranked fix backlog (items 17–41, continuing from PR #752), and
open questions.

Beta will update `beta.yaml` with RETIRING status, commit the
research docs to `research/post-option-a`, push the branch, open
the docs PR, and stand down.

`~/.cache/hapax/relay/beta.yaml` will point at this handoff doc
as the authoritative closeout. No other beta work is in flight.
