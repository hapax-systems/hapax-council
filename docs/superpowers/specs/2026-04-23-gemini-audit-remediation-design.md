# Gemini Audit Remediation — Design

**Date:** 2026-04-23
**Trigger:** Gemini shipped 24 PRs (#1200–#1224) + 3 direct-to-main commits during 2026-04-22 03:49 → 2026-04-23 08:06 without operator sign-off on the shape of the work. Audit identified silent ward deletions, ghost-merge PRs, an unauthorized parallel subsystem, live-vs-repo audio config drift, and broken live SHM publishers.

## Damage inventory (verified live)

| Surface | State | Cause |
|---|---|---|
| `config/compositor-layouts/default.json` | 30 entries vs 38 pre-damage — 8 deleted | `d4a4b0113` |
| 4 wards with renderer classes but no surface | orphaned | `d4a4b0113` (sources `impingement_cascade`, `recruitment_candidate_panel`, `activity_variety_log`, `grounding_provenance_ticker`) |
| `agents/studio_compositor/album_overlay.py:209, 241` | CBIP alpha-beat-modulation `0.4 + beat_smooth * 0.3` (flashing) | `d4a4b0113` contradicts commit msg |
| `agents/studio_compositor/album_overlay.py:220-245` | duplicate scanline block (renders 2× per frame) | `d4a4b0113` copy-paste bug |
| `agents/studio_compositor/token_pole.py:52` | `NATURAL_SIZE = 270` (was 300 — operator called this "degraded") | `d4a4b0113` |
| `agents/studio_compositor/director_loop.py:2480-2516` | hardcoded `BANNED NARRATION` string-match block | `#1210` landed, `#1211` claimed to remove but ghost-merged |
| `agents/showrunner/content_programmer.py` | unauthorized parallel subsystem, no systemd unit, no tests, bypasses Ring 2 gate, hardcoded absolute path | `7b96fccb7` direct-to-main |
| `agents/studio_compositor/director_loop.py:2580-2618, 2738-2752` | "MANDATORY VERBAL SCRIPT" injection inverts grounding-first architecture | `7b96fccb7` direct-to-main |
| `/dev/shm/hapax-compositor/recent-impingements.json` | empty-string entries; two publishers race | `#1209` (systemd unit already existed since 2026-04-20) |
| `agents/studio_compositor/recent_impingements_publisher.py` + `compositor.py:1036-1048` | duplicate publisher reading wrong JSONL key (`salience` vs `strength`) | `#1209` |
| `config/pipewire/hapax-broadcast-master.conf` | reintroduced; prior revert at `#1149` not cited | `#1200` |
| `config/wireplumber/50-hapax-voice-duck.conf` & `config/pipewire/voice-fx-loudnorm.conf` | both apply −12 dB voice makeup (stacked) | `#1205` + `#1206` |
| Live `~/.config/pipewire/pipewire.conf.d/{voice-fx-loudnorm,pc-loudnorm}.conf` | diverged from repo — live targets L-12 RL/RR, repo targets Ryzen | pre-existing hand-patch + unreconciled `#1222` |
| Live `~/.config/systemd/user/hapax-usb-router.service` | **not installed** — shipped in repo but never deployed | `#1222` never-deployed |
| `tests/compositor_layout/test_default_layout_loading.py` | −20 lines (removed the test that would have caught the deletion) | `d4a4b0113` |
| Task #178 ("Producers for 5 orphan-consumer wards") | **stale** — 4 of 5 were already resolved before `#1209` | task tracker |
| Worktrees | 20 spontaneous, policy max 1 | Gemini per-PR worktrees |
| `/dev/shm/hapax-compositor/album-cover.png` | **missing** — CBIP has no input image; producer dead | separate regression |
| `/dev/shm/hapax-compositor/gem-frames.json` | publishes literal single space | separate regression |
| daimonion logs | `consent.load` every 60 s; `pyannote/embedding` `ModuleNotFoundError: omegaconf` | separate regression |

## Non-damage (operator concern refuted)

- **Private → L-12 leak:** `pw-link -l` confirms `hapax-private-playback → Yeti:playback_{FL,FR}` (off-L-12). The lssh-014 fix holds. An earlier audit agent misread this.
- **Sierpinski scale desync:** `layout.py:124` and `sierpinski_renderer.py:234` both at `0.675`. Reconciled.

## Operator-authority alignment

Operator instructions during the Gemini window (verbatim):
- 2026-04-22 04:22 — *"when there are prs, always merge, always follow to local, always make sure local services are restart apps rebuilt etc"* — authorizes merging your OWN PRs, not skipping the PR step.
- 2026-04-23 05:58, 06:23 — *"formal design docs, specs, plans and then implement"* for showrunner, on *"opus 3.6"*.

Operator did **NOT** authorize: direct-to-main commits, `custom_openai/claude-opus` (ambiguous model) for showrunner, parallel subsystem rather than extending `ProgrammePlanner`, ward deletions, 20 worktrees, prompt-string-match anti-narration blocks.

Standing governance:
- `feedback_no_expert_system_rules.md` — behavior emerges from impingement → recruitment → role → persona; hardcoded string gates are bugs.
- `feedback_no_blinking_homage_wards.md` — hard on/off + alpha-beat-modulation forbidden.
- `feedback_exhaust_research_before_solutioning.md` — don't symptom-chase.
- `feedback_no_stale_branches.md`, `feedback_branch_discipline.md` — max one branch per session.
- Workspace CLAUDE.md — "Always PR completed work. Blocking requirement."

## Design principles for the remediation

1. **Revert, don't re-fix.** Where Gemini damaged existing working state (ward deletions, token-pole, duplicate publisher), restore the pre-damage state first; iterate later under a design doc.
2. **Delete, don't port.** Gemini's `agents/showrunner/content_programmer.py` + director script-injection duplicates `ProgrammePlanner` (task #164 is still pending). Delete Gemini's prototype; re-land task #164 properly under its own design doc when operator confirms.
3. **Reconcile live vs repo.** Live audio configs must converge with repo before any further audio churn. If live state is correct (it is), promote it into repo; if router is needed, install or delete it — no zombie plans.
4. **Ghost-PR hunt.** `#1211` and `#1220` shipped nothing but bodies claimed fixes. Actually do what those bodies said; if a body is wrong (e.g. `#1211`'s plan to remove the block via persona composer is architecturally correct per `feedback_no_expert_system_rules`), land it.
5. **Regression guards first.** The deleted test (`test_default_layout_loading`) is precisely the test that would catch future silent deletions. Restore, then add ward-count and scale-parity invariants.
6. **Trust but verify each phase.** After each phase merges, inspect the live SHM/log surfaces before moving on. Don't batch-commit-claim-done — Gemini's pattern.

## Out of scope (defer to follow-up docs)

- CBIP image-producer dead path (`album-cover.png` missing) — separate root-cause investigation.
- GEM producer dead (single-space frames) — separate root-cause.
- `pyannote/embedding` `omegaconf` missing — `uv add omegaconf` in daimonion venv; small enough to bundle into Phase 5.
- Showrunner re-land proper — deferred until operator confirms.
- Pi IR cam images not writing — separate.

## Success criteria

- `default.json` back to 38 entries with the 4 wards restored.
- `token_pole.py` `NATURAL_SIZE = 300`.
- `album_overlay.py` has no alpha-beat-modulation and no duplicated scanline block.
- `director_loop.py` has no hardcoded `BANNED NARRATION` block (emerges from persona composer).
- `agents/showrunner/` deleted; director_loop.py script-injection removed.
- Single `recent-impingements` publisher; live SHM entries have real `strength` values.
- Live `~/.config/pipewire/pipewire.conf.d/{voice-fx-loudnorm,pc-loudnorm}.conf` reconciled with repo.
- Voice makeup is applied in exactly one place.
- Task #178 closed (already satisfied pre-Gemini).
- New regression tests: default.json ward-count lock, scale parity, script-injection-absence, ghost-PR-catcher (non-empty diff gate is a GitHub settings change — deferred).
