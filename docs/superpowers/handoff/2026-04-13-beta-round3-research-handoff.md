# Beta Session Retirement Handoff — Round-3 Deep-Dive Research (Queue 024)

**Session:** beta
**Worktree:** `hapax-council--beta` @ `research/round3-deep-dive` (off main `4f659ad0f`)
**Date:** 2026-04-13, 17:30–18:15 CDT
**Queue item:** 024 — third-round-deep-dive-research
**Depends on:** PR #752 (queue 022), PR #756 (queue 023)
**Inflection:** `20260413-222000-alpha-beta-round3-research-brief.md`
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## One-paragraph summary

Six-phase deep-dive research shipped. All three convergence-critical
findings from PR #756 (FINDING-G/H/I) have named, evidence-backed
root causes, and Phase 5 surfaced a **fourth Critical finding**:
the daimonion's `ConsentGatedReader` is currently silently off in
the live process, violating the `interpersonal_transparency` axiom
(weight 88), with `axioms/contracts/contract--2026-03-23.yaml`
(malformed: empty party, empty scope) as the probable root cause.
Additionally the data-plane audit (Phase 6) found that
`vault-context-writer.service` has failed 165 times in the current
session with no operator alarm, and `obsidian-sync.timer` has never
fired on this boot.

Alpha's task #12 (command server bridge) is no longer blocked on
FINDING-G — the root cause is known and fixable. The
shipping-critical fix list is:

1. **Governance Critical** (axiom compliance failure): delete or
   fix `contract--2026-03-23.yaml`, then ship fail-closed init for
   `ConsentGatedReader`.
2. **FINDING-G fix**: compositor truncates director_loop react
   text to first sentence (max 180 chars) + raise tts_client
   timeout to 120 s. Two one-line changes.
3. **FINDING-H fix**: add `studio-compositor` scrape job to
   `llm-stack/prometheus.yml` + add `ufw` allow rules for ports
   9100 and 9482 from `172.18.0.0/16`. Cross-repo coordination.
4. **FINDING-I fix**: retire the whole Phase 7 BudgetTracker
   layer (Option B, 1467 lines net deletion) + reverse the budget
   freshness gauge wrappers from PR #754/#755.

## Phase ship record

| phase | doc | status |
|---|---|---|
| 1 — FINDING-G py-spy root cause | `phase-1-finding-g-tts-starvation.md` | **shipped** — py-spy captures + differential probes + named root cause |
| 2 — FINDING-H scrape config diff | `phase-2-finding-h-prometheus-scrape.md` | **shipped** — one-line prometheus.yml diff + ufw commands + unlock list |
| 3 — FINDING-I retirement scoping | `phase-3-finding-i-budget-layer.md` | **shipped** — Option A + Option B scoped with line counts, recommendation Option B |
| 4 — voice pipeline E2E | `phase-4-voice-pipeline-e2e.md` | **shipped** — coroutine map + log volume + failure mode catalog + memory steady state |
| 5 — silent-failure sweep | `phase-5-silent-failure-sweep.md` | **shipped** — 1 Critical + 6 High classified with specific fixes |
| 6 — data plane audit | `phase-6-data-plane-audit.md` | **shipped** — Qdrant + consent + Obsidian sync agent states with cross-system linkage to Phase 5 Critical |

Supporting data:

- `data/py-spy/dump-{1..5}.txt` — 5 py-spy stack captures at 2 s intervals
- `data/py-spy/dump-6-long.txt` — longer capture with MainThread active state
- `data/py-spy/probe-source.py` — standalone TTS UDS differential probe

## Convergence-critical findings (this session)

### BETA-FINDING-K (Critical): ConsentGatedReader silently disabled in live daimonion

**Source phases:** Phase 5 (discovery) + Phase 6 (root-cause chain)
**Severity:** CRITICAL — active axiom compliance failure

**Evidence:**

1. Live daimonion journal:
   `ConsentGatedReader unavailable, proceeding without consent filtering`
2. `init_pipeline.py:40–46` silent fallthrough pattern on init
   exception
3. `conversation_pipeline.py:1281–1285` `if self._consent_reader
   is not None: filter` fail-open guard
4. `axioms/contracts/contract--2026-03-23.yaml` malformed: `parties:
   [operator, ""]`, `scope: []`

**Likely chain:** malformed contract → `ConsentRegistry.load_all()`
raises → `ConsentGatedReader.create()` raises →
`init_pipeline.py:45` catches, logs warning → `daemon._precomputed_consent_reader
= None` → `conversation_pipeline.py:1281` silently skips consent
filter on every tool result.

**Governance impact:** `interpersonal_transparency` axiom (weight
88) requires consent filtering for all persistent non-operator-person
data. The live daimonion is currently violating this axiom on every
LLM tool result. Every tool call in the observation window has
passed through without consent filtering.

**Fix priority:** should land before any other Phase 5 work.

### BETA-FINDING-G root cause (from PR #756): Kokoro throughput vs compositor text length

**Source phase:** Phase 1 (root cause via py-spy)

**Evidence:**

1. py-spy dump shows `ThreadPoolExecutor-6_2` actively running
   `_synthesize_kokoro → KPipeline.__call__ → KModel.forward →
   DurationEncoder LSTM` on a compositor react text
   ("The screen gives us the state, at the podium, attempting
   to frame a way of being…")
2. Differential probe measurements:
   - 11 chars: 2.36 s
   - 81 chars: 8.31 s
   - **361 chars: 54.57 s** (2x the 30 s compositor timeout)
3. Compositor react texts 200–425 chars (mean 338, median 363)
4. Steady-state Kokoro CPU throughput: **6.6 chars/sec**

**Root cause (named):** throughput–timeout mismatch. NOT event-loop
starvation. NOT socket-handshake failure. NOT lock contention. The
TtsServer handler runs correctly; the synthesis is in progress for
every call; it simply does not finish within 30 s for typical
compositor text lengths.

**Fix:** compositor truncates to first sentence (max 180 chars)
AND raise `tts_client._DEFAULT_TIMEOUT_S` from 30.0 to 120.0.
Two one-line changes, see Phase 1.

**Alpha's original "event-loop starvation" hypothesis is refuted**
by py-spy dumps. The async loop is healthy; the CPAL impingement
loop fires continuously throughout the capture window.

### BETA-FINDING-H root cause (from PR #756): scrape config + firewall gap

**Source phase:** Phase 2

**Evidence:**

1. `llm-stack/prometheus.yml` has 8 scrape jobs; none targets
   `:9482`. Confirmed via `docker exec prometheus cat
   /etc/prometheus/prometheus.yml`.
2. `series_count({__name__=~"studio_.*"}) = 0` in live Prometheus.
3. `up{job=node-exporter} = 0` with "context deadline exceeded"
4. `ufw status numbered` shows allow rules for ports 8050, 8051,
   9835, 11434 from `172.18.0.0/16` but **not** for 9100 or 9482.
5. `nft list ruleset` compiled rules confirm the ufw gaps.

**Root cause (named):** two-part failure — (a) Prometheus config
has no scrape job for the compositor, (b) the Docker llm-stack
bridge network is firewall-blocked from reaching host ports 9100
and 9482.

**Fix:** one-line `prometheus.yml` diff + two `ufw allow` commands.
See Phase 2.

**Cross-repo coordination required** — the Prometheus config lives
in `llm-stack/`, not `hapax-council--beta/`.

### BETA-FINDING-I root cause (from PR #756): Phase 7 spec shipped without wiring

**Source phase:** Phase 3

**Evidence:**

1. Grep confirms **zero production callers** of `BudgetTracker(`,
   `publish_costs(`, `publish_degraded_signal(`, or
   `budget_tracker=` parameter.
2. Git archaeology: 7 PRs (#665, #671, #672, #676, #754, #755)
   built the Phase 7 layer + followups + observability wrappers.
   **None added caller wiring.**
3. The Phase 7 spec (`2026-04-12-phase-7-budget-enforcement-design.md`)
   lists file structure changes but does **not** specify
   `compositor.py` as a file to modify. The caller-wiring step
   was never specified.

**Root cause (named):** the Phase 7 epic shipped a complete API
surface without a caller, and subsequent PRs layered observability
on top without ever noticing the missing caller. The pattern is
"opt-in feature that was never opted in."

**Recommendation:** **Option B (retire)**. 1467 lines net
deletion. Keep the `atomic_write_json` helper by extracting it
into `_atomic_io.py`. Rebase PR #754 and PR #755 to remove the
budget-related freshness gauge wrappers (both PRs already merged
per git log — the retirement PR can roll them back in-place).

## Ranked fix backlog (items 42–88, continuing from PR #756)

### Critical (must ship before any other Phase 5 work)

66. **`fix(governance): ConsentGatedReader fail-closed init + NullConsentReader fallback`** [Phase 5 C1]
78. **`fix(governance): delete or fix contract--2026-03-23.yaml (the likely root cause)`** [Phase 6]
79. **`feat(governance): ConsentRegistry.load_all() validates contract shape at load time`** [Phase 5 + Phase 6]

### High — ship after Critical, before anything observability-adjacent

42. **`fix(compositor): truncate react text to first sentence (max 180 chars)`** [Phase 1 Option 1] — one-line. Fixes 100% compositor TTS failure rate.
43. **`fix(compositor): raise tts_client._DEFAULT_TIMEOUT_S from 30 to 120`** [Phase 1 Option 2] — one-line. Pair with #42.
47. **`fix(llm-stack): add studio-compositor scrape job to prometheus.yml`** [Phase 2] — 7 lines of yaml, cross-repo.
48. **`fix(host): ufw allow 172.18.0.0/16 → ports 9100, 9482`** [Phase 2] — two ufw commands.
55. **`chore(compositor): retire Phase 7 budget layer (Option B)`** [Phase 3] — 1467-line net deletion.
45. **`feat(daimonion): TtsServer._handle_client entry + success logs`** [Phase 1, Phase 5 H1] — two one-line additions. Root cause of the session's longest investigation.

### Medium — observability + silent-failure hygiene

44. **`feat(daimonion): streaming PCM chunks over UDS`** [Phase 1 Option 3]
46. **`research(voice): Kokoro-GPU vs Kokoro-CPU latency eval`** [Phase 1 Option 4]
49. **`fix(prometheus): scrape interval 5s for studio-compositor job`** [Phase 2 secondary]
50. **`feat(monitoring): pre-add scrape jobs for daimonion/VLA/imagination at :9483/84/85`** [Phase 2 forward link]
51. **`fix(monitoring): pre-add ufw rules for :9483/84/85`** [Phase 2 forward link]
52. **`docs(distro-work): hapax host metric exporter onboarding checklist`** [Phase 2]
54. **`feat(monitoring): Prometheus alert rules for dead scrape targets`** [Phase 2 + Phase 5 H2]
56. **`docs(compositor): supersede phase-7-budget-enforcement-design.md`** [Phase 3]
59. **`feat(daimonion): Prometheus exporter with voice pipeline metrics`** [Phase 4, restates PR #756 Phase 6 gap]
60. **`fix(daimonion): CPAL impingement log includes decision outcome`** [Phase 4 gap 4]
61. **`fix(daimonion): consent gate degradation emits steady WARNING not one-time log`** [Phase 4 gap 5, governance]
63. **`fix(otel): span exporter retry/drop policy under persistent downstream slowness`** [Phase 4 gap 6]
67. **`feat(daimonion): tts_server success-path info log`** [Phase 5 H1, dup of 45]
68. **`feat(monitoring): otel_spans_dropped_total + alert`** [Phase 5 H2]
69. **`fix(daimonion): _cpal_impingement_loop DEBUG → WARNING + counter`** [Phase 5 H3]
70. **`feat(compositor): album_cover_age_seconds gauge + alert`** [Phase 5 H4]
71. **`feat(compositor): studio_camera_seconds_in_fallback counter + alert`** [Phase 5 H5]
72. **`feat(daimonion): hapax_tts_empty_output_total counter`** [Phase 5 H6]
73. **`feat(compositor): tts_client distinguishes missing-pcm_len from zero-pcm_len`** [Phase 5 N1]
81. **`fix(vault-context-writer): circuit-breaker + ntfy when Obsidian not running`** [Phase 6]
87. **`feat(monitoring): obsidian_process_alive gauge + vault_context_writer_failures_total`** [Phase 6]

### Low — cleanup and docs

53. **`research(grafana): verify studio-cameras.json is the live dashboard path`** [Phase 2]
57. **`docs(handoff): correction to PR #756 Phase 3 recommendation`** [Phase 3]
58. **`feat(compositor): extract atomic_write_json helper into _atomic_io.py`** [Phase 3 step 6]
62. **`research(governance): does consent-gate fallback enforce?`** [Phase 4 gap 5 followup]
64. **`feat(daimonion): audio input frame rate counter`** [Phase 4 gap 7]
65. **`research(daimonion): 1.45 GB swap-out investigation`** [Phase 4]
74. **`fix(telemetry): per-site error counters in _telemetry.py`** [Phase 5 M1-M5]
75. **`feat(presence): hapax_backend_registered{name, status} gauge`** [Phase 5 M8-M12]
76. **`research(linter): flag .get(critical_key, default) anti-pattern`** [Phase 5 N1 followup]
77. **`docs(styleguide): silent-failure prohibition code-review rule`** [Phase 5 methodology]
80. **`fix(obsidian-sync): timer never fires on this boot`** [Phase 6]
82. **`fix(vault-context-writer): degrade gracefully if Obsidian not running`** [Phase 6 alt to 81]
83. **`research(qdrant): why is operator-patterns collection empty?`** [Phase 6]
84. **`docs(claude.md): add stream-reactions to the Qdrant collections list`** [Phase 6]
85. **`research(qdrant): low axiom-precedents count investigation`** [Phase 6]
86. **`research(sprint-tracker): verify it reads vault directly not via REST API`** [Phase 6]
88. **`research(cross-system): profiles/*.yaml vs Qdrant profile-facts drift check`** [Phase 6]

## Convergence log entries (this session)

- `17:35:20 SESSION_START | beta: queue 024 round-3 deep dive assigned. Branch research/round3-deep-dive off main 4f659ad0f (PR #756 just merged). Phase 1 (FINDING-G py-spy capture) starting now — this unblocks alpha on PR #751 fix.`
- `17:39:41 PHASE_1_CAPTURE_START | beta: starting py-spy dumps on daimonion PID 2902187. 5 dumps at 2s intervals. Alpha: please hold any manual restarts for 30s.`
- `17:44:02 PHASE_1_ROOT_CAUSE | beta: FINDING-G root cause IDENTIFIED via py-spy + differential probes. NOT event-loop starvation (alpha hypothesis refuted). Root cause: Kokoro CPU throughput ~6.6 chars/sec vs compositor react texts 200-425 chars + compositor tts_client timeout 30s.`

## What the next session should read first

1. **`phase-5-silent-failure-sweep.md` § Critical** — the
   ConsentGatedReader governance failure. Fix this before anything
   else.
2. **`phase-6-data-plane-audit.md` § Consent contracts audit** —
   the malformed `contract--2026-03-23.yaml` that is the likely
   root cause of the Critical finding. Delete-or-fix is the
   direct fix.
3. **`phase-1-finding-g-tts-starvation.md` § Named root cause** —
   unblocks alpha's PR #751 fix path.
4. **`phase-2-finding-h-prometheus-scrape.md` § Proposed fix** —
   the one-line Prometheus diff + two ufw commands that bring
   back every observability signal the session's other phases
   identified as blind.
5. **`phase-3-finding-i-budget-layer.md` § Recommendation** —
   the Option B retirement decision.

## Coordination notes

- **Alpha is NO LONGER BLOCKED on FINDING-G.** The Phase 1 root
  cause is named, the fix is specified, and the compositor-side
  one-line change (truncate react text) can land without any
  daimonion coordination. Alpha's task #12 (command server bridge)
  is safe to resume as soon as the Critical governance fix and
  the Phase 1 TTS fix are staged.
- **The Phase 5 Critical finding is actionable by alpha
  immediately.** No convergence coordination needed — delete the
  malformed contract, ship the fail-closed init, done. This is
  the most urgent fix in the entire backlog (items 42–88) and
  should take ~30 minutes.
- **The Phase 2 FINDING-H fix is cross-repo** (`llm-stack/` +
  host firewall). Operator coordination is needed because the
  ufw commands require sudo and the prometheus.yml diff is in a
  different repo from hapax-council.
- **Beta's research branch** `research/round3-deep-dive` is
  pushed to origin. Next commit + PR should be this retirement
  handoff + the six phase docs, mirroring PR #752/#756 shape.

## Open questions left for alpha + operator

1. **(operator)** Should the Critical governance fix ship as a
   hot-patch (direct-to-main, no PR gate) given it's an active
   axiom compliance failure? Or through the standard PR gate?
2. **(operator)** Is `contract--2026-03-23.yaml` supposed to be a
   real contract that needs filling in, or a template that should
   be deleted? Phase 6's evidence is insufficient to decide.
3. **(alpha)** The Phase 3 recommendation is Option B (retire).
   Alpha's PR #754 and #755 both merged before this retirement
   PR would land — retire PR needs to roll them back in-place.
   Is that acceptable, or is there a reason to keep the budget
   freshness gauge wrappers?
4. **(alpha)** Phase 6 Q: `operator-patterns` Qdrant collection
   is empty. Is this intentional (writer not yet implemented) or
   accidental (writer broken)?
5. **(operator)** `obsidian-sync.timer` has never fired on this
   boot. Is the operator intentionally running without Obsidian
   vault sync, or is this a regression that needs a fix?

## Beta retirement status

Beta considers queue 024 complete. All six phases shipped full
deliverables, each with method, evidence, named root cause, fix
proposal, and backlog additions. The retirement handoff
consolidates items 42–88 of the ranked fix backlog continuing
from PR #752 and PR #756.

Beta will commit the research docs to `research/round3-deep-dive`,
push the branch, open the docs PR (#757 or similar), and stand
down.

`~/.cache/hapax/relay/beta.yaml` will point at this handoff doc
as the authoritative closeout. No other beta work is in flight.
