# LRR Phase 6 — Governance Finalization + Stream-Mode Axis (per-phase plan)

**Spec:** `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md`
**Author:** beta (pre-staged during Phase 4 bootstrap / Hermes 3.5bpw quant wait window)
**Branch (Phase 6 open):** `feat/lrr-phase-6-governance-finalization` (to be created at phase open)
**Estimated effort:** 6 PRs across 2–3 sessions
**Dependency:** Phase 5 complete (Hermes 3 live; §5–§7 articulation drills require coherent Hermes output)

> **Pre-staging note.** This plan document is committed to `beta-phase-4-bootstrap` alongside the Phase 6 spec. Implementation tasks below execute when Phase 6 opens, **not** during Phase 4 bootstrap. Do not tick task boxes during the wait window — they belong to the Phase 6 branch.

## Phase-6 PR map

| PR | Title | Scope | Depends on | Operator sign-off? |
|---|---|---|---|---|
| 1 | Groundwork | §2 stream-mode axis + CLI + endpoint, §10 fortress retirement, §11 ConsentRegistry validation, §12 design language amendment | Phase 5 merged | no |
| 2 | Backend redaction | §3 ConsentGatedWriter + Qdrant policies + mental-state safe-summary backfill, §4.A–G redaction decorator + integration tests | PR 1 | no |
| 3 | Frontend gating | §4.5 StreamAwarenessContext + RedactWhenLive, seven panel wraps, §12.3 typography migration | PR 1 + PR 2 | no |
| 4 | Closed loops | §5 stimmung auto-private watchdog, §6 presence-detect-without-contract block, §7 mid-stream revocation drill | PR 1 + PR 2 | no |
| 5 | Constitutional amendments | §1 `it-irreversible-broadcast.yaml`, §8 `su-privacy-001` clarification, §9 `corporate_boundary` clarification — submitted against `hapax-constitution` repo | none (parallel-able from day 1 of Phase 6) | yes — operator approves the text |
| 6 | Phase 6 close-out | Drill runs, exit criteria verification, handoff doc, Phase 7 open-readiness note | PRs 1–5 merged | no |

Six PRs, one branch in this repo plus one PR against `hapax-constitution`. PR 1 and PR 5 can open concurrently at phase start. PR 2 starts once PR 1 lands. PR 3 and PR 4 parallelize on top of PR 2.

---

## Stage 1 — PR #1 Groundwork

**Title:** `feat(lrr): Phase 6 PR #1 — stream-mode axis + fortress retirement + consent-registry validation + design language §12`

### Task 1.1 — Claim Phase 6

- [ ] Verify Phase 5 closed (Condition A' locked in registry, drill scripts pass)
- [ ] Create branch `feat/lrr-phase-6-governance-finalization` from `main` (after Phase 5 merge)
- [ ] Update `~/hapax-state/lrr-state.yaml` (or whatever state tracker): `current_phase: 6`, `current_phase_branch: feat/lrr-phase-6-governance-finalization`, `current_phase_opened_at: <timestamp>`, `current_phase_owner: beta`

### Task 1.2 — Confirm spec + plan committed

- [x] `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md` pre-staged on `beta-phase-4-bootstrap` (done by beta during Phase 4 wait window)
- [x] `docs/superpowers/plans/2026-04-15-lrr-phase-6-governance-finalization-plan.md` pre-staged on same branch (this file)
- [ ] After Phase 4+5 merge, rebase these docs onto `main`; they land with the Phase 6 branch

### Task 1.3 — §2 stream-mode axis: Python reader

- [ ] Create `shared/stream_mode.py` with `StreamMode` StrEnum, `get_stream_mode()`, `set_stream_mode()`, `is_off/private/public/public_research()`, `is_publicly_visible()`, `is_research_visible()`
- [ ] **Fail-closed default:** missing file or malformed content → `PUBLIC` (most-restrictive) and log a `stream_mode_read_failed` event via `shared.telemetry.hapax_event`
- [ ] Constants: `STREAM_MODE_FILE = Path.home() / ".cache" / "hapax" / "stream-mode"`; `DENY_PATH_PREFIXES`, `DENY_PATH_SUFFIXES` tuples
- [ ] Helper: `is_path_stream_safe(path: Path) -> bool` for §4.C filesystem visibility block
- [ ] Unit tests in `tests/test_stream_mode.py` — every branch: off, private, public, public_research, missing file, malformed file, `is_publicly_visible` truth table, deny-path matching, .envrc suffix matching

### Task 1.4 — §2 stream-mode axis: CLI

- [ ] Create `scripts/hapax-stream-mode` (executable, same language as `hapax-working-mode` — likely shell)
- [ ] Subcommands: no-arg = print current; `off`/`private`/`public`/`public_research` = set; `--force-keep-open <mode>` = set with override flag (persisted in a separate `~/.cache/hapax/stream-mode-override` file; auto-private watchdog honors it)
- [ ] Atomic write pattern (tmp+rename)
- [ ] Emit `hapax-stream-mode-changed` via `systemctl --user kill -s USR1 stimmung-watchdog.service` (or dbus signal — choose the mechanism consistent with the rest of the stack)
- [ ] Integration test: set mode via CLI, read via Python, assert matches

### Task 1.5 — §2 stream-mode axis: API endpoint

- [ ] Create `logos/api/routes/stream.py` with `GET /api/stream/mode` returning `{"mode": <str>}`
- [ ] Register router in `logos/api/app.py` alongside existing domain routers
- [ ] No authentication gate (single-operator axiom); no caching (read is cheap)
- [ ] Test `tests/logos_api/test_stream_route.py` — set mode via `shared.stream_mode.set_stream_mode()`, call endpoint, assert response

### Task 1.6 — §10 fortress enum retirement

- [ ] Pre-deletion grep: `grep -rn 'WorkingMode\.FORTRESS\|fortress.*WorkingMode\|is_fortress\|FORTRESS = ' shared/ agents/ logos/ hapax-logos/ scripts/ tests/` — capture every caller
- [ ] Assert no production callers exist (only the declaring files + their tests)
- [ ] Edit `shared/working_mode.py` — remove `FORTRESS = "fortress"` line and `is_fortress()` function
- [ ] Edit `agents/_working_mode.py` — remove same
- [ ] Edit `logos/api/routes/working_mode.py` — remove `fortress` from validator accepted values
- [ ] Edit `scripts/hapax-working-mode` — remove `fortress` from usage string and value validation
- [ ] Update workspace `CLAUDE.md` fortress reference (via dotfiles edit — `~/dotfiles/workspace-CLAUDE.md`) replacing fortress mention with pointer to `hapax-stream-mode`
- [ ] Delete test lines asserting `FORTRESS` is a legal enum value
- [ ] Verification: rerun the grep from the first sub-task → empty

### Task 1.7 — §11 ConsentRegistry.load_all() validation

- [ ] Edit `shared/consent.py::ConsentRegistry.load_all()` to validate each YAML file against the `ConsentContract` Pydantic model
- [ ] Define `ConsentContractLoadError(Exception)` with `file_path` and `pydantic_error` attributes
- [ ] Fail loud: raise `ConsentContractLoadError` with file path and Pydantic detail on any malformed contract
- [ ] Test `tests/test_consent_registry_load_validation.py` — drop a malformed YAML into a tmp dir, point `ConsentRegistry` at it, assert `ConsentContractLoadError` raised with expected file path

### Task 1.8 — §12 design language amendment

- [ ] Edit `docs/logos-design-language.md` — append new §12 per spec §3.12.2 content
- [ ] Section title: "12. Stream Mode Considerations"
- [ ] Sub-sections: 12.1 Broadcast-safe type scale, 12.2 Broadcast-safe color envelope, 12.3 Animation stability, 12.4 Enforcement
- [ ] Table of new size tiers (`stream-minimum` 12px, `stream-body` 14px, `stream-emphasis` 18px, `stream-display` 24px+)
- [ ] No code changes in this task — doc only. Site migration is Task 3.8 below.

### Task 1.9 — Ruff + pyright + tests green

- [ ] `uv run ruff check shared/ logos/ tests/`
- [ ] `uv run ruff format --check shared/ logos/ tests/`
- [ ] `uv run pyright shared/stream_mode.py shared/consent.py logos/api/routes/stream.py`
- [ ] `uv run pytest tests/test_stream_mode.py tests/test_consent_registry_load_validation.py tests/logos_api/test_stream_route.py -q` → all pass

### Task 1.10 — Commit + push + PR #1

- [ ] One commit per scope item where reasonable (stream-mode axis = 1; fortress retirement = 1; consent registry validation = 1; design language §12 = 1)
- [ ] `git push -u origin feat/lrr-phase-6-governance-finalization`
- [ ] `gh pr create --title 'feat(lrr): Phase 6 PR #1 — stream-mode axis + fortress retirement + consent validation + design language §12'` with body checklist referencing spec §2, §10, §11, §12
- [ ] Monitor CI to green; merge when ready

---

## Stage 2 — PR #2 Backend redaction

**Title:** `feat(lrr): Phase 6 PR #2 — ConsentGatedWriter + stream-mode-aware API redaction`

**Depends on:** PR #1 merged.

### Task 2.1 — §3 ConsentGatedWriter class

- [ ] Extend `shared/consent.py` with `ConsentGatedWriter` class mirroring `ConsentGatedReader`
- [ ] Constructor: takes `QdrantClient` and `dict[str, CollectionPolicy]`
- [ ] Define `CollectionPolicy` Pydantic model: `require_consent_label: bool`, `egress_target: str`, `broadcast_allowed: bool`
- [ ] `upsert()` method validates each point's `_consent` label before calling underlying client
- [ ] Custom exceptions: `ConsentWriteDenied`, `ConsentFlowDenied`
- [ ] Env var `ENFORCE_CONSENT_GATE_WRITER` (default `false`) — when `false`, failures log a warning and pass through; when `true`, failures raise
- [ ] Unit tests `tests/test_consent_gated_writer.py` — missing label rejected, bad flow rejected, env var off allows through, env var on raises

### Task 2.2 — §3 Collection policies

- [ ] Create `shared/qdrant_collection_policies.py` with `COLLECTION_POLICIES: dict[str, CollectionPolicy]` per spec §3.3 table
- [ ] Ten entries: profile-facts, documents, axiom-precedents, operator-episodes, studio-moments, operator-corrections, affordances, hapax-apperceptions, operator-patterns, stream-reactions
- [ ] Import into caller sites (below)
- [ ] Test `tests/test_qdrant_collection_policies.py` — every collection has a policy; no extras; policy shape correct

### Task 2.3 — §3 Caller audit + migration

- [ ] `grep -rn 'QdrantClient\(\)\|qdrant_client\.upsert\|client\.upsert' shared/ agents/ logos/` — enumerate every caller
- [ ] For each caller, replace raw `upsert()` with `ConsentGatedWriter.upsert()` initialized from `COLLECTION_POLICIES`
- [ ] Callers without a `_consent` label must either be updated to add one or explicitly opted out (document the opt-out in the commit message)
- [ ] Set `ENFORCE_CONSENT_GATE_WRITER=false` in systemd unit environment files during PR 2 — flip to `true` in PR 6 after drift shakeout

### Task 2.4 — §4.E Mental-state safe-summary backfill

- [ ] Create `scripts/backfill-mental-state-summary.py`
- [ ] Script connects to Qdrant, iterates five collections (`operator-episodes`, `operator-corrections`, `operator-patterns`, `profile-facts`, `hapax-apperceptions`)
- [ ] For each point missing `mental_state_safe_summary`, build a prompt to Gemini Flash with the sensitive field content, get the safe summary back, upsert with the new field populated
- [ ] `--dry-run` flag prints first 50 proposed summaries without writing — this is the human-spot-check gate
- [ ] `--confirm` flag required to actually write; without it, dry-run is default
- [ ] Cost estimate logged before run: tokens × points × price
- [ ] Test `tests/test_backfill_mental_state.py` — mock Gemini Flash, mock Qdrant, assert correct upserts

### Task 2.5 — §4 Redaction decorator

- [ ] Create `logos/api/deps/stream_redaction.py`
- [ ] Define `redact_for_stream_mode(response: dict, policy: RedactionPolicy) -> dict` helper
- [ ] Define `RedactionPolicy` Pydantic: `drop_fields: list[str]`, `band_fields: dict[str, list[str]]`, `forbid_fields: dict[str, str]` (field → PII regex), `wholesale_forbid: bool`
- [ ] Decorator `@stream_redacted(policy=...)` usable on FastAPI route handlers
- [ ] Apply to each endpoint per spec §3.4.A table: stimmung, profile (both top-level and dimension), orientation, briefing, management (wholesale), perception, nudges, chat-history (wholesale), governance
- [ ] Fail-closed: if `get_stream_mode()` raises, treat as publicly visible
- [ ] Unit tests `tests/logos_api/test_stream_redaction.py` — one parametrized test per row in spec §3.4.A table, per mode

### Task 2.6 — §4.B Voice transcript + impingement firewall

- [ ] Create `logos/api/deps/transcript_read_gate.py`
- [ ] Define `TranscriptRedacted` sentinel (empty list or empty string)
- [ ] `read_transcripts(path: Path, since: datetime) -> list[str] | TranscriptRedacted` — returns sentinel when `is_publicly_visible()` is true
- [ ] `read_impingements(path: Path) -> list[Impingement] | TranscriptRedacted` — same pattern
- [ ] Audit all callers of `~/.local/share/hapax-daimonion/events-*.jsonl` and `/dev/shm/hapax-dmn/impingements.jsonl` — force them through the gate
- [ ] Audit script: `tests/test_transcript_read_gate_ast_scanner.py` — walks the AST of `logos/`, `agents/hapax_daimonion/`, `agents/studio_compositor/` asserting no `open("events-*.jsonl")` or `open("impingements.jsonl")` calls outside the gate module
- [ ] Verification: `pw-link --output` check — no path from recording sinks to `mixer_master`

### Task 2.7 — §4.C Filesystem visibility block

- [ ] Implement `is_path_stream_safe()` in `shared/stream_mode.py` (already scaffolded in Task 1.3)
- [ ] Integration with Phase 8's terminal capture tile is deferred to Phase 8, but the helper ships now
- [ ] Test `tests/test_stream_mode_deny_paths.py` — exhaustive deny-list + safe-path coverage

### Task 2.8 — §4.F Gmail + Calendar redaction

- [ ] Create `logos/data/calendar_redaction.py` with `redact_calendar_events(events: list[Event]) -> list[Event]`
- [ ] Private events (category ≠ work) → summary "personal time", attendees empty, body blank
- [ ] Wire into `logos/data/briefing.py` and `logos/data/orientation.py` calendar consumers
- [ ] Qdrant `documents` reader — add `source != "gmail"` filter automatically when `is_publicly_visible()` is true AND `include_mail` kwarg is not explicitly `True`
- [ ] Tests

### Task 2.9 — §4.G Integration test matrix

- [ ] One parametrized integration test per sub-gate A–F
- [ ] Helper fixture `stream_mode(mode: str)` as context manager in `tests/conftest.py` (ONE shared fixture allowed — documented as exception to the "no shared conftest" rule because it is a context manager not a pytest fixture)
- [ ] CI workflow: these tests run on every PR touching `logos/api/`, `shared/stream_mode.py`, `shared/consent.py`, `logos/api/deps/`

### Task 2.10 — Ruff + pyright + tests green

- [ ] `uv run pytest tests/test_stream_mode.py tests/test_consent_gated_writer.py tests/test_qdrant_collection_policies.py tests/test_backfill_mental_state.py tests/logos_api/test_stream_redaction.py tests/test_transcript_read_gate_ast_scanner.py tests/test_stream_mode_deny_paths.py tests/test_calendar_redaction.py -q`
- [ ] Full redaction test matrix green
- [ ] Ruff + format + pyright clean on all touched files

### Task 2.11 — Commit + push + PR #2

- [ ] Multiple commits grouped by sub-gate
- [ ] PR body includes the full redaction table from spec §3.4.A with ✓ per row

---

## Stage 3 — PR #3 Frontend gating

**Title:** `feat(lrr): Phase 6 PR #3 — StreamAwarenessContext + RedactWhenLive + typography migration`

**Depends on:** PR #1 (for `/api/stream/mode`) and PR #2 (for backend redaction as the integration anchor).

### Task 3.1 — StreamAwarenessContext provider

- [ ] Create `hapax-logos/src/contexts/StreamAwarenessContext.tsx` per spec §3.4.5 shape
- [ ] Poll `/api/stream/mode` every 2 seconds via React Query (key: `["stream-mode"]`, staleTime: 1000, refetchInterval: 2000)
- [ ] Poll compositor state every 5 seconds for `recording_enabled` and `guest_present` (existing `proxy_compositor_live` IPC)
- [ ] Derived booleans: `publiclyVisible = mode in (public, public_research)`, `researchVisible = mode === public_research`
- [ ] **Fail-closed default:** on fetch error, default context value is `{mode: "public", publiclyVisible: true, researchVisible: false, recordingEnabled: false, guestPresent: false}`
- [ ] On mode transition detected, invalidate React Query cache for affected endpoints (`/api/stimmung`, `/api/profile`, `/api/orientation`, `/api/briefing`, `/api/management`, `/api/perception`, `/api/nudges`, `/api/chat/history`, `/api/governance/contracts`)
- [ ] Export `useStreamAwareness()` hook

### Task 3.2 — RedactWhenLive component

- [ ] Create `hapax-logos/src/components/shared/RedactWhenLive.tsx`
- [ ] Props: `children: React.ReactNode`, `fallback?: React.ReactNode`
- [ ] Renders `children` when `!useStreamAwareness().publiclyVisible`, else `fallback` (default: `<RedactedPlaceholder />`)
- [ ] Placeholder shows a tiny zinc-500 "[redacted — stream visible]" block at `stream-minimum` 12px

### Task 3.3 — Wrap provider at app root

- [ ] Edit `hapax-logos/src/App.tsx` (or the root layout component) — add `<StreamAwarenessProvider>` wrapping the entire tree inside `<CommandRegistryProvider>` (order: CommandRegistry outer, StreamAwareness inner, or vice versa — decide based on whether stream mode can influence command gating; §3.4.5 says yes, so StreamAwareness is OUTER)

### Task 3.4 — Wrap seven high-sensitivity panels

- [ ] `ProfilePanel` — full wrap
- [ ] `ManagementPanel` — full wrap
- [ ] `ChatProvider` rendering sites (investigate — may need to wrap `InvestigationOverlay` Chat tab specifically)
- [ ] `NudgeList` — full wrap
- [ ] `OrientationPanel` — PARTIAL wrap (wrap the P0 goal name + next_action subtree; leave domain names and sprint progress unwrapped)
- [ ] `OperatorVitals` — full wrap (biometric data even in banded form is sensitive)
- [ ] `DetectionOverlay` — PARTIAL wrap (wrap enrichment labels — emotion, posture, gesture; leave boxes unwrapped — they're already consent-gated via `consent_suppressed`)

### Task 3.5 — Wire compositor state to context

- [ ] Extend `hapax-logos/src-tauri/src/commands/studio.rs` or similar to emit a Tauri event on `recording_enabled` / `guest_present` change
- [ ] Listen in `StreamAwarenessProvider` and update context on event
- [ ] Alternative: stick with 5-second polling if event mechanism adds too much code

### Task 3.6 — Keyboard binding: operator override indicator

- [ ] New terrain badge shown in the horizon region when `publiclyVisible` is true — small "LIVE" pip using `bg-red-400` palette token (stream-safe envelope applies via Task 3.7)
- [ ] Registered as a command `overlay.live-indicator.show` in the command registry
- [ ] Visible regardless of depth (safety indicator)

### Task 3.7 — §12 Typography migration (11 sites)

For each site from spec §3.12.3 table, apply either action A (wrap in `<RedactWhenLive>`) or action B (raise size to 12px+):

- [ ] **A — wrap:** `ZoneCard` (zone counters), `ZoneOverlay` (labels), `OperatorVitals`, `VoiceOverlay`, `GroundNudgePills`
- [ ] **B — raise:** `SystemStatus` pip → 12px, `PresenceIndicator` → 12px, `SplitPane` label → 12px, `SignalCluster` → 12px, `EventRipple` → 12px, `ActivityPanel` → 12px
- [ ] **exempt:** `DetectionOverlay` hardcoded colors (diagnostic surface per §7.2)
- [ ] Verification: `grep -rn 'text-\[7px\]\|text-\[8px\]\|text-\[9px\]\|text-\[10px\]\|text-\[11px\]' hapax-logos/src/` — after migration, every match must either be inside a `RedactWhenLive` subtree (check AST) or inside a `.classification-inspector` scope

### Task 3.8 — §12.4 ESLint custom rule for stream-safe text

- [ ] Add `.eslintrc` custom rule `hapax-stream/text-minimum-12px`
- [ ] Matches `text-\[(?:\d+px)\]` classes; warns if number < 12
- [ ] Exempt if the file path matches `DetectionOverlay\.tsx` or `ClassificationInspector\.tsx`
- [ ] Exempt if the JSX is inside a `<RedactWhenLive>` ancestor (AST check — nontrivial; may need a helper function or just allow an inline `// eslint-disable-next-line hapax-stream/text-minimum-12px` comment)
- [ ] Fail `pnpm lint` if the rule fires without an exemption

### Task 3.9 — Type-check + lint + test

- [ ] `pnpm --filter hapax-logos tsc --noEmit`
- [ ] `pnpm --filter hapax-logos lint`
- [ ] `pnpm --filter hapax-logos test` (Vitest) — new tests for `StreamAwarenessContext`, `RedactWhenLive`, and each wrapped panel (assert the wrap renders fallback under publiclyVisible=true)

### Task 3.10 — Visual verification (golden path)

- [ ] `pnpm tauri dev` in beta worktree
- [ ] Set stream-mode to `public` via `hapax-stream-mode public`
- [ ] Visually confirm: ProfilePanel renders redaction placeholder, ManagementPanel same, NudgeList same, OrientationPanel shows domain names but not goal titles, OperatorVitals renders redaction placeholder, DetectionOverlay shows boxes without enrichment labels
- [ ] Set back to `off` — all panels restore
- [ ] LIVE pip appears in horizon when public, disappears when off

### Task 3.11 — Commit + push + PR #3

- [ ] Commits grouped by: context + provider (Task 3.1–3.3), panel wraps (Task 3.4), compositor wiring (Task 3.5), LIVE indicator (Task 3.6), typography migration (Task 3.7), ESLint rule (Task 3.8)
- [ ] PR body includes the visual verification checklist with screenshots (off + public side-by-side for each panel)

---

## Stage 4 — PR #4 Closed loops

**Title:** `feat(lrr): Phase 6 PR #4 — stimmung auto-private + presence T0 block + revocation drill`

**Depends on:** PR #1 (stream-mode axis) and PR #2 (backend redaction tests as integration anchor). Can parallelize with PR #3.

### Task 4.1 — §5 Stimmung auto-private watchdog

- [ ] Create `agents/stimmung_watchdog/__init__.py` + `agents/stimmung_watchdog/__main__.py`
- [ ] Inotify-watch `/dev/shm/hapax-stimmung/state.json` (fall back to 1-second polling if inotify unavailable in the runtime)
- [ ] State machine per spec §3.5: NOMINAL → AUTO_PRIVATE (3 critical ticks) → RE_ALLOW (5 nominal ticks)
- [ ] Tick interval: 10 seconds
- [ ] On AUTO_PRIVATE: call `shared.stream_mode.set_stream_mode(StreamMode.PRIVATE)`, send ntfy via `shared.notify.send_notification()`, append to `~/hapax-state/stimmung-autoprivate.jsonl`, write impingement to `/dev/shm/hapax-dmn/impingements.jsonl`
- [ ] Honor `~/.cache/hapax/stream-mode-override` — if present and recent (< 1 hour), skip auto-private and log
- [ ] Systemd user unit `systemd/user/stimmung-watchdog.service` (`Type=simple`, `Restart=on-failure`, `After=hapax-secrets.service`)

### Task 4.2 — §5 Tests

- [ ] `tests/test_stimmung_autoprivate.py` — inject synthetic critical stimmung for 3 ticks, assert mode transitions to private, assert impingement written
- [ ] Inject nominal for 5 ticks after auto-private, assert watchdog enters RE_ALLOW state
- [ ] Override test: set `stream-mode-override` recent; inject critical; assert NO auto-private
- [ ] Impingement format regression: assert the narrative text, dimensions shape, material, salience match the spec

### Task 4.3 — §6 Presence-detect-without-contract block

- [ ] Edit `agents/hapax_daimonion/presence_engine.py::_evaluate_presence()`
- [ ] Add check after existing presence computation:
  ```python
  if (
      presence_probability > PRESENCE_THRESHOLD
      and detected_person_ids
      and not all(has_active_contract(pid) for pid in detected_person_ids)
      and is_publicly_visible()
  ):
      trigger_auto_private(reason="presence_detect_without_contract")
      log_presence_autoprivate(detected_person_ids)
  ```
- [ ] Helper `trigger_auto_private(reason: str)` in `shared/stream_mode.py`: sets mode to private + writes reason to `~/hapax-state/presence-autoprivate.jsonl`
- [ ] Helper `has_active_contract(person_id: str) -> bool` in `shared/consent.py` using the existing `ConsentRegistry`

### Task 4.4 — §6 Prerequisite: person_id on presence detections

- [ ] Audit `presence_engine.py` for whether `detected_person_ids` is actually populated today (face embedding → identity match)
- [ ] If not populated, Phase 6 §6 becomes the more-conservative "any presence probability > threshold + no contracts at all" fallback — document this in the PR body and file a Phase 7 follow-up for per-person identity matching
- [ ] Tests reflect whichever path is taken

### Task 4.5 — §6 Tests

- [ ] `tests/test_presence_autoprivate.py` — mock `PresenceEngine` observation with novel person_id (or no person_ids fallback path), assert auto-private fires

### Task 4.6 — §7 Mid-stream revocation drill script

- [ ] Create `scripts/drill-consent-revocation.py`
- [ ] Stages a synthetic utterance by writing directly to the daimonion intent extractor input (mock, not via STT)
- [ ] Measures wall-clock at each cascade stage: utterance received, intent parsed, contract moved, registry invalidated, writer fail-closed, reader returns empty, auto-private decision, articulation impingement written
- [ ] Asserts total duration ≤ 5 seconds
- [ ] Reports pass/fail; exits non-zero on fail

### Task 4.7 — §7 inotify on contract directory

- [ ] Edit `shared/consent.py::ConsentRegistry` — add `_watch_contracts()` method using inotify (via `pyinotify` or `watchdog` library)
- [ ] On contract file add/remove/move: invalidate cache immediately (bypass the existing 60-second cache)
- [ ] Fall back to 60-second polling if inotify unavailable
- [ ] Test `tests/test_consent_registry_inotify.py` — touch a contract file, assert cache invalidated within 100ms

### Task 4.8 — Drill end-to-end smoke

- [ ] With PRs 1–3 merged and this PR's code in place, run `scripts/drill-consent-revocation.py` against a staging compositor (or a loopback compositor mock)
- [ ] Attach run output to PR body as verification

### Task 4.9 — Commit + push + PR #4

- [ ] Commits grouped: stimmung watchdog, presence T0 block, revocation drill script, inotify registry watch
- [ ] PR body includes drill-script run output

---

## Stage 5 — PR #5 (hapax-constitution) Constitutional amendments

**Title:** `feat(axioms): it-irreversible-broadcast + su-privacy-001 clarification + corporate_boundary scope`

**Repo:** `hapax-constitution` (separate from hapax-council). Can parallelize with PRs 1–4 from Phase 6 open.

### Task 5.1 — Clone + branch

- [ ] `cd ~/projects/hapax-constitution`
- [ ] Verify clean state
- [ ] Create branch `feat/lrr-phase-6-axioms`

### Task 5.2 — §1 `it-irreversible-broadcast.yaml`

- [ ] Create `axioms/implications/it-irreversible-broadcast.yaml` with the schema from spec §3.1
- [ ] Validate against existing implication schema (run whatever validator hapax-constitution has — likely a pydantic check in a script)
- [ ] If a broadcast consent contract template schema needs a new file (`axioms/contracts/_templates/broadcast-consent.yaml.template`), add it

### Task 5.3 — §8 `su-privacy-001` clarification

- [ ] Edit `axioms/implications/su-privacy-001.yaml` (or wherever the current text lives) per spec §3.8 new text
- [ ] Preserve the ID; change the rule text

### Task 5.4 — §9 `corporate_boundary` scope clarification

- [ ] Create `axioms/implications/cb-scope-001.yaml` per spec §3.9

### Task 5.5 — Update hapax-sdlc package if needed

- [ ] If `hapax-constitution` publishes via `hapax-sdlc`, bump version and regenerate
- [ ] Council's `hapax-sdlc` dep pin gets bumped in a follow-up council PR (not part of this hapax-constitution PR)

### Task 5.6 — Commit + push + PR #5

- [ ] Clear commit messages explaining the scope change rationale
- [ ] PR body explicitly asks operator to approve the rule text changes; include the old-vs-new diff for §8 and §9

### Task 5.7 — Operator sign-off wait

- [ ] This PR BLOCKS on operator review. It is the only item in Phase 6 with an unbounded wait time.
- [ ] While blocked, PR 1–4 proceed independently. PR 6 (close-out) cannot complete until PR 5 merges.

---

## Stage 6 — PR #6 Close-out

**Title:** `docs(lrr): Phase 6 close-out — exit criteria verified + handoff`

**Depends on:** PRs 1–5 merged.

### Task 6.1 — Run exit-criteria verification

- [ ] Run `scripts/phase-6-pre-check.py` (same script as the pre-check, but run now as a post-check — same table of conditions, now all true)
- [ ] Run `scripts/drill-consent-revocation.py` — assert pass
- [ ] Run the stimmung auto-private drill — inject synthetic critical, verify auto-private + articulation
- [ ] Run the presence-detect-without-contract drill
- [ ] Capture output of each as artifacts in `~/hapax-state/phase-6-close-out/YYYY-MM-DD/`

### Task 6.2 — Flip enforcement flags

- [ ] Edit systemd unit environment files to set `ENFORCE_CONSENT_GATE_WRITER=true`
- [ ] Restart affected services
- [ ] Verify writers now fail closed on missing `_consent` labels (deliberate test: attempt a bare upsert via a mock; assert it raises)

### Task 6.3 — Write Phase 6 handoff

- [ ] `docs/superpowers/handoff/{YYYY-MM-DD}-beta-phase-6-close-out.md`
- [ ] Sections: what Phase 6 closed, what's still open (if anything), Phase 7 open-readiness (persona spec can proceed), Phase 8 Logos studio view tile prerequisites now met, known follow-ups (e.g. per-person identity matching in presence_engine if §6 fell back)
- [ ] Include the drill-run artifact paths

### Task 6.4 — Tune auto-private hysteresis from early data

- [ ] If auto-private fired false-positively during pilot (inspect `stimmung-autoprivate.jsonl`), propose a tightening; defer implementation to Phase 10 polish
- [ ] If auto-private missed a real critical event (inspect stimmung history), propose loosening; defer implementation to Phase 10

### Task 6.5 — Update epic phase summary

- [ ] Edit `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §4 phase summary table — mark Phase 6 row status as complete
- [ ] Note the commit SHA and close-out date

### Task 6.6 — Commit + push + PR #6

- [ ] Docs-only commits
- [ ] Merge into main

---

## Stage 7 — Post-phase operator actions

Not tasks, but items the operator performs after Phase 6 merges:

- [ ] Review auto-private false-positive rate over 48 hours of normal operation. If > 2/day, propose tightening.
- [ ] File broadcast consent contracts for any person expected to appear on stream using the new template.
- [ ] Verify `hapax-stream-mode public_research` transition triggers the correct articulation under Hermes 3.

---

## Verification commands (recap)

Per the epic's P-8 (verification before completion), each task has at least one verification command. Consolidated list:

| Scope item | Verification command | Expected |
|---|---|---|
| §2 state file | `cat ~/.cache/hapax/stream-mode` | one of `off`/`private`/`public`/`public_research` |
| §2 Python reader | `python -c 'from shared.stream_mode import get_stream_mode; print(get_stream_mode())'` | same value |
| §2 API endpoint | `curl -sS localhost:8051/api/stream/mode` | `{"mode": "..."}` |
| §3 ConsentGatedWriter wired | `grep -rn 'client\.upsert(' agents/ logos/ shared/ \| grep -v 'ConsentGatedWriter'` | empty (all routed through gate) |
| §4.A redaction decorator | `curl -sS -H 'X-Test-Stream-Mode: public' localhost:8051/api/stimmung \| jq` | banded fields only |
| §4.B transcript firewall | `tests/test_transcript_read_gate_ast_scanner.py` | pass |
| §4.C deny paths | `python -c 'from shared.stream_mode import is_path_stream_safe; from pathlib import Path; assert not is_path_stream_safe(Path.home() / ".password-store" / "test")'` | no assertion error |
| §4.5 frontend wrap | visual verification at `pnpm tauri dev` with mode toggled | panels redact/restore |
| §5 watchdog | `systemctl --user is-active stimmung-watchdog.service` | active |
| §5 drill | `python scripts/drill-stimmung-autoprivate.py` | exits 0 |
| §6 presence block | `python scripts/drill-presence-autoprivate.py` | exits 0 |
| §7 revocation drill | `python scripts/drill-consent-revocation.py` | exits 0 with duration < 5s |
| §10 fortress retired | `grep -rn 'WorkingMode\.FORTRESS\|is_fortress' shared/ agents/ logos/ hapax-logos/ scripts/ tests/` | empty |
| §11 load_all validation | `tests/test_consent_registry_load_validation.py` | pass |
| §12 design doc | `grep -n '^## 12' docs/logos-design-language.md` | line found |
| §12 typography migration | `grep -rn 'text-\[[0-9]px\]\|text-\[1[01]px\]' hapax-logos/src/` minus exempted sites | empty |
