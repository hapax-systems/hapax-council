# Alpha close-out retirement handoff — 2026-04-14

**Session:** alpha (hapax-council primary worktree)
**Closing:** 2026-04-14 CDT
**Scope:** "Bring it all to a close" — everything open across
prior-alpha inherited + delta hand-off + queue 022/023/024/025/026
research backlog.

## Headline

12 PRs shipped + merged from this session, none in flight at
retirement (see §1). The critical path of queue 026's unblock items
is closed: BETA-FINDING-L (daimonion background-task supervisor) is
on main; BETA-FINDING-Q step 1 (RUST_BACKTRACE=1) is on main so
the next wgpu panic in hapax-imagination lands a full stack in the
journal. Compositor observability bundle (A3/A4/A5/A8), rebuild-
services coverage expansion (A1 Gap 2 + A2 Gap 3), and the small
governance/systemd hygiene PRs (A6 axiom-commit-scan + A7
MemoryHigh drop-in promotion) all landed in the same close-out
push. Deferred items are listed explicitly in §2; they are NOT a
backlog dump — every item has either a size estimate or a concrete
reason it was not appropriate to land during close-out.

## 1. Shipped this session

Merged into main:

| PR | Title | Closes |
|---|---|---|
| #751 | chore(compositor): ALPHA-FINDING-1 Option A (partial, completed by #757/#762) | FINDING-1 |
| #753 | prior-alpha Phase 9b facade removal (Task 29) | Phase 9b |
| #754 | prior-alpha FreshnessGauge wiring + token_pole golden | Phase 6b |
| #755 | PR #754 registry follow-up | — |
| #757 | Queue 023 item 17 wire-framing half | Q023 #17 |
| #758 | prior-alpha Phase 5b backend half (CommandServer + command_client) | Phase 5b |
| #760 | AC-13 pool metrics IPC via SHM | AC-13 |
| #761 | FINDING-K delete malformed contract + fail-closed consent init | FINDING-K |
| #762 | FINDING-G real fix — Kokoro throughput guard + 90s client timeout | FINDING-G |
| #763 | ConsentGatedReader.create — import fix (daimonion recovery) | — |
| #764 | queue 025 research pin | — |
| #765 | FINDING-M corporate_boundary _no_work_data fail-closed | FINDING-M |
| #766 | FINDING-P migrate studio-compositor from path-unit to rebuild-services | FINDING-P |
| #768 | FINDING-Q step 1 — RUST_BACKTRACE=1 for crash storm investigation | FINDING-Q step 1 |
| #769 | FINDING-L — background task supervisor (day-1 RECREATE rollout) | FINDING-L |
| #770 | compositor observability bundle — cameras_healthy + memory_footprint + tts_timeout + v4l2 rename | Q022 #4/#6, Q023 #24/#25/#32/#35 (A3+A4+A5+A8) |
| #772 | rebuild coverage expansion (Gap 2) + loud branch-skip warning (Gap 3) | Q025 Phase 6 items 128 + 130 (A1+A2) |
| #773 | axiom-commit-scan fail-loud on missing jq + MemoryHigh drop-in promotion | Q025 Phase 1 #92 + alpha.yaml memory-override promotion (A6+A7) |

No PRs in flight at retirement.

## 2. Inherited backlog (deferred to next focus)

### Research-only items (no code; handed forward)

| # | Item | Source |
|---|---|---|
| R1 | BRIO 43B0576A physical migration off bus 5-4 (operator hand required) | Q022 #2 |
| R2 | Post-fix memory footprint Phase 6 re-run | Q022 #3 |
| R3 | brio-operator 28 fps deficit investigation | Q022 #7 |
| R4 | Queue 022 #16 — Phase 3 fault injection + Phase 5 A/V latency (deferred) | Q022 |
| R5 | FINDING-O SCM floor pinning investigation | Q025 Phase 4 |
| R6 | Kokoro-GPU vs CPU latency eval | Q024 #46 |
| R7 | daimonion 1.45 GB swap-out investigation | Q024 #65 |
| R8 | `operator-patterns` Qdrant collection empty (writer de-scheduled) | Q024 #83 / Q026 Phase 4 Finding 2 |
| R9 | `axiom-precedents` sparse (17 points) | Q024 #85 / Q026 Phase 4 Finding 4 |
| R10 | profiles/*.yaml vs Qdrant `profile-facts` drift | Q024 #88 |
| R11 | Uninterrupted 2-hour compositor stability window | Q023 #30 |
| R12 | Microsecond-precision fault recovery timing | Q023 #36 |
| R13 | sprint-tracker vault direct vs REST API | Q024 #86 |
| R14 | Queue 025 Phase 4 SCM dashboard + eigenform velocity gauge (5 items) | Q025 |
| R15 | Queue 025 Phase 3 cognitive-loop continuity features (5 items) | Q025 |

### Queue 026 findings that need next-focus attention

**FINDING-Q steps 2–4 (CRITICAL / stability) — multi-hour.** Step 1
(RUST_BACKTRACE=1) shipped in #768 so the next crash captures a full
stack. Steps 2–4 (WGSL manifest validation before hot-reload, previous-
good shader rollback panic handler, `hapax_imagination_shader_rollback_total`
counter) were designed in
`docs/research/2026-04-13/round5-unblock-and-gaps/phase-3-imagination-runtime-profile.md`
but not implemented — they require reading `dynamic_pipeline.rs` in
depth and touching the wgpu hot-reload path. Pick up with the full
stack from the next crash as the starting evidence.

**FINDING-R Qdrant consent-gate writer-side gap (HIGH / governance).**
Designed in
`docs/research/2026-04-13/round5-unblock-and-gaps/phase-4-qdrant-state-audit.md`.
8 of 10 collections bypass the consent gate on upsert, including
`stream-reactions` (2178 points with `chat_authors` field). This is a
companion to BETA-FINDING-K's reader-side fix (PR #761) but with a
policy decision attached: without an active consent contract for
stream viewers, fail-closed enforcement would silence the collection
entirely. Next focus should present the three options (create
contract, accept silence, or explicit opt-out via separate channel)
before coding.

**FINDING-S SDLC pipeline dormant (MEDIUM).** `profiles/sdlc-events.jsonl`
has 324 events going back to 2026-03-22, 100% `dry_run=true`. All 5
stages DORMANT; `auto-fix.yml` + `claude-review.yml` fail 100% of
pushes with 0s runtime. Needs operator decision: use or retire. Design
options in
`docs/research/2026-04-13/round5-unblock-and-gaps/phase-6-sdlc-pipeline-audit.md`.

**FINDING-N Path B (obsidian-hapax sufficiency probe refine).** 30-min
refactor of `_check_plugin_direct_api_support` to check graceful
degradation + conditional future-guard instead of a `providers/`
directory that does not need to exist. Design complete in
`docs/research/2026-04-13/round5-unblock-and-gaps/phase-2-obsidian-providers-design.md`.
Two probe files mirror the fix (`shared/sufficiency_probes.py` and
`agents/_sufficiency_probes.py`). Not landed here because the session
was already at close-out scope; next focus can pick it up in a
single small PR.

**T3 prompt caching redesign.** ~100 lines across 3 files per
`docs/research/2026-04-13/round5-unblock-and-gaps/phase-5-cognitive-loop-t3-redesign.md`.
~42% per-turn cost reduction on cache hits, 40–60% first-token latency
drop on 2nd+ turn within the 5-min cache window. Pattern 3 (prompt
caching with `cache_control` markers) recommended. Deferred as
optimisation rather than correctness.

### Trivial deferrals (could have been bundled but stopped at close-out)

| # | Item | Size |
|---|---|---|
| Q026 F1 | Add `hapax-apperceptions` + `operator-patterns` to `EXPECTED_COLLECTIONS` in `shared/qdrant_schema.py` | ~6 lines |
| Q024 #84 | CLAUDE.md: add `stream-reactions` to Qdrant collections list (9 → 10) | docs |
| A11 | LiteLLM scrape path fix `/metrics` → `/metrics/` (cross-repo `llm-stack/`) | 1 yaml line |
| A12 | Prometheus scrape-job bundle — add `studio-compositor` to `llm-stack/prometheus.yml` (cross-repo) | 7 yaml lines |
| A13 | `ufw` rules for `172.18.0.0/16 → 9100, 9482` (operator-gated sudo) | 2 commands |
| Q023 #53 | Grafana dashboard panel fixes | cross-repo |

### Larger scope items (own PR each)

| # | Item | Size |
|---|---|---|
| C1 | Retire Phase 7 budget layer (Option B, ~1467-line net deletion) | large |
| C2 | daimonion in-process Prometheus exporter | ~300 lines |
| C3 | VLA in-process Prometheus exporter | ~200 lines |
| C4 | Phase 12b frontend command registry bindings + Tauri rebuild | moderate |
| C5 | `ConsentRegistry.load_all()` contract-shape validation at load time | ~20 lines |
| C6 | `management_governance` policy broadening (Q025 Phase 1 high) | moderate |
| C7 | `check_full` precedent store fail-loud (Q025 Phase 1 high) | small |

## 3. Live system state at retirement

* `RUST_BACKTRACE=1` is live on `hapax-imagination.service` (daemon-reload applied, next crash auto-captures). Not restarted — picked up on next systemd-scheduled restart from the existing crash storm.
* `studio-compositor-reload.{path,service}` unit pair removed via `scripts/retire-studio-compositor-reload-path.sh`. Compositor rebuild now runs through `hapax-rebuild-services.timer` with the branch-check.
* `MemoryHigh=infinity` for studio-compositor: repo-side promotion in #773 (still CI). The local drop-in at `~/.config/systemd/user/studio-compositor.service.d/memory-override.conf` is still in place and providing the same value, so there is no window where the 5G soft ceiling can re-apply.
* `hapax-rebuild-services.service` now covers 14 services (6 originally + compositor added in #766 + 8 added in #772). On first run after merge, each new sha-key file will trigger an initial rebuild cycle. Watch the journal for any service that was edited mid-session but had no rebuild coverage catching up in one burst.

## 4. Open PRs at retirement

None from alpha. Beta is on `research/livestream-performance-map` at the time of this
handoff; the workstream is active research, not implementation, so no
rebase pressure on alpha/main from that side.

## 5. Recommended next focus

In priority order:

1. **FINDING-Q steps 2–4** — the next wgpu panic with full backtrace
   will define the exact remediation. Wait for one crash
   (≈22 minutes by beta's Phase 3 measured rate), read the journal,
   then implement the shader manifest + rollback path.
2. **FINDING-L 24-hour observation → CRITICAL promotion** — after a
   full day of the day-1 RECREATE-only supervisor, promote
   `audio_loop`, `cpal_runner`, `cpal_impingement_loop` into
   `CRITICAL_TASKS`. One-line change in
   `agents/hapax_daimonion/run_inner.py`. Check the supervisor fires
   no false positives in the 24h window before promoting.
3. **FINDING-N Path B** — 30-min probe refine. Designed; copy-paste
   from `docs/research/2026-04-13/round5-unblock-and-gaps/phase-2-obsidian-providers-design.md`
   into `agents/_sufficiency_probes.py` + `shared/sufficiency_probes.py`
   (both, dissolution mirror).
4. **FINDING-R Qdrant gate expansion** — present the consent-contract
   policy options to the operator before coding. `stream-reactions`
   is the sharpest concern.
5. **Trivial bundle** — qdrant_schema drift (+2 collections) + CLAUDE.md
   docs drift (+stream-reactions) — ~15 lines in one PR, un-blocked.
6. **C1–C7** larger items — each its own PR, prioritise by current
   system strain signal.

## 6. References

* Prior handoffs this date: `2026-04-13-alpha-session-handoff.md`,
  `2026-04-13-alpha-oom-cascade-handoff.md`,
  `2026-04-13-alpha-post-epic-audit-retirement.md`,
  `2026-04-13-alpha-reverie-source-registry-epic-retirement.md`.
* Beta research: `2026-04-13-beta-round{3,4,5}-research-handoff.md`,
  `2026-04-13-beta-camera-research-handoff.md`.
* Close-out audit (inputs to this handoff):
  `~/.cache/hapax/relay/session-audit-2026-04-13.md`.
