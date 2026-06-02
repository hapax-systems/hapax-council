---
title: Acceptance Oracle — a machine-checkable definition-of-done
status: pilot-shipped (research + kind=build shadow pilot; enforce/liveness deferred)
created: 2026-06-02
authority_case: CASE-SDLC-REFORM-001
parent_request: REQ-20260601-sdlc-next-wave
parent_plan: ~/Documents/Personal/30-areas/hapax/sdlc-next-wave-plan-2026-06-01.md
task: bb-acceptance-oracle-20260601
tags: [sdlc, reform, acceptance-oracle, verifier, definition-of-done, wave-5]
---

# Acceptance Oracle — machine-checkable definition-of-done

> **What ships in this task:** the survey + typed-stack design below, plus a *decoupled `kind=build` shadow pilot* (`scripts/hapax-acceptance-oracle`) that EXECUTES note-authored acceptance tests from a clean tree the lane did not touch and ledgers a verdict — advisory-only, blocking nothing. **What is explicitly deferred** (future tasks, sequenced behind their dependencies): the enforce flip, the decomposer test-mandate schema change, the L2 metamorphic / L3 judge-with-verifier layers, signed acceptance receipts, and the liveness `oracle_distance` wire-in. This document is the parent_spec for those follow-ups.

## 0. Why this exists — the one blind spot every coordination formalism shares

The next-wave architecture (statechart-as-schema + level-triggered reconciliation + queueing dispatch + control-theoretic recovery + event-sourced fold; see [[sdlc-next-wave-plan-2026-06-01]]) makes the **coordination plane** provably sound: every task is in a known stage, every transition is legal, every stuck-by-quietness state gets a watchdog. None of it can see *inside* a state. The reconciler converges *observed stage* → *desired stage*; it never asks **is the WORK inside this state progressing toward acceptance, or spinning?**

"Done" in Hapax bottoms out in `shared/sdlc_lifecycle.py::acceptance_criteria_state()` (verified origin/main, lines 138–154): it regex-counts `- [ ]` vs `- [x]` checkboxes under the `## Acceptance criteria` heading; `complete == not unchecked_items`. `scripts/cc-task-closure-check.py::gate()` blocks closure iff an unchecked box remains (fail-OPEN on read error; bypass `HAPAX_CC_TASK_CLOSURE_GATE_OFF=1`). **The agent that did the work checks its own boxes.** That is machine-checkable only *syntactically* — the gate verifies the box is `[x]`, never that the claim behind the box is true. Three lanes are therefore indistinguishable to every model the system has:

- **Lane A** ran the test suite, it passed, checked the box.
- **Lane B** edited the test file to delete the failing case, re-ran, checked the box. *(EvilGenie's exact reward-hack — arXiv 2511.21654.)*
- **Lane C** re-emits `output.jsonl` every 90s ("still working on it…") while making zero progress toward any acceptance condition. Heartbeat fresh → the progress-watchdog (PR #3852) never fires → slot occupied forever → wave halts until a human looks.

**The research question:** can Hapax have a predicate `oracle(task) ∈ {PASS, FAIL, INDETERMINATE}` computed from *ground truth* (not self-report) such that (a) closure can eventually require PASS, not just `[x]`, and (b) "stuck" can mean "heartbeating but the oracle has not moved toward PASS," not merely "quiet"?

This is **research first, a small build second.** The hard part is heterogeneity: Hapax tasks span `kind ∈ {build, hardening, feature, research_packet, …}` × `mutation_surface ∈ {source, runtime, vault_docs, public, …}`. A code task has an obvious oracle (tests). A 3000-word design doc does not. A research packet's "done" is "the question is answered well," which is *itself* the oracle problem. We must NOT pretend one oracle fits all; we survey, classify by checkability, and pilot only where the oracle is cheap and sharp.

## 1. The generator–verifier gap — why a verifier, not a smarter generator

The governing move (Doctrine #1 of the wave plan): **VERIFIER over candidates, not constraint in the objective.** Verification is empirically far easier and more reliable than constrained generation. Prior art, June 2026:

- **Generator–verifier gap** — across domains, *checking* a candidate answer is dramatically more reliable than *producing* one. This is the load-bearing asymmetry: a cheap independent verifier beats a constrained generator.
- **"One Token to Fool LLM-as-a-Judge"** (arXiv 2507.08794) — naked LLM-judges are trivially gamed by superficial tokens → any judge MUST be paired with a deterministic verifier.
- **EvilGenie / R4P** (arXiv 2511.21654) — agents reward-hack by hardcoding expected outputs or *editing the test files themselves* → the oracle must run tests **the agent cannot mutate**.
- **Metamorphic testing** (Chen et al.) — solves the oracle problem for "non-testable" programs (no reference output) via *metamorphic relations* instead of golden outputs — the route for docs/research classes.
- **"Tool Receipts, Not Zero-Knowledge Proofs"** (NABAOS, arXiv 2603.10060) — HMAC-signed runtime receipts the LLM cannot forge — a near-exact match for Hapax's HMAC `DispatchCapability` + the append-only authority-case ledger fold.

## 2. The three primitives Hapax already has (the seeds to generalize)

Verified against origin/main (HEAD `e30fcb60b`):

1. **`shared/route_metadata_schema.py::VerificationSurface`** (lines 153–162): every dispatchable cc-task carries `deterministic_tests: list[str]`, `static_checks: list[str]`, `runtime_observation: list[str]`, `operator_only: bool`. The schema slot for an executable acceptance predicate **already exists**. But the *derivation* (`_derive_verification_surface`, lines 727–740) only appends the **literal placeholder string `"task-specified-tests"`** when a task is tagged `tests`/`deterministic-ok` — it never produces a runnable command, and `dispatchable` (line 335) never EXECUTES it. **Crucial correction to the original design:** the executable test commands do NOT come from the derivation. They come from **note-authored `verification_surface.deterministic_tests`** blocks that many cc-tasks already carry by hand, e.g. (verified, `closed/capacity-routing-route-metadata-schema.md`):
   ```yaml
   verification_surface:
     deterministic_tests:
       - uv run pytest tests/test_frontmatter_schemas.py tests/shared/test_route_metadata_schema.py -q
     static_checks:
       - uv run ruff check shared/route_metadata_schema.py ...
   ```
   **This is the pilot's wedge, and it needs zero schema change** (see §5, must-fix resolution D/E). Live coverage as of 2026-06-02: **89** of ~2,723 cc-task notes carry a `deterministic_tests` block; **101** active notes are `kind ∈ {build, hardening, feature}`. Coverage is sparse but the sharp entries are real and runnable.
2. **The egress oracle** (`202605181733-anti-audio-visual-p3-implement-oracle`): "metric → calibrated threshold → governance verdict → enforcement," already shipped for ONE task class. This IS a verifier-based oracle in Hapax.
3. **`scripts/hapax-reform-complete`** (merged PR #3833): a mechanical predicate over the LIVE host — "exit 0 = complete, `reasons[]` otherwise," with an `--observations FILE` hook that loads a JSON map and skips live probing so the pure decision logic is deterministically testable. **The acceptance oracle is modeled line-for-line on this** (impure `gather_*` split from pure `decide()`), plus `cc-task-closure-check.py`'s fail-OPEN + single-bypass-env-var contract.

The receipt/event-sourced substrate for the *end-state* (option F): `shared/coord_capabilities.py::DispatchCapability` (HMAC-signed, single-use) and the append-only `~/.cache/hapax/authority-case-ledger.jsonl` fold — **65 live records** as of 2026-06-02 (was 55 at design time), every record keyed `ts` (ISO-8601 string; keys: `authority_case, from_stage, kind, note, role, task_id, to_stage, tool, ts` — **no `timestamp`**), replayed by `shared/policy_decide.py::replay_decision_log`.

## 3. Approach survey — six options assessed against Hapax's heterogeneous task classes

| Option | Oracle = | Reuses | Covers | Breaks on |
|---|---|---|---|---|
| **A. Executable acceptance tests** | run code the agent cannot mutate | egress oracle, `hapax-reform-complete`, note-authored `deterministic_tests` | `build`, `hardening`, `source`/`runtime` w/ tests | docs/design/research (no executable referent) |
| **B. CI-green-as-proxy** | the merge gate already running | `cc-pr-autoqueue.py` all-green admission (#3849) | code tasks (necessary, not sufficient) | "green ≠ acceptance criteria met" — weak proxy; use as a free pre-filter only |
| **C. Property / metamorphic** | relations, for "non-testable" outputs | vault wikilink/parent_request checkers | `vault_docs`, `research_packet` (structural only) | genuine quality judgment |
| **D. LLM-judge WITH a verifier** | judge cites file:line/test-name evidence; verifier mechanically re-checks each citation | LiteLLM gateway, `frontier_required` quality_floor | the quality layer for ALL classes — *only* gated behind A/C | naked judge (no verifier) = self-attestation one level up (2507.08794) |
| **E. Existing checkboxes** | self-attested `[x]` | `acceptance_criteria_state` | declares INTENT | is not DONE — keep as L0 pre-filter, never the authority |
| **F. Proof-carrying receipts** | unforgeable runtime provenance | HMAC `DispatchCapability` + ledger fold (NABAOS) | the end-state for all classes | presupposes option A's runner; key management |

### A in detail (the pilot)
The acceptance predicate is a test/check an **independent process** runs against the produced artifact, in a **clean checkout the lane did not touch**. Anti-reward-hack has two legs: (1) run from a committed tree, not the worktree, and (2) a `static_check` that diffs the test files against the task's base SHA — *if the lane edited the very tests it was supposed to satisfy, FAIL* (directly answers EvilGenie). Cheapest, sharpest oracle, and the only one piloted first.

### D in detail (the quality layer, deferred)
A naked judge ("score this 1-10, is it done?") is what we must NOT ship. The defensible form: the judge must (1) cite *specific evidence* (file:line, a test name, a quoted passage) per acceptance criterion, and (2) every citation is *mechanically re-checked* — the quoted line must exist, the named test must have run and passed, the cited section must contain the claim. The judge proposes; the verifier disposes. Generator–verifier gap applied recursively. **Out of the pilot — research-only until the deterministic layers prove out.**

### Synthesis — the typed L0–L3 + receipt stack (per-class routing)
Not one approach — a typed stack; each task class is routed to the strongest oracle it admits:

```
done(task) :=
  L0  acceptance_criteria_state.complete          # syntactic INTENT (existing, kept as pre-filter)
  AND L1  deterministic acceptance tests PASS       # option A — classes that admit it
          (run from a committed tree; test-file-tamper static check)   # anti-reward-hack
  AND L2  metamorphic / structural properties hold  # option C — docs/research (FUTURE)
  AND L3  (if quality_floor=frontier_required)      # option D — judge-WITH-verifier (FUTURE)
          verifier-checked LLM-judge PASS
  → emit a signed acceptance_receipt to the ledger  # option F — the audit fold (FUTURE)
```

Per-class **REQUIRED** levels (what makes the predicate total without over-reaching):

| Task class | Required | Rationale |
|---|---|---|
| `build` / `hardening` × `source`/`runtime` | **L0 ∧ L1** | tests are the cheap sharp oracle — **the pilot scope** |
| `feature` × `source` | L0 ∧ L1 (if tests declared) else L0 | many features carry tests; fall back to L0 when none |
| `vault_docs`, `research_packet` | L0 ∧ L2 (∧ L3 if frontier) | no executable referent — metamorphic + judge (FUTURE) |
| `public` | L0 ∧ (class-specific) ∧ operator | publication stays operator-gated |

`INDETERMINATE` at any required level is **NOT** FAIL → it routes to escalation/refine, never to a silent self-block (NEVER-FREEZE, Doctrine #6).

## 4. The pilot — "executed acceptance predicate for `kind=build`" (shipped here, in shadow)

**Hypothesis:** for code/build tasks, EXECUTING the note-authored `verification_surface.deterministic_tests` from a clean tree (+ the tamper check) catches reward-hacked / incomplete closures the checkbox gate misses, at near-zero added cost, with **zero false self-blocks**.

**Scope (hard):** `kind ∈ {build, hardening}` **AND** `mutation_surface ∈ {source, runtime}`. Everything else is untouched and keeps today's checkbox gate.

**Artifact:** `scripts/hapax-acceptance-oracle` — modeled on `hapax-reform-complete` + `cc-task-closure-check.py`.

- **Contract:** exit `0 = PASS`, `2 = FAIL` (+ `reasons[]`), `3 = INDETERMINATE` (fail-OPEN-with-ledger). **NEVER fails-stuck.** Bypass: `HAPAX_ACCEPTANCE_ORACLE_OFF=1` → immediate INDETERMINATE + ledger note.
- **What it does** (`gather` → `decide` → ledger):
  1. Parse the cc-task note frontmatter → `kind`, `mutation_surface`, `verification_surface.deterministic_tests`, `branch`, `pr`, `authorizes_test_changes` (default `false`), and `acceptance_criteria_state.complete`.
  2. **Scope filter** — out-of-scope class → `INDETERMINATE("out-of-scope-class")`, never FAIL.
  3. **Load gate** — `os.getloadavg()[0]` over a conservative core-relative ceiling (`HAPAX_ACCEPTANCE_ORACLE_LOAD_CEIL`, default `1.5×ncpu`) → `INDETERMINATE("deferred-high-load")`. Don't add a test-suite run to an already-saturated box (Doctrine #7). Works WITHOUT PR #3850's slice; when the slice lands, `admission_state()` supersedes this (see §6).
  4. **Clean-tree resolve** (must-fix A, below) — resolve a committed SHA from the note (`pr` head, or `git rev-parse origin/<branch>`); `git worktree add --detach <tmp> <SHA>`; run there; remove in a `finally`. **No committed SHA → `INDETERMINATE("no-clean-tree")`** — the oracle is a *post-commit verifier*, never blocks pre-commit work.
  5. **No declared tests** for an in-scope task → `INDETERMINATE("no-declared-tests")` — this is the coverage-gap signal, never FAIL.
  6. **Tamper static check** — `git diff <base>..<SHA> -- <test-paths>` must be empty unless `authorizes_test_changes: true`; else `FAIL("test-file-tamper")`. `<test-paths>` are the `tests/…` path args extracted from the declared commands; `<base> = git merge-base <SHA> origin/main`.
  7. **Run** each declared command in the clean tree (bounded timeout). Any non-zero → `FAIL("test-failed:<cmd>")`. All zero → `PASS`.
  8. **Ledger** one JSONL record per run to `~/.cache/hapax/acceptance-oracle-findings.jsonl` with an **ISO-string `ts`** (NOT a `time.time()` float — the design's own do-now warning applied to itself), the verdict, `reasons`, `checkbox_complete`, and the headline **`divergence`** field (`oracle-fail-checkbox-pass` = a false closure the checkbox gate would have passed).
- **`--observations FILE`** — loads a JSON observation map, skips all live probing, exercises pure `decide()` + the exit-code contract deterministically (mirrors `hapax-reform-complete`; the test suite uses only this — no real subprocess/worktree in CI).
- **`--sweep [--limit N]`** — the decoupled shadow experiment: iterate the most recent closed `kind=build|hardening` notes, run the oracle against each, ledger every verdict, and print the **false-closure-catch rate** (oracle-FAIL on a checkbox-PASS task). **Touches no live gate** — runs on demand, safe today.

**Live shadow hook** (`scripts/cc-task-closure-check.py`): a behavior-preserving, **default-OFF**, env-gated (`HAPAX_ACCEPTANCE_ORACLE_SHADOW=1`), load-gated, *backgrounded* advisory observation. With the env unset, `gate()` is byte-identical to today; when set, it merely spawns the oracle detached (writes to the findings ledger) and **never affects the gate's return**. This is the live arm of Phase P0 in true shadow — present but inert by default, so it is safe to ship before #3850.

**Pilot acceptance (succeeds iff):**
- ≥1 real merged-but-not-actually-done `kind=build` closure is caught in shadow that the checkbox gate passed (existence proof the gap is real); **OR** a clean zero-catch run across N waves (the gap is empirically smaller than feared — *also a publishable negative result*).
- Zero false self-blocks even when later promoted to enforcing (INDETERMINATE never blocks; only a concrete reproducible FAIL blocks).
- Added wall-cost per run ≤ the declared suite's own runtime + one clean checkout (both bounded).

## 5. Reviewer must-fixes — resolved

- **A — CLEAN-CHECKOUT FEASIBILITY (was load-bearing & unresolved).** Resolved by making the oracle a **post-commit verifier**: the clean tree is an ephemeral `git worktree add --detach <tmp> <SHA>` where `<SHA>` is resolved from the note's `pr` head (`gh pr view --json headRefOid`) or `git rev-parse origin/<branch>`. If no committed SHA is resolvable at run time (a pre-PR closure), the oracle returns **INDETERMINATE("no-clean-tree")**, never FAIL — so the anti-tamper premise is execution-ready *exactly when it is meaningful* (you can only diff tests against a base once a commit exists), and the pre-commit path is unaffected. The original design's "run at closure-check time against whatever tree" is replaced by "run against the committed SHA, or abstain."
- **B — FILES_TOUCHED MISATTRIBUTION.** `scripts/hapax-lane-supervisor` is **bash** (respawns DEAD lanes by PID-absence via `kill -0`; it cannot `os.kill` a live-but-looping lane). The `oracle_distance` leg and the `os.kill`-exact-PID recovery belong to the **separate Python `reform-lane-progress-watchdog` (PR #3852)** — *that* is the wire-in host. This document names PR #3852's watchdog (not the bash supervisor) as the `oracle_distance` host, and the entire liveness wire-in is **DEFERRED** (out of this task's scope) and sequenced behind #3852 + the reconciler.
- **C — GROUNDING NUMBERS pinned.** A single live measurement, taken 2026-06-02: the authority-case ledger has **65 records** (was 55 at design time), **all** keyed `ts` (no `timestamp`). The `sdlc_invariants.py` `ts`/`timestamp` read bug is real and is the **do-now's** to fix and to count — this spec does not re-assert a contested false-finding integer (the prior 53/55/83/87 spread is dropped).
- **D — DECOMPOSER SCHEMA SURFACE: descoped, not understated.** The pilot reads **note-authored** `verification_surface.deterministic_tests` (which already exist and are runnable), so it adds **no** field to `agents/request_decomposer/models.py::TaskSpec` and **no** decomposer rule. The "softly mandate ≥1 deterministic_tests for kind=build" rule — which *would* add a new `TaskSpec` field + writer change + route-metadata plumbing — is a **separate future phase**, filed in the follow-up note. Measure coverage first (89 notes today); only then decide whether to mandate.
- **E — "NO SCHEMA MIGRATION" corrected by descoping.** Because D is descoped, Phase P0 *is* genuinely pure-addition: a new script + tests + a default-OFF advisory hook. No `VerificationSurface` migration (it already exists), no `TaskSpec` field, no decomposer change. The "small additive pilot" framing is now accurate.

## 6. Migration, rollback, constraint compliance

**Migration (additive, reversible, gate-compatible):** Phase R = this doc (`vault_docs`, no runtime risk). Phase P0 (shipped) = the runner + `--sweep` + the default-OFF shadow hook, advisory-only. Phase P1 (FUTURE) = flip one env/config flag so FAIL blocks closure for `kind=build|hardening` only (mirrors the `policy_decide` shadow→enforce discipline). Phase D (FUTURE) = the decomposer test-mandate (the schema change). Phase L (FUTURE) = the `oracle_distance` leg into PR #3852's watchdog, gated behind the liveness substrate + #3850's `sdlc.slice`. Later: L2 metamorphic, L3 judge-with-verifier, signed receipts. An optional `systemd/units/hapax-acceptance-oracle.{service,timer}` regression sweep is FUTURE and gated on #3850's slice (no always-on loop ships here).

**Rollback (NEVER-FREEZE at every layer):** shadow phase → delete the findings file / unset the env (zero blast radius). Enforce phase → fail-OPEN-with-ledger on any infra error (exit 3 → closure proceeds + a ledger record), so a broken oracle can NEVER brick closures; `HAPAX_ACCEPTANCE_ORACLE_OFF=1` disables it instantly. The oracle is advisory-with-escape *by construction* — it can never become a sink with no escape edge.

**Constraint self-audit:** **NEVER-FREEZE** ✓ (advisory-with-ledger → enforce-with-fail-OPEN; INDETERMINATE routes to escalation; single ledgered bypass). **NO-STALL/NO-MANUAL** ✓ (a FAIL routes to bounded re-dispatch via the watchdog's existing max-attempts→ntfy, never an infinite loop or a required human step). **LIVESTREAM-SAFE** ✓-with-caveat (the runner only executes on explicit invocation / `--sweep`; the live hook is default-OFF + load-gated + backgrounded; no always-on loop ships before #3850's slice — when the slice lands, `admission_state()` supersedes the loadavg gate). **BOUNDED RECOVERY** ✓ (the oracle only *reads* and *reports*; recovery is delegated to PR #3852's `os.kill`-exact-PID watchdog, never `killpg`). **GATE-COMPATIBLE** ✓ (bootstraps via the sanctioned `REQ-*.md` + cc-task notes; flows through the cc-task lifecycle). **SUBAGENT-GIT-SAFETY** ✓ (a single new script + a default-OFF hook; all code in the main session; subagents read-only survey only). **SECRETS** ✓ (`~/` throughout; future receipts sign with the oracle process key via existing HMAC, never egress).

## 7. Open questions (carried to the follow-up)

- `research_packet` whose acceptance IS answering an open question — does `oracle_distance` even have a monotone definition there, or is the research class permanently INDETERMINATE (checkbox-only) until L3 exists?
- Tamper check: hard FAIL vs scope-authorized? The pilot ships the `authorizes_test_changes` note field (default `false`); a task whose explicit job is to fix/add tests sets it `true`.
- Receipt end-state (F): its own signing key vs reuse the `DispatchCapability` key — cleaner provenance vs one more key to manage.
- Calibration of the liveness leg: how many consecutive K ticks of unchanged `oracle_distance` before a fresh-but-looping lane is declared stuck — measured against the dispatch service-time distribution (FUTURE, with PR #3852).
- Does mandating `deterministic_tests` for `kind=build` shift the decomposer's output distribution enough to slow intake? Measure coverage (89 notes today) before mandating.
