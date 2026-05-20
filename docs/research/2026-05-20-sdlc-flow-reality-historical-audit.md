# SDLC Flow Reality And Historical Gap Audit

Generated: 2026-05-20T22:48:16Z

Authority context: `CASE-SDLC-COMPLETION-GATE-20260518`, CCTV intake gate design, baseline ISAP/AuthorityCase methodology, and AVSDLC methodology.

## Scope

This audit covers the actual path from request intake to production and closure:

1. Request capture and read receipts.
2. CCTV hardening and request eligibility.
3. Request decomposition into cc-tasks.
4. Dispatch, lane pickup, and claim.
5. Mutation, evidence, PR, CI, and merge queue.
6. Source activation, runtime deployment, and production witness.
7. Task closure and request fulfillment reconciliation.
8. Historical drift detection and correction.

Operator prose, relay notes, dashboards, and terminal transcripts are treated as intake evidence, not implementation authority.

## Live Inventory

Read-only inventory from the vault and runtime on 2026-05-20:

- Active request files: 77.
- Request types: 36 `hapax-request`, 41 legacy `request`.
- Legacy `request` notes with explicit `request_id`: 0.
- Active request statuses: 65 `accepted_for_planning`, 6 `captured`, 5 `active`, 1 `phase0_active`.
- Requests with explicit `downstream_tasks`: 1.
- Undecomposed accepted requests after full-frontmatter scan: 47.
- Request fulfillment dry-run: 1 eligible, 76 blocked.
- Request fulfillment blockers: 53 `no_linked_tasks`, 17 `implicit_linkage_requires_explicit_fulfillment`, 5 `request_status_not_closeable:active`, 1 `request_status_not_closeable:phase0_active`.
- Active cc-tasks: 125.
- Active cc-task statuses: 73 `blocked`, 22 `offered`, 11 `pr_open`, 7 `merge_queue`, 7 `in_progress`, 4 `claimed`, 1 `open`.
- Closed cc-task non-canonical statuses still exist: `completed`, `withdrawn_stale`, `closed_poisoned`, `closed_superseded`, `resolved`, `not_applicable`, `deferred`.
- Planning feed after legacy request visibility repair: 77 total requests, 55 attention items, 2 dispatchable tasks.
- User timers: request intake active, request decomposition active, merge watcher active, PR autoqueue disabled/inactive, source activation timer not found.
- Merge queue snapshot: PR #3613 awaiting checks, PR #3614 queued.

## Intended Flow

The intended SDLC is coherent:

1. Intake captures a request note and durable receipt.
2. CCTV hardening classifies it as ready for decomposition, needs hardening, needs research, or rejected.
3. Accepted requests receive authority, parent lineage, route metadata, mutation surface, quality floor, and explicit acceptance criteria.
4. Decomposition creates a complete DAG of cc-tasks with dependencies, WSJF, non-null lineage, route metadata, and explicit downstream links back to the parent request.
5. Dispatch goes through `hapax-methodology-dispatch`, which binds task, lane, platform, profile, worktree, claim command, close command, route evidence, and capability blockers.
6. Workers claim exactly the dispatched task through `cc-claim`; mutation is gated by active claim, authority, state, declared surface, and evidence expectations.
7. PR creation links the task to the PR; autoqueue admits only governed, linked, green, checklist-complete PRs.
8. Merge queue and CI establish source-level acceptance only.
9. Source activation and post-merge deploy make merged source operationally visible.
10. Runtime or production witness satisfies S7/S8/S9 evidence, especially for runtime, visual, audio, audiovisual, public, or aesthetic work.
11. `cc-close` moves completed tasks to closed.
12. Request fulfillment reconciliation closes the request only when explicit downstream work actually satisfies the request.

## Actual Failure Pattern

The system currently fails by fragmentation, not by absence of policy.

- Receipts can be fresh while decomposition is broken.
- Requests can be accepted but invisible because the live vault contains legacy `type: request` notes without `request_id`.
- Decomposition was a separate timer and could abort the entire backlog on one duplicate generated task id.
- Generated tasks could carry route metadata that did not match the routing ontology.
- Generated tasks did not write `downstream_tasks` back to the parent request, so fulfillment reconciliation could not prove explicit request coverage.
- Dispatch policy exists, but some wrappers or bootstrap text still contain generic self-claim or fail-open behavior.
- PR autoqueue is disabled/inactive, so merge queue hygiene depends on manual shepherding.
- The activated source worktree can lag `origin/main`, so merged automation fixes may not affect live timers.
- Merge can be treated as task acceptance even when production runtime witness is still missing.
- AVSDLC S7/S8/S9 requirements are documented, but they are not uniformly release-blocking in PR autoqueue, merge watcher, source activation, or post-merge deploy.

## Baseline Methodology Enforcement Gaps

| Stage | Intended enforcement | Actual gap | Repair in this change | Remaining correction |
| --- | --- | --- | --- | --- |
| Request identity | Active requests are first-class SSOT records | 41 active legacy requests used `type: request` and no `request_id` | Intake now accepts legacy `request` type and derives id from filename | Normalize vault records through governed migration |
| Decomposition scan | Scan only truly undecomposed accepted requests | Scan read only first 500 chars of task notes and missed existing `parent_request` links | Scan parses full frontmatter and respects `downstream_tasks` | Run decomposition after activation and review generated DAGs |
| Decomposition resilience | One duplicate must not stall the whole backlog | One `FileExistsError` stopped all decomposition | Scan logs duplicate and continues | Add dashboard alert for repeated duplicate ids |
| Parent linkage | Requests know their downstream tasks | Writer created task files only | Writer updates parent request `downstream_tasks` and decomposition metadata | Reconcile historical implicit links into explicit links |
| Parent lineage | Mutating tasks carry non-null parent spec | Decomposer could emit `parent_spec: null` | Decomposer falls back to parent plan or request path | CCTV hardening should supply stronger parent specs before decomposition |
| Route metadata | Task metadata matches routing ontology | Prompt allowed `vault` and `system`, not valid route surfaces | Prompt and normalizer use `none`, `vault_docs`, `source`, `runtime`, `public`, `provider_spend` | Audit existing generated tasks with invalid surfaces |
| Dispatch | Cross-runtime launch goes through methodology dispatch | Direct executable path can fail outside venv with missing `agentgov` | Cross-runtime wrapper uses `uv run python` and exports repo/agentgov path for standard dispatcher | Remove stale self-claim instructions in Antigrav/Vibe bootstrap surfaces |
| Closure cursor | Merge watcher retries failed closes | Cursor could advance past a failed close when a later unlinked PR was observed | Watcher now advances only across the failure-free prefix | Repair any tasks skipped by previous cursor advancement |
| Multi-task PRs | One merged PR closes all linked active tasks | Watcher closed only first linked task | Watcher now closes every active task linked to the PR | Audit active PR-linked tasks for prior missed closes |

## AVSDLC And Aesthetic Methodology Gaps

AVSDLC policy is materially stronger than the current enforcement surface.

Intended AVSDLC requirements include classification of visual, audio, audiovisual, aesthetic, theoretical, public, and runtime axes; explicit standards and failure predicates; fresh witness evidence; S7 runtime verification; S8 release decision; and S9 post-merge production regression.

Observed gaps:

- PR merge and CI can close source work before live production witness exists.
- Post-merge smoke is advisory rather than release-blocking.
- ORR-lite release gate exists in code but is not wired into autoqueue, source activation, or post-merge deploy as a hard blocker.
- Some AVSDLC dossiers defer live witness; that is valid as an interim record but not full release evidence.
- Aesthetic/visual/audio requests can enter accepted planning without a mechanically enforced AVSDLC axis dossier.
- Request closure currently reasons mostly from task linkage and checkboxes, not from AVSDLC dossier freshness or production witness.

Historical correction for AVSDLC must not bulk-close based on merged PRs. It must classify each impacted request/task by axes, then require the missing dossier or witness before fulfillment.

## Repairs Included Here

This change makes the following mechanical corrections:

- `request-intake-consumer` recognizes legacy `type: request` notes and derives missing request ids from filenames, while preserving strict malformed handling for canonical `hapax-request` records missing `request_id`.
- `request-decompose` parses full task/request frontmatter, skips requests with `downstream_tasks`, tolerates duplicate task files without aborting the backlog, emits non-null parent lineage from the request path when needed, and normalizes mutation surfaces.
- `agents/request_decomposer/writer.py` writes task files and then links the parent request with `downstream_tasks`, `decomposed_at`, `decomposition_model`, and `decomposition_task_count`.
- `cc-pr-merge-watcher.py` closes all active tasks linked to a merged PR and makes cursor advancement prefix-safe after any failed close.
- `hapax-cross-runtime-dispatch` invokes the standard methodology dispatcher through `uv run python` and exports the repo plus `packages/agentgov/src` path when using the in-repo dispatcher.

## Historical Correction Plan

Correction should be systematic and evidence-preserving:

1. Activate this source change into the live source-activation worktree.
2. Enable or repair missing automation timers: PR autoqueue and source activation are currently not enforcing the intended loop.
3. Run `request-decompose --scan --dry-run` and inspect the 47 accepted undecomposed requests.
4. Run `request-decompose --scan` only after confirming CCTV hardening inputs and LLM availability; duplicates must continue, not stop the batch.
5. Run `request-fulfillment-reconciler --dry-run --json`; focus first on the 17 `implicit_linkage_requires_explicit_fulfillment` requests because they likely need historical `downstream_tasks` repair, not new implementation.
6. Audit the 53 `no_linked_tasks` requests and split them into needs decomposition, needs hardening, rejected/withdrawn, or fulfilled outside automation.
7. Run merge watcher against a cursor before recent skipped closure failures and audit active `pr_open`/`merge_queue` tasks whose PRs are already merged.
8. For active tasks in invalid states such as `open`, create governed normalization or withdrawal tasks rather than direct edits.
9. For all visual/audio/audiovisual/aesthetic/theoretical/public/runtime requests, attach or verify AVSDLC dossiers and production witness before request fulfillment.
10. Remove or supersede stale generic self-claim instructions and fail-open claim behavior in runtime launchers.

## Correction Backlog

High-confidence backlog items identified by this audit:

- Normalize 41 legacy request notes or keep compatibility until normalization is complete.
- Decompose or harden 47 accepted requests with no downstream tasks.
- Repair explicit downstream fulfillment links for 17 requests blocked by implicit-only evidence.
- Triage 53 requests with no linked tasks.
- Reconcile 125 active cc-task files, especially 11 `pr_open`, 7 `merge_queue`, 1 `open`, and any merged-PR tasks stranded by prior watcher cursor movement.
- Enable and validate `hapax-cc-pr-autoqueue.timer`.
- Install or restore `hapax-source-activate.timer`, or document the intended non-timer activation route.
- Refresh the activated source worktree so live timers use current automation.
- Wire ORR-lite and AVSDLC release evidence into hard release/closure gates.
- Remove generic self-claim instructions from Antigrav/Vibe/bootstrap relay surfaces and make claim absence fail closed.
- Align state schemas so dashboards, shape checker, hooks, and runtime accept the same active and closed status vocabularies.

## Acceptance Standard For Future Closure

A request is not fulfilled merely because a PR merged or a task note moved to `closed`.

For source-only work, fulfillment requires explicit downstream task closure plus request acceptance criteria evidence.

For runtime, visual, audio, audiovisual, aesthetic, theoretical, public, or production-impacting work, fulfillment also requires current methodology evidence: axis classification, standards, failure predicates, runtime or media witness where applicable, release decision, and post-merge production regression evidence.

Anything else is a historical gap, not a fulfilled request.
