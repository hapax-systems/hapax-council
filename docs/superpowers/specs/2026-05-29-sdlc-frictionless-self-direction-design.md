# SDLC Frictionless Self-Direction — Design

**Date**: 2026-05-29
**AuthorityCase**: CASE-SDLC-REFORM-001
**Parent request**: REQ-20260529-sdlc-dispatch-friction-audit
**Source audit**: workflow `wf_15bdcc6e-411` (full audit + adversarially-verified design, 27 fixes)
**Status**: foundational cluster implemented (this PR); later clusters deferred (see below)

This is the canonical parent_spec for the SDLC frictionless reform. It completes the
half-deployed `CASE-SDLC-REFORM-001` by flipping the fail-closed mutation/work gates to
**fail-open-WITH-ledger** for *authorized* work while retaining every governance invariant.
The full adversary-hardened design (all clusters) is reproduced verbatim in
[§ Unified Friction-Removal Design](#unified-friction-removal-design-v2-adversary-hardened)
below. This PR implements only the **foundational cluster** (audit steps 1–4 + the step-2
review mechanism); the claim-slot model, dispatch, release/storm, and self-direction clusters
are separate follow-on tasks rooted in this same spec.

---

## Foundational cluster — as-built (this PR)

Spirit retained (none broken): authorized-work-only, intake-as-authority-source, append-only
ledger traceability, quality-gates-before-release, scope-bounded mutation, zero synchronous
operator gate. **Every loosening is fail-open-WITH-ledger** — advisory + logged, never silent.

Baseline: the live 651-line `hooks/scripts/cc-task-gate.sh` from PR #3731 (origin/main), not
the older 428-line form. Line references in the task note were against this baseline.

### Changes

1. **FR-BASH-MUTATION-FALSE-POSITIVES** — `cc-task-gate.sh`. Two complementary fixes feed the
   shell-source-scope guard (`bash_source_mutation_requires_scope`), and **only** that guard —
   `bash_is_mutating` / `bash_is_runtime_mutation` stay raw so a quoted `systemctl` or a
   python-heredoc write still fails closed:
   - `CMD_STRIPPED` strips single/double-quoted spans (the proven `no-stale-branches.sh:75`
     `sed -zE` line, which spans newlines for `"$(cat <<'EOF'…)"` payloads) plus trailing
     comments anchored at a word boundary (`s/(^|[[:space:]])#[^\n]*//g`, so `${v#x}` / URL
     fragments survive). This kills false positives where `rm`/`mv`/`>` appear only inside a
     commit message or echo payload.
   - The `sed`/`perl`/`cat` sub-patterns are anchored with `[^|;&]*` (not greedy `.*`) so the
     mutating flag/redirect must belong to that command and cannot be borrowed across a pipe or
     separator. This kills the `sed 's/x/y/' f | grep -iE p` false positive (the `-i` there is
     grep's). `CMD_STRIPPED` alone does **not** fix this case (the proven quote-strip leaves the
     downstream `grep -iE` intact), so the anchor is a required, in-spirit addition documented
     here. A genuine `sed -i …` / `cat … > f` stays blocked.

2. **FR-EMERGENCY-BYPASS-UNSURFACED** (the review mechanism the loosening depends on; built
   first) — `session-context.sh` reads `~/.cache/hapax/methodology-emergency-ledger.jsonl` and
   prints a 24h SessionStart digest grouped by kind, flagging emergency bypasses for REVIEW and
   marking them OVERDUE past the SLA. The same jq summary is packaged as a reusable, read-only
   tool `hooks/scripts/methodology-ledger-digest.sh` with `--since` / `--sla` / `--json` /
   `--ntfy` / `--exit-code` — one core for the daily ntfy digest, the CI PR check, and the
   review-SLA escalation. (Wiring a systemd timer and a GitHub workflow is **runtime/CI scope**,
   excluded from this task's mutation surface; deferred to a follow-on runtime task. The script
   is the reusable, tested core those wirings call.)

3. **FR-STAGE-S6-TRAP** — `cc-task-gate.sh`. A blank/unparseable `stage` on a task that already
   carries `authority_case` + `parent_spec` (both verified non-null upstream) + `implementation_authorized: true`
   is a template gap, not a stage deficiency. The gate derives S6 **and stamps an explicit
   numeric stage** (`stage: S6_IMPLEMENTATION`) durably into the note so downstream release/packet
   checks read it consistently (closing the `stage_num=-1` shadow-denial brick). Emits a
   `{"kind":"stage_derived"}` ledger line. A blank stage **without** `implementation_authorized: true`
   still blocks — the loosening never invents authority.

4. **FR-AUTHORITY-FIELDS-FIRST-MUTATION-BLOCK** — `cc-task-gate.sh`. `authority_case` and
   `parent_spec` remain **hard** requirements (the verified authority root), with error messages
   now pointing at in-session repair (`cc-task-repair`, next cluster). A nullish
   `route_metadata_schema` (only legal value: `1`) is defaulted in-memory to `1` with a
   `{"kind":"route_schema_defaulted"}` ledger line instead of `exit 2`.

5. **FR-SCOPE-GATES-COGNITION** — `cc-task-gate.sh`. A cognition/diagnostic early-return is placed
   immediately after `edit_path` is parsed and **before** the claim/authority/stage/scope blocks
   (the adversarial review flagged a defect where it sat after them, re-introducing the brick).
   Always-allowed regardless of claim or scope, emitting a `{"kind":"cognition_allow"}` ledger
   line (never silent): operator auto-memory (`~/.claude/**/memory/`), the personal vault
   (`~/Documents/Personal/**`), `/dev/shm/**`, and project diagnostic scratch (`/tmp/hapax-*`).
   Two deliberate, safer narrowings vs the raw design list, documented for review:
   - **Governance SSOT excluded.** `~/Documents/Personal/20-projects/hapax-cc-tasks/` and
     `…/hapax-requests/` are NOT cognition — they keep the dedicated content-validated
     bootstrap/claim path so task/request notes cannot be forged or edited unclaimed. (Claim
     files live in `~/.cache/hapax/` and are never carved out.)
   - **`/tmp` narrowed to `/tmp/hapax-*`.** A bare `/tmp` carve-out would let an unclaimed lane
     write arbitrary `/tmp` source; only the project's own diagnostic scratch is exempt.
   - **Repo `docs/*.md` NOT carved here.** Repo markdown keeps the existing
     `docs_mutation_authorized` gate (which already relaxes the S6/impl requirement for docs).
     Broadening cognition to repo docs would change the docs-authorization invariant and is a
     separate, explicit follow-on.

6. **FR-WRG-PARKED-BRANCH-EDIT-BLOCK** — `work-resolution-gate.sh`. Cognition/docs/diagnostic
   `edit_path`s are exempted from the parked-branch ("commits ahead, no PR") block so a session
   can keep notes, docs, and diagnostics flowing while source work awaits a PR. The source block
   remains keyed to **this worktree's branch** (via `git rev-parse` in the file's repo and, on
   main, the §7 `git worktree list --porcelain` membership filter) — never a role-name prefix
   (the repo convention is `feat|fix|docs|chore` prefixes, which makes role-prefix ownership
   vacuous). The governance SSOT is likewise not blanket-exempted here.

### Ledger kinds (all in `methodology-emergency-ledger.jsonl`)

| kind | meaning | needs review? |
|------|---------|---------------|
| `emergency_bypass` / `early_infra_bypass` (or no `kind`) | `HAPAX_METHODOLOGY_EMERGENCY=1` bypass | **yes** (SLA) |
| `stage_derived` | blank stage → S6 derived + stamped | informational |
| `route_schema_defaulted` | nullish `route_metadata_schema` → 1 | informational |
| `cognition_allow` | cognition/diagnostic surface allowed | informational |

### Tests

- `tests/hooks/test_sdlc_frictionless_loosening.py` — CMD_STRIPPED + pipe-tighten (and real
  `sed -i` still blocked), route-schema default + ledger, cognition allow + ledger (memory,
  vault, `/tmp/hapax-*`), governance-SSOT-and-repo-docs-are-not-cognition, WRG cognition exempt.
- `tests/hooks/test_methodology_ledger_digest.py` — digest script (empty / inferences-only /
  bypass-review / overdue-SLA / `--json` / `--exit-code`) and the session-context surfacing fragment.
- `tests/hooks/test_authority_case_gate.py` — updated: `test_missing_stage_with_impl_auth_derives_s6`
  (was `test_missing_stage_blocks_source_mutation`) + `test_missing_stage_without_impl_auth_still_blocked`.

All existing hook tests pass unchanged in a clean environment (the one updated test reflects the
intentional stage-derivation behavior change required by the acceptance criteria).

### Deferred to follow-on clusters (rooted in this spec)

Claim-slot model (`HAPAX_PER_SESSION_CLAIMS`, `resolve-active-claim.sh`), `cc-task-repair` and the
governed-tool fleet, `--promote` child-case minting + signed standing-case receipts
(`verify_case_granted`), dispatch auto-mint, `cc-pr-autoqueue --drain`, AVSDLC re-witness, branch
worktree-membership reform in `no-stale-branches.sh`, and the systemd-timer / GitHub-workflow
wiring of the digest. See the full design below.

---

## Unified Friction-Removal Design (v2, adversary-hardened): Self-Directing Sessions, Zero Operator Gates

### Goal

A VISIBLE Claude session (e.g. alpha) must OWN work and DIRECT it to other lanes fully autonomously, in the spirit of the methodology, with ZERO synchronous operator gates and ZERO catch-22s. Every governance invariant survives; all friction collapses. Every line reference and every claim below was re-verified live against the canonical worktree `~/projects/hapax-council`, and the three adversarial verdicts have been incorporated: every false-premise fix dropped, every fabricated API implemented, every new catch-22 closed.

### Governing principle

For an AUTHORIZED session, every gate flips from **fail-closed-and-opaque** to **fail-open-with-ledger-and-review** — and every governance object becomes **repairable in place by a diff-gated writer**. "Authorized" means the claimed task carries a non-null `authority_case` that is **verifiably granted** (a signed standing-case receipt, not a self-typed string), a non-null `parent_spec` **file** whose `case_id` matches, and the relevant boolean is `true`. The fail-closed core survives exactly there. Everything redundant or stricter than those verified-authority facts becomes a loosen-log-AND-review condition. This is safe because (a) the authority root is now externally verifiable, (b) the loosening writers enforce explicit field-diffs (they cannot escalate authority), and (c) the review SLA (FR-EMERGENCY, sequenced early) ensures the ledgers are acted on, not rubber-stamped.

### What changed from v1 in response to the adversary (the load-bearing corrections)

1. **`case_migration.mint_child_case` does not exist** (verified: only `generate_case_id` at :181). v2 IMPLEMENTS it on top of `generate_case_id`, and crucially it WRITES a REAL `parent_spec` CASE/spec file so the promoted task satisfies `cc-task-gate.sh:421` AND `dispatch validate_task:515-535`, which both require a parent_spec **file** with matching `case_id` (verified). v1's `parent_request`-only task would claim but never mutate/dispatch — that catch-22 is now removed, not relocated.
2. **The authority root was never verified.** v1 "trusted the recorded authority more" while the codebase only nullish+regex-checks `authority_case`. v2 adds a SIGNED standing-case receipt (reusing the proven `PlatformCapabilityReceipt` StrictReceiptModel + sha256 + freshness, verified at `shared/platform_capability_receipts.py`) and a `verify_case_granted(case_id)` helper called by cc-dispatch-bind, cc-task-repair authority backfill, and dispatch auto-mint. The standing case is written ONCE by an OPERATOR-ONLY guarded script, never a writable cache file.
3. **FR-LOOSE-MQ-BINDING-FOOTGUN is DROPPED** — the SQL already mandates `m.authority_case = :authority_case` (verified dispatch:431) and `relay_mq.py:53` has `CHECK(message_type != 'dispatch' OR authority_case IS NOT NULL)`. The wrong-case bind is structurally impossible. The effort is redirected to `verify_case_granted` (the real gap).
4. **Storm is non-mutating by contract** (verified `as_dict:210`). v2 does NOT inject merge/close into the storm advisor; it adds a SEPARATE explicit `cc-pr-autoqueue --drain` action. The advisor's contract is intact.
5. **cc-task-repair re-running `_validate_task` would refuse claimed/in_progress notes** (verified it requires `status:offered` + `assigned_to:unassigned` at bootstrap:202-205 — exactly the bricked-mid-work case). v2 uses a relaxed `repair_validate()` accepting offered/claimed/in_progress, and enforces "cannot flip a boolean true / body frozen / authority only from real parent" with an EXPLICIT field-diff in the writer (not the value-blind validator).
6. **No session-id plumbing exists** (verified) and per-pid is unstable across hook subprocesses. v2 keys the session id to the stable PGID and persists it at SessionStart.
7. **`claimed-deferred` would be an orphan status** no reader understands. v2's cc-defer reuses the existing `claimed` status + a `deferred:true` marker.
8. **The cc-claim rewrite would break `check_worktree_claim_guard`** (verified string-matches at dispatch:319-327) and v1 only synced hooks/. v2 makes syncing BOTH hooks/ AND scripts/ into every worktree a HARD step and preserves the literal strings.
9. **Cognition carve-out placement** must be BEFORE the authority/stage blocks at L410 (v1's "before L447" was after them — verified the stage block is at L470).
10. **Blank-stage→S6 left a release-time shadow-denial brick** (verified packet-validator:179 fires when stage_num=-1 and release!=false). v2 STAMPS an explicit numeric stage so the release gate reads it consistently.
11. **Branch/parked-branch ownership by role-prefix is vacuous** — the convention is feat/fix/docs/chore (verified no-stale L109). v2 scopes ownership by WORKTREE MEMBERSHIP.
12. **No unconditional `--self-bind`/env escape** — auto-mint is gated on the session HOLDING the task's case (receipt-verified). A double-spawn race in retry is closed with a launch-idempotency key. AVSDLC never silently advisory-merges a stale/bad frame — it re-witnesses only on a verified-healthy surface, else signals + stays blocked.
13. **FR-EMERGENCY (the review mechanism) is sequenced EARLY** with a review SLA, so loosening is reviewed not rubber-stamped.

### Verified ground truth (re-confirmed at audit)

- `cc-task-gate.sh:42-60` greps the RAW command (no quote-strip); `:138-173` resolves role then reads the hardcoded `cc-active-task-$role`; `:410-442` blocks on nullish authority_case/parent_spec/route_metadata_schema; `:447-462` docs carve-out (`.md`/`docs/`) + emergency bypass log; the stage trap is at `:470` (`-z _stage_num || <6`); impl block at `:483`; scope check `:527+`.
- `no-stale-branches.sh:75` `CMD_STRIPPED` strips ONLY `'...'`/`"..."` (NOT heredoc bodies); `:88/:101` destructive gate; `:109` uses `(feat|fix|docs|chore)/` prefixes; `:168` cap=20; `:197-251` stale loops already skip other-worktree (`:202/:242`) and open-PR (`:244`) refs but have no ownership filter.
- `cc-claim:142` `READY_STATUSES={pr_open,merge_queue}`; `:70-73` --force prints "releasing" but the Python exits 4 for in_progress and never rewrites the slot; `:331-337` accepts `parent_spec|parent_plan|parent_request`; `:459/:483` writes the role slot.
- `cc-task-gate-bootstrap.py:202-205` requires `status:offered`+`assigned_to:unassigned`; `:221-223` route_metadata_schema must be 1; `:315-316` unconditional "target note already exists"; `_validate_task` does NOT require stage or boolean VALUES.
- `authorization-packet-validator.sh:82` reads the merger's `cc-active-task-$role`; `:149-159` requires all 5 no-go fields PRESENT (reports all at once); `:172-179` shadow-denial when `stage_num<7 and release!=false`.
- `hapax-methodology-dispatch:299` lane_worktree; `:319-327` check_worktree_claim_guard string-matches cc-claim; `:384-466` binding check; `:431` mandates `m.authority_case=:authority_case` (AND); `:499-535` assigned_to!=lane block + parent_spec file + case_id match requirement.
- `cc-pr-autoqueue.py:81` INDEPENDENT_QUEUE_ADMISSION; `:85` STORM_MAX_ENTRIES_TO_BUILD=1; `:210` "storm mode is non-mutating"; `:549` `_task_blockers` calls `evaluate_avsdlc_release_gate` but NOT `release_authorized`; `:566-575` independent exempts storm only.
- `shared/case_migration.py:181` `generate_case_id` (only); NO `mint_child_case`. `shared/relay_mq.py:53` dispatch CHECK constraint. `shared/platform_capability_receipts.py` StrictReceiptModel + sha256 + freshness. `shared/dispatcher_policy.py:450-487` rollback degraded; `:655-661` route_policy_green already in the record dict. NO `CLAUDE_SESSION_ID`/`HAPAX_SESSION_ID`/`director-lanes`/`--self-bind` anywhere.
- `request-intake-consumer` is read-only (`--write-receipt|--write-state|--write-planning-feed`; no `--promote`).

### Spirit invariants — mechanically preserved

- **Authorized-work-only, verifiably rooted.** Source mutation requires `implementation_authorized:true` (gate:483) + non-null `authority_case` (gate:410) + a real `parent_spec` file with matching case_id (dispatch:515-535) + the case is GRANTED (verify_case_granted against the signed standing-case receipt). We trust the booleans more only because the case beneath them is now externally verifiable.
- **Intake-as-authority-source.** Prose → read-only `hapax-request` → `--promote` (verify held case → mint a real child case+spec → offered task with real parent_spec → MQ binding). The seam is retained; the dead-end is removed; no authority is invented.
- **Append-only traceability + review.** Every loosening (stage inferred+stamped, field defaulted, binding auto-minted, branch reassigned, drain-merge/close, emergency bypass) appends a record, AND surfaces at SessionStart/ntfy with a review SLA (FR-EMERGENCY, early).
- **Release authority distinct from implementation.** `release_authorized:true` stays a separate explicit flip; the release gate reads the PR's ORIGINATING task (via a mandatory cc-task trailer); `--drain` merges only green + release-authorized + AVSDLC-fresh PRs.
- **Scope as a source guardrail.** Source/runtime scope (gate:527+) untouched. Cognition surfaces are carved out via an early-return BEFORE L410; their integrity is enforced by the diff-gated repair writer, not by scope alone.
- **Zero SYNCHRONOUS operator gate.** Two one-time PRE-authorizations remain by design (signed standing-case grant; one-time signed model-entitlement receipt), each written by an operator-only-guarded script and never synchronous to later progress.

### Claim-slot model (the linchpin)

Session-keyed lease slots `cc-active-task-<role>--<session_id>` with `session_id` keyed to the stable PGID (persisted at SessionStart), a `cc-active-task-<role>` symlink for back-compat (the packet-validator reads the role file), resolved by one extracted `resolve-active-claim.sh`. Precedence: this-session slot → single-unambiguous role slot (today's behavior, zero regression) → BLOCK on multiplicity (a self-serviceable hop, not an operator gate). Heartbeat lease (>12h or terminal → no-claim, swept). cc-claim idempotent + resumes in_progress for the owner; `--force` atomically release-then-writes (fixing the dangling-slot bug); cc-defer reuses `claimed`. The rewrite preserves the worktree-guard literals and ships with the scripts/ fleet-sync. Behind `HAPAX_PER_SESSION_CLAIMS=1` (off = today).

### The catch-22 cycles, each broken at its root (and re-verified)

1. shared-role-slot collision → session-keyed PGID-stable lease slots + single-unambiguous fallback.
2. in_progress-claim refusal → idempotent resume + atomic --force + cc-defer/cc-resume on the existing `claimed` status.
3. malformed-task unrepairable (offered AND claimed) → diff-gated cc-task-repair with relaxed repair_validate + bootstrap additive-upsert + blank-stage-derives-and-stamps-S6.
4. packet-validator template gap → absent→false (presence-check only, never leaking to gate VALUE checks) + one-pass backfill + template.
5. storm-admission deadlock → storm advisor stays non-mutating; a separate explicit `--drain` merges clean-mergeable and closes terminal-task PRs.
6. manual-merge release lockout → release gate reads the PR's originating task via a mandatory cc-task trailer enforced at PR-create.
7. branch-creation/parked-branch block → ownership by WORKTREE MEMBERSHIP (the feat/fix/docs/chore convention makes role-prefix vacuous).
8. degraded-route default → loud banner + on-demand refresh-registry + operator-only signed opus/sonnet receipts.
9. idle-watchdog vs raw-prose self-direction → `--promote` mints a REAL parent_spec child case (mint_child_case implemented) rooted in a SIGNED standing case + coordinator author-affinity.
10. worktree-script-drift self-block → sync BOTH hooks/ AND scripts/ fleet-wide as a hard step; preserve the guard literals.
11. double-spawn on retry → launch-idempotency key.
12. AVSDLC false-fresh/advisory-merge → re-witness only on a verified-healthy surface; signal + stay blocked otherwise.

### Self-direction protocol (one session, zero synchronous operator gates)

Signed standing case granted ONCE → INTAKE (write request note) → AUTHORIZE (`--promote`: verify held case → mint real child case+spec → offered task with real parent_spec → MQ binding) → CLAIM (idempotent; blank stage derives+stamps S6; no-go defaults false; route schema defaults 1; first mutation still needs impl_authorized:true which --promote sets; cc-task-repair if malformed, offered OR claimed) → IMPLEMENT (cognition scope-exempt via early-return before L410; diagnostics no longer false-positive) → DIRECT (offered tasks with preferred_lane, held-case-gated auto-minted bindings, cc-reassign with parent_spec re-validation; coordinator author-affinity first-offer-then-fall-through) → RELEASE (cc-task trailer → release gate reads originating task; `--drain` self-merges clean PRs even under storm; manual merge of any green release-authorized PR) → RECOVER (own-worktree re-attach by membership, guarded merged-clean prune, ntfy; idempotent resume; retry transient blocks with held-case auto-mint + refresh-registry + launch-idempotency) → OBSERVE (`cc-why-blocked` drives real gates via synthesized payloads; bypasses/inferences/degraded routes surface loudly with a review SLA).

### Files touched (complete set — across all clusters)

- `hooks/scripts/cc-task-gate.sh` — CMD_STRIPPED quote+comment strip on the L56 source-scope grep ONLY; blank-stage→S6-with-explicit-stamp + ledger; route_metadata_schema default 1; report-all (`--report`) + repair-pointer; cognition early-return before L410; resolver-based slot read.
- `hooks/scripts/authorization-packet-validator.sh` — absent no-go → false (presence-check only, not value checks); PR-originating-task release check; resolver-based slot read.
- `hooks/scripts/cc-task-gate-bootstrap.py` — additive-upsert on offered notes (diff-gated); template adds docs_mutation_authorized + public_current.
- `hooks/scripts/no-stale-branches.sh` — worktree-membership stale-ref filter; own-worktree re-attach cap exemption; guarded merged-clean auto-prune; ntfy on true cap.
- `hooks/scripts/work-resolution-gate.sh` — cognition/docs/diagnostics always-allow; source block keyed to this worktree's branch.
- `hooks/scripts/session-context.sh` — write/export PGID-stable HAPAX_SESSION_ID; emergency/inference-ledger SessionStart summary + review SLA; RAW-PROSE-GATE points at `--promote`.
- `hooks/scripts/resolve-active-claim.sh`, `hooks/scripts/agent-role.sh` — NEW shared resolver + role inference.
- `scripts/cc-claim` — session-keyed pgid lease slot; in_progress resume; atomic --force; role inference; preserves worktree-guard literals.
- `scripts/cc-task-repair`, `scripts/cc-task-stamp-stage`, `scripts/cc-task-backfill-nogo`, `scripts/cc-reassign`, `scripts/cc-defer`, `scripts/cc-resume`, `scripts/cc-dispatch-bind`, `scripts/cc-why-blocked`, `scripts/cc-avsdlc-rewitness`, `scripts/hapax-grant-standing-case`, `scripts/hapax-record-model-entitlement`, `scripts/cc-record-quality-equivalence` — NEW governed tools (the last three operator-only-guarded).
- `scripts/request-intake-consumer` — `--promote` child-case mode (verify held case → mint real spec → offered task → bind).
- `scripts/hapax-methodology-dispatch` — held-case-gated auto-mint on --launch; dry-run headline fix; lane_worktree dynamic fallback + .hapax-lane; auto-claim on launch; retry/requeue + launch-idempotency key; loud degraded + stale-registry banners; refresh-registry subcommand; hooks/+scripts/ drift sync.
- `scripts/cc-pr-autoqueue.py` — `_is_clean_mergeable` (with explicit release_authorized read) + storm-throttle exemption; SEPARATE `--drain` action (merge clean + close terminal-task, storm advisor untouched); independent/release naming clarification.
- `agents/coordinator/core.py` — author-affinity dispatch (first-offer-then-fall-through).
- `shared/case_migration.py` — NEW `mint_child_case(parent_case_id, task)` writing a real child CASE/spec note, built on `generate_case_id`.
- `shared/dispatcher_policy.py` — loud route_policy_green surfacing; bounded inline registry refresh; opus/sonnet blocked_reasons receipt-clearable; `verify_case_granted` consumer.
- `shared/standing_case_receipts.py` — NEW signed standing-case receipt model (reusing the platform-capability-receipt pattern) + `verify_case_granted`.
- `shared/release_gate.py` / `avsdlc-release-precheck.py` — surface-health-probed re-witness + rewitness_needed signal + blocked fallback.
- `config/platform-capability-registry.json` — opus/sonnet entitlement/equivalence receipt-clearable.

### Risk posture

The Medium-risk edits (session-keyed slot readers, coordinator author-affinity, the `--drain` merge action, PR→task release mapping, mint_child_case + signed standing case, held-case-gated auto-mint) are each gated so the default path is unchanged when the new field/flag/receipt is absent (HAPAX_PER_SESSION_CLAIMS off = today; affinity only on preferred_lane; `--drain` is a separate opt-in action on green+release+fresh / terminal PRs only; auto-mint only for held cases), fail closed on ambiguous mapping, and reuse proven machinery (the no-stale CMD_STRIPPED sed, cc-pr-autoqueue `_matching_tasks`, the platform-capability-receipt model, the existing claim-release path, the storm decision predicates). The two genuinely escalation-capable primitives — `mint_child_case` in `--promote` and held-case auto-mint in dispatch — are both constrained to a SIGNED, operator-granted standing case verified by `verify_case_granted`, both produce a real parent_spec that satisfies gate+dispatch, and both are fully ledgered and reviewed under the SLA. The remaining fixes are S-effort, low/very-low risk, mostly output-only surfacing, diff-gated repair, or narrow non-source allowlists. Every adversarial gap — fabricated API, non-existent footgun, storm contract break, claimed-malformed dead-end, orphan status, worktree-script drift, session-id instability, heredoc fail-open, shadow-denial brick, role-prefix vacuity, unconditional self-bind, AVSDLC advisory-merge, double-spawn, missing review SLA — is closed in this revision.
