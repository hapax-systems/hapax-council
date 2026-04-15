# Cross-epic integration smoke test design

**Date:** 2026-04-15
**Author:** beta (PR #819 author, AWB mode) per delta queue refill 5 Item #79
**Scope:** conceptual design (no code) for a cross-epic integration smoke test that exercises LRR Phases 1-2 + HSEA Phases 0-1 together once all have shipped.
**Status:** design document (not implementation)

---

## 1. Why a cross-epic smoke test

LRR Phases 1-2 and HSEA Phases 0-1 are intentionally designed as separate epics that share a set of filesystem-as-bus surfaces (research-marker.json, stream-reactions Qdrant collection, reactor log JSONL, CairoSourceRegistry zone catalog, consent registry, axiom precedents). Each phase ships its own TDD-covered unit tests, but the cross-epic interaction has no single test surface today.

**Specific integration surfaces that no unit test exercises end-to-end:**

1. **condition_id propagation chain:** `research-registry.py open <condition>` → atomic write to `/dev/shm/hapax-compositor/research-marker.json` → `shared/research_marker.py::read_marker()` returns the new value → director loop tags next reaction with the new condition_id → reactor log JSONL entry carries it → Qdrant upsert carries it → HSEA Phase 1 research-state broadcaster reads it → HUD strip renders it.
2. **Governance queue surfacing:** HSEA Phase 0 0.5 consent event writes to governance queue → HSEA Phase 1 1.4 governance queue placard zone renders it via `CairoSourceRegistry` → operator sees it on livestream within ≤1 frame of write.
3. **Spawn budget gate:** HSEA Phase 0 spawn budget config → HSEA Phase 1 1.2 objective strip reads remaining budget → reactor director checks budget before spawning a sub-task → denial path fires the frozen-files placard on budget exhaust.
4. **Frozen-files pre-commit hook + placard:** LRR Phase 1 `check-frozen-files.py --probe` returns non-zero → pre-commit hook blocks commit → HSEA Phase 1 1.3 frozen-files placard zone renders within ≤1 frame of the block event.
5. **Consent contract revocation → purge:** operator revokes consent via consent CLI → LRR Phase 2 purge CLI detects revocation → auditable deletion fires → audit log append confirmed.

A smoke test is the lightweight cousin of a full integration test: it exercises the golden path of each surface without trying to test every edge case. If the smoke test passes, the operator can trust that the epic-boundary wiring works; if it fails, the operator has a concrete breakpoint to investigate.

## 2. What this design covers

- **Inputs the smoke test provides** (§3)
- **What it verifies** (§4)
- **Infrastructure needed** (§5)
- **Test-mode flags** (§6)
- **Fixture data** (§7)
- **Teardown** (§8)
- **Execution cadence** (§9)
- **Failure modes + debugging** (§10)

Not in scope: concrete pytest code, CI wiring, multi-host smoke tests, load/stress tests, reverse-engineering of unit-test gaps.

## 3. Inputs the smoke test provides

### 3.1 Stub research condition

The smoke test creates a stub condition via:

```python
smoke_condition_id = "cond-smoke-test-2026-04-15-001"
smoke_condition_yaml = {
    "condition_id": smoke_condition_id,
    "claim_id": "claim-smoke-test",
    "opened_at": "2026-04-15T00:00:00Z",
    "closed_at": None,
    "substrate": {"model": "smoke-test-stub"},
    "sub_experiments": [],
    "frozen_files": [],
    "notes": "Cross-epic integration smoke test condition — safe to purge after run",
}
```

Writes `~/hapax-state/research-registry/cond-smoke-test-2026-04-15-001/condition.yaml` via the production `research-registry.py open` CLI path (not directly — we want to exercise the CLI). Sets the research marker to point at the smoke condition.

### 3.2 Stub governance queue entry

```python
smoke_governance_item = {
    "queue_id": "smoke-gov-2026-04-15-001",
    "kind": "consent_review",
    "subject": "smoke test consent review",
    "filed_at": "2026-04-15T00:00:00Z",
    "status": "pending",
}
```

Writes to the HSEA governance queue surface (path TBD — check HSEA Phase 0 0.5 spec for exact location; likely `~/hapax-state/governance-queue/pending/smoke-gov-2026-04-15-001.yaml`).

### 3.3 Stub Cairo source registration

```python
class SmokeTestCairoSource(CairoSource):
    """Smoke test Cairo source — renders 'SMOKE TEST' text in the test zone."""
    ...

CairoSourceRegistry.register(
    source_cls=SmokeTestCairoSource,
    zone="smoke_test_zone",
    priority=9999,  # higher than any production source
)
```

Registers a one-off zone `smoke_test_zone` declared in a test-only `config/compositor-zones.smoke.yaml` (NOT the production catalog).

### 3.4 Stub frozen-file

```python
smoke_frozen_file = "docs/smoke-test-frozen-marker.md"
# Append to the active condition's frozen_files list via research-registry CLI:
subprocess.run(["research-registry.py", "freeze-file",
                smoke_condition_id, smoke_frozen_file])
```

The smoke test later attempts a commit touching this file and verifies the pre-commit hook blocks it.

### 3.5 Stub consent contract

```python
smoke_consent_contract = {
    "contract_id": "smoke-consent-001",
    "subject": "smoke test subject",
    "granted_at": "2026-04-15T00:00:00Z",
    "revocable": True,
}
```

Writes to `axioms/contracts/smoke-consent-001.yaml` via consent CLI.

## 4. What the smoke test verifies

### 4.1 condition_id propagation chain

1. After `research-registry.py open cond-smoke-test-2026-04-15-001`, read `/dev/shm/hapax-compositor/research-marker.json` and assert `condition_id == "cond-smoke-test-2026-04-15-001"`.
2. Send a stub reaction through the director loop (via a test-mode reactor injection — see §6). Assert the reaction's reactor-log JSONL entry carries `condition_id=cond-smoke-test-...`.
3. Query Qdrant `stream-reactions` collection for the stub reaction. Assert the payload's `condition_id` field matches.
4. Read HSEA Phase 1 research-state broadcaster output (SSE stream or SHM file — depends on HSEA Phase 1 final design). Assert the broadcaster's current-state reports `condition_id=cond-smoke-test-...`.
5. Read HSEA Phase 1 1.1 HUD strip output (either via the Cairo source's render buffer or via a test-mode `get_current_render()` accessor). Assert the rendered HUD shows the smoke condition_id.

**Golden path:** CLI → marker → reactor → JSONL → Qdrant → broadcaster → HUD, all with the same condition_id.

### 4.2 Governance queue surfacing

1. After writing the stub governance queue entry, wait for the HSEA Phase 1 1.4 governance queue placard zone renderer to pick it up (should be ≤1 frame = ≤33ms at 30fps).
2. Read the placard zone's render buffer. Assert it shows the smoke governance item.
3. Mark the item as `status: resolved` via the HSEA Phase 0 governance CLI. Wait ≤1 frame.
4. Assert the placard zone hides the item (or shows it as resolved).

### 4.3 Spawn budget gate

1. Read the current spawn budget from HSEA Phase 0 config + state.
2. Attempt to spawn a sub-task via HSEA Phase 1 1.2 objective strip interface. Assert the spawn succeeds AND the objective strip shows remaining budget decremented.
3. Exhaust the budget by spawning until denied.
4. Assert the reactor director denies the next spawn.
5. Assert the frozen-files placard (zone reused for budget exhaust events per HSEA Phase 1 1.3) fires.

### 4.4 Frozen-files pre-commit hook + placard

1. Create a file at `docs/smoke-test-frozen-marker.md` with some stub content.
2. Run `git add docs/smoke-test-frozen-marker.md`.
3. Run `git commit -m "smoke test"` — EXPECT non-zero exit from pre-commit hook.
4. Parse the hook output. Assert it mentions the frozen-file path + the active condition_id.
5. Wait ≤1 frame for HSEA Phase 1 1.3 frozen-files placard to fire.
6. Read the placard zone's render buffer. Assert it shows the blocked commit.

### 4.5 Consent contract revocation → purge

1. Grant the stub consent contract.
2. Write a stub segment sidecar (via the sidecar writer from LRR Phase 2 item #56) carrying the smoke condition_id + a stub consent contract reference.
3. Revoke the stub consent contract via consent CLI.
4. Run `archive-purge.py --condition cond-smoke-test-2026-04-15-001 --confirm` (from LRR Phase 2 item #62).
5. Assert the purge CLI DOES NOT require `--force` (because consent is revoked, not because it's absent).
6. Assert the segment sidecar file is deleted.
7. Assert the audit log entry at `~/hapax-state/stream-archive/audit/purge-YYYY-MM-DD.jsonl` carries the correct schema.

## 5. Infrastructure needed

### 5.1 Test-mode flags (see §6)

- `HAPAX_TEST_MODE=1` in environment
- `HAPAX_SMOKE_TEST_CONDITION_ID` for the stub condition
- `HAPAX_ARCHIVE_ROOT=/tmp/hapax-smoke-archive-$$` for isolated archive state
- `HAPAX_STATE_ROOT=/tmp/hapax-smoke-state-$$` for isolated research-registry + governance queue
- `HAPAX_CONSENT_STORE=/tmp/hapax-smoke-consent-$$` for isolated consent store

### 5.2 Isolated directories

All test state lives under `/tmp/hapax-smoke-$$` (or similar). The smoke test MUST NOT write to production paths (`~/hapax-state/`, `~/Documents/Personal/`, `/dev/shm/hapax-compositor/`).

Two options for achieving isolation:

- **Option A — environment variable override:** every production path is constructed via `os.environ.get("HAPAX_STATE_ROOT", "~/hapax-state")`. The smoke test sets the env var before invoking the CLIs.
- **Option B — pytest fixture with mock pathlib:** use `pyfakefs` or monkeypatch to redirect all path lookups.

Option A requires code audit + consistent env var usage (add to every state write site). Option B works without code changes but may miss subprocess-invoked CLIs that don't inherit the mock filesystem.

**Recommendation:** Option A. The env-var-override pattern is explicit, testable, and also serves other operational purposes (e.g., running hapax under a different home directory during migrations).

### 5.3 Mock LLM gateway (optional)

For the reactor path, a real LLM call via LiteLLM is overkill. The smoke test should use a deterministic fake reactor that produces a pre-scripted reaction (e.g., a canned reaction JSON read from a fixture file).

Register the fake reactor via a test-mode reactor registry: `REACTORS = {"smoke": SmokeReactor}` and select it via `HAPAX_REACTOR=smoke`.

### 5.4 Mock GPU / compositor

The smoke test does not run the real GStreamer compositor. It runs the compositor in test-mode where:

- Zones are still registered via `CairoSourceRegistry`
- CairoSources are instantiated and their `render()` methods are called
- The rendered output is written to an in-memory buffer, not a /dev/video device
- A test helper `get_zone_render(zone_name)` reads the in-memory buffer for assertions

This is a substantial infrastructure item. Alternatives:

- **Option X — real compositor, scaped output:** run the real compositor in a test mode that writes to `/tmp/hapax-smoke-compositor-output/` instead of `/dev/video42`. Assertions read JPEG frames from this path.
- **Option Y — CairoSource unit test pattern:** invoke each source's `render()` directly in Python, never start the GStreamer pipeline. Assertions read the Cairo surface bytes.
- **Option Z — full compositor with vglrun:** run the full compositor in a Xvfb / vglrun environment. Most realistic, slowest.

**Recommendation:** Option Y for the initial smoke test. Cheap, fast, covers the zone-registration + source-render path without compositor overhead. Upgrade to Option X when the smoke test catches "compositor doesn't pick up my CairoSource" bugs that Option Y misses.

## 6. Test-mode flags

The smoke test needs production code paths to be test-mode-aware. Proposed env vars:

| Env var | Purpose | Scope |
|---|---|---|
| `HAPAX_TEST_MODE` | Master switch: tells production code it's running in a test | Read by all production CLIs + services |
| `HAPAX_STATE_ROOT` | Override `~/hapax-state` | Research registry, governance queue, stream archive |
| `HAPAX_VAULT_ROOT` | Override `~/Documents/Personal` | Vault note writer (item #60) |
| `HAPAX_SHM_ROOT` | Override `/dev/shm/hapax-compositor` | Research marker, stimmung SHM, pipeline SHM |
| `HAPAX_ARCHIVE_ROOT` | Override `~/hapax-state/stream-archive` | Archive search + purge |
| `HAPAX_CONSENT_STORE` | Override `axioms/contracts/` | Consent CLI |
| `HAPAX_REACTOR` | Select reactor backend | Reactor registry |
| `HAPAX_SMOKE_TEST_CONDITION_ID` | Pre-assigned smoke condition_id | Smoke test bootstrap only |

**Implementation note:** every production path construction site must go through a helper. Proposed helper: `shared/paths.py::state_root() -> Path`, `vault_root() -> Path`, etc. The helpers read the env var and fall back to the production default. This is a modest refactor (~30 sites across the repo) but pays back in smoke-test + migration + portability value.

## 7. Fixture data

Fixture files live at `tests/smoke/fixtures/`:

- `cond-smoke-test-2026-04-15-001.yaml` — stub condition YAML
- `smoke-reaction-001.json` — stub reaction JSON for the fake reactor
- `smoke-gov-2026-04-15-001.yaml` — stub governance queue entry
- `smoke-consent-001.yaml` — stub consent contract
- `smoke-test-frozen-marker.md` — stub file to trigger the frozen-files hook
- `smoke-compositor-zones.yaml` — test-mode zone catalog with `smoke_test_zone` entry
- `smoke-segment-000.ts` + `smoke-segment-000.json` — stub HLS segment + sidecar for archive purge test

All fixtures are deterministic + checked into the repo. The smoke test copies them to the test state root at the start of each run.

## 8. Teardown

The smoke test's cleanup phase:

1. `rm -rf /tmp/hapax-smoke-$$` — purge the isolated state root
2. Remove the smoke test Cairo source from `CairoSourceRegistry` (call `CairoSourceRegistry.clear()` — but be careful, this also removes production registrations; better to track the smoke source ID + call a `unregister()` helper if added, OR run the smoke test in a subprocess that gets its own process state)
3. Remove any vault notes created under the test vault root (handled by the `rm -rf` from step 1 if the test vault root is under `/tmp/hapax-smoke-$$`)
4. Revoke any test consent contracts still active

**Recommendation:** run the smoke test in a subprocess. Subprocess exit cleanly cleans up `CairoSourceRegistry` + all other in-process state without risk of leaking state into the next test run or into production.

## 9. Execution cadence

**When to run:**

- **CI:** on every PR that touches a cross-epic surface (LRR Phase 1/2 code, HSEA Phase 0/1 code, `shared/research_marker.py`, `cairo_source_registry.py`, `consent.py`). Add a GitHub Actions workflow `cross-epic-smoke-test.yml` triggered by `paths:` filter.
- **Local dev:** after any change that touches the above, run `uv run pytest tests/smoke/ -q`.
- **Nightly:** systemd user timer `hapax-cross-epic-smoke.timer` runs nightly at 05:00Z, ntfy's on failure. Serves as a canary against drift over time.

**Expected runtime:** 10-30 seconds (not 10 minutes — smoke tests are fast by definition). If the smoke test grows beyond ~60 seconds, split it into cheap smoke + slower integration.

## 10. Failure modes + debugging

Each verification step in §4 should produce a rich failure message when it fails. Example:

```
AssertionError: condition_id propagation broken at step 3 (Qdrant payload)

Expected: condition_id=cond-smoke-test-2026-04-15-001
Got:      condition_id=None

Probable cause:
  - Director loop reactor is not reading the research marker at tag time
  - OR: Qdrant upsert is missing the condition_id field in payload construction
  - Check: agents/hapax_daimonion/director_loop.py:<line>
  - Check: shared/telemetry.py::hapax_span metadata dict
```

Rich diagnostics are the point of a smoke test. Cryptic failures waste more time than the test saves.

**Debugging aid:** smoke test dump mode — when `HAPAX_SMOKE_TEST_DUMP=1`, every intermediate state is written to `/tmp/hapax-smoke-dump-$$/step-<N>-<name>.json`. The dump survives teardown so the operator can inspect what the smoke test saw at each step when investigating a failure.

## 11. Dependencies — what must ship first

This smoke test design assumes the following have shipped:

- LRR Phase 1 (research registry, research marker, reactor log with condition_id, frozen-files hook)
- LRR Phase 2 items 1-9 (archive pipeline, sidecar writer, search CLI, purge CLI)
- HSEA Phase 0 (governance queue surface, consent contract flow, spawn budget config)
- HSEA Phase 1 deliverables 1.1-1.5 (HUD, objective strip, frozen-files placard, governance queue placard, condition transition banner)
- `shared/paths.py` helper refactor (§6 test-mode flags)

It does NOT assume:

- LRR Phase 3+ (stress tests, substrate swap)
- HSEA Phase 2+ (quality, research orch, self-monitor, etc.)
- Real compositor output to /dev/video42 (Option Y mock pattern instead)

## 12. Non-goals

- This smoke test is NOT a replacement for unit tests or per-phase integration tests.
- This smoke test does NOT exercise the real LLM gateway or real GStreamer pipeline.
- This smoke test does NOT test performance, load, or concurrency edge cases.
- This smoke test does NOT validate the visual output of rendered frames (pixel comparison); it validates that the rendered text content contains expected strings.

## 13. Recommended next step

The smoke test belongs to Phase 10 polish OR a dedicated cross-epic phase. It is NOT blocking for any epic's in-flight work. Recommended timing: land the smoke test as part of LRR Phase 10 §"cross-epic integration verification" OR at the start of the session immediately after HSEA Phase 1 ships.

The `shared/paths.py` helper refactor (§6) can be landed earlier as an independent low-risk PR. It does not require the rest of the smoke test to exist, and it pays back in migration + portability value independent of the smoke test.

## 14. References

- LRR Phase 1 spec `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md`
- LRR Phase 2 spec `docs/superpowers/specs/2026-04-15-lrr-phase-2-archive-research-instrument-design.md`
- HSEA Phase 0 spec `docs/superpowers/specs/2026-04-15-hsea-phase-0-bootstrap-governance-design.md`
- HSEA Phase 1 spec `docs/superpowers/specs/2026-04-15-hsea-phase-1-hud-governance-overlay-design.md`
- LRR Phase 10 spec `docs/superpowers/specs/2026-04-15-lrr-phase-10-observability-drills-polish-design.md`
- Drop #62 §3 ownership table (`docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`)
- `shared/research_marker.py` (LRR Phase 1 item 3 — shipped PR #841)
- `agents/studio_compositor/cairo_source_registry.py` (LRR Phase 2 item 10a — shipped PR #849)
- `config/compositor-zones.yaml` (LRR Phase 2 item 10b — shipped PR #850)

— beta (PR #819 author, AWB mode), 2026-04-15T15:50Z
