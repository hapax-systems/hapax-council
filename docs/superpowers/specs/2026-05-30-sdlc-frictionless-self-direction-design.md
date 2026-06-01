---
title: "Hapax Coordination Reform — Master Design (final, post-critique)"
type: design-research
created: 2026-05-30
tags: [hapax, sdlc, dispatch, coordination, reform, sbcl, clog, master-design]
source: claude-code reform-research workflow (12 findings + synthesis + adversarial critique)
related: [[sbcl-clog-coordination-frontend-authority-case-2026-05-17]]
---

Ground truth confirmed. The critique is right on nearly every anchor, with refinements:

- **17 ledger copies** (per-worktree, git-tracked) — confirmed.
- **0 CLOS classes** in coord — confirmed (the typed model is net-new).
- **2618 total cc-task files**; **255 active** (non-closed path), **18 with a stage** — so the stuck mass is ~237 active stage-less, and bulk total ~2600. (Critique said 423/120; my live count says 255/18 by path-based active filter — I'll cite both methods and the conservative reading.)
- **Three-way gate drift**: 779 LIVE / 651 repo / 427 lane-worktrees — confirmed, lanes run the *oldest* gate.
- **`is_cognition_path` exists ONLY in the LIVE cache gate, NOT in the repo** — confirmed (NEW-CATCH-3 is an active vector; the rebuild timer can clobber it).
- Daemon: `Restart=on-failure`, `StartLimitBurst=5`, ~150MB RSS — SPOF posture confirmed; Swank/live_eval forbidden.

Now I have what I need. Writing the final design as my response.

---

# THE HAPAX COORDINATION REFORM — FINAL
## SBCL-Orchestrated, Coherent-API, Formally-Rigorous, Obligatory Dispatch/SDLC
### Revision 2 — reworked against ground truth and the adversarial audit

*Chief architect synthesis, 2026-05-30. **All anchors re-verified live this session** and corrected where the prior draft was wrong (see §10). Confirmed this session: `hapax-coord.service` active, `Restart=on-failure`, `StartLimitBurst=5`, RSS ~150 MB; `coord` defines **0 `defclass`** across its 14 src files (the typed model is **net-new**, not "80% built"); `authority-case-ledger.jsonl` exists in **17 git-tracked per-worktree copies**, each ~7 lines; **2618 total cc-task files, 255 active (non-closed), only 18 with a `stage:`**; `cc-task-gate.sh` has **three live versions — 779 (LIVE `.cache`), 651 (repo), 427 (lane worktrees)** — lanes run the oldest; `is_cognition_path()` exists **ONLY in the LIVE `.cache` gate, not in the repo**; `live_eval`/`arbitrary_shell`/`service_mutation`/`merge_pr`/`direct_lane_launch` all `forbidden` (`config.lisp:173-177`); Swank unloaded.*

---

## 1. EXECUTIVE THESIS — the core reframe (corrected)

**The reform is a build of one hard new thing — a typed coordination kernel — plus a collapse of sprawl around it.** The prior draft called this a "promotion." That was wrong and the audit is right: **`coord` owns zero typed model today.** Its 6,680 LoC is a *CLI multiplexer* that shells out via `uiop:run-program` and re-exposes every coherence problem. So the honest framing:

> **Net-new (the hard 80%):** the CLOS world-model, the projection/replay engine, the `policy-decide` decision function (a faithful reimplementation of ~13k lines of branchy bash across 3 gate versions), the durable dispatch object, the lane supervisor, and the daemon-independent escape substrate.
> **Reuse (genuinely strong, verified):** the `GateToken` capability pattern (`shared/governance/gate_token.py` — unforgeable, frozen, nonce-bearing, demanded in persist signatures); the vault schema (cc-task/REQ/AuthorityCase, no-go booleans, S0–S11); the receipt *shape* already emitted by `control-preflight.lisp`; the `conductor-pre.sh` UDS pattern proving PreToolUse-JSON → daemon → exit 0/2 works; shadow-mode migration discipline.

The disease still has exactly four mechanisms, and every catch-22 traces to one:

1. **No typed model.** ~6 stores, 3 schema languages, 2–4 names per concept, no shared key. Gates re-derive shape by globbing/regex.
2. **Policy is imperative bash, now confirmed triplicated** (779/651/427) and string-matched, with the lanes that *run agents* carrying the oldest gate.
3. **Authority is ambient and TTL'd, not capability-bound.** Role-keyed claims → phantom-alpha deadlock; bypass via env var that never reaches the in-session hook; MQ authority is a loose `subject==task_id` query expiring in 10 min; escape hatches are themselves gated.
4. **The frontend renders the sprawl instead of resolving it.** 30s full-page `location.reload()`, blank to curl/agents, loopback-only, SDLC ladder drawn nowhere.

**The reframe — unchanged in direction, corrected in cost and centralization-safety:** Lift scattered policy, file-scraped state, and ambient authority into **one typed, model-checked, capability-secured, event-sourced Common Lisp coordination kernel** — `hapax-coord`, **rebuilt from multiplexer to kernel** — and make its **SDLC statechart the legible hero** of a reactive, evidence-able, reachable frontend all three runtimes call identically. **But every irreversible-harm gate and every escape hatch must remain executable when the daemon is dead** (the audit's central safety correction). SBCL *orchestrates*; the daemon-independent shim layer *enforces the floors and reads the escape grants*.

**The one-line spec:** *Keep every safety floor and make it daemon-independent. Cure opacity by making every gate a queryable predicate over a typed, projected, event-sourced model behind one `coord.*` API. Make obligation a signed, recorded grant — read directly by the bash shim, never via an RPC to a process that can be down. Guarantee never-stuck by giving every fail-closed a named, daemon-independent, authorized escape and an always-writable cognition surface — and check the invariants at runtime, advisory-with-ledger, never as a self-blocking proof gate.*

---

## 2. TARGET ARCHITECTURE — SBCL-orchestrated, floor-independent

### 2.1 The layered picture (centralization-corrected)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ L0  OPERATOR SURFACES                                                          │
│   CLOG cockpit (reactive, :8765) · Croatoan TUI · Obsidian (vault native)      │
│   · phone (Tailscale read-only ISAP) · Claude/Codex/Antigrav (API clients/MCP) │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │  ONE coherent API  (coord.* verbs; typed receipts)
┌───────────────▼──────────────────────────────────────────────────────────────┐
│ L1  SBCL COORDINATION KERNEL  (hapax-coord — ORCHESTRATOR, not enforcer)        │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ NET-NEW: Typed CLOS world-model: request·authority-case·cc-task·lane·    │  │
│  │   dispatch-run·pr·mq-message·grant-capability   [HEAP = DERIVED ONLY]    │  │
│  ├────────────────────────────────────────────────────────────────────────┤  │
│  │ SDLC STATECHART (*sdlc-ladder* data: S0..S11 + AVSDLC region + S3.5)     │  │
│  ├────────────────────────────────────────────────────────────────────────┤  │
│  │ policy-decide  (PURE fn → Decision)  ·  capability MINT (dispatch ocap)  │  │
│  ├────────────────────────────────────────────────────────────────────────┤  │
│  │ DURABLE DISPATCH (idempotency key) · LANE SUPERVISOR (one_for_one)       │  │
│  │ PROJECTION/REPLAY: rebuild ALL in-memory state from L2 ledger on boot    │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│   Kernel can be DOWN. When down: floors still enforce, escapes still mint.      │
└───────┬───────────────────────┬───────────────────────┬──────────────────────┘
        │ appends events         │ shares policy-decide   │ projects to / reads
┌───────▼──────────┐   ┌─────────▼──────────────┐   ┌─────▼──────────────────────┐
│ L2 EVENT LOG     │   │ L3 ENFORCEMENT FLOOR    │   │ L4 STORES (SSOT-of-record)  │
│  ONE daemon-owned│   │  (DAEMON-INDEPENDENT)   │   │  Obsidian vault = PROJECTION│
│  append-log,     │   │  18 hook shims, stable  │   │   of L2 for coordination    │
│  OUTSIDE all     │   │  abs-path, call         │   │   fields; operator-owned    │
│  worktrees       │   │  policy-decide IF up,   │   │   for life-planning fields  │
│  (SQLite/JSONL   │   │  ELSE evaluate embedded │   │  · messages.db (SQLite MQ)  │
│  at fixed path); │   │  floor + read grant     │   │  · capability registry      │
│  SSOT of every   │   │  FILE directly.         │   │  Logos API :8051 (read src) │
│  transition.     │   │  CI runs SAME fn.       │   │  RAG/Qdrant (vault feed)    │
│  Vault = replay  │   │  Fail-CLOSED: release/  │   │                             │
│  projection.     │   │  egress/axiom/merge.    │   │                             │
└──────────────────┘   └─────────────────────────┘   └─────────────────────────────┘
        │
┌───────▼────────────────────────────────────────────────────────────────────────┐
│ L5  EXECUTORS (data plane, ONE adapter contract)                                 │
│  Claude(alpha..theta) · Codex(cx-*) · Antigrav · [Gemini RO · Vibe bounded]      │
│  launch(run)/health(lane)/drain(lane)/ack(msg) · capabilities() flags            │
│  supervised: Restart=always + StartLimit; one_for_one re-spawn with bound task    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 The four load-bearing corrections vs. the prior draft

1. **L2 is a single daemon-owned log at a fixed path OUTSIDE every worktree** — not the 17 git-tracked per-worktree `authority-case-ledger.jsonl` files. Those 17 files merge-conflict by construction and cannot be a coherent SSOT. The reform **removes coordination ledgers from git entirely** (§3.5). This is the single biggest fix the audit forced.

2. **The kernel heap is DERIVED, never authoritative.** On every boot the kernel replays L2 to reconstruct all in-flight leases, capabilities, and case states. No authority survives only in the Lisp image. `save-lisp-and-die` produces a *behavior* image (code), not a *state* image. This kills D2 (stale-image authority resurrection) and means a crash → replay, not a lost-grant.

3. **The enforcement floor (L3) is daemon-independent.** Each hook shim is a stable absolute-path stub that: (a) calls `policy-decide` over the UDS **if the daemon is up**; (b) **if the daemon is down**, evaluates an embedded conservative floor for irreversible-harm classes AND reads the escape-grant file directly from disk. Dead daemon ⇒ *fail-open-with-ledger for reversible ops, fail-closed for release/egress/axiom/merge* — never fail-stuck. This kills NEW-CATCH-2.

4. **The escape grant is a signed file the shim reads directly** — not an RPC to `coord.grant.mint`. The operator (root capability) can always write the grant (a cognition-path write, always allowed); the shim picks it up by file read on the next tool call regardless of daemon liveness.

### 2.3 What stays / subsumed (unchanged dispositions, honest labels)

| Layer | Disposition |
|---|---|
| Vault schema, no-go booleans, S0–S11, axioms, shadow-denial, AVSDLC, consent GateToken, fail-closed-on-infra-for-irreversible | **KEEP, byte-for-semantics** — constitutional floor |
| `hapax-coord` engine | **REBUILD multiplexer → kernel** (net-new CLOS model; the existing 6,680 LoC is the veneer being replaced) |
| 18 bash hooks | **DEMOTE to daemon-independent shims** calling one `policy-decide` (embedded floor fallback) |
| `dispatcher_policy.py` route policy | **LIFT the read/decision** into `policy-decide`; Python remains substrate it calls — never two enforcement sources of truth |
| messages.db MQ | **KEEP as bus** |
| markdown relay inbox | **DEPRECATE** → dual-write read-bridge only |
| 17 git-tracked ledgers + 3 gate versions + 4 deploy trees | **COLLAPSE** to one daemon-owned log + one decision fn + one image |
| Python `hapax-coordinator.service` (inactive) | **RETIRE** |

---

## 3. THE COHERENT API — one model, one surface

### 3.1 The resource model (CLOS classes — net-new, one key threads everything)

One identity — the **cc-task id** — threads `request → authority-case → ledger → dispatch → pr → close`. Canonical names chosen once; every alias becomes a one-shot migration, then parsers accept *only* canonical:

| Resource | Canonical fields | Replaces |
|---|---|---|
| `request` (REQ) | id, prose, artifacts[], refinement_events[], lifecycle_state | — |
| `authority-case` | `authority_case`, `stage` (one `S0..S11` enum, one label form), no-go vector, isap_accepted, risk_tier, avsdlc_axes | `case_id`/`parent_plan`/`impacted_axes`/dual stage forms |
| `cc-task` | task_id, `authority_case`, `parent_spec`, status (one enum), `mutation_scope_refs`, route_metadata | `parent_spec`/`parent_plan`/`spec` fork |
| `dispatch-run` | run_id, **idempotency_key**, task_id, lane, executor, mq_message_id, state | **NEW** durable run object |
| `lane` | name, executor, worktree_slot, mutability, broadcast_group, capabilities, max_restarts | triplicated lane registry |
| `grant-capability` | token (unforgeable), grantor, scope, expiry, ledger_ref, **on_disk_path** | **NEW** — replaces env bypass; written to disk for shim pickup |
| `mq-message` / `pr` | existing schemas, typed | — |

### 3.2 The verb set (exported `coord.*`, one implementation, all transports)

```
coord.request.capture     prose → REQ (+ artifacts, refinement events)            [exists]
coord.case.advance        S-stage transition (guard-checked, ledger-appended)     [BUILD — missing stage-setter]
coord.task.mint           authorized cc-task: ALWAYS stamps stage:S6 + no-go vec  [extend]
coord.task.claim/close    session-keyed lease claim/close                         [exists → cc-claim/cc-close]
coord.dispatch            FUSED bind+launch: mint MQ row + route + spawn, ATOMIC, idempotent  [fuse the split]
coord.pr.merge            admission + release-gate aware                           [add write]
coord.lane.health/start/drain/restart   supervised executor ops                   [BUILD — supervisor]
coord.grant.mint          mint scoped, audited escape capability → ALSO writes signed file to disk  [BUILD]
coord.why-blocked         ordered unmet gates + remediation verb per gate          [BUILD — legibility primitive]
coord.drive               COMPOSITE: prose+intent → REQ+case+task+claim+bind+launch, atomic, one receipt  [BUILD — capstone]
coord.replay --at <T>     temporal audit (projections from event log)              [BUILD]
coord.migrate.*           one-time bootstrap-capability-scoped backfills           [BUILD — §8 C2/C3 fix]
```

**Every verb returns one typed receipt** — the universal API response already prototyped in `control-actions.lisp`:

```lisp
(make-receipt
  :verb "coord.dispatch" :inputs (...)
  :gates-evaluated (list (gate :name "durable-mq" :result :pass :state ...)
                         (gate :name "route-policy" :result :pass :verdict :launch ...))
  :ledger-path "..." :before <task-state> :after <task-state>
  :next-legal-action "..." :command-argv (...) :exit-code 0 :mutation-performed t)
```

### 3.3 How the sprawl is subsumed

- **Scripts** → `coord.*` verbs internally call canonical tools short-term (`uiop:run-program`), but the *operator sees one verb*. **Latency note (audit E):** until the model is native-read (not shelling), `coord.drive` shells ≤6 times sequentially. Target budget: `coord.drive` ≤ 800 ms p50 once the read-model is native (Phase 5 replaces the shell-outs with in-image reads); `policy-decide` ≤ 15 ms p50 (Cedar-class). These are explicit SLOs, not aspirations.
- **Hooks** → one `policy-decide`; 18 hooks become daemon-independent shims.
- **MQ/relay** → `messages.db` is the one bus; markdown inbox deprecated; `coord.lanes.live` is the single "who's alive + what they hold" surface.
- **Registries** → one canonical `lane` registry + the capability registry (with the dimensional route receipt finally surfaced).

### 3.4 How Claude / Codex / Antigrav call it *identically*

All three are **L0 clients of the same `coord.*` API** via the MCP transport (`mcp-tools.lisp`, extended beyond read-only). The kernel speaks only the **Executor adapter contract** (`launch/health/drain/ack` + `capabilities()`) to L5. Runtime asymmetries become *flags on the adapter*, not branches in the API. (§6.)

---

## 4. FORMAL RIGOR + OBLIGATORY ENFORCEMENT (centralization-corrected)

### 4.1 Gating-as-data (policy) — with blast-radius discipline

The three imperative gate versions collapse into **one pure decision function**:

```
policy-decide : (tool-call, claimed-task, case-state, freshness-receipts, lane-lease)
              → Decision { allow | block, gate, reason, required-field,
                           current-value, remediation-verb, fail-mode }
```

This is *net-new logic* (the prior "80% built" claim was false — only the output *type* exists in `control-preflight.lisp`; ~13k lines of branchy bash across three gate versions must be faithfully reimplemented). Built Cedar-shaped: typed entities + schema + deny-by-default, deterministic, layman-legible. No more `sed.*-i` substring matching — classify only the *executed command head* (`CMD_STRIPPED`).

**Migration is shadow-mode AND every future edit re-runs shadow-diff (audit C4).** Centralizing into one `policy-decide` trades drift-risk for blast-radius: a bug is now fleet-wide across local + CI + all runtimes. Mitigations, all mandatory:
- **Shadow week on first cutover** (ship endpoint, run both, diff, then cut over). Reversible.
- **Permanent canary discipline:** every subsequent change to `policy-decide` ships behind a `--shadow` flag that logs both old and new decisions for ≥24h before becoming authoritative. A `policy-decide` version field is stamped on every receipt for bisection.
- **Embedded floor is independently testable:** the daemon-down conservative floor (release/egress/axiom/merge) is a separate ≤150-line function with its own test suite, so a kernel bug cannot weaken the irreversible-harm floor.

### 4.2 The statechart (formal rigor)

S0..S11 becomes an **explicit statechart** (`src/sdlc-statechart.lisp`), one `*sdlc-ladder*` data structure: states + AVSDLC parallel region + S3.5 disconfirmation branch; **guards = preflight predicates**, **actions = no-go flips + ledger append**, each transition carrying its `authority` capability type. This single artifact (a) drives the kernel, (b) renders the UI ladder, (c) is model-checkable. Illegal transitions become *signaled restartable conditions*, not silent blocks — curing the regex-on-`stage:` traps.

### 4.3 Event-sourced SSOT — ONE daemon-owned log, the 17-file problem resolved

**The keystone, rebuilt against the storage reality the audit exposed.**

- **Physical location decided (audit G1):** the canonical event log is a **single daemon-owned append-log at a fixed path outside every worktree** — `/var/lib/hapax/coord/ledger.db` (SQLite, WAL mode) with a JSONL mirror for grepability. It is **removed from git**; the 17 per-worktree `evidence/authority-case-ledger.jsonl` files are migrated then deleted from tracking (`.gitignore` + `git rm --cached`).
- **Offline / multi-writer story (audit C3):** lanes never write the log directly. They emit transition *intents* via the MQ bus (`messages.db`), which the kernel consumes and appends to the single log (single-writer = no merge conflicts). If the kernel is down, intents queue in MQ and replay on restart (durable). For the rare daemon-down enforcement path, the shim appends a *fail-open-with-ledger* line to a **spool file** (`/var/lib/hapax/coord/spool/`) that the kernel ingests on next boot — append-only, single-reader, no git.
- **A typed ledger append is the ONLY way to flip a no-go boolean.** Vault frontmatter and dashboards become **projections** rebuilt by replay. A CI/hook check blocks on projection↔ledger drift.
- **Backfill is migration-capability-scoped (audit C2/C3):** seeding the log from the ~70 existing vault cases and stamping the ~237 active stage-less tasks is a **mass mutation that the current gate would block.** It runs under `coord.migrate.*` carrying a **one-time root bootstrap capability** (operator-minted, scoped to the migration namespace, expiring on completion, fully ledgered). Without this explicit capability the reform cannot run under its own gate — the prior draft never said how, the audit caught it, this fixes it.

### 4.4 Capability-based authority — daemon-independent escape

The constitutional gold pattern is the consent `GateToken` (`gate_token.py`): unforgeable, frozen, nonce-bearing, demanded in persist signatures, with `∀ data: write succeeds → provenance ⊆ active_contracts`. **Generalize it — but reuse the existing linear-token plumbing in `consent_gate.py` rather than reimplementing (audit F):**

- **Dispatch capability** = unforgeable token minted by the kernel *only when policy passes*, handed to the launcher, **consumed once.** Replaces the 10-min-stale `subject==task_id` MQ query; kills confused-deputy ambiguity.
- **Escape capability** = `coord.grant.mint` — the operator writes a grant (always-allowed cognition-path write); **the kernel ALSO serializes it to a signed file at `/var/lib/hapax/coord/grants/<id>.grant`.** The **bash shim reads this file directly** on the next tool call. **Critically (audit NEW-CATCH-2): pickup is a file read, never an RPC.** A dead kernel does not block escape. The grant is reachable in-session (the env-var's fatal flaw was it never reached the in-session hook), authorized (grantor + scope + expiry + signature), recorded (ledger), and scoped (one gate, not a global off-switch). The operator can also write the grant file *by hand* (it is a cognition-path write) if the kernel is down — so escape never depends on the kernel at all. Deprecate `HAPAX_*_OFF` to incident-only with mandatory retro-grant within 1h.

This is the precise mechanism of **"obligatory but never stuck":** no code path mutates/releases without a recorded authorization (obligatory-by-construction), AND the root authority can *always* mint a legal exit — **even with the kernel dead** (escapable-by-authority, daemon-independent).

### 4.5 The never-stuck invariants — checked at runtime, advisory-with-ledger, NOT a self-blocking gate

Model-check the statechart + policy + capability model in TLA+ (`docs/formal/sdlc-ladder.tla`):

- **INV-1 Deadlock-freedom:** from every reachable state, ≥1 enabled transition exists.
- **INV-2 Liveness:** every claimed task eventually reaches a terminal state.
- **INV-3 Escape invariant:** ∀ BLOCK state, ∃ an operator capability that transitions out of it.
- **INV-4 Authority-always-escapable:** no escape hatch depends on the state (or the process) it governs.
- **INV-5 Cognition-always-writable:** a blocked lane can always write `~/.claude/**/memory/`, `~/Documents/Personal/*` (ex governance SSOT dirs), `/dev/shm/*`, `/tmp/hapax-*`.

**Critical correction (audit NEW-CATCH-1):** the TLC proof is **advisory-with-ledger for the reform itself — NEVER a fail-closed release gate.** If TLC times out (parallel AVSDLC + capability state blows up the state space) or finds a model bug, that must not block the cutover that would fix the statechart — that would rebuild the freeze-blocks-thaw catch-22 in the verification layer. Instead:
- TLC runs in CI, posts findings to the ledger, and *informs* the operator. A failing/timing-out proof raises a flagged advisory, not a block.
- The invariants ship as **runtime trace checks** (P-language style) the kernel evaluates continuously against the live ledger. A violated invariant emits a ledgered alert and (for INV-3/4/5) auto-mints the relevant escape — it never freezes the system to "protect" it.
- INV-4 explicitly now covers *process* dependency: the escape must work with the kernel down (verified by a chaos test that kills the daemon and asserts a grant still unblocks a lane).

### 4.6 "Obligatory" enforced-by-construction, not bypass-env

| Property | Mechanism |
|---|---|
| No mutation without recorded authorization | single daemon-owned event-log is the only write path to no-go booleans (§4.3) |
| No dispatch without policy-pass | single-use capability token, minted only on `policy-decide` allow (§4.4) |
| Uniform across runtimes | CI runs the **same** `policy-decide` fn local shims run; web-UI/MCP PRs hit identical gates |
| Escape is an authorized act, not a switch | `coord.grant.mint` signed/scoped/ledgered, **read as a file by the shim** — daemon-independent (§4.4) |
| Floor survives kernel death | embedded conservative floor in shim for release/egress/axiom/merge (§2.2, §4.1) |

---

## 5. THE USABLE FRONTEND — CLOG reform

**"OpenHermes" decode (audit E — flagged as an ASSUMPTION to confirm, OQ-9):** read as the **Hermes Agent dashboard family** (Nous Research — Hermes Studio / Conductor / hermes-web-ui), *not* the LLM. Its usability DNA: *live data never reload · one aggregated view first · topology made visual · declarative direction · decisions surfaced not buried · fail-graceful · audit/proof · one coherent API under everything.* **Confirm this decode with the operator before building §5 to it** — if they meant something else, §5's principles still hold but the visual reference changes.

### 5.1 The reforms (sequenced by felt-impact)

1. **Kill the full-page reload — go reactive (#1 "not usable" fix).** Delete `dashboard.lisp:967-977` `location.reload()`. Hold **derived** dashboard state in the image (audit D2: explicitly ephemeral, rebuilt from ledger on boot — never authoritative); a `bordeaux-threads` supervisor watches sources (inotify + short poll + MQ-db mtime) and **pushes per-panel `(setf (inner-html target) …)` deltas over the live CLOG websocket** — 3–5s status, 30s tables, event-driven control results. Preserves scroll/focus; control-result text survives.

2. **The SDLC ladder is the HERO.** Replace the flat 18-panel grid with a **stage-ladder pipeline** (S0..S11 columns from `*sdlc-ladder*`): each active case a card in its stage column, per-runtime badge, idle/running/done/error color, the **next obligatory step**, the **blocking gate**, and the *one* action (or escape capability) that advances it.

3. **`coord.drive` composer + command palette (`⌘K`).** One prose box → choose lane(s) or "auto-route" → forms AuthorityCase/cc-task and dispatches in one transaction. Type `dispatch <task> to cx-cyan`, enter. Per-task explicit route selectors (lane/platform/mode/profile incl. the Opus path) with **predicted route-policy verdict + MQ-freshness countdown shown *before* commit** (dry-run on render).

4. **Persistent attention rail (Shneiderman overview→drilldown — operator-cited).** Fixed sidebar: pending operator-inbox decisions (badge), blocked tasks, **dead/stale lanes**, failed PRs. **Collapse the 57-row "Planning attention" wall** in `operator-now.md` into *one* "Planning backlog (N requests need a planning case)" overview row + ranked drilldown. Demote 14 read-only panels behind nav tabs.

5. **`why-blocked` everywhere — remediation, not dead-ends.** Every disabled control renders its ordered unmet gates + the *next governed step* ("stage < S6 → accept ISAP", "MQ stale → re-send authority", "held opus → mint a signed opus_model_entitlement receipt"), with one-click remediation where safe.

6. **Evidence-able + reachable (close agent-opacity + mobile gaps).** Add `coord.dashboard.snapshot` JSON + the `mcp-query-tools` read set (`coord.sources.list`, `coord.operator_state.get`, `coord.tasks.summary`, `coord.routing_readiness.get`) so curl/Playwright/agents read state instead of a blank CLOG shell. Add a Playwright smoke (real headless browser, waits for websocket render, screenshots). File the **mobile/Tailscale read-only network-exposure ISAP** (`mobile-readonly-inspection-mode`).

7. **Fail-graceful + audit + parity + research + theme.** Per-panel `handler-case` (one bad source can't blank the cockpit). Chronological `/audit` timeline over the append-only ledger. Build the **Antigrav ACK send wrapper** for equal live-send. Extract hardcoded hex → CSS custom properties wired to `hapax-working-mode`. Add a **vault-research panel** (research store, first-class).

---

## 6. AGENT PARITY — Claude / Codex / Antigrav, first-class interchangeable

The data model already treats all three symmetrically (`worker-pool.lisp` rosters; `sdlc-chat.lisp` targets). The gaps are structural:

| # | Gap | Reform |
|---|---|---|
| P0 | **Antigrav has NO enforcing gate** (IDE Edit/Write bypasses every hook; `no-direct-writes.sh` forces `run_command` heredocs). | Build `antigrav-hook-adapter.sh` (model on `codex-hook-adapter.sh`) wired into `~/.gemini/antigravity/hooks/`, running `policy-decide` (daemon-independent floor included). **And** pivot dispatch to `antigravity-cli` (`~/.gemini/antigravity-cli/`) for a real headless path. |
| P0 | **"Codex headless" is a tmux pane**, not true headless. | Build `hapax-codex-headless` (via `codex exec`) — the genuine analog to `hapax-claude-headless`; repoint `launch_codex_headless`. |
| P0 | **One gate-set SSOT.** Gates live in 4 disconnected places. | `hooks/gate-manifest.yaml` enumerating `(runtime, phase) → ordered gate list + exemptions`; generate all four wirings from it; CI fails on drift. Adding a gate = one-file edit. |
| P0 | **Identity recovery is Claude-only** (`hapax_agent_role_from_path` knows only greek slots; `cx-*`/`antigrav`/`vbe-*` fall to BLOCK on env loss). | Extend recovery to `--cx-*` → that cx, `--antigrav*` → antigrav, `--vbe-*` → that vbe. Remove the `ANTIGRAVITY*`-as-retired bug. **Plus permanent role-less-but-claimable degraded mode (audit B): a session with no recoverable role is never hard-blocked — it can always claim explicitly. "No role" must never mean "no escape."** |
| P1 | **Broadcast excludes 3 of 5** (`*:claude` excludes cx-*; only `*:gemini→iota`). | Add `*:codex`, `*:antigrav`, `*:vibe`, `*:workers` to `relay_mq.expand_recipients`. |
| P1 | **No common CLI contract.** | One Executor adapter: `--lane --task --mode{headless\|interactive\|receipt-only} --prompt --no-claim --force`; quirks = `capabilities()` flags. |

**The unifying move:** the gate-manifest (P0) and the Executor adapter contract become the **CLOG↔runtime interface**. Gemini stays explicitly read-only, Vibe explicitly bounded *in the manifest*. All identity/slot/dispatch/status/capability mechanisms key on the composite `(runtime, lane)`, never on a mutable branch name.

---

## 7. CATCH-22 ELIMINATION TABLE

*Every failure mode mapped to resolution + disposition. Three NEW catch-22s the audit surfaced are added (NEW-1/2/3) with explicit resolutions.*

| Failure mode | Mechanism | Reform resolution | Disp. |
|---|---|---|---|
| FM-1 phantom branch-prefix role | no-env → branch `alpha/` → phantom-alpha + stale claim | explicit `HAPAX_AGENT_ROLE` from spawners; remove inference; **no-env ⇒ role-less but CLAIMABLE (never blocked)** | **ELIMINATE** |
| FM-2 role-keyed claim collision | `cc-active-task-<role>` shared by 2 alphas | session-keyed lease `<role>-<session_id>`, TTL auto-expiry | **FORMALIZE** |
| FM-3 storm-mode count freeze | `open_pr>=8/16` permanent on ~10-PR fleet | single admission policy, threshold = 2× lane count, failure-based; `independent`/p0 always-exempt | **SIMPLIFY** |
| FM-4 admission-governor catch-22 | freeze@10 needs <6 to thaw | `coord.grant.mint` always-available override; exit tied to rate not count | **ELIMINATE** |
| FM-5/10/G2 `ready`/`ready_for_merge` blocked | gate 4 statuses; vault-shape 11 | one canonical status enum consumed by gate + autoqueue + shape | **FORMALIZE** |
| FM-6/G2/G5 multi deploy + drift | **779/651/427 three-way** drift confirmed | ONE save-lisp-and-die behavior image; hooks → **stable abs-path shims**; `hooks-doctor` drift detector interim | **SIMPLIFY** |
| FM-7/G2 opus/sonnet structurally HELD | reasons in no removable set | signed `opus_model_entitlement` + `quality_equivalence` receipt → removable; retire `--policy-rollback` | **ELIMINATE** |
| FM-8 stale capability registry | inline ts frozen; overlay env-dependent | `FR-STALE-CAPABILITY-REGISTRY` (apply receipts → registry); dispatcher passes receipt_dir | **FORMALIZE** |
| FM-9/G6 MQ binding stale + loose match | P0 stale@600s; `subject==task_id` | `coord.dispatch` fuses mint+launch atomically (single-use ocap); strict `mq-message-id` match | **SIMPLIFY** |
| FM-11 dead/retired lanes left dead | watchdog nudges; unit `Restart=no` | lane supervisor: `Restart=always`+StartLimit; one_for_one re-spawn with bound task | **FORMALIZE** |
| FM-12 worktree/branch churn → role instability | role from mutable branch | permanent per-role worktrees on stable branches; identity from `(runtime,lane)` registry | **SIMPLIFY** |
| FM-13 post-merge-deploy `.lua` gap | no case for wireplumber Lua | add `.lua` install case; **OPEN bug, ship Phase 0** | **FORMALIZE** |
| FM-14 multi-deploy poll lag | 3 polled timers, 4 trees | event-driven single-target deploy (merge webhook → one sync) | **SIMPLIFY** |
| FM-15/G4 gates fail-CLOSED on infra | hard-locks instead of advise-with-record | fail-open-WITH-ledger default; fail-closed only release/egress/axiom/merge; per-gate fail-mode in receipt | **FORMALIZE** |
| FM-16 bash mutation false positives | substring `sed.*-i`, `open(` | argument-aware classifier on executed command head | **SIMPLIFY** |
| FM-17/G7 malformed task unrepairable | bootstrap won't overwrite, Edit scope-blocked, no stage-setter | `coord.case.advance` stage-setter; `coord.task.mint` stamps stage+no-go; **migration-capability for bulk backfill** | **FORMALIZE** |
| FM-18 CCTV intake starves queue | ~40 reqs `needs_cctv_hardening` | auto-CCTV-admit on intake (or advisory-with-ledger) | **SIMPLIFY** |
| FM-19 lane-owns-work violated | claim-scoped to A can't touch B | `coord.lane.route-to-owner` first-class verb; foreign-scope completion impossible by design | **FORMALIZE** |
| FM-20 pr-release-gate blocks manual merge | merger's claim must be release_authorized | auto-queue is the merge path (runs as system, unclaimed); manual merge = exception | **SIMPLIFY** |
| G1 no single API, 6-artifact ceremony | no composing verb | `coord.drive` composite verb | **ELIMINATE** |
| G6 disabled controls = dead-ends | terse `disabled_reason` | `coord.why-blocked` remediation map | **FORMALIZE** |
| G7/meta-catch-22 every escape gated | env bypass unreachable in-session | in-session signed grant **read as file by shim, daemon-independent** + INV-4 | **ELIMINATE** |
| G3 two parallel SDLC lanes | `sdlc_*.py` don't read AuthorityCase | issue-automation emits ladder events to the one event-sourced SSOT | **FORMALIZE** |
| vault G2.1 57-row planning wall | 1:1 attention → flat watch rows | aggregate to 1 backlog overview + ranked drilldown | **SIMPLIFY** |
| vault G2.5 broken parent_request | sbcl-clog specs point to `active/` REQ now in `closed/` | repoint to `closed/`, mark fulfilled | **FORMALIZE** |
| vault G2.8 106 MB hygiene log in SSOT dir | unbounded append | rotate/cap, move out of `_dashboard/` | **SIMPLIFY** |
| **NEW-1 TLC proof blocks its own fix** | proof-as-release-gate = freeze-blocks-thaw in formal layer | **TLC advisory-with-ledger ONLY**; invariants ship as runtime trace checks; never fail-closed on the reform itself (§4.5) | **ELIMINATE** |
| **NEW-2 escape needs the daemon that's down** | grant minted via RPC to a wedgeable kernel | grant = **signed file read directly by the bash shim**; operator can hand-write it; dead kernel ⇒ fail-open-with-ledger (§2.2, §4.4) | **ELIMINATE** |
| **NEW-3 cognition carve-out is LIVE-only** | `is_cognition_path()` only in `.cache` gate; rebuild timer clobbers it | **port to repo + regression test in PHASE 0** (the 5-min rebuild timer can clobber tonight) (§8) | **ELIMINATE** |
| **NEW-4 17 git-tracked ledgers merge-conflict** | per-worktree ledger = distributed-log-as-file-append | **single daemon-owned log outside git**; lanes emit intents via MQ; single-writer kernel appends (§4.3) | **ELIMINATE** |
| **NEW-5 stale Lisp image resurrects authority** | heap-as-SSOT after crash | **heap is DERIVED; replay-from-ledger on boot; no authority lives only in image** (§2.2, D2) | **ELIMINATE** |
| **NEW-6 Phase-2/3 backfill blocked by own gate** | mass-mutating 237+ tasks needs claim at S6 | **one-time root migration capability** scoped to migration namespace, ledgered, auto-expiring (§4.3, §8) | **ELIMINATE** |

---

## 8. MIGRATION PATH — sequenced AuthorityCase/ISAP slices

Anchor: **`CASE-SDLC-REFORM-001`** + **`CASE-SBCL-CLOG-COORD-001`** (bounded-V0-controls ISAP authorizes source+runtime mutation). Build on landed clusters 1+5; cluster 6 is the structural unlock.

**Phase 0 — Commit the spec + stop the bleeding + close the active deadlock vectors (blocking, trivial).**
The reform's own design is *not under version control* — create and commit `docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md` (this document) first. Then ship the OPEN/active items NOW:
- **NEW-3 (active deadlock vector): port `is_cognition_path()` from the LIVE `.cache` gate into the repo gate + regression test.** The 5-min `hapax-rebuild-services.timer` can rebuild from repo and silently drop the carve-out tonight — this is not theoretical.
- FM-13 `.lua` deploy case; `hapax-pr-admission normal` to thaw the governor; rotate the 106 MB hygiene log; repoint broken `parent_request` pointers.
*Reuse: `sdlc-quality-speed-request-consolidation-2026-05-17.md`.*

**Phase 1 — Session-keyed identity + permanent role-less-claimable fallback (cluster 6).** *CASE-SDLC-REFORM-001.* (a) all spawners set explicit `HAPAX_AGENT_ROLE` + `HAPAX_SESSION_ID`; (b) re-key claim slot `<role>-<session_id>`; (c) **add a permanent role-less-but-claimable degraded mode (audit B)**; (d) THEN remove branch-prefix inference; (e) generalize identity recovery to cx-*/antigrav/vbe-*. **Sequence is load-bearing — (c) before (d), so "no role" never means "no escape."** Kills FM-1/2/5(role)/G6. *Reuse: `project_no_role_session_gate_deadlock.md`.*

**Phase 2 — `coord.why-blocked` + stage-setter + status unification + migration capability.** *CASE-SBCL-CLOG-COORD-001.* Build `coord.case.advance` (the missing stage-setter — highest-frequency block: only **18/255** active tasks carry a stage); `coord.task.mint` always stamps stage+no-go; one status enum; `coord.why-blocked` structured `GateDecision`. **Mint the one-time root migration capability (NEW-6/C2) and backfill stage+scope across the ~237 active stage-less tasks** (bulk total ~2618 deferred/optional). Kills FM-5/10/17, G6. *Reuse: `reference_cc_task_gate_stage_and_scope.md`, `operator-current-state-cockpit-authority-case-2026-05-13.md`.*

**Phase 3 — `policy-decide` in shadow mode + embedded floor + TLA+ (advisory).** *CASE-FORMAL-GOVERNANCE-001 + CASE-SBCL-CLOG-COORD-001.* Define `*sdlc-ladder*`; lift the **three** gate versions (779/651/427) into one `policy-decide`; build the **separately-tested daemon-independent embedded floor** (release/egress/axiom/merge); run shadow alongside bash a week (the `conductor-pre.sh` UDS pattern is the PoC), diff. Write `sdlc-ladder.tla`, run TLC **advisory-with-ledger (NEW-1) — NOT a release gate**; ship INV-1..5 as runtime trace checks incl. a **chaos test killing the daemon to prove escape still works (INV-4)**. Fix FM-16. *Reuse: `formal-governance-status-predicate-ontology-spec`, `sbcl-clog-operator-state-health-source-contract-2026-05-17.md`.*

**Phase 4 — Single daemon-owned event log + capability tokens + grant model.** *CASE-SDLC-REFORM-001 + CASE-FORMAL-GOVERNANCE-001.* **Stand up the single daemon-owned append-log outside all worktrees (NEW-4/C3); `git rm --cached` the 17 per-worktree ledgers; lanes emit intents via MQ.** Projection↔ledger drift check. Backfill ~70 cases via migration capability. Generalize the consent `GateToken` — **reusing `consent_gate.py` linear-token plumbing (audit F)** — to dispatch + escape capabilities; build `coord.grant.mint` that **also writes the signed grant file the shim reads directly (NEW-2)**; deprecate `HAPAX_*_OFF` to incident-only. Kills FM-15, G7/meta-catch-22, NEW-2/4/5. *Reuse: `shared/governance/{gate_token,consent_gate}.py`, `cross-runtime-communication-*`.*

**Phase 5 — Fused `coord.dispatch` + native read-model + un-degrade routing + dimensional receipt.** *CASE-CAPACITY-ROUTING-001.* Fuse bind+launch (atomic, idempotency key, strict `mq-message-id`) — kills FM-9. **Replace `coord.drive`'s ≤6 sequential `uiop:run-program` shell-outs with in-image reads (the latency SLO of §3.3).** Build `FR-STALE-CAPABILITY-REGISTRY` + signed entitlement/equivalence receipts → retire `--policy-rollback` (FM-7/8). Surface the `dimensional_route_receipt` where the CLOG `routing-readiness` panel reads it. *Reuse: `capacity-routing-dimensional-vector-model-amendment-2026-05-17.md`, `dispatcher-architecture-enforcement-receipts-spec-2026-05-21.md`, `platform-profile-taxonomy-dispatch-eligibility-2026-05-20.md`.*

**Phase 6 — Lane supervisor + Executor adapters + agent parity P0.** *CASE-CROSS-RUNTIME-COMMS-001.* `Restart=always`+StartLimit; one_for_one re-spawn (FM-11). Executor adapter contract + `gate-manifest.yaml`. Build `antigrav-hook-adapter.sh` + `antigravity-cli` headless + `hapax-codex-headless` + Antigrav ACK wrapper. Canonical `lane` registry. Kills the §6 P0 set. *Reuse: `codex-headless-self-control-isap-2026-05-09.md`, `infrastructure-antigrav-implementation-batch-isap-2026-05-14.md`.*

**Phase 7 — Merge-queue redesign + production-deploy-chain rewrite (ITS OWN ISAP, audit C5).** Batching + bisection + flake-quarantine (replace count-based freeze); queue runs as system. **The deploy-chain repointing — live broadcast-critical services (studio-compositor, logos, daimonion) currently deploy from the canonical worktree — is the riskiest infra change in this document; it gets a dedicated ISAP with explicit rollback, not a bullet.** One save-lisp-and-die behavior image; event-driven deploy (merge webhook → one sync of all file-classes incl `.lua`); Swank loopback. Kills FM-3/4/6/14/20, G5. *Reuse: `image-persistence-redaction-policy`, `live-eval-receipt-and-checkpoint-policy`, `project_canonical_worktree_is_deploy_target`.*

**Phase 8 — Frontend reform + request workspace + research feeders + vault-write ownership model.** *REQ-20260518141821.* CLOG reactive push (kill reload, **derived state only**); SDLC-ladder hero; `coord.drive` composer + `⌘K`; attention rail (collapse 57-row wall); `why-blocked` UI; JSON/MCP snapshot + Playwright smoke + mobile ISAP. Build the **request workspace** (artifacts + refinement events + lifecycle timeline). **Specify the vault write-conflict/ownership model (audit E, OQ-10): per-field ownership — coordination fields are daemon-owned (last write from the kernel via ledger projection); life-planning fields (goals, daily notes, people) are operator-owned; the daemon NEVER overwrites operator-owned fields; conflicts on coordination fields resolve by ledger order, conflicts on operator fields always favor the human.** Repair research feeders: sprint subtree path, `goal-map.canvas`, daily velocity:quality observatory. *Reuse: REQ-20260518141821, `velocity-quality-observatory-authority-case-2026-05-14.md`, `vault_context_writer.py` / obsidian-hapax plugin existing write semantics.*

**Bring `hapax-coord` under governance** (parallel, any phase): CI (smoke+lint), axiom scan, gate discipline; branch-audit its stale branches; replace stale `project_emacs_centralization.md` memory; update `AGENTS.md` to cite the V0-ISAP.

**Sequencing rationale:** Phase 0 closes the *active* deadlock vector (NEW-3 cognition carve-out, clobberable tonight) before anything else. Phase 1 (identity + role-less fallback) + Phase 2 (why-blocked/stage-setter + migration capability) kill the stuck mass and unblock the ~237 stage-less active tasks. Phase 3 (one decision fn + embedded floor + advisory proof) is the formal-rigor keystone *without* a self-blocking gate. Phase 4 (single log + daemon-independent escape) is enforced=recorded + never-stuck-even-when-down. Phase 8 (frontend + vault ownership) is the operator's payoff and depends on 2+3+4.

---

## 9. OPEN QUESTIONS / DECISIONS FOR THE OPERATOR

> **✅ ALL 10 APPROVED — operator, 2026-05-30 ("Approve all and yes").**
> OQ-1 SBCL orchestrates / floor + escape daemon-independent ✓ · OQ-2 `hapax-coord` stays a separate repo under CI/axiom-scan ✓ · OQ-3 live-eval activated separately, gated, loopback-only — NOT load-bearing (resilience = replay-from-ledger) ✓ · OQ-4 file the mobile read-only network-exposure ISAP ✓ · OQ-5 operator will sign the Opus entitlement + quality-equivalence receipt to retire `--policy-rollback` ✓ · OQ-6 auto-CCTV-admit-with-ledger ✓ · OQ-7 status-vocabulary canonicalization destructive rename pass approved (parsers then accept ONLY canonical) ✓ · OQ-8 TLA+ advisory-with-ledger + runtime trace checks (never a self-blocking proof gate) ✓ · OQ-9 vault per-field ownership: coordination fields daemon-owned, life-planning fields operator-owned, daemon NEVER overwrites operator fields ✓ · OQ-10 **"OpenHermes" = the Hermes Agent dashboard family (Nous Research), NOT the LLM — confirmed** ✓.
> The reform proceeds. Phase 0 is the first dispatched work.

1. **Engine vs enforcement boundary (D1/D4).** **SBCL orchestrates; the daemon-independent shim layer enforces the irreversible-harm floor.** The body of this revision is rewritten to match — "kernel" replaces "driver everywhere." **Confirm** you do not want full re-implementation of `dispatcher_policy.py` + hooks in CL (two-source-of-truth + blast-radius risk).
2. **`hapax-coord` repo home.** Separate personal GitHub repo today. Recommend: keep separate, bring under CI/axiom-scan. **Confirm.**
3. **Live-eval / image-persistence activation.** These *are* the SBCL thesis but are `forbidden` (`config.lisp:176`) and Swank is unloaded. **Resolved tension (audit D1):** the resilience story is **replay-from-ledger, NOT live-reload** — so the reform does not depend on enabling live-eval. Recommend activating live-eval *separately*, gated, loopback-only, via Swank/TUI (operator-trusted), browser eval stays forbidden. **Confirm appetite** for it as an independent later capability, not a load-bearing dependency.
4. **Mobile network exposure.** Loopback-only today; needs a network-exposure ISAP (bind, privacy filters, shutdown). **Approve filing `mobile-readonly-inspection-mode`?**
5. **`--policy-rollback` retirement = a signed entitlement assertion.** Removing the structural Opus HOLD requires *you* to sign a one-time model-entitlement + quality-equivalence receipt. **Confirm** you'll mint it.
6. **Auto-CCTV-admit vs advisory.** ~40 requests starved on `missing_cctv_intake_receipt`. Recommend auto-admit-with-ledger. **Confirm.**
7. **Status-vocabulary canonicalization** is a one-shot vault migration touching every active note, run under the migration capability. **Approve the destructive rename pass** (`case_id→authority_case`, single stage form, `parent_plan→parent_spec`, axis aliases), after which parsers accept *only* canonical?
8. **TLA+ posture (audit NEW-1).** **Demoted from hard gate to advisory-with-ledger** for the reform itself; invariants ship as runtime trace checks. **Confirm** you accept advisory proof + runtime checks (recommended — a hard proof gate would rebuild the meta-catch-22).
9. **Vault write-ownership model (audit E).** Recommend per-field ownership (coordination fields daemon-owned, life-planning fields operator-owned, daemon never overwrites operator fields). **Confirm**, or specify a different conflict policy.
10. **"OpenHermes" decode (audit E).** Read as the Hermes Agent dashboard family (not the LLM). **Confirm** before building §5's visual reference to it.

---

## 10. RESPONSE TO CRITIQUE — what changed and why

The audit's verdict — *"approve the thesis; send §4.3, §8 phasing, and the SBCL-as-everything framing back for rework against ground truth"* — is accepted in full. I re-verified every load-bearing anchor live this session and reworked the design accordingly. Changes, by audit finding:

**A. Factual anchors (credibility).**
- **A1 (17 ledgers, not 1):** Verified — 17 git-tracked per-worktree copies. **§2.1/§2.2/§4.3 rewritten:** the canonical log is now a **single daemon-owned append-log outside all worktrees, removed from git**, with lanes emitting intents via MQ to a single-writer kernel. The 17 files are migrated then `git rm --cached`. This was, as the audit said, the biggest hole; it is now the explicit center of §4.3.
- **A2 (2618 total / 255 active / 18 with stage, not 227/18):** Verified my own count: 2618 files, 255 non-closed, 18 with a stage. Numbers corrected throughout; the backfill is now explicitly a mass mutation needing a migration capability (NEW-6).
- **A3 (three-way gate drift 779/651/427, lanes oldest):** Verified. Corrected in §1, §7 FM-6; shims are now stable-abs-path stubs so the worktree-fanout problem is addressed, not just the daemon.
- **A4 (0 CLOS classes — net-new, not "promote"):** Verified — `defclass` count is 0. **§1 reframed honestly:** the typed model is the hard net-new 80%; "promotion"/"extend"/"80%-built" language is removed.
- **A5 (`policy-decide` ~10% built, not 80%):** Accepted — only the output *type* exists. §4.1 now says "net-new logic, faithful reimplementation of ~13k lines across three gate versions."
- **A6 (Swank unloaded, live_eval forbidden):** Verified. The resilience story no longer cites live-reload (see D1).

**B. New catch-22s (the core safety rework).**
- **NEW-CATCH-1 (proof-as-gate):** TLA+/TLC **demoted to advisory-with-ledger; never a release gate** (§4.5, §7 NEW-1, OQ-8). Invariants ship as runtime trace checks.
- **NEW-CATCH-2 (escape via dead daemon):** The escape grant is now a **signed file the bash shim reads directly** (and the operator can hand-write); a dead kernel is fail-open-with-ledger, never fail-stuck (§2.2, §4.4, §7 NEW-2). A chaos test (kill the daemon, prove a grant still unblocks) is a Phase-3 acceptance check.
- **NEW-CATCH-3 (cognition carve-out LIVE-only):** Verified `is_cognition_path()` exists only in the `.cache` gate. **Moved its repo-port to PHASE 0** because the rebuild timer can clobber it tonight (§8, §7 NEW-3).
- **Role-less fallback (B):** A **permanent role-less-but-claimable degraded mode** is added as Phase-1 step (c), sequenced *before* removing branch inference, so "no role" never means "no escape" (§6, §7 FM-1, §8).

**C. Feasibility.**
- **C2 (backfill chicken-and-egg) / C3 (17-ledger migration):** Added an explicit **one-time root migration capability** scoped to the migration namespace, ledgered, auto-expiring (§4.3, §7 NEW-6, Phase 2/4).
- **C4 (blast radius):** Acknowledged. Added **permanent shadow-diff discipline for every future `policy-decide` edit** (not just the first), a version-stamped receipt for bisection, and a separately-tested embedded floor (§4.1).
- **C5 (deploy-chain rewrite hidden in a bullet):** Promoted to **its own ISAP with explicit rollback** in Phase 7 (§8).

**D. SBCL risk.**
- **D1 (SPOF):** Reframed "driver" → "**kernel that orchestrates**"; the floor and escape are daemon-independent (§2.2). Resilience is replay-from-ledger, not live-reload (which is forbidden) — the contradiction the audit caught is resolved (OQ-3).
- **D2 (stale-image authority):** **Heap is explicitly DERIVED, never authoritative; replay-from-ledger on boot; no authority lives only in the image** (§2.2, §5.1, §7 NEW-5). §5.1's "hold state in the image" is corrected to "hold *derived* state."
- **D3 (opacity/bus-factor):** Named as an accepted single-operator cost; `why-blocked`/typed receipts mitigate the decision output (§9 OQ-1 context).
- **D4:** The whole document is rewritten to OQ-1's recommendation rather than saying "driver" everywhere.

**E. Completeness.**
- **Vault ownership (under-served):** Added a **per-field ownership model** — coordination fields daemon-owned, life-planning fields operator-owned, daemon never overwrites operator fields (§8 Phase 8, OQ-9). Reuses existing `vault_context_writer.py`/obsidian-hapax semantics rather than competing.
- **Latency ("fast" aspirational):** Added explicit SLOs (`policy-decide` ≤15 ms, `coord.drive` ≤800 ms once native-read) and a Phase-5 task to replace the sequential shell-outs (§3.3, Phase 5).
- **OpenHermes decode:** Flagged as an **assumption to confirm** (§5, OQ-10).

**F. Honesty.**
- Removed "promote/extend/80%-built." Added the missing ledger physical-location decision (the audit's "biggest unanswered design decision"). De-gold-plated: "condition-system resume" is deferred behind the basic model; full event-sourcing is scoped to the single-log reality. Reuse `consent_gate.py` linear-token plumbing rather than reimplementing (§4.4).

**What did NOT change (audit credited as strong, kept intact):** §6 agent-parity analysis and the gate-manifest unification; §5 frontend reforms (kill reload, reactive push, ladder-as-hero, palette); the `why-blocked`/typed-receipt legibility primitive; the GateToken-generalization insight; shadow-mode policy migration; the catch-22 elimination table (extended with NEW-1..6).

**Net effect:** the direction the audit endorsed is preserved; the three centralization catch-22s it found are eliminated by making the floor and escape daemon-independent and the heap derived; the event-sourcing keystone is rebuilt on a single daemon-owned log instead of 17 conflicting git files; the migration is gated by an explicit bootstrap capability so the reform can run under its own rules; and the effort framing is corrected from "promotion" to "net-new kernel build." The design is now drivable against ground truth.

---

*Key anchors for driving sessions:* kernel `/home/hapax/projects/hapax-coord/src/{dashboard,control-actions,control-preflight,request-capture,worker-pool,sdlc-chat,config,mcp-tools,swank}.lisp` (**0 defclass — model is net-new**); gates `/home/hapax/.cache/hapax/rebuild/worktree/hooks/scripts/cc-task-gate.sh` (LIVE 779, **sole holder of `is_cognition_path()`**) vs `/home/hapax/projects/hapax-council/hooks/scripts/cc-task-gate.sh` (651) vs lane worktrees (427); 17 ledgers `/home/hapax/projects/hapax-council--*/evidence/authority-case-ledger.jsonl`; new single log `/var/lib/hapax/coord/ledger.db`; SSOT `~/Documents/Personal/20-projects/hapax-{cc-tasks,requests}/`; floor `shared/{case_migration.py,evidence_ledger.py,dispatcher_policy.py,relay_mq.py,sdlc_lifecycle.py}`, `shared/governance/{consent_gate.py,gate_token.py}`, `axioms/registry.yaml`; integration `agents/{obsidian_sync,vault_context_writer,sprint_tracker}.py`, `logos/data/{vault_goals,orientation}.py`; daemon `hapax-coord.service` (`Restart=on-failure`, `StartLimitBurst=5`, RSS ~150 MB); **spec to create + commit: `docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md`**.