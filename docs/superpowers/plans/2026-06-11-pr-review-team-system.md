# PR Review Team System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every PR gets a strategically-constituted, tactically-sized, cross-model-family review team; a quorum-accept dossier becomes a hard admission requirement in cc-pr-autoqueue.

**Architecture:** Three pieces. (1) A versioned lens registry (`config/review-lenses/registry.yaml`) + per-lens charter checklists (`config/review-lenses/<lens>.md`) encode "all the right things" per surface, sizing per risk class, and the model-family roster. (2) A pure-logic module `scripts/review_team.py` does lens selection, team classification/constitution (cross-family rules), dossier synthesis (quorum math), and gate blockers; `scripts/cc-pr-autoqueue.py` imports it and adds review-dossier blockers in `_task_blockers`. (3) A dispatcher CLI `scripts/cc-pr-review-dispatch.py` fetches a PR, constitutes the team, dispatches blind reviewers in parallel through all configured roster-family commands via a stub-able runner, parses structured verdicts, writes the dossier beside the task note, posts the PR comment, emits the acceptance receipt on quorum-accept for review-floor tasks, and auto-wakes the authoring lane on BLOCK/critical.

**Tech Stack:** Python 3 + PyYAML (repo conventions), `gh` CLI, subprocess + ThreadPoolExecutor, pytest with importlib loading of hyphenated scripts.

**Authority:** CASE-ROUTING-OPERATIONALIZATION-20260609; parent spec `~/Documents/Personal/30-areas/hapax/pr-review-team-design-2026-06-11.md`. Mutation scope: `scripts/`, `config/review-lenses/`, `scripts/cc-pr-autoqueue.py` (+ tests as evidence). Systemd timer for the dispatcher is deliberately deferred (systemd/ is outside this task's mutation scope) — `--all --apply` mode is timer-ready; follow-up task wires the unit.

---

## Design decisions locked here

1. **Dossier location/keying** — same pattern as acceptance receipts: `<task_id>.review-dossier.yaml` beside the task note. Keyed to `head_sha`; a push/synchronize invalidates the old dossier (gate emits `review_dossier_stale_head:*`).
2. **Gate placement** — `_task_blockers()` in cc-pr-autoqueue.py, right after `acceptance_receipt_blockers()`, with `pr_head_sha`, PR number, changed-file paths, and `changedFiles` count threaded from `classify_pr`. Reason codes name the truth (sdlc-legibility): `missing_review_dossier`, `review_dossier_changed_files_unknown`, `review_dossier_changed_files_count_unknown`, `review_dossier_changed_files_truncated:<seen>/<total>`, `review_dossier_task_id_mismatch:*`, `review_dossier_pr_mismatch:*`, `review_dossier_malformed:*`, `review_dossier_stale_head:<sha8>`, `review_dossier_team_class_scope_mismatch:<recorded>!=<expected>`, `review_dossier_missing_required_lenses:<lenses>`, `review_dossier_quorum_not_met:<accepts>/<required>`, `review_dossier_unresolved_critical:<count>`, `review_dossier_family_diversity:<detail>`, `review_team_verdict_not_quorum_accept:<verdict>`.
3. **Gate recomputes, never trusts** — the gate re-derives expected team class and mandatory lenses from the PR changed-file list, and re-derives accepts/criticals/family-diversity from the dossier's reviewer entries. The dossier `task_id` and `pr` must match the current linked task and PR; every reviewer family/verdict must be in the configured roster/enums. The `review_team_verdict` field must ALSO say `quorum-accept` (fail-closed both ways, anti-theater). Missing, empty, or truncated changed-file scope blocks admission rather than downgrading to T2/always-on.
4. **Rollout killswitch** — `HAPAX_REVIEW_TEAM_GATE_OFF=1|true|yes|on` disables only the new blockers (the whole-autoqueue killswitches stay as-is). Default ON per ratified directive "No quorum, no merge"; values such as `false` do not disable the gate. Dispatcher has `HAPAX_REVIEW_TEAM_DISPATCH_OFF=1|true|yes|on`.
5. **Dossier IS the acceptance receipt** — on quorum-accept for a `frontier_review_required` task, the dispatcher writes `<task_id>.acceptance.yaml` (acceptor `review-team:<families>`, artifact = dossier path + PR URL, plus PR/head SHA/verdict/reviewer snapshot) unless a receipt already exists. The original receipt path does not require shared lifecycle changes; the later GLMCP auto-arm carve-out is tracked separately in `shared/sdlc_lifecycle.py`.
6. **Blindness** — each reviewer gets PR meta + diff + charter texts + output contract; never another reviewer's verdict. Prior-sha unresolved criticals for the same PR ARE included with bounded current-file excerpts around the prior file:line claims (resolution verification, not peeking). When one PR links multiple task notes, the prompt includes all linked notes and the dispatcher writes one task-bound dossier per note from the same review round.
7. **Classification is replayable at admission** — the dispatcher records `team_class`, `quorum_required`, and lenses in the dossier, but the gate recomputes the expected class and lens floor from the PR changed-file list before trusting the dossier.
8. **Reviewer invocation** — family roster in the registry holds argv templates (prompt on stdin): claude `claude -p`, codex `codex exec --sandbox read-only -`, gemini `gemini --skip-trust --approval-mode plan -p "Perform the review request provided on stdin; reply with exactly one fenced yaml code block and no prose."`, and glm `scripts/hapax-glmcp-reviewer`. The GLM review adapter is a direct OpenAI-compatible Coding Plan caller that reads the prompt from stdin and is configured with `HAPAX_GLMCP_REVIEW_*` environment variables, separate from the Claude Code launcher `HAPAX_GLMCP_*` variables. Dispatcher abstracts this behind a `runner` callable so tests stub it. Recheck with `scripts/hapax-glmcp-reviewer --check` and `uv run pytest tests/scripts/test_hapax_glmcp_reviewer.py -q`.
9. **Invalid reviewer output fails closed** — unparseable verdict YAML records `verdict: invalid-output` (never counts toward quorum). Provider availability failures are explicit `quota-wall` or `provider-outage` reviewer verdicts so constitutions can degrade with receipts instead of sealing. Parsing must not make T1 quorum unreachable, and must not make quorum wrongly reachable. The output contract asks for exactly one fenced YAML block; multiple, malformed, or surrounded fences fail closed. The parser also accepts a whole-reply raw YAML document only when the reply is fence-free, uses exactly the contract keys, and has valid `findings`/`checklist` shapes. Recheck with `uv run pytest tests/test_cc_pr_review_dispatch.py::TestApply tests/test_cc_pr_review_dispatch.py::TestFamilyOutageDegradation tests/test_review_team.py::TestSynthesizeDossier tests/test_review_team.py::TestFamilyOutageDegradation tests/test_review_team.py::TestLensRegistry::test_families_roster_covers_four_model_families -q`.
10. **Writer family never holds the majority alone** — derived from the task's lane (`assigned_to`) via the registry `lane_families` map; constitution caps writer-family seats at `ceil(n/2)-1` for T2+, and T1 requires all roster families unless a fresh family-outage witness degrades the constitution with `post_recovery_rereview_required`.

## File structure

- Create: `config/review-lenses/registry.yaml` — surfaces→lenses, sizing, families, lane map (registry_schema: 1)
- Create: `config/review-lenses/<lens>.md` × 21 — versioned charter checklists
- Create: `scripts/review_team.py` — pure logic: registry, selection, constitution, synthesis, gate blockers
- Create: `scripts/cc-pr-review-dispatch.py` — dispatcher CLI (gh fetch, prompts, parallel dispatch, dossier/comment/receipt/auto-wake)
- Modify: `scripts/cc-pr-autoqueue.py` — import review_team; `_task_blockers(..., pr_head_sha, changed_files)`; changed-file scope fail-closed; killswitch
- Create: `tests/test_review_team.py`, `tests/test_cc_pr_review_dispatch.py`
- Modify: `tests/test_cc_pr_autoqueue.py` — admission blocks without quorum / admits with quorum dossier

## The 21 lenses (charter inventory — items are the content)

Always-on (every PR): **tests-cover-the-diff** (each changed behavior has a test exercising it; tests fail before fix; no coverage theater), **exit-predicate-adequacy** (task exit predicate is testable, evidenced, matches the diff actually shipped), **doc-claims-recheck** (every doc/runbook claim added carries a recheck command; claims match code).
Daimonion: **correctness** (logic, ABI/version windows, None/empty paths, state-machine honesty, off-by-one in ring/window code), **live-runtime-composition** (composes with LIVE daemons: restart ordering, socket/SHM contracts, event-loop blocking, backpressure), **voice-doctrine** (never-cut-music, witness discipline, destination gates, abstention vs drop classes).
Governance: **axiom-compliance** (single_user/executive_function/corporate_boundary/interpersonal_transparency/management_governance weights respected), **formal-soundness** (algebra laws hold: idempotence, monotone gates, no lossy round-trips), **consent-provenance** (consent gate fail-closed, provenance/attribution preserved, no new persistent state on non-operator).
Audio: **audio-protected-invariants** (golden chain intact; MPC/L-12 never bypassed; no unauthorized livestream-tap targeting; pipewire.conf.d untouched without approval), **audio-routing-witness** (scripts/hapax-audio-routing-check run before/after; revert-on-failure evidenced), **audio-levels-doctrine** (levels via MIDI not node volumes; LUFS/ducking governance respected).
Systemd/deploy: **wire-contract** (the 6 wire predicates; units in systemd/units/ only; WantedBy/BindsTo sane), **deploy-drift** (deployed-vs-repo reconciliation; pre-staging of models/data before activation), **canonical-root** (release-root pinning, no live-PID deletion paths, ghost-release detection).
SDLC: **sdlc-legibility** (reason codes name the true failure; no euphemistic blockers; logs say what actually happened), **sdlc-gate-compose** (admission/queue/receipt gates compose without deadlock; fail-closed defaults; killswitch documented).
Tests-only: **test-validity** (test actually tests the claim; assertions would fail on regression), **anti-theater** (no fixture-greens, no mocking the thing under test, no tautological asserts).
Trust boundaries: **security** (input validation at boundary, no secret leakage, least privilege, injection surfaces), **silent-failure-hunting** (no swallowed exceptions, fallback-on-dependency-down is loud, error paths reach logs/ntfy).

---

### Task 1: Lens registry + registry validation test

**Files:**
- Create: `config/review-lenses/registry.yaml`
- Test: `tests/test_review_team.py` (registry section)

- [ ] **Step 1: Write failing registry tests** — registry parses; has `registry_schema: 1`;
  every `surface_lenses[].lenses` and `always_on_lenses` entry has a charter file;
  sizing has the 3 classes with spec quorums (t3: 2/2, t2: 2/3, t1: quorum 3 with
  all roster families unless outage-degraded); families roster covers all configured
  model families.
- [ ] **Step 2: Run, verify fails** (`uv run pytest tests/test_review_team.py -x -q` → file-not-found).
- [ ] **Step 3: Write registry.yaml** with: `always_on_lenses`, `surface_lenses`
  rows mirroring spec §1 globs (`agents/hapax_daimonion/**`;
  `shared/governance/**`+`axioms/**`; `config/pipewire/**`+`config/audio-*`+
  `scripts/*audio*`; `systemd/**`+`scripts/*deploy*`; `scripts/cc-*`+
  `shared/sdlc_lifecycle.py`+`shared/release_gate.py`; tests-only special row;
  `*mcp*`+`*oauth*`+`*egress*`+`*publish*` trust row), `sizing` (t3_docs 2/2;
  t2_standard 3, quorum 2, block_on_named_critical; t1_critical 4-5, quorum 3,
  require_all_families, criticals_must_resolve), `families` (argv templates per
  design decision 8, timeout 1200), `lane_families` (greek→claude, `cx-*`→codex,
  iota/kappa/lambda/mu→gemini, `cx-glmcp`/`codex-glmcp`/`glmcp` and `glm-*`→glm,
  `vbe-*`→vibe non-reviewing).
- [ ] **Step 4: Tests pass.**  - [ ] **Step 5: Commit** `feat(review-team): lens registry — surfaces, sizing, families`.

### Task 2: 21 lens charters

**Files:** Create `config/review-lenses/<lens>.md` × 21 per inventory above.

- [ ] **Step 1: Failing test** — every lens in registry has charter; frontmatter `{lens_id, version: 1, title}`; ≥3 `- [ ]`-style checklist items; lens_id matches filename.
- [ ] **Step 2: Write all 21 charters** (format: frontmatter + `## Checklist` items + `## Verdict contract` line "address every item pass/finding/NA"). Items per the inventory parenthetical lists above, expanded to one line each; §4 seed items distributed: ABI windows→correctness, composition-with-live-daemons + event-loop blocking→live-runtime-composition, fallback-on-dependency-down→silent-failure-hunting, doctrine clauses→voice-doctrine, state-machine honesty→correctness, pre-staging→deploy-drift.
- [ ] **Step 3: Tests pass. Commit** `feat(review-team): 21 lens charters`.

### Task 3: review_team.py — selection + classification + constitution

**Files:** Create `scripts/review_team.py`; Test `tests/test_review_team.py`.

- [ ] **Step 1: Failing tests:** `lenses_for_files` (daimonion file → its 3 lenses + always-on; tests-only diff → test-validity+anti-theater; mixed never tests-only); `team_class_for` (risk_tier T3/docs-only → t3_docs; T1 or governance-glob hit → t1_critical; default t2_standard); `constitute_team` (t2 → 3 seats ≥2 families, writer family ≤1 seat; t1 → 4-5 seats across all roster families unless outage-degraded; t3 → 2 seats, ≥2 families when available; unavailable family → deterministic fallback + recorded `constitution_notes`).
- [ ] **Step 2-4: TDD until green.** Pure functions over the parsed registry; no I/O beyond `load_lens_registry(path)`. Deterministic (no randomness — seat order = registry family order rotated by `pr_number % len(families)`).
- [ ] **Step 5: Commit** `feat(review-team): team constitution engine`.

### Task 4: review_team.py — synthesis + gate blockers

- [ ] **Step 1: Failing tests:** `synthesize_dossier` (2/3 accepts → quorum-accept; any unresolved critical → blocked + escalations entry; cross-family split on a finding → escalation at top; t1 without per-family accept → no-quorum; invalid-output never accepts); `review_team_verdict_blockers` (missing file; malformed; stale head_sha; verdict field not quorum-accept; recomputed accepts < quorum_required; unresolved criticals; t1 family diversity; killswitch env → ()).
- [ ] **Step 2-4: TDD until green.** Dossier schema (dossier_schema: 1, task_id, pr, head_sha, team_class, quorum_required, lenses, reviewers[{id, family, verdict, findings[{severity,lens,file,line,title,detail,resolved}], checklist}], escalations, review_team_verdict, constituted_at). Verdict values: `accept`, `accept-with-findings`, `block`, `invalid-output`, `quota-wall`, `provider-outage`.
- [ ] **Step 5: Commit** `feat(review-team): dossier synthesis + admission blockers`.

### Task 5: Gate wiring in cc-pr-autoqueue.py

**Files:** Modify `scripts/cc-pr-autoqueue.py` (import + `_task_blockers` + `classify_pr` head_sha and changed-file threading); Modify `tests/test_cc_pr_autoqueue.py`.

- [ ] **Step 1: Failing tests:** matched ready task + green PR + NO dossier → action blocked with `missing_review_dossier`; with quorum-accept dossier at matching head_sha and matching changed-file scope → queue; stale sha → blocked; missing/empty changed-file scope → blocked with `review_dossier_changed_files_unknown`; truncated changed-file scope → blocked with `review_dossier_changed_files_truncated:<seen>/<total>`; surface-required class/lens mismatch → blocked; task/PR mismatch → blocked; invalid reviewer family/verdict → blocked; `HAPAX_REVIEW_TEAM_GATE_OFF=1` → queue; `HAPAX_REVIEW_TEAM_GATE_OFF=false` does not bypass.
- [ ] **Step 2-4: Wire + green.** `sys.path` gains scripts dir (mirror REPO_ROOT pattern); `import review_team`; fetch `files` and `changedFiles` from `gh pr list`; `_task_blockers(..., pr_head_sha=pr.head_sha, pr_number=pr.number, changed_files=pr.files, changed_file_count=pr.changed_files_count)` extends with `review_team.review_team_verdict_blockers(...)` after acceptance receipt line.
- [ ] **Step 5: Run FULL existing autoqueue test file** (regressions: every pre-existing test now needs either the killswitch fixture or a dossier — prefer an autouse monkeypatch fixture setting the killswitch in legacy tests, with the new tests explicitly clearing it; keeps 100+ assertions honest without rewriting them).
- [ ] **Step 6: Commit** `feat(autoqueue): review-team quorum admission gate`.

### Task 6: Dispatcher CLI — fetch, prompts, parallel dispatch, parse

**Files:** Create `scripts/cc-pr-review-dispatch.py`; Test `tests/test_cc_pr_review_dispatch.py`.

- [ ] **Step 1: Failing tests** (stub `gh` runner + stub reviewer runner): `--pr N` dry-run prints constitution (class, lenses, seats); `--apply` calls reviewer runner once per seat with blind prompts (assert: no prompt contains another reviewer's verdict; charters + diff + output contract present); YAML fence extraction parses verdict; garbage output → `invalid-output`; oversized diffs are truncated into bounded per-file excerpts with a truncation notice.
- [ ] **Step 2-4: TDD.** `gh pr view --json number,title,body,headRefName,headRefOid,isDraft,files` + `gh pr diff`; task-note lookup via `review_team.find_task_notes(vault_root, pr_number, head_ref)`; ThreadPoolExecutor dispatch with per-family timeout; prompt = header + task/PR meta + prior unresolved criticals (same PR) + charter texts + diff + output contract (yaml fence, verdict enum, findings with file:line, checklist per lens item).
- [ ] **Step 5: Commit** `feat(review-team): blind parallel dispatcher`.

### Task 7: Dispatcher side-effects — dossier, comment, receipt, auto-wake

- [ ] **Step 1: Failing tests:** dossier written beside note; multi-task PR writes one dossier beside every linked task note; markdown comment body posted via gh runner (contains per-reviewer verdicts + escalations at top); quorum-accept + review-floor + gate-valid current changed-file scope → acceptance.yaml written (acceptor `review-team:<families>`, artifact = dossier path + PR url), existing receipt never overwritten; BLOCK/critical → wake payload file `~/.cache/hapax/review-team/wake/<task_id>-<sha8>.md` (path overridable for tests) + best-effort lane send invoked; idempotency: existing same-sha gate-valid dossier → skip unless `--force`; existing same-sha blocked dossier → skip/replay wake until a new head sha or `--force`; existing same-sha no-quorum/invalid dossier → re-review for reviewer recovery; `--all` scans open PRs and skips only fresh terminal/admissible dossiers.
- [ ] **Step 2-4: TDD until green.** Lane send: `scripts/hapax-{claude,codex,gemini}-send --session <lane> -- <short pointer to payload file>` chosen by lane_families; failures logged, never fatal.
- [ ] **Step 5: Commit** `feat(review-team): dossier receipts, PR comment, critical auto-wake`.

### Task 8: Exit-predicate integration test + evidence

- [ ] **Step 1: Integration test** (stubbed runners, real tmp vault): test PR through dispatcher `--apply` → dossier with 3 reviewers across ≥2 families; then `classify_pr` WITHOUT dossier → blocked (`missing_review_dossier` in reasons); WITH the produced quorum-accept dossier → queue. This is the task's exit predicate, executable.
- [ ] **Step 2:** `uv run pytest tests/test_review_team.py tests/test_cc_pr_review_dispatch.py tests/test_cc_pr_autoqueue.py tests/shared/test_sdlc_lifecycle.py -q` all green; `uv run ruff check` + `uv run ruff format` on touched files.
- [ ] **Step 3: Live dry-run evidence:** `uv run python scripts/cc-pr-review-dispatch.py --pr <this PR>` (no --apply) → constitution plan for the self-application T1 row.
- [ ] **Step 4: Commit, push, `gh pr create --head zeta/pr-review-team-system-20260611`** with before/after reason-code evidence in body; update task note (branch, pr); avsdlc precheck; relay receipt; idle at pr_open (frontier_review_required — not lane-closable).

## Self-review notes
- Spec §1→registry rows ✔; §2→sizing table ✔; §3→constitution rules + escalations ✔; §4→charters ✔; §5 trigger→`--all` timer-ready, unit deferred (scope) — flagged in PR body; dossier-as-receipt ✔ (decision 5); auto-wake ✔ (Task 7); §6 self-application → live dry-run in Task 8.
- Deadlock check: gate ON blocks all open PRs until dossiers exist — intended ("no quorum, no merge"); recovery = killswitch env; flagged in PR body for operator.
