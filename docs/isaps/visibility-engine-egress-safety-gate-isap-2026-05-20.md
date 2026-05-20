# ISAP: Visibility Engine Egress Safety Gate

**Date:** 2026-05-20
**Request:** `REQ-20260510-visibility-engine`
**Authority case:** `CASE-VISIBILITY-ENGINE-001`
**Authority item:** `VISIBILITY-ENGINE-EGRESS-SAFETY-GATE-ISAP`
**Task:** `20260510-visibility-engine-phase0-research-egress-safety-gate`
**Status:** implementation authorization packet; no runtime activation
**Risk tier:** T2 public-egress expansion

## 1. Decision

Runtime activation verdict: **NO-GO for broad visibility runtime activation**;
**GO only for implementing the V0 source gate described below**.

Broad visibility activation remains blocked until the next source slice
implements a single pre-egress decision gate for every increased autonomous
publication path. The gate must fail closed, emit operator-visible receipts,
and prove that each targeted surface is one of:

- publication-bus backed and dispatchable through the canonical registry;
- RVPE-backed or orchestrator-backed legacy omg.lol scope that is explicitly
  broad-visibility eligible;
- guarded legacy scope that is not eligible for broad visibility fanout; or
- refused.

This ISAP authorizes the source task
`visibility-engine-egress-safety-gate-v0`. It does not authorize enabling new
timers, starting services, changing credentials, moving artifacts into
`publish/inbox/`, removing source-activation holds, or performing any public
egress.

| Runtime state | Verdict | Reason |
| --- | --- | --- |
| Current clean `origin/main` | NO-GO for broad visibility activation | Existing envelope is global-only and lacks per-surface budgets, dry-run fanout receipts, explicit surface classification receipts, and spike containment evidence. |
| `visibility-engine-egress-safety-gate-v0` source implementation | GO | Source-only mutation may add the gate, receipts, metrics, and tests. |
| Dry-run volume replay after V0 | GO only when no public publisher client is called | Needed to prove volume, classification, idempotency, and receipts before public writes. |
| Production public fanout above current baseline | NO-GO until Section 11 criteria pass | Public egress expansion without the V0 gate would make unexpected broadcast spikes plausible. |

## 2. Dependency Receipt

The task was blocked on the publication-bus/default-surface and legacy omg.lol
source queue. That queue is now resolved:

| Dependency | PR | Merge receipt | Consequence |
| --- | --- | --- | --- |
| `visibility-engine-publication-bus-default-surface-audit-v0` | #3229 | merged 2026-05-13T18:16:46Z, `79d94868ceae91a81458d3c0948e73e3686d7bf5` | weblog direct fanout is opt-in; canonical default is `omg-weblog` only |
| `visibility-engine-non-broadcast-producer-readiness-v0` | #3230 | merged 2026-05-13T18:08:13Z, `ec0dcde33086748b10c34addc66a84c7cd4793f5` | weblog producer is bus-only by default; non-broadcast units are source-pinned |
| `visibility-engine-legacy-omg-surface-bus-reconciliation-v0` | #3231 | merged 2026-05-13T18:41:32Z, `b9d1fc419c8ae5d1d729fa30c66a533832172e29` | legacy omg.lol paths are classified as RVPE-backed, orchestrator-backed, guarded legacy, or refused |

This ISAP was re-evaluated against clean `origin/main` at
`2c434972d` on 2026-05-20 after those merges.

## 3. Current Source Baseline

Current source already contains a first-pass global envelope:

- `shared/publication_hardening/egress_safety.py` defines
  `EgressSafetyEnvelope` with a file kill switch at
  `~/hapax-state/publish/KILL_SWITCH` and a global sliding-window limit.
- `agents/publish_orchestrator/orchestrator.py` calls that envelope before
  processing `publish/inbox/*.json`.
- `shared/publication_hardening/gate.py` produces `pass`, `hold`, and `reject`
  hardening decisions.
- `agents/publication_bus/surface_registry.py` is the canonical surface
  registry. `dispatch_registry()` excludes refused surfaces.
- `shared/legacy_omg_surface_policy.py` records the legacy omg.lol lifecycle
  classifications and broad-visibility eligibility.
- Mastodon, Bluesky, Are.na, weblog producer, statuslog poster, and
  publication-artifact projection code already carry event-id or
  artifact-fingerprint idempotency.

The existing envelope is not enough for rolling autonomous volume. It is
global-only, has no per-surface budgets, has no explicit dry-run mode for the
orchestrator path, and does not write a dedicated egress-safety receipt for
each hold/reject/pass decision. The source slice must extend it rather than
creating a parallel egress policy.

## 4. Scope

In scope for `visibility-engine-egress-safety-gate-v0`:

- Extend the existing `EgressSafetyEnvelope` into a single pre-egress policy
  object used by the publish orchestrator and any rolling visibility fanout
  workers before public writes.
- Add configurable global and per-surface budgets.
- Add explicit `pass`, `hold`, and `reject` decisions with stable reasons.
- Add global dry-run mode that writes receipts but never calls public
  publisher clients.
- Add operator-visible JSON receipts and Prometheus counters.
- Require dispatch target classification before fanout.
- Preserve and test idempotency ownership.

Out of scope:

- Starting or enabling visibility timers.
- Publishing test posts.
- HN submission.
- Credential bootstrap.
- New publication surfaces.
- Changing platform copy, composer prompts, or public claim language except
  where needed for gate receipts.
- Livestream face-obscuring or compositor privacy work.

## 5. Decision Semantics

The V0 gate returns one of three terminal gate decisions for each candidate
artifact or public-event fanout batch. Result names may be represented as an
enum, but their semantics must remain stable.

| Decision | Meaning | Public write allowed? | Queue behavior | Receipt requirement |
| --- | --- | --- | --- | --- |
| `pass` | Candidate is eligible, all target surfaces are classified, hardening passed or a valid operator hold override exists, budgets remain, dry-run is off, and idempotency says this is not a duplicate. | Yes, for target surfaces that individually pass. | Continue to publisher dispatch. | Write `decision=pass` receipt before dispatch and per-surface result receipts after dispatch. |
| `hold` | Candidate may become eligible later: kill switch active, dry-run active, rate budget exhausted, missing bootstrap receipt, hardening hold without override, temporary credentials unavailable, source-activation not green, or retryable external failure. | No. | Leave in inbox for retry, move to held/draft if human-facing hardening review is required, or preserve cursor without marking public success for event-tailers. | Write `decision=hold` with retry/owner fields and no public URL claim. |
| `reject` | Candidate must not be autonomously published: refused surface, unknown/unregistered surface, guarded legacy surface requested for broad visibility, rights/privacy/provenance failure, known legal-name or safety rejection, or hardening reject. | No. | Move artifact to failed/dropped or mark per-event receipt as rejected; do not retry automatically. | Write `decision=reject` with exact blocking predicate and surface. |

Kill switch and budget exhaustion are `hold`, not `reject`, because they do not
prove the candidate is unsafe. Refused, unregistered, and guarded-legacy broad
visibility targets are `reject` because retrying without a source change would
only repeat unsafe egress intent.

## 6. Rate Policy

V0 must enforce both a global cap and per-surface caps. The most restrictive
active budget wins.

Default global budgets:

| Budget | Default |
| --- | --- |
| successful public writes per rolling 24h | 20 |
| successful public writes per rolling hour | 6 |
| concurrent in-flight public writes | 4 |

Default per-surface budgets:

| Surface family | 24h cap | 1h cap | Notes |
| --- | ---: | ---: | --- |
| `omg-weblog`, `oudepode-omg-weblog` | 8 | 2 | canonical long-form/artifact weblog writes |
| `mastodon-post` | 30 | 6 | existing adapter contract already cites 30/day, 6/hour |
| `bluesky-post` | 30 | 6 | existing adapter contract already cites 30/day, 6/hour |
| `arena-post` | 30 | 6 | existing adapter contract already cites 30/day, 6/hour |
| `bridgy-webmention-publish` | 8 | 2 | secondary fanout only after source weblog URL exists |
| `omg-lol-statuslog` | 3 | 1 | statuslog poster default daily cap is 3; keep broad volume off this surface |
| DOI/deposit surfaces | 5 | 1 | archival/deposit surfaces are not social-volume surfaces |
| conditional-engage surfaces | 0 until bootstrap receipt | 0 until bootstrap receipt | dry-run receipts may still be produced |
| refused surfaces | 0 | 0 | reject if targeted |

Budget accounting must count only successful public writes (`ok` or equivalent
receipt with a public write). Holds, rejections, dry-run receipts, duplicate
idempotency skips, and credential failures must not consume success budget.

Any override above these defaults must be source-controlled or operator-receipt
backed. Environment variables may lower budgets for emergency containment; they
must not be the only authority for raising rolling public volume.

## 7. Surface Classification Gate

Before any candidate reaches a publisher:

1. Every target surface must be present in
   `agents.publication_bus.surface_registry.SURFACE_REGISTRY`.
2. Refused surfaces must reject, not hold.
3. `CONDITIONAL_ENGAGE` surfaces may pass only with a current bootstrap receipt
   named by the surface policy. Without that receipt they hold or dry-run.
4. Runtime dispatchable artifact surfaces must resolve through
   `dispatch_registry()` unless explicitly handled by a source-controlled
   RVPE adapter.
5. omg.lol legacy paths must consult `shared.legacy_omg_surface_policy`.
   Only `orchestrator_backed` and `rvpe_backed` rows with
   `broad_visibility_eligible=True` may participate in broad fanout.
   Guarded legacy rows remain available only for their narrow manual or
   utility scope.

Unknown surface slugs are rejects. They are not silently skipped.

## 8. Idempotency Contract

The gate must preserve existing idempotency owners:

| Path | Idempotency owner |
| --- | --- |
| publish orchestrator artifact fanout | `artifact_fingerprint + surface_result` |
| publication-artifact public events | `publication_artifact_public_event_id(...)` |
| weblog RSS public events | stable `weblog_publish_event_id(item)` |
| Mastodon/Bluesky/Are.na posters | per-surface `event_ids` ledgers plus byte cursors |
| omg.lol statuslog poster | `event_id` state in the poster state file |

A duplicate candidate must produce a receipt with `decision=hold` or
`decision=pass_duplicate_skip` if the implementation uses a sub-decision, but
it must not perform a second public write and must not consume rate budget.

## 9. Dry-Run Mode

V0 must add a global dry-run mode for increased visibility fanout. The exact
configuration key can be refined in source, but the behavior is fixed:

- no external publisher client is called;
- no public URL is claimed;
- the candidate still runs classification, hardening, budget, idempotency, and
  composition checks;
- receipts are written with `dry_run=true`;
- metrics count `dry_run`, not `ok`;
- the mode is operator-visible in the same log/receipt surface as holds and
  rejects.

Surface-local dry-run flags may remain, but broad visibility activation must
have one global dry-run switch so a single source-activation profile can prove
volume without public egress.

## 10. Operator-Visible Receipts

Each gate evaluation must write a JSON receipt under the publish state root
before a public write is attempted. The recommended path is:

`~/hapax-state/publish/log/{candidate_id}.egress-safety.json`

Minimum fields:

- `schema_version`
- `candidate_id`
- `candidate_kind` (`artifact`, `rvpe`, or `surface_event`)
- `artifact_fingerprint` or `event_id`
- `decision`
- `reason_codes`
- `checked_at`
- `dry_run`
- `kill_switch_active`
- `source_activation_state`
- `target_surfaces`
- `surface_classifications`
- `global_budget`
- `per_surface_budgets`
- `idempotency_key`
- `operator_action`
- `source_refs`

Receipts must avoid private excerpts and credential values. Operator-visible
does not mean public.

## 11. GO/NO-GO Criteria For Runtime Activation

Broad visibility runtime activation is **GO** only when every required
predicate below is true. Any false predicate is a **NO-GO** for enabling timers,
starting services, moving artifacts into `publish/inbox/`, or removing
source-activation holds.

| Gate | GO predicate | NO-GO condition |
| --- | --- | --- |
| Source gate presence | Every increased autonomous publication path calls the same V0 pre-egress gate before any public client. | Any path can call a public publisher directly or through a legacy helper without the gate. |
| Surface classification | Every target surface is registry-backed, RVPE/orchestrator-backed and broad-eligible, conditional with a current bootstrap receipt, or refused/rejected. | Unknown surface, refused surface, or guarded-legacy surface can be silently skipped or retried. |
| Budgets | Global and per-surface hourly/daily/concurrency budgets are source-controlled and tests prove holds before public calls. | Only a global cap exists, caps are env-only raises, or one surface can exhaust the whole visibility envelope. |
| Dry-run | One global dry-run switch exercises classification, hardening, budget, idempotency, receipts, and metrics while calling zero publisher clients. | Dry-run is surface-local only, partial, or cannot prove no public egress. |
| Idempotency | Duplicate artifacts/events produce no second public write and consume no success budget. | Retry loops or event replays can produce duplicate posts. |
| Receipts | Each pass/hold/reject writes an operator-visible JSON receipt with reason codes before dispatch. | Decisions only appear in process logs or after publisher calls. |
| Kill switch | File kill switch produces `hold` before inbox processing and before any rolling fanout worker dispatch. | Kill switch only covers the publish orchestrator artifact path. |
| Activation discipline | Implementation PR ships source/tests/docs only; runtime activation is a separate, dated operator/governance action. | Source PR also enables timers, starts services, changes credentials, or publishes test posts. |

Runtime activation must start with a dry-run replay. Public writes may begin
only after the dry-run receipts prove the intended daily volume, surface mix,
budget behavior, and duplicate handling.

## 12. Unexpected Broadcast Spike Risks And Mitigations

The phrase "broadcast spike" here means an unexpected burst of public egress:
many posts, many surface writes, duplicate fanout, or a retry storm. It does
not require livestream/audio broadcast involvement.

| Spike risk | Plausible trigger | Required mitigation | Verification |
| --- | --- | --- | --- |
| Backlog flush | A producer starts after days of accumulated events and drains them into `publish/inbox/` or RVPE at once. | Rolling budgets plus per-surface caps; dry-run replay before removing source holds; candidate receipts include source cursor and budget state. | Test seeded backlog over cap and assert `hold` with no publisher calls. |
| Fanout multiplier | One artifact targets weblog, Mastodon, Bluesky, Are.na, Bridgy, and legacy omg.lol helpers simultaneously. | Surface classification gate plus per-surface budgets; direct weblog-derived downstream fanout stays opt-in unless source URL sequencing is proven. | Test multi-surface artifact and assert each surface has an independent budget/classification receipt. |
| Duplicate replay | Cursor reset, event-id ledger loss, branch rollback, or artifact re-drop replays the same content. | Preserve existing idempotency owners; duplicate decision writes receipt but performs no public write and consumes no success budget. | Test duplicate event/artifact across orchestrator and surface-event paths. |
| Retry storm | Temporary auth/rate/network failures are retried every tick across many surfaces. | Retryable failures are `hold` with retry owner/backoff metadata; missing credentials remain terminal configuration failures unless explicitly re-dropped. | Test repeated retryable failure does not increase public call count or success budget. |
| Credential restoration burst | A missing credential or bootstrap receipt becomes available and previously held candidates all become eligible. | Budget still applies after credential recovery; conditional surfaces require current bootstrap receipts and begin in dry-run for broad visibility. | Test held candidates after bootstrap are released only within cap. |
| Timer overlap | Multiple systemd timers or manual invocations overlap, bypassing per-process counters. | Success-budget accounting reads persisted receipts, not process memory; concurrency cap applies across current in-flight receipts. | Test two gate instances sharing the same state root. |
| Legacy bypass | Guarded legacy omg.lol utilities are called by a new producer outside publication-bus/RVPE lifecycle. | `shared.legacy_omg_surface_policy` classification is load-bearing; guarded legacy broad fanout is `reject`. | Test guarded legacy surface requested for broad visibility rejects. |
| Operator bulk move | Many approved artifacts are moved from draft to inbox at once. | Operator action remains allowed, but gate budgets and receipts pace public writes; excess holds rather than publishes. | Dry-run with representative bulk inbox and assert no cap breach. |
| Source activation profile mistake | A deployment enables every visibility timer/profile at once. | Runtime activation is separate from source implementation; source-controlled activation profile must start in global dry-run and include source holds. | Activation checklist requires dry-run receipts before public profile switch. |

These mitigations are mandatory for V0 because the request target is tens of
drops per day. The system should be able to generate high volume internally
without creating high public volume until the gate deliberately releases it.

## 13. Pass Criteria For Broad Visibility Activation

The future V0 implementation may be accepted only when all of these are true:

- Focused tests prove kill-switch hold, global cap hold, per-surface cap hold,
  dry-run hold/no-send, unknown/refused surface reject, guarded-legacy reject,
  bus-backed pass, idempotent duplicate no-send, and receipt shape.
- Existing publication hardening gate tests still pass.
- Existing publish orchestrator tests still pass.
- Existing publication bus surface registry tests still pass.
- Existing legacy omg.lol policy tests still pass.
- A dry-run volume replay with representative artifacts/events writes receipts
  and performs zero public egress.
- No service is enabled or restarted as part of the implementation PR.

## 14. Acceptance Mapping

This ISAP satisfies the planning slice as follows:

| Requirement | Disposition |
| --- | --- |
| Dependency queue resolved before planning | #3229, #3230, and #3231 are merged; source baseline is clean `origin/main` |
| Pass/hold/reject behavior | Sections 5, 11, and 13 define behavior and validation |
| Rate limits and caps | Section 6 defines global and per-surface defaults |
| Idempotency | Section 8 binds existing owners and duplicate behavior |
| Kill switch | Sections 5, 6, 9, and 10 preserve file kill switch semantics |
| Dry-run mode | Section 9 requires global no-egress dry run |
| Operator-visible receipts | Section 10 defines the receipt contract |
| Bus-backed/refused/legacy-scoped surfaces | Section 7 defines classification requirements |
| GO/NO-GO criteria | Sections 1 and 11 define runtime activation criteria |
| Unexpected broadcast spike risks and mitigations | Section 12 defines spike scenarios, mitigations, and verification requirements |
| No activation/public egress | Sections 1, 4, and 11 prohibit runtime activation and public writes |
