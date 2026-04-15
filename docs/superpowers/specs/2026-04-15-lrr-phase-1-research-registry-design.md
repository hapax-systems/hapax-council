# LRR Phase 1 — Research Registry Foundation — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction from LRR epic spec per the LRR-epic extraction pattern; LRR execution remains alpha's workstream)
**Status:** DRAFT pre-staging — awaiting operator sign-off + LRR UP-0 close before Phase 1 open
**Epic reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 1 (canonical source)
**Plan reference:** `docs/superpowers/plans/2026-04-15-lrr-phase-1-research-registry-plan.md` (companion TDD checkbox plan)
**Branch target:** `feat/lrr-phase-1-research-registry`
**Cross-epic authority:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` (drop #62) — §3 ownership table rows 1–6 and §5 unified sequence row UP-1 take precedence over any conflicting claim in this spec
**Unified phase mapping:** **UP-1 Research Registry Foundation** (drop #62 §5 line 135): depends on UP-0 closed; 2-3 sessions, ~1400 LOC; blocks UP-2 (HSEA Phase 0), UP-3 (LRR Phase 2 archive), and everything downstream that touches condition_id

---

## 1. Phase goal

Create the append-only research registry that stores condition definitions, sub-experiment IDs, claim state, frozen-file manifests, and per-segment metadata. **Every reaction on the livestream must be taggable with a condition ID.** LRR Phase 1 is the substrate for research-grade livestream work: it makes the difference between a stream that collects data and a stream whose data is attributable, falsifiable, and publishable.

**What this phase is:** the filesystem-as-bus registry (per-condition YAML, frozen-files list, research-marker.json SHM, director-loop tagging), the frozen-files pre-commit hook, the condition_id tagging across Qdrant + JSONL + Langfuse, the `scripts/research-registry.py` CLI, the backfill of the ~2178 existing reactions to `cond-phase-a-baseline-qwen-001`, the stats.py BEST verification, the OSF project creation procedure, and the adjacent Qdrant schema drift fixes from the alpha close-out handoff.

**What this phase is NOT:** this phase does not open a new OSF pre-registration (that's Phase 4 / UP-6), does not ship the Hermes 3 8B parallel substrate swap (Phase 5a / UP-7a), does not author the persona spec (Phase 7 / UP-9), does not ship the archival pipeline re-enablement (Phase 2 / UP-3), and does not draft the `sp-hsea-mg-001` axiom precedent (HSEA Phase 0 0.5 / UP-2 deliverable; LRR Phase 6 / UP-8 ships the joint constitutional PR that bundles it).

**Theoretical grounding** (per LRR epic spec): I-1 (append-only research, adaptive not phased) + P-3 (conditions never close, they branch).

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62):**

1. **LRR UP-0 (Phase 0 verification) closed.** Standard LRR phase precondition. Phase 0 verification work (chat-monitor fix, token ledger wiring, inode pressure, FINDING-Q steps, Sierpinski baseline, RTMP path documentation, huggingface-cli, voice transcript path, Kokoro baseline) must be verified complete. Verify via `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[0].status == closed` OR `research-stream-state.yaml::unified_sequence[UP-0].status == closed`.

2. **No intra-epic HSEA dependencies on Phase 1 open.** HSEA Phase 0 (UP-2) depends on Phase 1 closed; HSEA Phase 1 (UP-4) depends on Phase 1 closed. Phase 1 does NOT depend on any HSEA phase. Phase 1 is pure LRR substrate work.

3. **Axiom precedent NOT in scope.** Per drop #62 §3 row 11 + operator Q5 ratification (2026-04-15T05:35Z, option a — joint PR), the `sp-hsea-mg-001` axiom precedent is drafted by HSEA Phase 0 deliverable 0.5 and bundled into LRR Phase 6's joint `hapax-constitution` PR. LRR Phase 1 does NOT draft this precedent. The drop #62 §5 line 135 phrasing "HSEA Phase 0 deliverable 0.5 (axiom precedent draft, deferred submission to UP-7)" is a pre-ratification framing superseded by the Q5 ratification; the draft belongs to HSEA Phase 0 (UP-2), not LRR Phase 1 (UP-1).

**Intra-epic:** Phase 0 closed. No other LRR phase prerequisite.

**Infrastructure:**

1. `~/hapax-state/` directory (existing, used by many agents; Phase 1 creates the `research-registry/` and `research-integrity/` subtrees).
2. `/dev/shm/hapax-compositor/` directory (existing, used by compositor; Phase 1 creates `research-marker.json` file).
3. `shared/qdrant_schema.py` (existing, `EXPECTED_COLLECTIONS` list; Phase 1 extends per item 10).
4. `shared/config.py` (existing, Qdrant client construction).
5. `agents/hapax_daimonion/director_loop.py` or whichever module currently contains the reaction tick (existing; Phase 1 adds condition_id tagging per item 5).
6. `shared/telemetry.py::hapax_span` / `hapax_score` (existing; Phase 1 extends `metadata` with condition_id per item 5).
7. `stream-reactions` Qdrant collection (existing, 2178 points; Phase 1 backfills per items 2 + 9).
8. `reactor-log-YYYY-MM.jsonl` (existing, per-reaction ledger; Phase 1 extends schema per item 2).
9. `scripts/` directory (existing; Phase 1 adds `check-frozen-files.sh` / `.py` and `research-registry.py`).
10. `research/protocols/` directory (existing if prior deviations have shipped; Phase 1 adds `osf-project-creation.md` per item 6).
11. `.pre-commit-config.yaml` OR `.git/hooks/pre-commit` (existing or to-be-created; Phase 1 wires the frozen-files hook per item 4).
12. Git working tree integrity (pre-commit hooks must not conflict with existing `hooks/scripts/` PreToolUse chain).

---

## 3. Deliverables (10 items)

Each item below extracts directly from LRR epic spec §5 Phase 1 items 1–10.

### 3.1 Registry data structure (item 1)

**Scope:**
- Directory: `~/hapax-state/research-registry/` (filesystem-as-bus idiom per council architecture)
- Per-condition subdirectory with YAML definition: `~/hapax-state/research-registry/<condition_id>/condition.yaml`
- Condition ID format: `cond-<short-name>-<sequential>` (examples: `cond-phase-a-baseline-qwen-001`, `cond-phase-a-prime-hermes-002`)
- Per-condition YAML schema:
  ```yaml
  condition_id: cond-phase-a-baseline-qwen-001
  claim_id: claim-shaikh-sft-vs-dpo
  opened_at: 2026-04-14T00:00:00Z
  closed_at: null  # open indefinitely (P-3: conditions never close, they branch)
  substrate:
    model: Qwen3.5-9B-exl3-5.00bpw
    backend: tabbyapi
    route: local-fast|coding|reasoning
  frozen_files:
    - agents/hapax_daimonion/grounding_ledger.py
    - agents/hapax_daimonion/conversation_pipeline.py
    - agents/hapax_daimonion/persona.py
    - agents/hapax_daimonion/conversational_policy.py
  directives_manifest:
    - path: agents/hapax_daimonion/grounding_directives.py
    - sha256: <hash>
  osf_project_id: null  # set when filed at Phase 4 / UP-6
  pre_registration:
    filed: false
    url: null
  notes: |
    Human-readable notes field.
  ```
- Append-only semantics: the YAML file is writable once at creation, mutable only for `closed_at`, `osf_project_id`, `pre_registration.filed`, `pre_registration.url`, and `notes`. All other fields are read-only after creation (enforced by item 8 CLI + optionally by a separate write-lock sentinel).
- Additional per-condition files alongside `condition.yaml`:
  - `scores-today.jsonl` (written by director loop when scoring occurs during this condition — HSEA Phase 1 deliverable 1.2 reads this)
  - `schedule.yaml` (optional, operator-edited; HSEA Phase 1 1.2 reads this)
- **Target files:**
  - `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/condition.yaml` (initial condition)
  - `shared/research_registry_schema.py` (~120 LOC Pydantic model + validation)
  - `tests/shared/test_research_registry_schema.py` (~80 LOC)

**Size:** ~200 LOC (schema + tests + initial condition YAML), 0.2 day serial work

### 3.2 Per-segment metadata schema extension (item 2)

**Scope:**
- Extend `stream-reactions` Qdrant collection payload schema to include a `condition_id` string field
- Extend `reactor-log-YYYY-MM.jsonl` entry schema to include a `condition_id` field (new entries only; backfill for existing per item 9)
- Update `shared/qdrant_schema.py` to document the new payload field (no type change needed if Qdrant payloads are unstructured; document in the expected-schema comment)
- Update whichever writer currently appends to `reactor-log-*.jsonl` to include `condition_id` from the research-marker (deliverable 3.3) on every append
- Any downstream consumer that queries `stream-reactions` without a `condition_id` filter continues to work (backward compatible); consumers that WANT to slice by condition_id can filter via `payload["condition_id"] == "cond-..."`
- **Target files:**
  - `shared/qdrant_schema.py` (documentation comment addition; no schema migration needed)
  - Director loop writer code (location TBD — likely `agents/hapax_daimonion/director_loop.py` or similar; ~10 LOC extension to add the field)
  - Reactor log writer (~10 LOC extension)

**Size:** ~50 LOC (mostly documentation + 2 small extensions), 0.2 day serial work (excluding the backfill itself, which is item 9)

### 3.3 Research-marker injection (item 3)

**Scope:**
- Dedicated SHM file at `/dev/shm/hapax-compositor/research-marker.json` holds the current active condition ID
- Schema:
  ```json
  {
    "condition_id": "cond-phase-a-baseline-qwen-001",
    "set_at": "2026-04-14T05:35:00Z",
    "set_by": "research-registry-cli",
    "epoch": 42
  }
  ```
- Written atomically via `shared/atomic_io.atomic_write_json` (or equivalent temp+rename pattern)
- Director loop reads this file on every reaction tick and tags the reaction with the current `condition_id`
- **Condition changes** are atomic writes to this file; any condition change coincides with a frame-accurate timestamp appended to a new audit log `~/hapax-state/research-registry/research_marker_changes.jsonl`
- The audit log schema:
  ```json
  {"at": "ISO8601", "from_condition": "cond-phase-a-baseline-qwen-001", "to_condition": "cond-phase-a-prime-hermes-8b-002", "epoch": 43, "changed_by": "research-registry-cli", "reason": "UP-7a substrate swap"}
  ```
- **Atomic-read pattern for consumers:** read the file with stale-detection (`os.stat().st_mtime`). If the marker is missing or malformed, consumers (like HSEA Phase 1 1.2 research state broadcaster) render "condition unknown — check registry" rather than crashing.
- **Target files:**
  - `/dev/shm/hapax-compositor/research-marker.json` (initial file, created by item 8 CLI at phase open time)
  - `shared/research_marker.py` (~100 LOC read/write helper with atomic semantics; reused by director loop + CLI)
  - `tests/shared/test_research_marker.py` (~80 LOC)
  - `~/hapax-state/research-registry/research_marker_changes.jsonl` (append-only audit log)

**Size:** ~180 LOC, 0.2 day serial work

### 3.4 Frozen-file pre-commit enforcement (item 4)

**Scope:**
- `scripts/check-frozen-files.sh` OR `scripts/check-frozen-files.py` (per drop #62 §3 row 1, either is acceptable; `.py` is preferred for better error messages + testability)
- Reads the current active condition's `frozen_files` list from `~/hapax-state/research-registry/<current>/condition.yaml` (current condition resolved via research-marker)
- Refuses to commit any change that touches those paths while the condition is open
- Installed via either:
  - `.git/hooks/pre-commit` (direct shell invocation)
  - OR `.pre-commit-config.yaml` entry (if the repo is using pre-commit framework)
- **Override mechanism:** an explicit `DEVIATION-NNN` filed by committing a markdown file to `research/protocols/deviations/DEVIATION-NNN.md` whose frontmatter includes a `paths` list matching the exceptional files. The hook reads the deviations directory at pre-commit time; if any open deviation's `paths` list includes the file being modified, the commit is allowed.
- Deviation frontmatter schema:
  ```yaml
  ---
  id: DEVIATION-037
  filed_at: 2026-04-15T00:00:00Z
  filed_by: alpha
  condition_id: cond-phase-a-prime-hermes-8b-002
  paths:
    - agents/hapax_daimonion/conversation_pipeline.py
  status: active  # active | closed
  reason: "Substrate swap requires conversation_pipeline dispatch extension"
  ---
  ```
- **HSEA Phase 0 `--probe` extension (drop #62 §3 row 1):** if HSEA Phase 0 deliverable 0.4 (promote scripts) needs a probe mode that checks a target file without requiring it to be staged, Phase 1 SHOULD ship that probe mode as part of `check-frozen-files.py`'s initial implementation. Signature: `check-frozen-files.py --probe <target_path>` returns exit 0 if target is not frozen OR has an active deviation, exit 2 otherwise.
- **Tests:** shell/bats tests that stage a test edit to `agents/hapax_daimonion/grounding_ledger.py` and verify the hook rejects with a clear error message; another test stages the same edit with an active `DEVIATION-test` listing that path and verifies the hook allows.
- **Target files:**
  - `scripts/check-frozen-files.py` (~200 LOC including `--probe` mode)
  - `.git/hooks/pre-commit` wiring (either new hook or an `--add` flag to existing composite)
  - `research/protocols/deviations/` (directory exists or is created; 0 bytes of new deviation files at phase open, but the directory schema is exercised)
  - `tests/scripts/test_check_frozen_files.sh` (~150 LOC bats)

**Size:** ~350 LOC, 0.3 day serial work

### 3.5 Langfuse scoring extension (item 5)

**Scope:**
- `shared/telemetry.py::hapax_span` and `hapax_score` calls in `director_loop.py` gain a `condition_id` metadata field derived from reading `research-marker.json`
- Per LRR epic spec item 5: this is a 3-line change at the call site (one read, one assignment, one inclusion in metadata dict)
- **Caveat per council CLAUDE.md:** metadata values MUST be strings; non-string values are dropped by langfuse's `propagate_attributes`. condition_id is already a string.
- **`hapax_span` refactor constraint (council CLAUDE.md):** `hapax_span` uses an `ExitStack` so setup failures yield a no-op span and caller exceptions propagate cleanly. Phase 1 does NOT refactor `hapax_span` — only the call sites in `director_loop.py` (and any other Phase-1-in-scope call site) get the `condition_id` kwarg passed through.
- Post-verify: Langfuse traces in the `stream-experiment` tag now show `condition_id` metadata on every span/score emitted from the director loop
- **Target files:**
  - Director loop call site (~3 LOC per call site, likely 2-3 sites total)
  - `tests/` regression ensuring every director-loop span has `condition_id` set

**Size:** ~30 LOC (including tests), 0.1 day serial work

### 3.6 OSF project creation procedure (item 6)

**Scope:**
- Document how to create the OSF project for the voice-grounding / Shaikh claim
- Create the project, generate a pre-registration URL, but **DO NOT FILE THE PRE-REG YET** — that's Phase 4 (UP-6)
- The procedure is committed as `research/protocols/osf-project-creation.md`
- Procedure contents:
  - OSF account login instructions (operator uses existing account)
  - Project creation CLI or UI flow (screenshots optional)
  - Pre-registration template URL pattern
  - How to link the generated URL into `condition.yaml::pre_registration.url`
  - How to set `pre_registration.filed: true` at Phase 4 / UP-6 time
- No code; pure documentation deliverable
- **Target file:**
  - `research/protocols/osf-project-creation.md` (~150 lines of markdown)

**Size:** ~150 lines markdown, 0.1 day serial work

### 3.7 `stats.py` BEST verification (item 7)

**Scope:**
- Per `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`: Bayesian Estimation Supersedes the t-Test (BEST) was decided but implementation state is unverified
- Grep for current analysis code; verify it uses Bayesian estimation vs. two-sample t-test, NOT beta-binomial
- If still beta-binomial, migrate to PyMC 5 BEST per drop #57 tactic T1.3
- **Drop #62 §3 row 6 note:** HSEA Phase 4 I1 drafter does NOT write the PyMC 5 port from scratch; I1 is narration-only and watches LRR Phase 1's commits. So Phase 1 IS the authoritative port site. HSEA Phase 4 I1 drafts narration based on Phase 1's commits.
- PyMC 5 dependency: `pymc` + `arviz` (install via `uv add pymc arviz` if not present)
- BEST implementation sketch:
  ```python
  import pymc as pm
  import arviz as az

  def best_two_group(y1, y2, samples=2000, tune=1000):
      with pm.Model() as model:
          mu1 = pm.Normal("mu1", mu=y1.mean(), sigma=y1.std() * 2)
          mu2 = pm.Normal("mu2", mu=y2.mean(), sigma=y2.std() * 2)
          sigma1 = pm.HalfNormal("sigma1", sigma=y1.std())
          sigma2 = pm.HalfNormal("sigma2", sigma=y2.std())
          nu = pm.Exponential("nu", lam=1/30)
          pm.StudentT("y1_obs", nu=nu+1, mu=mu1, sigma=sigma1, observed=y1)
          pm.StudentT("y2_obs", nu=nu+1, mu=mu2, sigma=sigma2, observed=y2)
          diff_mu = pm.Deterministic("diff_mu", mu1 - mu2)
          effect_size = pm.Deterministic("effect_size",
                                         diff_mu / pm.math.sqrt((sigma1**2 + sigma2**2) / 2))
          idata = pm.sample(samples, tune=tune, return_inferencedata=True)
      return az.summary(idata, var_names=["diff_mu", "effect_size"])
  ```
- **Tests:** compare output to a known reference dataset (e.g., Kruschke 2013 simulation numbers) with tolerance ±0.02 on `diff_mu` posterior mean
- **Target files:**
  - `stats.py` or wherever the current analysis code lives (verify + potentially rewrite)
  - `tests/test_stats_best.py` (~80 LOC)
  - `pyproject.toml` if PyMC 5 + ArviZ need to be added

**Size:** verification-only path ~20 LOC; full migration path ~350 LOC (including tests). **Decision gate:** the opener verifies current state first, then chooses. 0.1 day verification, 0.5 day full migration.

### 3.8 Research-registry CLI (item 8)

**Scope:**
- `scripts/research-registry.py` with subcommands:
  - `open <name>` — creates a new condition with `cond-<name>-NNN` format (auto-incrementing suffix); writes the condition.yaml with operator-supplied or default values; writes research-marker.json pointing at the new condition; appends an entry to `research_marker_changes.jsonl`
  - `close <condition_id>` — sets `closed_at` in the condition.yaml; does NOT delete the directory (P-3: conditions never close, they branch — `close` is a bookkeeping transition)
  - `current` — prints the current active condition_id from research-marker.json
  - `list` — prints all conditions in the registry with their status (open/closed/deferred)
  - `tag-reactions <start-ts> <end-ts> <condition_id>` — backfills condition_id on `stream-reactions` Qdrant points whose `timestamp` falls in the window (used by item 9)
  - `show <condition_id>` — prints the full condition.yaml content
  - `set-osf <condition_id> <project_id>` — sets `osf_project_id` (Phase 4 / UP-6 uses this)
  - `file-prereg <condition_id> <url>` — sets `pre_registration.filed: true` and `pre_registration.url: <url>` (Phase 4 / UP-6 uses this)
- Short (~200 lines target per epic spec item 8) but fully tested
- Uses `shared/research_registry_schema.py` from deliverable 3.1 for validation
- Uses `shared/research_marker.py` from deliverable 3.3 for marker writes
- **Target files:**
  - `scripts/research-registry.py` (~200 LOC)
  - `tests/scripts/test_research_registry.py` (~200 LOC)

**Size:** ~400 LOC, 0.5 day serial work

### 3.9 Backfill existing data (item 9)

**Scope:**
- Tag all pre-2026-04-14 `stream-reactions` with `cond-phase-a-baseline-qwen-001` (the initial baseline condition)
- Tag the reactor JSONL logs for the current month with the same condition_id
- Verify counts match: `count(stream-reactions where condition_id = 'cond-phase-a-baseline-qwen-001')` should equal the pre-existing point count (≈2178 per LRR epic spec)
- Backfill procedure:
  1. `research-registry open phase-a-baseline-qwen` → creates cond-phase-a-baseline-qwen-001
  2. `research-registry tag-reactions 2024-01-01T00:00:00Z 2026-04-14T00:00:00Z cond-phase-a-baseline-qwen-001` → Qdrant backfill
  3. Shell script to add `condition_id` to every entry in `reactor-log-YYYY-MM.jsonl` files (simple awk or python one-liner)
- **Risks:**
  - Qdrant batching: if 2178 points exceeds the client's default batch size, the CLI must page through. Use `scroll_with_filter` + `set_payload` patterns per `qdrant-client` docs.
  - Partial failure: if backfill halfway fails, re-running must be idempotent. Use Qdrant's `set_payload` (not `upsert`) so existing fields are preserved.
- **Verification:** after backfill, run a count query and compare to the pre-backfill total. They MUST match exactly (no points silently dropped).
- **Target files:**
  - Backfill script or one-time invocation (could be ad-hoc, or committed as `scripts/backfill-condition-id.py` for reproducibility)
  - `tests/scripts/test_backfill.py` (~80 LOC dry-run test against a fixture Qdrant)

**Size:** ~150 LOC (script + tests), 0.3 day serial work (plus wall time for Qdrant pagination, ~5 minutes)

### 3.10 Fix adjacent Qdrant schema drift (item 10)

**Scope (absorbed from alpha close-out handoff Q026 F1 + Q024 #83 + #84 per LRR epic spec):**

a. **`hapax-apperceptions` + `operator-patterns` missing from `EXPECTED_COLLECTIONS`** (Q026 F1): add both to `shared/qdrant_schema.py::EXPECTED_COLLECTIONS` (~6 lines). These collections exist in Qdrant but are not validated at startup, so drift is invisible.

b. **`operator-patterns` empty investigation** (Q024 #83, Q026 Phase 4 Finding 2): the writer was de-scheduled. Decide:
   - **Re-schedule** — find the writer agent, re-enable its systemd timer, verify points appear within 24h
   - **Retire** — remove from `EXPECTED_COLLECTIONS` + document in the condition registry notes that this collection is retired
   - Phase 1 opens this decision to the operator; default is re-schedule if a writer is identifiable.

c. **CLAUDE.md Qdrant collections list 9 → 10** (Q024 #84): update the council `CLAUDE.md` Qdrant section to reflect the correct count (adds `stream-reactions`). This is a ~3-line documentation edit.

d. **`axiom-precedents` sparse state** (Q024 #85, Q026 Phase 4 Finding 4): document in the condition registry as a known data-quality observation. 17 points is notable; determine if this is expected (axioms are rare) or if points are being lost.

e. **`profiles/*.yaml` vs Qdrant `profile-facts` drift** (Q024 #88): decide authoritative source and document:
   - **Filesystem authoritative:** Qdrant is a derived index; deletions in the YAML propagate to Qdrant via a reconciliation pass
   - **Qdrant authoritative:** YAML is a cache, rebuilt from Qdrant on restart
   - Document the decision in `research/protocols/profile-source-authority.md` OR in a condition.yaml `notes` field

**Target files:**
- `shared/qdrant_schema.py` (~6 LOC addition + ~10 LOC comment)
- Council `CLAUDE.md` (~3 LOC edit in the Qdrant section)
- `research/protocols/profile-source-authority.md` (~40 lines markdown) OR equivalent documentation location
- Potentially a new agent writer (if re-scheduling `operator-patterns`); likely 0 new LOC if the existing writer just needs a timer re-enable
- `tests/shared/test_qdrant_schema.py` (~20 LOC extension)

**Size:** ~80 LOC + operator decision on sub-item b, 0.2 day serial work (excluding operator decision time)

---

## 4. Phase-specific decisions since epic authored

Drop #62 fold-in (2026-04-14) + operator batch ratification (2026-04-15T05:35Z) introduce the following clarifications relative to the original LRR epic spec §5 Phase 1. None are scope changes — all are cross-epic coordination clarifications.

1. **LRR Phase 1 owns ALL five primitive families per drop #62 §3 rows 1–6:**
   - `scripts/check-frozen-files.sh`/`.py` (row 1) — Phase 1 item 4
   - `condition.yaml` (row 2) — Phase 1 item 1
   - `research-marker.json` (row 3) — Phase 1 item 3
   - `research-registry.py` CLI (row 4) — Phase 1 item 8
   - `condition_id` tagging on Qdrant + JSONL + Langfuse (row 5) — Phase 1 items 2 + 5
   - `stats.py` PyMC 5 BEST port (row 6) — Phase 1 item 7
   - HSEA reads all of these; HSEA writes none of them.

2. **HSEA Phase 0 sequencing depends on LRR Phase 1 landing** (drop #62 §3 row 1): HSEA Phase 0 (UP-2) does NOT open until LRR Phase 1 (UP-1) is closed and all 10 items merged. This makes Phase 1 a hard prerequisite for the entire HSEA chain.

3. **No axiom precedent drafting in Phase 1** (per §2 precondition 3 above): the `sp-hsea-mg-001` axiom precedent is HSEA Phase 0 deliverable 0.5 / UP-2 work. Phase 1 does NOT draft it. The drop #62 §5 line 135 "HSEA Phase 0 deliverable 0.5 (axiom precedent draft, deferred submission to UP-7)" wording is a pre-ratification framing superseded by the Q5 ratification (2026-04-15T05:35Z, option a — joint PR via LRR Phase 6 / UP-8).

4. **HSEA Phase 4 I1 drafter is narration-only** (drop #62 §3 row 6 + Q3 ratification): the PyMC 5 BEST port (Phase 1 item 7) is the authoritative implementation site. HSEA Phase 4 I1 drafter is NOT permitted to write the port from scratch; it watches Phase 1's commits and drafts a research drop summarizing the change for stream content. Phase 1 does NOT need to coordinate with HSEA Phase 4 on the port itself.

5. **`--probe` mode for `check-frozen-files.py`** (drop #62 §3 row 1): Phase 1 item 4 SHOULD ship with a `--probe <target_path>` mode so HSEA Phase 0 deliverable 0.4's `_promote-common.sh::_frozen_files_check` can call it without requiring the target to be staged. This is a minor scope addition; estimated +30 LOC on item 4. If Phase 1 ships without `--probe`, HSEA Phase 0 0.4 files a follow-up to add it.

6. **Per-condition Prometheus slicing NOT in Phase 1 scope** (drop #62 §3 row 13): that's LRR Phase 10 (UP-13) work. Phase 1 only tags spans/scores with `condition_id` via item 5; the per-condition Prometheus cardinality budget is downstream.

7. **All drop #62 §10 open questions are closed** as of 2026-04-15T05:35Z. No Phase 1 deliverable is gated on a pending operator decision. Phase 1's opening preconditions are entirely upstream (LRR UP-0 closed) + infrastructure (Qdrant + Langfuse + filesystem accessible).

---

## 5. Exit criteria

Phase 1 closes when ALL of the following are verified:

1. **`~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/condition.yaml` exists** with well-formed YAML per the schema in deliverable 3.1

2. **`/dev/shm/hapax-compositor/research-marker.json` exists** and is read by the director loop on every reaction tick. Verify: add a debug log in the director loop that prints `condition_id` on each tick; tail the log for 30 seconds; every tick prints `cond-phase-a-baseline-qwen-001`.

3. **Every new reaction has a `condition_id` field** in both JSONL and Qdrant. Verify: after Phase 1 close, trigger a stream reaction, check the reactor JSONL log for the new entry's `condition_id` field, check the Qdrant point for the same.

4. **Backfilled reactions have `cond-phase-a-baseline-qwen-001`.** Verify: `count(stream-reactions where condition_id = 'cond-phase-a-baseline-qwen-001')` ≈ 2178 (or the actual pre-backfill total if different).

5. **`scripts/check-frozen-files.py` rejects a test edit** to `agents/hapax_daimonion/grounding_ledger.py` with a clear error message. Verify: stage such an edit, run `git commit -m "test"`, assert exit code 2 and error text mentions the frozen file.

6. **`check-frozen-files.py --probe` mode works.** Verify: `scripts/check-frozen-files.py --probe agents/hapax_daimonion/grounding_ledger.py` returns exit 2; `scripts/check-frozen-files.py --probe docs/research/test.md` returns exit 0.

7. **`stats.py` uses BEST** (or Bayesian estimation equivalent), NOT beta-binomial. Verify: grep for `beta.pdf\|binom.pmf`; if found, the migration was incomplete and exit criteria fails.

8. **OSF project creation procedure documented** at `research/protocols/osf-project-creation.md`. Verify: the file exists and has at least the steps listed in deliverable 3.6.

9. **`scripts/research-registry.py` operational.** Verify: `uv run python scripts/research-registry.py current` returns `cond-phase-a-baseline-qwen-001`. `uv run python scripts/research-registry.py list` returns at least one condition. `uv run python scripts/research-registry.py show cond-phase-a-baseline-qwen-001` prints the YAML content.

10. **Langfuse traces in `stream-experiment` tag show `condition_id` metadata.** Verify: emit a test score via `hapax_score(...)`, check the Langfuse dashboard for the span, confirm `condition_id: cond-phase-a-baseline-qwen-001` is in the metadata panel.

11. **Qdrant schema drift fixes applied** (item 10):
    - [ ] `hapax-apperceptions` + `operator-patterns` in `EXPECTED_COLLECTIONS`
    - [ ] `operator-patterns` writer decision documented (re-scheduled or retired)
    - [ ] Council CLAUDE.md Qdrant list updated
    - [ ] `axiom-precedents` sparse state documented
    - [ ] `profiles/*.yaml` vs Qdrant authority decision documented

12. **`lrr-state.yaml::phase_statuses[1].status == closed`** written at phase close. `research-stream-state.yaml::unified_sequence[UP-1].status == closed` if the shared index has landed (per Q8 ratification, alpha creates the shared index at UP-0 fold-in time; if it exists, Phase 1 close updates it; if not, Phase 1 close blocks on shared index creation first).

13. **Phase 1 handoff doc written** at `docs/superpowers/handoff/YYYY-MM-DD-lrr-phase-1-complete.md` with summary of what shipped, links to PRs/commits, verification evidence for each exit criterion.

14. **Smoke test: HSEA Phase 0 (UP-2) pre-open check works.** With Phase 1 closed, a dry-run of the HSEA Phase 0 opening procedure (reading `research-marker.json`, calling `research-registry.py current`, verifying `check-frozen-files.py --probe` works) succeeds. This is the acceptance test that Phase 1 is actually ready to support downstream work.

---

## 6. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Backfill of 2178 Qdrant points may be slow or require batching | MEDIUM | Delays Phase 1 close; partial backfill state is observable | Use `scroll` + `set_payload` with page_size=500; idempotent re-runs; verify counts match before closing |
| Frozen-file enforcement pre-commit conflicts with existing `hooks/scripts/` chain | MEDIUM | Pre-commit hook stack order breaks builds | Install as a composite hook; test with `git commit --dry-run` before committing real changes; run on a throwaway branch first |
| `stats.py` migration is larger than expected (full BEST port vs verification-only) | MEDIUM | Phase 1 runs over 3 sessions if full port is needed | Decision gate at item 7: verify first, migrate only if beta-binomial is still in use; if migration required, it's the longest tail item in the phase |
| HSEA Phase 0 opens prematurely before LRR Phase 1 closes | HIGH | HSEA Phase 0 0.4 promote scripts fail because `_frozen_files_check` wrapper points at a nonexistent tool | Enforce via session-onboarding check; HSEA Phase 0 spec + plan (already committed at `5b75ad1cd`) require LRR UP-1 closed before opening |
| `operator-patterns` writer cannot be identified for re-schedule | LOW | Item 10b decision defaults to retirement | Document retirement clearly in the condition registry; the collection can be re-introduced later if a new writer is designed |
| `research-marker.json` is read at high frequency by director loop; tmpfs contention | LOW | Director loop tick latency | `/dev/shm` is memory-backed; reads are O(1); cache the parse result with a 100ms stale-grace if needed |
| Pre-commit hook false-positive on merge commits | MEDIUM | Can't merge PRs while a condition is open | Skip the frozen-files check on merge commits (`git rev-parse --verify MERGE_HEAD &>/dev/null && exit 0`) |
| Langfuse metadata propagation drops non-string values (council CLAUDE.md note) | LOW | `condition_id` is already a string; not at risk | Document in the item 5 test that metadata assignment must be `str(condition_id)` defensively |
| Qdrant `set_payload` vs `upsert` confusion during backfill | MEDIUM | Backfill accidentally overwrites other payload fields | Use `set_payload` exclusively (preserves other fields); add a regression test that backfill preserves the `reaction_text` field on each point |

---

## 7. Open questions

All drop #62 §10 open questions are resolved as of 2026-04-15T05:35Z. LRR Phase 1 has no remaining operator-pending decisions from the cross-epic fold-in.

Phase-1-specific design questions (operator or Phase 1 opener can decide at open time; not blocking the phase open):

1. **`check-frozen-files.sh` vs `.py` file format.** Epic spec item 4 lists both. Recommendation: `.py` for better error messages and testability. Operator can override at phase open time.

2. **`operator-patterns` writer decision (item 10b):** re-schedule or retire. Default is re-schedule if a writer is identifiable; retire otherwise. Operator can override.

3. **`profiles/*.yaml` vs Qdrant `profile-facts` authority decision (item 10e):** filesystem-authoritative vs Qdrant-authoritative. Default is filesystem-authoritative (Qdrant is a derived index) per the single-user axiom rationale (filesystem-as-bus is the canonical surface). Operator can override.

4. **`stats.py` current state (item 7):** verification-only path vs full PyMC 5 migration. Phase 1 opener runs the verification first; the decision gate is automatic if the current code is already Bayesian, and operator-facing if migration is needed.

5. **`DEVIATION-037` file location:** LRR epic spec + drop #62 + beta's PR #819 all assume `research/protocols/deviations/DEVIATION-037.md`. Phase 1 item 4 creates the deviations directory convention; DEVIATION-037 itself is beta's PR #819 pre-staging and lands when that PR merges, NOT via Phase 1. Phase 1 just sets up the directory + hook-reading pattern.

---

## 8. Companion plan doc

TDD checkbox task breakdown at `docs/superpowers/plans/2026-04-15-lrr-phase-1-research-registry-plan.md`.

Execution order inside Phase 1 (serial, single-session-per-item-cluster model):

1. **Item 1 Registry data structure** — foundational; needed by items 3, 4, 8. Ship first.
2. **Item 3 Research-marker injection + item 8 CLI `open`/`current`** — the CLI's `open` and `current` subcommands depend on item 1's schema and item 3's marker file. Ship together so `research-registry.py open phase-a-baseline-qwen` produces both the condition.yaml AND the research-marker.json.
3. **Item 5 Langfuse scoring extension** — 3-line change; ship right after item 3 so director loop tags reactions immediately.
4. **Item 2 Per-segment metadata schema extension** — depends on item 3 for the source of truth on condition_id. Ship after item 5 so the director loop writer has a live marker to read.
5. **Item 4 Frozen-file pre-commit enforcement** — independent of items 2/3/5 but depends on item 1's schema for the frozen_files list. Ship after item 2 so the full condition ownership chain is in place.
6. **Item 8 full CLI (remaining subcommands: `close`, `list`, `tag-reactions`, `show`, `set-osf`, `file-prereg`)** — ship after item 4; `tag-reactions` is required by item 9 backfill.
7. **Item 9 Backfill existing data** — depends on items 1, 2, 8. Ship after the full CLI is in place.
8. **Item 7 `stats.py` BEST verification + optional migration** — independent of items 1-6, 8, 9; can be shipped in parallel with any of them. Recommend shipping after item 9 so the registry is fully operational before touching analysis code.
9. **Item 6 OSF project creation procedure** — documentation; can be shipped at any point. Recommend shipping last so it references the actual `condition.yaml::pre_registration` fields that item 1 creates.
10. **Item 10 Qdrant schema drift fixes** — independent; can be interleaved. Sub-item b (operator decision on `operator-patterns`) is the only blocking piece if the operator is not responsive.

Each item is a separate PR (or a single multi-commit PR with reviewer pass per item). Phase 1 closes when all 10 items are merged, all 14 exit criteria verified, and HSEA Phase 0 (UP-2) can open against the Phase 1 foundation.

---

## 9. End

This is the standalone per-phase design spec for LRR Phase 1. It extracts the Phase 1 section of the LRR epic spec (`docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 1) and incorporates:

- Drop #62 fold-in corrections (§3 ownership table rows 1–6 + §5 unified phase sequence row UP-1 + §3 row 11 axiom precedent joint PR clarification)
- Operator batch ratification 2026-04-15T05:35Z (all 10 §10 questions closed)
- `--probe` mode scope addition on item 4 per drop #62 §3 row 1

This spec is pre-staging. It does not open Phase 1. Phase 1 opens only when:

- LRR UP-0 is closed (phase 0 verification work complete)
- A session claims the phase via `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[1].status: open`
- The compositor and Langfuse are reachable (deliverables 3.2 + 3.5 depend on them)

**LRR execution remains alpha's workstream.** Delta is a research session pre-staging the per-phase spec + plan so that whichever session opens LRR Phase 1 does not need to re-derive the scope from the epic spec. This follows the same pattern delta used for HSEA Phase 0 + Phase 1 extraction, and matches the pattern beta + epsilon used for LRR Phase 4/5/6 pre-staging on `beta-phase-4-bootstrap`.

Pre-staging authored by delta per the request "extract" (2026-04-15) following a prior evaluation that identified LRR Phase 1 as the highest-value pre-staging target (critical path for HSEA Phases 0 + 1 and all downstream work).

— delta, 2026-04-15
