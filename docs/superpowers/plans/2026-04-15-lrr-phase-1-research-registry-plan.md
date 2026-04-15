# LRR Phase 1 — Research Registry Foundation — Plan

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction from LRR epic plan per the extraction pattern; LRR execution remains alpha's workstream)
**Status:** DRAFT pre-staging — awaiting operator sign-off + LRR UP-0 close before Phase 1 open
**Spec reference:** `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md`
**Epic reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 1
**Branch target:** `feat/lrr-phase-1-research-registry`
**Cross-epic authority:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` (drop #62) — §3 ownership rows 1–6 + §5 unified sequence UP-1
**Unified phase mapping:** UP-1 Research Registry Foundation (2-3 sessions, ~1400 LOC per drop #62 §5)

---

## 0. Preconditions (MUST verify before task 1.1)

- [ ] **LRR UP-0 (verification) closed.** Check `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[0].status == closed`.
- [ ] **FDL-1 deployed to a running compositor** (recommended; not strictly required for Phase 1 items, but director-loop tagging in item 5 + research-marker reads in item 3 are easier to verify against a running compositor).
- [ ] **Qdrant reachable.** `curl -s http://localhost:6333/ | head` returns a response. `qdrant-client` imports cleanly.
- [ ] **Langfuse reachable.** `curl -s http://localhost:3000/api/public/health | grep "OK"` returns OK.
- [ ] **`~/hapax-state/` writable by the session** (trivially true on the single-user system, but verify if running under unusual permissions).
- [ ] **Drop #62 §10 Q8 shared index ratification confirmed.** `research-stream-state.yaml` either exists (in which case Phase 1 close updates it) or the session accepts that Phase 1 close blocks on alpha creating it during UP-0 fold-in commit.
- [ ] **Drop #62 §10 batch ratification in place.** All 10 questions closed as of 2026-04-15T05:35Z; no pending decisions block Phase 1.
- [ ] **Session claims the phase.** Write `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[1].status: open` + `current_phase: 1` + `current_phase_owner: <session>` + `current_phase_branch: feat/lrr-phase-1-research-registry` + `current_phase_opened_at: <now>`. Update `research-stream-state.yaml::unified_sequence[UP-1].status: open` + `owner: <session>` if the shared index exists.

---

## 1. Item 1 — Registry data structure

Executed FIRST because items 3, 4, and 8 all depend on the schema.

### 1.1 Pydantic schema module (TDD: tests first)

- [ ] Create `tests/shared/test_research_registry_schema.py`:
  - [ ] `test_minimal_valid_condition` — construct `ResearchCondition(condition_id="cond-test-001", claim_id="claim-test", opened_at=..., substrate=..., frozen_files=[...])`; no exceptions
  - [ ] `test_condition_id_format_validation` — invalid ids like `cond-test`, `test-001`, `cond-test-abc` fail validation; `cond-test-001` passes
  - [ ] `test_append_only_closed_at` — construct with `closed_at: None`; set to a datetime; re-set to `None` or a different datetime fails validation (immutable after first set)
  - [ ] `test_frozen_files_list_not_empty` — at least one frozen file required (or allow empty, depending on design — decide at write time; default: allow empty but warn)
  - [ ] `test_directives_manifest_sha256_format` — each entry's `sha256` field must be a 64-char hex string
  - [ ] `test_round_trip_yaml_serialization` — serialize to YAML, parse back, assert equality
- [ ] Create `shared/research_registry_schema.py`:
  - [ ] `class ResearchCondition(BaseModel)` with all fields per spec §3.1
  - [ ] `condition_id: str = Field(pattern=r"^cond-[a-z0-9-]+-\d{3}$")`
  - [ ] `substrate: SubstrateInfo` nested model (model, backend, route)
  - [ ] `frozen_files: list[str]`
  - [ ] `directives_manifest: list[DirectiveEntry]` with path + sha256
  - [ ] `opened_at: datetime`, `closed_at: datetime | None`
  - [ ] `osf_project_id: str | None = None`
  - [ ] `pre_registration: PreRegistrationInfo` nested (filed: bool, url: str | None)
  - [ ] `notes: str = ""`
  - [ ] `def to_yaml(self) -> str` / `def from_yaml(yaml_text: str) -> Self` helpers
- [ ] Run tests: all pass

### 1.2 Initial condition YAML

- [ ] Create `~/hapax-state/research-registry/` directory if not exists
- [ ] Create `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/` subdirectory
- [ ] Write `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/condition.yaml` with:
  - [ ] `condition_id: cond-phase-a-baseline-qwen-001`
  - [ ] `claim_id: claim-shaikh-sft-vs-dpo`
  - [ ] `opened_at: 2026-04-14T00:00:00Z` (historical baseline open time)
  - [ ] `closed_at: null`
  - [ ] `substrate.model: Qwen3.5-9B-exl3-5.00bpw`
  - [ ] `substrate.backend: tabbyapi`
  - [ ] `substrate.route: local-fast|coding|reasoning`
  - [ ] `frozen_files` list of the 4 files from spec §3.1
  - [ ] `directives_manifest` with `agents/hapax_daimonion/grounding_directives.py` + sha256 computed via `sha256sum`
  - [ ] `osf_project_id: null`
  - [ ] `pre_registration: {filed: false, url: null}`
  - [ ] `notes: "First condition under the new epic..."`
- [ ] Verify: `python -c "import yaml; yaml.safe_load(open('$HOME/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/condition.yaml'))"` succeeds

### 1.3 Commit item 1

- [ ] `uv run ruff check shared/research_registry_schema.py tests/shared/test_research_registry_schema.py`
- [ ] `uv run ruff format` same files
- [ ] `uv run pyright shared/research_registry_schema.py`
- [ ] `git add shared/research_registry_schema.py tests/shared/test_research_registry_schema.py`
- [ ] NOTE: the condition.yaml file is not committed — it's session-local state under `~/hapax-state/`, not in the repo
- [ ] `git commit -m "feat(lrr-phase-1): item 1 ResearchCondition pydantic schema + validation"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[1].status: completed`

---

## 2. Item 3 — Research-marker injection + Item 8 CLI `open` / `current`

Executed TOGETHER because the CLI `open` command creates both the condition.yaml AND the research-marker.json, and `current` reads the marker.

### 2.1 `shared/research_marker.py` helper

- [ ] Create `tests/shared/test_research_marker.py`:
  - [ ] `test_write_marker_atomic` — call `write_marker("cond-test-001", "test-actor", reason="test")`; read back; assert content + timestamp
  - [ ] `test_read_marker_happy_path` — write a marker; call `read_marker()`; assert returns `MarkerState(condition_id, set_at, set_by, epoch)`
  - [ ] `test_read_marker_missing_file` — no marker file; `read_marker()` returns `None` (or `MarkerState(condition_id=None, ...)`; decide at write time)
  - [ ] `test_read_marker_malformed_json` — corrupt the file mid-write (simulate); `read_marker()` returns `None` without crashing
  - [ ] `test_read_marker_stale_detection` — `read_marker(max_age_s=30)` on a 60s-old file returns stale indicator
  - [ ] `test_atomic_write_no_partial` — kill writer mid-write; verify no partial JSON visible to concurrent reader
  - [ ] `test_epoch_increment_on_change` — change condition; verify epoch increments by 1
  - [ ] `test_audit_log_appended_on_change` — call `write_marker` with new condition; verify entry appears in `research_marker_changes.jsonl`
- [ ] Create `shared/research_marker.py`:
  - [ ] `@dataclass(frozen=True) class MarkerState(condition_id: str, set_at: datetime, set_by: str, epoch: int)`
  - [ ] `def read_marker(max_age_s: float | None = None) -> MarkerState | None`
  - [ ] `def write_marker(condition_id: str, set_by: str, reason: str = "") -> None` — atomic write + audit log append
  - [ ] Uses `shared.atomic_io.atomic_write_json` (existing in the compositor tree; verify module name)
  - [ ] Marker path: `/dev/shm/hapax-compositor/research-marker.json`
  - [ ] Audit log path: `~/hapax-state/research-registry/research_marker_changes.jsonl`

### 2.2 CLI skeleton with `open` + `current`

- [ ] Create `tests/scripts/test_research_registry_cli.py`:
  - [ ] `test_open_creates_condition_yaml` — `research-registry.py open phase-a-test`; assert `~/hapax-state/research-registry/cond-phase-a-test-001/condition.yaml` exists + parseable
  - [ ] `test_open_writes_marker` — same; assert research-marker.json now points at the new condition
  - [ ] `test_open_auto_increments_suffix` — `open phase-a-test` twice; second creates `cond-phase-a-test-002`
  - [ ] `test_current_prints_marker_condition_id` — `research-registry.py current` prints the condition_id from the marker
  - [ ] `test_current_no_marker` — marker absent; `current` prints "no active condition" + exit 1
- [ ] Create `scripts/research-registry.py` (initial with just `open` + `current` subcommands):
  - [ ] argparse setup with subcommands
  - [ ] `open <name>` handler: compute next-suffix integer, construct `ResearchCondition(...)`, write YAML to `~/hapax-state/research-registry/<condition_id>/condition.yaml`, write marker via `shared.research_marker.write_marker(...)`
  - [ ] `current` handler: `read_marker()` → print `condition_id` or "no active condition"
  - [ ] Python shebang + `uv run python` compatibility

### 2.3 Commit item 3 + partial item 8

- [ ] Lint + format + pyright on all new files
- [ ] `git add shared/research_marker.py tests/shared/test_research_marker.py scripts/research-registry.py tests/scripts/test_research_registry_cli.py`
- [ ] `git commit -m "feat(lrr-phase-1): item 3 research marker + item 8 CLI open/current subcommands"`
- [ ] Run `uv run python scripts/research-registry.py open phase-a-baseline-qwen` to bootstrap the initial condition (or manually place the condition.yaml from task 1.2 then run `open` which should detect and skip the `-001` slot). Verify `uv run python scripts/research-registry.py current` returns `cond-phase-a-baseline-qwen-001`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[3].status: completed`

---

## 3. Item 5 — Langfuse scoring extension (3-line change)

Executed THIRD because it's trivial and immediately gives director-loop tagging once the marker exists.

### 3.1 Director loop call site extension

- [ ] Locate `director_loop.py` or equivalent in `agents/hapax_daimonion/` (verify exact path at open time)
- [ ] Find every `hapax_span(...)` and `hapax_score(...)` call in the director loop
- [ ] Add `condition_id` to the metadata dict at each call site:
  ```python
  from shared.research_marker import read_marker
  _marker = read_marker()
  _condition_id = _marker.condition_id if _marker else "unknown"
  with hapax_span(name="...", metadata={"condition_id": str(_condition_id), ...}) as span:
      ...
  ```
- [ ] Defensive `str(...)` wrap per council CLAUDE.md: langfuse drops non-string metadata values via `propagate_attributes`
- [ ] Do NOT refactor `hapax_span` itself — only call sites

### 3.2 Regression test

- [ ] Create `tests/test_director_loop_condition_id.py`:
  - [ ] Mock the research marker to return `MarkerState(condition_id="cond-test-001", ...)`
  - [ ] Invoke one director loop tick
  - [ ] Assert the emitted span/score metadata dict contains `condition_id="cond-test-001"`

### 3.3 Commit item 5

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/director_loop.py tests/test_director_loop_condition_id.py`
- [ ] `git commit -m "feat(lrr-phase-1): item 5 condition_id metadata on director-loop spans + scores"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[5].status: completed`

---

## 4. Item 2 — Per-segment metadata schema extension

Executed FOURTH because it depends on item 3 (research marker) to pull the live condition_id at write time.

### 4.1 Qdrant payload documentation update

- [ ] Edit `shared/qdrant_schema.py`:
  - [ ] Add a comment block in the `stream-reactions` section documenting the `condition_id` payload field
  - [ ] No code change to schema enforcement (Qdrant payloads are unstructured); documentation only
- [ ] Edit the existing Qdrant schema test if it asserts payload fields; ensure `condition_id` is in the expected set for new points

### 4.2 Reactor log writer extension

- [ ] Locate the writer that appends to `reactor-log-YYYY-MM.jsonl` (likely in `agents/hapax_daimonion/` or `agents/reaction_logger.py`; verify at open time)
- [ ] Add `condition_id` field to the JSONL entry dict, pulled from `shared.research_marker.read_marker()`
- [ ] Defensive fallback: if marker read fails, set `condition_id: "unknown"` + log warning (do not crash the logger)

### 4.3 Qdrant writer extension

- [ ] Find the code that writes `stream-reactions` points to Qdrant (likely same module or sibling)
- [ ] Add `condition_id` to the `payload` dict at write time
- [ ] Same fallback as reactor log writer

### 4.4 Regression tests

- [ ] Create `tests/test_reactor_log_condition_id.py`:
  - [ ] Mock marker; invoke writer; assert JSONL entry has condition_id field
- [ ] Create `tests/test_qdrant_writer_condition_id.py`:
  - [ ] Mock marker + mock Qdrant client; invoke writer; assert `upsert` payload has condition_id field

### 4.5 Commit item 2

- [ ] Lint + format + pyright
- [ ] `git add shared/qdrant_schema.py agents/hapax_daimonion/reaction_logger.py tests/test_reactor_log_condition_id.py tests/test_qdrant_writer_condition_id.py`
- [ ] `git commit -m "feat(lrr-phase-1): item 2 condition_id on stream-reactions + reactor-log JSONL"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[2].status: completed`

---

## 5. Item 4 — Frozen-file pre-commit enforcement

Executed FIFTH. Depends on item 1's schema but not on items 2/3/5 directly.

### 5.1 `scripts/check-frozen-files.py` (TDD)

- [ ] Create `tests/scripts/test_check_frozen_files.sh` (bats or plain bash):
  - [ ] `test_rejects_frozen_file_staged` — stage an edit to `agents/hapax_daimonion/grounding_ledger.py`; run `check-frozen-files.py`; assert exit 2 + error message mentions the file
  - [ ] `test_allows_nonfrozen_file_staged` — stage an edit to `docs/research/test.md`; run; assert exit 0
  - [ ] `test_deviation_override_allows_frozen_edit` — create `research/protocols/deviations/DEVIATION-test.md` with frontmatter listing the frozen file + `status: active`; stage the edit; assert exit 0
  - [ ] `test_closed_deviation_rejects` — same but `status: closed`; stage the edit; assert exit 2
  - [ ] `test_merge_commit_bypass` — simulate merge commit (MERGE_HEAD exists); run; assert exit 0 (skip)
  - [ ] `test_no_active_condition_skips` — research-marker absent; assert exit 0 (no gating active)
  - [ ] `test_probe_mode_frozen` — `check-frozen-files.py --probe agents/hapax_daimonion/grounding_ledger.py`; assert exit 2
  - [ ] `test_probe_mode_nonfrozen` — `check-frozen-files.py --probe docs/research/test.md`; assert exit 0
  - [ ] `test_probe_mode_with_deviation` — same as probe_frozen but active DEVIATION covers the file; assert exit 0
- [ ] Create `scripts/check-frozen-files.py`:
  - [ ] argparse: positional args for staged files (default to `git diff --cached --name-only`); `--probe <path>` for non-staged check
  - [ ] `read_active_condition()` — uses `shared.research_marker.read_marker()`; returns condition_id or None
  - [ ] `read_frozen_files(condition_id)` — parses `~/hapax-state/research-registry/<condition_id>/condition.yaml`; returns frozen_files list
  - [ ] `read_active_deviations()` — scans `research/protocols/deviations/*.md` for frontmatter with `status: active`; returns list of covered paths
  - [ ] Main logic: for each target path, check if it's in frozen_files AND not in any active deviation's paths; if so, reject
  - [ ] Merge commit bypass: `git rev-parse --verify MERGE_HEAD &>/dev/null && exit 0`
  - [ ] Clear error messages with file + condition_id + how to file a deviation

### 5.2 Pre-commit hook wiring

- [ ] Add entry to `.git/hooks/pre-commit` (or `.pre-commit-config.yaml` if used) that calls `scripts/check-frozen-files.py` on staged files
- [ ] Coordinate with existing `hooks/scripts/` PreToolUse chain — check-frozen-files.py is a GIT pre-commit hook, not a Claude Code PreToolUse hook, so there should be no conflict; verify
- [ ] Test composite hook order: `git commit -m "test"` on a throwaway branch with a benign change; assert all hooks fire in order

### 5.3 Commit item 4

- [ ] Lint + format (scripts/ is python; also `shellcheck` on the bats test if installed)
- [ ] `git add scripts/check-frozen-files.py tests/scripts/test_check_frozen_files.sh .git/hooks/pre-commit`
- [ ] `git commit -m "feat(lrr-phase-1): item 4 check-frozen-files.py + --probe mode + deviation override"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[4].status: completed`

---

## 6. Item 8 — Full research-registry CLI (remaining subcommands)

Executed SIXTH. Extends the CLI skeleton from task 2.2 with all remaining subcommands.

### 6.1 Remaining subcommand tests

- [ ] Extend `tests/scripts/test_research_registry_cli.py`:
  - [ ] `test_close_sets_closed_at` — `open` then `close <condition_id>`; assert condition.yaml has `closed_at` populated
  - [ ] `test_close_idempotent` — calling `close` twice; second call is no-op (or errors with "already closed"; decide at write time)
  - [ ] `test_close_does_not_delete_directory` — condition directory still exists after `close`
  - [ ] `test_list_prints_all_conditions` — open 3 conditions, one closed; `list` shows all 3 with status
  - [ ] `test_show_prints_yaml_content` — `show <condition_id>` prints parseable YAML that matches the file
  - [ ] `test_tag_reactions_dry_run` — `tag-reactions --dry-run 2026-01-01 2026-04-14 cond-test-001`; no Qdrant mutations; prints affected point count
  - [ ] `test_tag_reactions_idempotent` — run twice; second run tags 0 new points
  - [ ] `test_set_osf_updates_project_id` — `set-osf cond-test-001 osf_project_xyz`; assert condition.yaml has `osf_project_id: osf_project_xyz`
  - [ ] `test_file_prereg_updates_both_fields` — `file-prereg cond-test-001 https://osf.io/abc`; assert `pre_registration.filed: true` + `url: https://osf.io/abc`

### 6.2 Implementation

- [ ] Extend `scripts/research-registry.py` with subcommand handlers:
  - [ ] `close` — read condition.yaml, set `closed_at`, write back (careful: do NOT overwrite other fields — use round-trip YAML via `ruamel.yaml` or careful dict update)
  - [ ] `list` — scan `~/hapax-state/research-registry/*/condition.yaml`; print table: condition_id + status + opened_at + claim_id
  - [ ] `tag-reactions <start-ts> <end-ts> <condition_id>` — uses qdrant-client `scroll_with_filter` on `stream-reactions` filtered by timestamp range; for each point, `set_payload({condition_id: ...}, point_id=...)`; page through with batch size 500
  - [ ] `show <condition_id>` — cat the condition.yaml
  - [ ] `set-osf` — edit `osf_project_id` field in condition.yaml (round-trip YAML)
  - [ ] `file-prereg` — edit `pre_registration.filed` + `url` in condition.yaml
- [ ] Ensure all mutations preserve YAML field order and comments (use `ruamel.yaml` with `default_flow_style=False` and `indent(mapping=2, sequence=4, offset=2)` for consistency)

### 6.3 Commit item 8 (full CLI)

- [ ] Lint + format + pyright
- [ ] `git add scripts/research-registry.py tests/scripts/test_research_registry_cli.py`
- [ ] `git commit -m "feat(lrr-phase-1): item 8 research-registry CLI full subcommand set"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[8].status: completed`

---

## 7. Item 9 — Backfill existing data

Executed SEVENTH. Depends on item 1 (schema), item 2 (payload field), item 8 (`tag-reactions` subcommand).

### 7.1 Reactor log JSONL backfill

- [ ] Locate current month's `reactor-log-YYYY-MM.jsonl` files (likely under `~/hapax-state/reactor-logs/` or similar; verify)
- [ ] Write a one-time python script (committed for reproducibility) that reads each existing JSONL entry, adds `condition_id: cond-phase-a-baseline-qwen-001`, writes back atomically
- [ ] Idempotency: if an entry already has `condition_id`, skip it
- [ ] Verify: `jq '.condition_id' reactor-log-2026-04.jsonl | sort -u` shows only `cond-phase-a-baseline-qwen-001` (or empty for entries from before this date if unbackfilled)

### 7.2 Qdrant `stream-reactions` backfill

- [ ] Invoke `uv run python scripts/research-registry.py tag-reactions 2024-01-01T00:00:00Z 2026-04-14T00:00:00Z cond-phase-a-baseline-qwen-001`
- [ ] Monitor progress (the CLI should print batch counts every 500 points)
- [ ] Verify count:
  ```python
  from qdrant_client import QdrantClient
  c = QdrantClient("localhost:6333")
  r = c.count("stream-reactions", filter=Filter(must=[FieldCondition(key="condition_id", match=MatchValue(value="cond-phase-a-baseline-qwen-001"))]))
  print(r.count)  # should be ≈ 2178
  ```
- [ ] Compare to pre-backfill total (before Phase 1 started): `c.count("stream-reactions").count`
- [ ] Assert they match exactly (no dropped points)

### 7.3 Commit item 9

- [ ] Lint + format + pyright on any new scripts
- [ ] `git add scripts/backfill-condition-id.py` (if committed) + any regression test
- [ ] `git commit -m "feat(lrr-phase-1): item 9 backfill 2178 stream-reactions + reactor-log to cond-phase-a-baseline-qwen-001"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[9].status: completed`

---

## 8. Item 7 — `stats.py` BEST verification + optional migration

Executed EIGHTH. Independent of items 1-6, 8, 9 but scheduled late so the registry is fully operational before touching analysis code.

### 8.1 Current state verification

- [ ] Grep for analysis code: `grep -rn "beta.pdf\|binom.pmf\|ttest\|BEST\|pymc" --include="*.py" agents/ shared/`
- [ ] Locate `stats.py` or equivalent analysis module (may not exist as `stats.py` specifically)
- [ ] If `pymc` imports are already present AND `beta.pdf`/`binom.pmf` are NOT: verification-only path; proceed to task 8.3
- [ ] If `beta.pdf`/`binom.pmf` are present OR no Bayesian code exists: full migration path required

### 8.2 Full migration (conditional)

- [ ] `uv add pymc arviz --group analysis` (or equivalent dependency group)
- [ ] Create `tests/test_stats_best.py`:
  - [ ] `test_best_two_group_kruschke_reference` — run BEST on a Kruschke 2013 reference dataset; assert `diff_mu` posterior mean within ±0.02 of published value
  - [ ] `test_best_effect_size_computed` — verify `effect_size` Deterministic is computed correctly
  - [ ] `test_best_nu_exponential_prior` — verify nu prior is Exponential(1/30) + 1 per Kruschke
- [ ] Create or rewrite `stats.py` with `best_two_group(y1, y2, samples, tune)` function per spec §3.7 sketch
- [ ] If an existing beta-binomial function is replaced, add a deprecation warning or a clean removal + callers updated

### 8.3 Commit item 7

- [ ] Lint + format + pyright
- [ ] `git add stats.py tests/test_stats_best.py pyproject.toml uv.lock`
- [ ] `git commit -m "feat(lrr-phase-1): item 7 stats.py BEST verification [+ optional PyMC 5 migration]"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[7].status: completed`

---

## 9. Item 6 — OSF project creation procedure

Executed NINTH. Pure documentation; ships near the end so it can reference the finalized `condition.yaml::pre_registration` field naming.

### 9.1 Write the procedure doc

- [ ] Create `research/protocols/osf-project-creation.md`:
  - [ ] Title + purpose
  - [ ] Prerequisites (OSF account, operator has login)
  - [ ] Step 1: create project via OSF UI or CLI
  - [ ] Step 2: generate pre-registration template URL (do NOT file the pre-reg; defer to Phase 4 / UP-6)
  - [ ] Step 3: link the generated URL into `condition.yaml::pre_registration.url` via `research-registry.py file-prereg` (but set `filed: false` because it's only the draft URL at this point)
  - [ ] Step 4: at Phase 4 / UP-6 open time, re-run `file-prereg` with `filed: true` to commit
  - [ ] Troubleshooting section: common OSF UI pitfalls
  - [ ] Screenshots optional (operator may add)

### 9.2 Commit item 6

- [ ] `git add research/protocols/osf-project-creation.md`
- [ ] `git commit -m "docs(lrr-phase-1): item 6 OSF project creation procedure"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[6].status: completed`

---

## 10. Item 10 — Fix adjacent Qdrant schema drift

Executed TENTH. Five sub-items (a–e); sub-item b (operator-patterns re-schedule vs retire) may require operator input.

### 10.1 Sub-item a — Add `hapax-apperceptions` + `operator-patterns` to `EXPECTED_COLLECTIONS`

- [ ] Edit `shared/qdrant_schema.py::EXPECTED_COLLECTIONS`:
  - [ ] Add `"hapax-apperceptions"` with expected vector size + distance
  - [ ] Add `"operator-patterns"` with expected vector size + distance
- [ ] Extend `tests/shared/test_qdrant_schema.py` (if it exists) to assert both are validated

### 10.2 Sub-item b — `operator-patterns` writer investigation + decision

- [ ] Grep for the `operator-patterns` writer: `grep -rn "operator-patterns\|operator_patterns" --include="*.py" agents/ shared/`
- [ ] Identify the writer agent (may be `agents/operator_pattern_learner.py` or similar)
- [ ] Check if it has a systemd timer: `systemctl --user list-timers | grep operator-pattern`
- [ ] Decision:
  - [ ] **Re-schedule**: re-enable the timer; verify points appear within 24h via `c.count("operator-patterns").count`
  - [ ] **Retire**: remove the collection from `EXPECTED_COLLECTIONS`, document retirement in `research/protocols/qdrant-retired-collections.md`, remove the writer agent systemd unit if present
- [ ] If operator input required, surface via relay inflection and block Phase 1 close on this decision

### 10.3 Sub-item c — CLAUDE.md Qdrant count update

- [ ] Edit council `CLAUDE.md` (the one at the repo root, not the workspace one) in the Qdrant section
- [ ] Change Qdrant collections count from 9 to 10 (adds `stream-reactions`)
- [ ] Add `stream-reactions` to the list of collections
- [ ] Note: CLAUDE.md rotation policy may apply; keep the change minimal

### 10.4 Sub-item d — `axiom-precedents` sparse state documentation

- [ ] In the condition registry, add a note to `cond-phase-a-baseline-qwen-001/condition.yaml::notes`: "axiom-precedents collection has only 17 points as of 2026-04-14; this is expected (axioms are rare), not a drift indicator. Q024 #85 / Q026 Phase 4 Finding 4."
- [ ] Alternatively: create `research/protocols/qdrant-collection-notes.md` with per-collection observations

### 10.5 Sub-item e — `profiles/*.yaml` vs Qdrant authority

- [ ] Decision (default: filesystem authoritative)
- [ ] Create `research/protocols/profile-source-authority.md` documenting:
  - [ ] Authority: filesystem (profiles/*.yaml) is the canonical source
  - [ ] Derivation: Qdrant `profile-facts` is rebuilt from filesystem on demand
  - [ ] Reconciliation: a periodic sync agent reads YAMLs and upserts to Qdrant; deletions in YAML trigger point deletion in Qdrant
- [ ] Operator can override the default at open time

### 10.6 Commit item 10

- [ ] Lint + format + pyright
- [ ] `git add shared/qdrant_schema.py tests/shared/test_qdrant_schema.py research/protocols/profile-source-authority.md research/protocols/qdrant-collection-notes.md CLAUDE.md`
- [ ] `git commit -m "feat(lrr-phase-1): item 10 Qdrant schema drift fixes (a-e)"`
- [ ] Update `lrr-state.yaml::phase_statuses[1].deliverables[10].status: completed`

---

## 11. Phase 1 close

All 10 items complete. Final steps:

### 11.1 Smoke tests (matching spec §5 exit criteria)

- [ ] **Condition + marker present:** `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/condition.yaml` exists; `/dev/shm/hapax-compositor/research-marker.json` exists with that condition_id
- [ ] **Director loop tags reactions:** trigger a stream reaction, tail the reactor JSONL log, verify condition_id is present
- [ ] **Backfill verified:** `count(stream-reactions where condition_id = 'cond-phase-a-baseline-qwen-001')` ≈ 2178
- [ ] **Frozen-files hook blocks:** stage an edit to `agents/hapax_daimonion/grounding_ledger.py`, run `git commit -m "test"`, verify exit 2 + error message
- [ ] **Frozen-files `--probe` mode:** `scripts/check-frozen-files.py --probe agents/hapax_daimonion/grounding_ledger.py` returns exit 2
- [ ] **BEST verification:** `grep -rn "beta.pdf\|binom.pmf" --include="*.py"` finds nothing in the analysis codepath
- [ ] **CLI operational:** `uv run python scripts/research-registry.py current` prints `cond-phase-a-baseline-qwen-001`
- [ ] **Langfuse metadata:** emit a test score via the director loop, check Langfuse dashboard, verify `condition_id` is in the metadata
- [ ] **Qdrant schema fixes:** `hapax-apperceptions` + `operator-patterns` present in `EXPECTED_COLLECTIONS`; schema test passes
- [ ] **HSEA Phase 0 pre-open dry-run:** simulate HSEA Phase 0 0.4 `_frozen_files_check` wrapper calling `scripts/check-frozen-files.py --probe <test path>`; verify it works end-to-end

### 11.2 Handoff doc

- [ ] Write `docs/superpowers/handoff/2026-04-15-lrr-phase-1-complete.md`:
  - [ ] Summary of what shipped (10 items)
  - [ ] Links to PRs/commits for each item
  - [ ] Verification evidence for each exit criterion
  - [ ] Known issues / deferred items (e.g., if operator hasn't answered `operator-patterns` writer decision)
  - [ ] Next phase (LRR Phase 2 — Archive instrument / UP-3) preconditions
  - [ ] Downstream unblocking: HSEA Phase 0 (UP-2) can now open

### 11.3 State file close-out

- [ ] Edit `~/.cache/hapax/relay/lrr-state.yaml`:
  - [ ] `phase_statuses[1].status: closed`
  - [ ] `phase_statuses[1].closed_at: <now>`
  - [ ] `phase_statuses[1].handoff_path: docs/superpowers/handoff/2026-04-15-lrr-phase-1-complete.md`
  - [ ] `phase_statuses[1].deliverables[*].status: completed` (all 10)
  - [ ] `last_completed_phase: 1`
  - [ ] `last_completed_at: <now>`
  - [ ] `overall_health: green`
- [ ] Request operator update to `~/.cache/hapax/relay/research-stream-state.yaml::unified_sequence[UP-1]`:
  - [ ] `status: closed`
  - [ ] `owner: null`
  - [ ] (Per Q8 ratification, the shared index is operator-only-edits-after-initial; this edit goes through a governance-queue request if Phase 0 0.2 has landed, or via direct operator edit)

### 11.4 Final verification

- [ ] `git log --oneline` shows one `feat(lrr-phase-1): …` commit per item (10 commits minimum)
- [ ] All 10 exit criteria pass
- [ ] Fresh shell shows `LRR: Phase 1 · status=closed` in session-context advisory
- [ ] Inflection written to peer sessions announcing Phase 1 closure + HSEA Phase 0 + LRR Phase 2 unblock

---

## 12. Cross-epic coordination (canonical references)

This plan defers to drop #62 §3 (ownership) + §5 (unified sequence) for all cross-epic questions. Specifically:

- **LRR Phase 1 owns ALL five primitive families** (drop #62 §3 rows 1–6); HSEA reads them all. HSEA writes none of them.
- **HSEA Phase 0 (UP-2) blocks on LRR Phase 1 closed** (drop #62 §3 row 1). HSEA Phase 0 session-onboarding MUST verify.
- **`--probe` mode** is a Phase 1 item 4 scope addition per drop #62 §3 row 1 + HSEA Phase 0 0.4 dependency.
- **Axiom precedent `sp-hsea-mg-001`** is NOT Phase 1 work; it's HSEA Phase 0 deliverable 0.5, bundled into LRR Phase 6's joint `hapax-constitution` PR per drop #62 §3 row 11 + Q5 ratification.
- **`stats.py` PyMC 5 BEST port (item 7)** is the authoritative implementation site; HSEA Phase 4 I1 drafter is narration-only per drop #62 §3 row 6 + Q3 ratification.
- **Per-condition Prometheus slicing** is LRR Phase 10 / UP-13 work, not Phase 1. Phase 1 only tags via `condition_id` metadata.
- **5b 70B substrate path** is structurally unreachable per operator 2026-04-15T06:20Z direction ("hardware env unlikely to change within the year") — see drop #62 §13. No Phase 1 impact (Phase 1 is substrate-independent), but the narrowing of Phase 6's 70B reactivation guard rule is downstream.

---

## 13. End

This is the standalone per-phase plan for LRR Phase 1. It is pre-staging — the plan is not executed until the phase opens per the preconditions in §0. The companion spec lives at `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md`.

**LRR execution remains alpha's workstream.** Pre-staging authored by delta per the operator directive + "extract" instruction on 2026-04-15.

— delta, 2026-04-15
