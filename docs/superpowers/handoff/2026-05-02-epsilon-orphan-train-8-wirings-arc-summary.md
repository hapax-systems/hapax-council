---
date: 2026-05-02
session: epsilon
type: handoff/arc-summary
related_pr_range: "2086–2163 (8 wirings) + 2149/2152/2154 (M8 mission)"
status: in-progress
parent_arc: docs/superpowers/handoff/2026-05-01-epsilon-orphan-train-arc-summary.md
---

# Orphan-Train 8-Wirings Arc + M8 Mission — Closeout Summary

## What

Continuation of the orphan-implication coherence audit train (parent arc:
the 2026-05-01 closeout doc), interleaved with an alpha-assigned M8
capability batch (Gaps 2/3/7/9). Session ran ~25 hours across two
operator wake messages — 2026-05-02T03:00Z (M8 carry-fork batch
assignment) and the resumption of orphan-train Phase 2 wiring at
2026-05-02T04:14Z.

**Cumulative session arc this leg:** 53 PRs shipped (53 merged), 8
genuine Phase 2 probe-wirings + 4 M8 cc-tasks closed.

**Total orphan train progress:** 61 of 92 closed (66%) — up from
58/92 (63%) at the start of this leg.

## Wiring inventory (8 probe-wirings shipped)

| # | PR | Implication | Probe | Surface scanned | Threshold |
|---|---|---|---|---|---|
| 1 | #2086 | `su-paths-001` | `_check_no_user_keyed_paths` | `agents/**/*.py`, `shared/**/*.py`, `logos/**/*.py` for user-keyed path patterns | 0 violations |
| 2 | #2091 | `ex-feedback-001` | `_check_long_running_agent_progress_emission` | 7 canonical long-running agents (hapax_daimonion, imagination_daemon, dmn, studio_compositor, visual_layer_aggregator, content_resolver, reverie) for hapax_event/logger.* emission | ≥2 instrumented |
| 3 | #2096 | `ex-init-002` | `_check_systemd_unit_exec_self_contained` | `systemd/units/*.service` ExecStart placeholder patterns | ≥95% self-contained (147/148 = 99.3%) |
| 4 | #2117 | `ex-state-002` | `_check_state_visibility_emission` | `agents/**/*.py` for `/dev/shm/*-state.json` and `~/hapax-state/*.jsonl` patterns | ≥10 modules (got 22) |
| 5 | #2155 | `ex-routine-002` | `_check_scheduled_agents_have_timers` | `systemd/units/{health-monitor,drift-detector,scout,daily-briefing}.service` paired with `.timer` | All 4 paired |
| 6 | #2157 | `ex-context-001` | `_check_agents_have_context_query_path` | agent modules for `def status/get_status/describe/health/info/state` or FastAPI `@app.get` decorators | ≥5 modules |
| 7 | #2160 | `ex-context-002` | `_check_status_outputs_have_timestamps` | 5 canonical status surfaces (chronicle, health_monitor, consent_audit, stimmung_sync, drift_detector/freshness) for ISO-8601 timestamp patterns | ≥3 (got 5/5) |
| 8 | #2163 | `ex-state-003` | `_check_task_context_persistence` | cc-task vault SSOT (active *.md with claimed_at + cc-active-task-{role} files) | ≥1 cc-task with claimed_at + ≥1 role claim file (got 166 + 2) |

## M8 capability mission (4 cc-tasks closed in 3 PRs)

| PR | cc-task | Gap | WSJF |
|---|---|---|---|
| #2149 | m8-system-info-firmware-ingest + m8-button-activity-perception-signal | 9 + 7 | 9.0 + 8.5 |
| #2152 | m8-stem-archive-recorder | 3 | 9.5 |
| #2154 | m8-dmn-mute-solo-transport | 2 | 7.7 |

Carry-fork extension stayed under the 50-LOC trivially-rebasable bar:
Gap 9 (system_info SHM publishing) + Gap 7 (button-activity SHM
publishing) added two new functions to `shm_sink.{c,h}` + two new
hunks in `command.c`. Stem archive recorder (Gap 3) is a parallel
parec→sox pipeline that doesn't touch the loudnorm broadcast chain.
M8Sequencer (Gap 2) extended `MidiOutput` with note_on/note_off
methods and added a new `M8Sequencer` module translating director
intent (mute/solo/transport) to SONG ROW CUE CHANNEL note pairs.

## Probe-wiring template (proven 8×)

Each probe-wiring follows the same shape. Replicable for the
remaining ~31 orphans.

### Template

1. **Identify the implication's enforcement surface** — what brute
   fact, file, or runtime invariant satisfies the rule?
2. **Add a new `_check_<rule>` function** to the appropriate
   `agents/drift_detector/probes_*.py` file. Function returns
   `tuple[bool, str]` (sufficient/insufficient + diagnostic).
3. **Append a `SufficiencyProbe` entry** to the module's `*_PROBES`
   list with `implication_id="<orphan-id>"`. The implication ID
   text-reference satisfies `linkage: code-direct`.
4. **Annotate the implication YAML** with `linkage: code-direct`.
5. **Verify orphan delta**: `uv run python -c "from shared.coherence
   import check_coherence; print(len([g for g in check_coherence().gaps
   if g.gap_type=='orphan_implication']))"` should drop by 1.
6. **Verify probe runs**: `uv run python -c "import
   agents.drift_detector.sufficiency_probes; import
   agents.drift_detector.probes_executive as p; print(p._check_<rule>())"`.
7. **Test pin** (optional, recommended): if the probe has interesting
   logic (more than a path check), add a unit test in
   `tests/test_drift_detector.py`.

### Threshold tuning

Probes are sufficiency questions, not adversarial gates. They should
return True when the system is "good enough" — not require perfection.
Most useful threshold pattern: ≥3-5 surfaces match. Below that, the
sufficiency claim is too thin; above, the probe is too lenient.

For module-bound probes (e.g. canonical long-running agents), require
≥2 modules to match — proves the pattern is in use, even if some
modules are Python launchers for native daemons that don't emit
progress at the Python layer.

## Lesson learned: stacked-PR squash bug + recovery (#2158 → #2160)

**Bug:** when a second PR is built atop a first PR's branch (B stacks
on A), and A merges via squash before B, the GitHub squash-merge of B
uses A's commit message and A's diff (since B's branch is now BEHIND
main with no new content). The result: B silently merges as a no-op.

**Symptom:** PR #2158 was opened to wire `ex-context-002` on top of
#2157's `ex-context-001`. After #2157 merged, #2158's branch became
BEHIND main with the same diff as #2157. When #2158 squash-merged,
the merge commit subject was "wire ex-context-001..." (PR #2158) and
the actual diff was empty against the post-#2157 main.

**Detection:** post-merge orphan delta verification. Expected 33 → 32
after #2158; observed 33 → 33. The orphan count not dropping was the
canary.

**Recovery:** PR #2160 — re-applied the ex-context-002 wiring on top
of post-#2157 fresh main, with a single isolated commit. Cleanly
shipped.

**Going forward (now in absolute_directives #13):** verify each
wiring's post-merge orphan delta matches expectation. If off-by-one,
re-do as a fresh PR on top of latest main.

## Anti-pileup governor adherence

The `≤8 open PRs` governor was respected throughout. Push points:
- 4 PRs opened with count 4-5 (well under)
- 3 PRs opened with count 6-7 (at threshold)
- 1 PR opened with count 8 (the boundary)

Twice the queue rose above 8 (peaks at 9-10) — both times the session
held idle until queue drained. No pushes during over-cap.

## Admin-merge rubric usage

- **timeout-at-25min**: used for #2091 (CI runner queue stalled)
- **diff-surface-disjoint**: used 3× for #2154, #2158, #2160 (all
  failed with the same `test_axiom_enforcer_env_off_then_on_for_agent_outputs`
  flake — unrelated to my probe wiring or M8 changes)

The flake is a known-flaky test (briefing/digest output assertions
that race with axiom_enforcer state). Worth follow-up triage but not
blocking for diff-surface-disjoint admin-merge.

## Remaining orphans (31, post-#2163)

By cluster:
- **ex-*** (~14 remaining): ex-batch-001, ex-cogload-002,
  ex-decision-012, ex-doc-001, ex-error-006, ex-feedback-002,
  ex-feedback-008, ex-governance-001, ex-interrupt-011, ex-log-001,
  ex-ui-001, ex-depend-001, plus a few others
- **su-*** (~17 remaining): su-admin-001, su-agents-001, su-api-001,
  su-audit-001, su-cache-001, su-config-001, su-data-001, su-deploy-001,
  su-error-001, su-feature-001, su-logging-001, su-naming-001,
  su-notify-001, su-scale-001, su-scaling-001, su-security-001,
  su-storage-001, su-ui-001
- **mg-*** (0 remaining): mg-deterministic-001 — wait, was this 1
  remaining? Re-check before any wiring claim.

Many of the remaining su-* orphans are absurdity-canonical T0/block
rules ("admin interfaces must not exist", "feature collaboration must
not be developed"). For those, the cleanest wiring is a probe that
asserts the *absence* of forbidden patterns — analogous to su-paths-001's
`_check_no_user_keyed_paths`.

## Suggested next-session pickup

1. **First wave** (similar to su-paths-001): wire su-config-001,
   su-storage-001, su-naming-001, su-cache-001 — all about
   absence-of-multi-user-patterns in specific scopes. Each ~50 LOC of
   probe code, replicating the su-paths-001 template.
2. **Second wave** (canonical-agent-attestation, similar to
   ex-feedback-001): wire ex-feedback-002 (success states explicitly
   confirmed), ex-feedback-008 (next-action recommendations), ex-doc-001
   (documentation focuses on what-this-does-for-you).
3. **Closeout target**: 70/92 (76%) reachable in one more session if
   the train continues at this rate.

## Pointers

- Audit catalog: `docs/research/2026-04-25-coherence-orphan-implications-catalog.md`
- Coherence module: `shared/coherence.py`
- Implication loader: `shared/axiom_registry.py::load_implications`
- Constitutive rules: `axioms/constitutive-rules.yaml`
- Probe modules: `agents/drift_detector/probes_*.py`
- Test pins: `tests/test_axiom_registry.py` (42 tests),
  `tests/test_drift_detector.py` (40 tests)
- Hook source: `hooks/scripts/no-stale-branches.sh` (anti-pileup
  governor enforcement)
- This session's parent arc: `docs/superpowers/handoff/2026-05-01-epsilon-orphan-train-arc-summary.md`

## Train PR Range

Cumulative across both arc-summary docs:
- Earlier (2026-05-01 arc): #1928–#2086 — 53 closures (58%)
- This arc (2026-05-02): #2086–#2163 — 8 additional probe-wirings +
  4 M8 cc-tasks → 61 closures (66%)
