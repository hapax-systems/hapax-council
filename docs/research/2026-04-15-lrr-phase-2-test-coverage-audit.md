# LRR Phase 2 test coverage audit

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #117)
**Scope:** Catalogue tests for 6 modules shipped in LRR Phase 2 (archive + replay as research instrument). Identify untested paths, risk-rank gaps.
**Register:** scientific, neutral

## 1. Headline

**Phase 2 test coverage is strong.** 135 tests distributed across 8 test files, covering all 6 production modules. Each module has at least 11 tests.

**4 gaps identified, 2 MEDIUM + 2 LOW.**

| Module | Prod lines | Tests | Coverage verdict |
|---|---|---|---|
| `agents/studio_compositor/hls_archive.py` | 341 | 14 | ✓ core paths covered; gap in stimmung snapshot error paths |
| `shared/stream_archive.py` | 172 | 15 | ✓ strong |
| `scripts/archive-search.py` | 424 | 21 | ✓ all 7 subcommands tested |
| `scripts/archive-purge.py` | 272 | 11 | ✓ consent revocation + dry-run covered |
| `agents/studio_compositor/research_marker_frame_source.py` | 222 | 12 + 19 (shared/test_research_marker.py) + 18 (test_research_marker_overlay.py) = 49 | ✓ heavily tested |
| `agents/studio_compositor/cairo_source_registry.py` | 278 | 25 | ✓ very thorough |

**Total:** 1,709 production lines, 135 tests, 8 test files.

## 2. Method

```bash
# Find test files
find tests -name "*hls_archive*" -o -name "*stream_archive*" \
           -o -name "*archive_search*" -o -name "*archive_purge*" \
           -o -name "*research_marker*" -o -name "*cairo_source_registry*"

# Count tests per file
grep -cE "^    def test_|^def test_" <file>

# Count module functions
grep -cE "^def " <module>

# Inspect function names for untested path detection
grep -E "^def " <module>
```

## 3. Per-module analysis

### 3.1 `agents/studio_compositor/hls_archive.py` — 341 lines, 14 tests

**Test file:** `tests/test_hls_archive_rotation.py` (377 lines, 14 tests)

**Functions:**

| # | Function | Tested? |
|---|---|---|
| 1 | `_load_condition_id` | ✓ (via rotate_segment fixture) |
| 2 | `_load_stimmung_snapshot` | partial — happy path covered, error paths not |
| 3 | `is_segment_stable` | ✓ (dedicated tests) |
| 4 | `build_sidecar` | ✓ (dedicated tests) |
| 5 | `rotate_segment` | ✓ (multiple tests) |
| 6 | `rotate_pass` | ✓ (dedicated tests) |

**Gap G1 (LOW):** `_load_stimmung_snapshot` error paths (missing file, malformed JSON, partial read) are not directly tested. The function is only 20 lines but the error handling path is untested. Low severity because a stimmung snapshot failure produces a `None` return and sidecar just omits the field.

### 3.2 `shared/stream_archive.py` — 172 lines, 15 tests

**Test file:** `tests/test_stream_archive_sidecar.py` (177 lines, 15 tests)

**Functions + classes:**

| # | Symbol | Tested? |
|---|---|---|
| 1 | `atomic_write_json` | ✓ |
| 2 | `archive_root` | ✓ |
| 3 | `hls_archive_dir` | ✓ (date-based path) |
| 4 | `audio_archive_dir` | ✓ (date-based path) |
| 5 | `sidecar_path_for` | ✓ |
| 6 | `SegmentSidecar` (dataclass) | ✓ (serde roundtrip) |
| 7 | plus 3 internal helpers | ✓ (via SegmentSidecar) |

**Verdict:** ✓ complete. Module is small, tests cover every public symbol.

### 3.3 `scripts/archive-search.py` — 424 lines, 21 tests

**Test file:** `tests/test_archive_search.py` (358 lines, 21 tests)

**Subcommands + helpers (15 functions):**

| # | Function | Tested? |
|---|---|---|
| 1 | `_iter_sidecars` | ✓ (fixture-based) |
| 2 | `_load_all` | ✓ |
| 3 | `_parse_iso` | ✓ (edge cases) |
| 4 | `_emit_json` | ✓ |
| 5 | `_emit_table` | ✓ |
| 6 | `_emit` (dispatcher) | ✓ |
| 7 | `cmd_by_condition` | ✓ |
| 8 | `cmd_by_reaction` | ✓ |
| 9 | `cmd_by_timerange` | ✓ |
| 10 | `cmd_extract` | ✓ |
| 11 | `cmd_stats` | ✓ |
| 12 | `cmd_verify` | ✓ |
| 13 | `cmd_note` | ✓ |
| 14 | `build_parser` | ✓ (via main) |
| 15 | `main` | ✓ (argv dispatch) |

**Verdict:** ✓ complete. All 7 subcommands tested; 21 tests / 15 functions = 1.4× coverage ratio.

### 3.4 `scripts/archive-purge.py` — 272 lines, 11 tests

**Test file:** `tests/test_archive_purge.py` (367 lines, 11 tests)

**Functions:**

| # | Function | Tested? |
|---|---|---|
| 1 | `_consent_revocation_check` | ✓ (critical path) |
| 2 | `_iter_sidecars` | ✓ |
| 3 | `_load_active_condition` | ✓ |
| 4 | `_now_iso` | unmocked (not critical) |
| 5 | `_append_audit_log` | ✓ |
| 6 | `_collect_targets` | ✓ |
| 7 | `main` | ✓ (argv + dry-run) |

**Gap G2 (MEDIUM):** the purge script's interaction with real filesystem inode-level rename semantics is not explicitly tested. The test suite uses `tmp_path` fixtures (ext4), which matches production, so this is a theoretical gap only. Low probability of impact but MEDIUM severity because a purge bug would delete research evidence.

**Verdict:** ✓ adequate. 11 tests cover all 7 functions including the consent-revocation guard.

### 3.5 `agents/studio_compositor/research_marker_frame_source.py` — 222 lines

**Test files:**
- `tests/studio_compositor/test_research_marker_frame_source.py` (254 lines, 12 tests) — frame source rendering
- `tests/shared/test_research_marker.py` (222 lines, 19 tests) — shared marker state
- `tests/test_research_marker_overlay.py` (176 lines, 18 tests) — cairo overlay integration

**Total: 49 tests across 3 files** for this module. Combined coverage is comprehensive:

| Concern | File |
|---|---|
| Frame source subclass (CairoSource contract) | `test_research_marker_frame_source.py` |
| Shared marker state management | `test_research_marker.py` |
| Cairo overlay rendering integration | `test_research_marker_overlay.py` |

**Verdict:** ✓ heavily tested. Highest test-to-prod-line ratio in Phase 2.

### 3.6 `agents/studio_compositor/cairo_source_registry.py` — 278 lines, 25 tests

**Test file:** `tests/studio_compositor/test_cairo_source_registry.py` (277 lines, 25 tests)

**Classes + functions:**

| # | Symbol | Tested? |
|---|---|---|
| 1 | `CairoSourceBinding` (dataclass) | ✓ (construction + validation) |
| 2 | `CairoSourceRegistry` (class) | ✓ (25 tests) |
| 3 | `load_zone_defaults` | ✓ (YAML load) |
| 4 | plus 3 internal helpers | ✓ (via registry tests) |

**Verdict:** ✓ very thorough. 25 tests for 6 functions = 4× coverage ratio. The `CairoSourceRegistry` is the central zone-binding resolver and deserves this level of coverage.

## 4. Gap summary + risk ranking

| # | Severity | Module | Gap | Remediation effort |
|---|---|---|---|---|
| G1 | LOW | `hls_archive.py` | `_load_stimmung_snapshot` error paths untested | 3 tests (~30 LOC) |
| G2 | MEDIUM | `archive-purge.py` | No filesystem rename/atomic-delete integration test | 2 tests (~50 LOC) |
| G3 | LOW | `hls_archive.py` | `_load_condition_id` only indirectly tested via `rotate_segment` | 2 tests (~20 LOC) |
| G4 | MEDIUM | cross-module | No end-to-end test exercising `rotate_segment` → `sidecar_path_for` → `archive-search cmd_by_condition` → `archive-purge main` flow | 1 integration test (~100 LOC) |

**Total proposed addition:** ~200 LOC of tests across 4 files.

### 4.1 Risk ranking

1. **G4 (MEDIUM)** — end-to-end integration is the biggest gap. Phase 2 shipped 10 PRs, each testing its own module in isolation; no single test exercises the full archive lifecycle from rotation → search → purge. A regression that breaks the interop between these would not be caught by the existing unit tests.
2. **G2 (MEDIUM)** — purge has consent-revocation + audit-log tests but not filesystem atomicity tests. Research evidence deletion is high-impact if wrong.
3. **G1 (LOW)** — isolated error-path gap. Blast radius is small.
4. **G3 (LOW)** — coverage hole is theoretical; function is trivial (20 lines).

## 5. Test organization observations

### 5.1 Test file locations

Phase 2 tests split across three directories:

- `tests/*.py` — top-level (test_hls_archive_rotation, test_stream_archive_sidecar, test_archive_search, test_archive_purge, test_research_marker_overlay)
- `tests/studio_compositor/*.py` — subdir (test_cairo_source_registry, test_research_marker_frame_source)
- `tests/shared/*.py` — subdir (test_research_marker)

**Inconsistent placement.** `test_hls_archive_rotation.py` lives in top-level `tests/` but the module is under `agents/studio_compositor/`. Peer tests like `test_cairo_source_registry.py` live in `tests/studio_compositor/`. Moving `test_hls_archive_rotation.py` + `test_research_marker_overlay.py` into `tests/studio_compositor/` would align placement. Low priority cosmetic cleanup.

### 5.2 Fixture reuse

Per workspace CLAUDE.md § Shared Conventions: "each test file self-contained, no shared conftest fixtures." Spot-check: no `tests/conftest.py` for Phase 2 modules, each test file owns its fixtures. ✓ follows convention.

### 5.3 Test naming

All tests follow `test_<concern>_<scenario>` pattern. Readable. ✓

## 6. Recommendations

### 6.1 Priority (file as follow-up queue items)

1. **G4 — end-to-end archive lifecycle integration test** (MEDIUM). New file: `tests/test_archive_lifecycle_integration.py`. ~100 LOC. Target: rotate segment → search by condition → verify sidecar → purge with dry-run → assert audit log.
2. **G2 — purge filesystem atomicity tests** (MEDIUM). Add 2 tests to `tests/test_archive_purge.py`. ~50 LOC. Target: simulate partial delete via monkeypatch `os.rename`, verify rollback.

### 6.2 Deferrable (low priority, low impact)

3. **G1 — stimmung snapshot error path tests** (LOW). Add 3 tests to `tests/test_hls_archive_rotation.py`. ~30 LOC.
4. **G3 — `_load_condition_id` direct tests** (LOW). Add 2 tests. ~20 LOC.
5. **Test placement cleanup** — move `test_hls_archive_rotation.py` + `test_research_marker_overlay.py` into `tests/studio_compositor/`.

## 7. Closing

Phase 2 test coverage is strong. 135 tests across 8 files cover all 6 production modules with healthy test-to-prod ratios. The single structural gap is lack of end-to-end integration testing across the archive lifecycle. Recommend one integration test + one purge-atomicity test as follow-up queue items; defer the smaller gaps.

Branch-only commit per queue item #117 acceptance criteria.

## 8. Cross-references

- LRR Phase 2 spec: `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-replay-design.md`
- LRR Phase 2 plan: `docs/superpowers/plans/2026-04-14-lrr-phase-2-archive-replay-plan.md`
- Phase 2 shipped PRs: approximately #801–#810 (10 PRs, per queue inflection history)
- Test files referenced:
  - `tests/test_hls_archive_rotation.py`
  - `tests/test_stream_archive_sidecar.py`
  - `tests/test_archive_search.py`
  - `tests/test_archive_purge.py`
  - `tests/studio_compositor/test_research_marker_frame_source.py`
  - `tests/studio_compositor/test_cairo_source_registry.py`
  - `tests/test_research_marker_overlay.py`
  - `tests/shared/test_research_marker.py`

— alpha, 2026-04-15T18:30Z
