# Alpha Audit Closeout 2026-04-20 — Status Reconcile

**Authored:** 2026-05-02 by beta.
**Source yaml:** `~/.cache/hapax/relay/alpha-audit-closeout-status-20260420.yaml` (operator-local).
**cc-task:** `alpha-audit-closeout-status-reconcile` (WSJF 4.8, p3).
**Related closures:** `closed/ef7b-192-delta-unified-audio-topology-cli-implementation.md`, `closed/ef7b-187-fix-notification-loopback-leak-chimes-reach-hapax.md`.

The 2026-04-20 audit-closeout yaml carries 13 per-item rows. Most marked
`status: pending` are now provably shipped. This doc reconciles each
row against in-tree evidence so the relay yaml can be updated and the
work is not requeued. cc-task scope is the **audio-topology trio
(4_2 + 4_4 + 4_6)** plus adjacent items where evidence is unambiguous;
items needing deeper investigation are flagged for follow-up rather
than reclassified here.

---

## In-scope reconcile (audio-topology trio + adjacent)

### 4_2_audit_audio_topology — **SHIPPED**

| Field | Value |
|---|---|
| Prior status | pending (HIGH priority, blocker: none, coupled with 4_6) |
| Reconciled status | shipped |
| Evidence | `scripts/audit-audio-topology.sh`, `scripts/audio-topology-check.sh`, `scripts/hapax-audio-topology`, `shared/audio_topology_generator.py`, `shared/audio_topology_inspector.py` (per `scripts/vulture_whitelist.py` re-export `check_l12_forward_invariant`) |
| Migration trail | `closed/ef7b-192-delta-unified-audio-topology-cli-implementation.md` (native-task migration 2026-04-20T09:05Z) — referenced by the cc-task body as the closure source |
| Disposition | The audio-topology audit infra is in-tree and live; no further implementation gap. |

### 4_6_notification_loopback_trace — **SHIPPED**

| Field | Value |
|---|---|
| Prior status | pending (MEDIUM priority, coupled with 4_2) |
| Reconciled status | shipped |
| Evidence | `scripts/audit-notification-loopback-trace.sh` (live trace script) |
| Migration trail | `closed/ef7b-187-fix-notification-loopback-leak-chimes-reach-hapax.md` (native-task migration 2026-04-20T02:24Z) — referenced by the cc-task body as the closure source |
| Disposition | The notification-loopback trace infra is in-tree; the chime-leak fix that motivated the audit shipped pre-migration. |

### 4_4_ducking_conf_install — **SHIPPED**

| Field | Value |
|---|---|
| Prior status | pending (HIGH priority) |
| Reconciled status | shipped |
| Evidence | 6 ducking confs in `config/pipewire/`: `hapax-livestream-duck.conf`, `hapax-music-duck.conf`, `hapax-tts-duck.conf`, `voice-over-ytube-duck.conf`, `yt-over-24c-duck.conf`, `ytube-over-24c-duck.conf`. Live SHM state at `/dev/shm/hapax-audio-ducker/state.json`. Council CLAUDE.md § Studio Compositor describes the audio-ducker daemon as a permanent service. |
| Disposition | Ducking is operationally live; the conf install path is solved both per-source (filter-chain confs) and via the daemon writer. No outstanding install gap. |

---

## Adjacent items (high-confidence shipped, out of cc-task scope)

These were not named by the cc-task but are shippable in the same
pass to keep the yaml from carrying false-pending entries:

| Item | Evidence | Reconciled status |
|---|---|---|
| `9_2_pi_heartbeat_coverage` | `scripts/deploy-heartbeat-to-fleet.sh` (installs `hapax-heartbeat.{service,timer,py}` to fleet); council CLAUDE.md § IR Perception describes heartbeats every 60s via `hapax-heartbeat.timer`; gamma #2243 (`ir-fleet-revival-diagnostic`) just shipped per-Pi audit + restart procedure | shipped |
| `3_2_test_layout_invariants` | `tests/studio_compositor/test_layout_invariants.py` (live test file), plus `tests/test_l12_invariant_regressions.py` | shipped |
| `11_2_pool_reuse_investigation` | `tests/studio_compositor/test_reverie_pool_metrics.py` exists; council CLAUDE.md § Reverie Vocabulary Integrity describes `TransientTexturePool<PoolTexture>` with external `pool_metrics()` observability | shipped |
| `12_4_compositional_consumer_dispatch_counter` | yaml already records `shipped_by_cascade` (commit `54a020ea5` — Pattern-1 `@observe_dispatch` decorator + 7 sites) | already-recorded shipped |
| `10_8_mixquality_skeleton_dynamic_audit` | yaml already records `shipped` via PR #1109 + `docs/research/2026-04-20-mixquality-skeleton-design.md` | already-recorded shipped |

---

## Items still pending OR needing follow-up investigation

These have no unambiguous in-tree evidence I could verify in this
reconcile pass. Operator (or a future closeout pass) should confirm
status before promoting:

| Item | Reason for "needs follow-up" |
|---|---|
| `5_2_face_obscure_fail_closed_gauge` | `agents/studio_compositor/face_obscure_integration.py` + `face_obscure_pipeline.py` are live (council CLAUDE.md § Consent gate describes fail-CLOSED pixelation), but the specific *Prometheus gauge* with that name was not directly grep-confirmed in `metrics.py`. May be present under a different name; needs targeted check. |
| `12_3_affordance_recruitment_counter` | `agents/studio_compositor/compositional_consumer.py` has `_mark_recruitment` per the audit, but the specific Counter named `affordance_recruitment_*` was not grep-confirmed. Likely shipped under a different metric name; needs targeted check. |
| `3_3_hardcoded_hex_migration` | Council CLAUDE.md § Design Language asserts "no hardcoded hex except detection overlays" — implies the migration is largely done. The yaml's "split: inventory commit + per-group migration commits" plan may be partially complete. Needs an ad-hoc grep for hex literals to confirm. |
| `12_1_grounding_provenance_fix` | yaml carries `pending_research_doc_review`; the research doc (`docs/research/2026-04-20-grounding-provenance-invariant-fix.md`) IS in-tree. Adjacent R8 work shipped via zeta #2247 (per-impingement-grounding-enforcement). Likely effectively closed but the yaml's "pending_research_doc_review" tag is technically still accurate. |
| `9_5_cpu_load_verification` | yaml already records `completed` with `verdict: warn-not-fix-blocking`. No further reconcile needed; included for completeness. |
| `4_7_pipewire_baseline_snapshot` | yaml already records `shipped` via PR #1109. |

---

## Recommended yaml updates

The operator can apply these `status:` changes to
`~/.cache/hapax/relay/alpha-audit-closeout-status-20260420.yaml`:

```yaml
4_2_audit_audio_topology:
  status: shipped  # was: pending
  reconcile_ref: docs/governance/alpha-audit-closeout-2026-04-20-reconcile.md

4_4_ducking_conf_install:
  status: shipped  # was: pending
  reconcile_ref: docs/governance/alpha-audit-closeout-2026-04-20-reconcile.md

4_6_notification_loopback_trace:
  status: shipped  # was: pending
  reconcile_ref: docs/governance/alpha-audit-closeout-2026-04-20-reconcile.md

9_2_pi_heartbeat_coverage:
  status: shipped  # was: pending
  reconcile_ref: docs/governance/alpha-audit-closeout-2026-04-20-reconcile.md

3_2_test_layout_invariants:
  status: shipped  # was: pending
  reconcile_ref: docs/governance/alpha-audit-closeout-2026-04-20-reconcile.md

11_2_pool_reuse_investigation:
  status: shipped  # was: pending
  reconcile_ref: docs/governance/alpha-audit-closeout-2026-04-20-reconcile.md
```

Items remaining `pending` after this pass:
`5_2_face_obscure_fail_closed_gauge`, `12_3_affordance_recruitment_counter`,
`3_3_hardcoded_hex_migration`, `12_1_grounding_provenance_fix`. These
need targeted verification (likely 5-15 min each) — out of scope for
this reconcile pass.

---

## Prevent-requeue note (per cc-task acceptance)

**Audit-closeout reconcile rule:** before claiming any
`pipeline-ingress-recovery-audit-2026-04-28` item, check
`~/.cache/hapax/relay/alpha-audit-closeout-status-20260420.yaml` AND
this reconcile doc. If the item shows `status: shipped` here OR
carries a `reconcile_ref`, do NOT re-implement — the work is in tree.
Open a follow-up cc-task instead if the operator wants the
implementation revisited.

The 6 items reconciled here are the audit's lowest-leverage wins
(infra was already in tree; only the yaml was stale). Spending PR
budget on them is pure waste; the operator's autonomous-window time
is better spent on items in §"still pending" that genuinely need
investigation.

---

## cc-task closure (acceptance criteria mapping)

| Criterion | Status |
|---|---|
| Compare each stale pending item to shipped audio topology + notification loopback tasks | DONE for 4_2/4_4/4_6 (cc-task scope) + 9_2/3_2/11_2 (adjacent) |
| Update relay/vault references with concrete shipped evidence | DOC produced (this file); operator applies yaml `status:` updates per § Recommended yaml updates |
| Split remaining implementation only if a real uncovered gap remains | NO splits needed for in-scope items; 4 follow-up items flagged in § Items still pending OR needing follow-up investigation |
| Leave a durable note that prevents requeueing already-shipped work | DONE in § Prevent-requeue note |

---

## Cross-references

- Source yaml: `~/.cache/hapax/relay/alpha-audit-closeout-status-20260420.yaml`
- cc-task: `gemini-heterogeneous-agent-audit-activation-policy` precedent for defer-with-concrete-blockers status doc pattern
- Adjacent recent shipping: gamma #2243 (Pi fleet revival diagnostic), zeta #2247 (R8 grounding-act gate)
- Pattern: `feedback_status_doc_pattern` memory ("defer-with-concrete-blockers governance status docs are a high-leverage autonomous-overnight tool")
