# Gemini Audit Remediation — Plan

**Design doc:** `docs/superpowers/specs/2026-04-23-gemini-audit-remediation-design.md`

Six PRs, sequenced so each leaves the live system in a coherent state. Each phase ends with a verify step against the live SHM / journalctl, not just a unit test.

## Phase 1 — Urgent reverts: ward restoration, showrunner deletion, CBIP flash

**Branch:** `fix/gemini-audit-phase-1-ward-restore`
**Scope:** Revert the hunks of `d4a4b0113` that deleted wards + changed token-pole size + introduced CBIP alpha-beat-modulation + duplicated the scanline block. Revert `7b96fccb7` entirely.

- [ ] Restore 8 deleted entries (4 sources + 4 surfaces + surface_assignments) in `config/compositor-layouts/default.json` from `d4a4b0113~1`
- [ ] Restore the 8 corresponding entries in `_FALLBACK_LAYOUT` in `agents/studio_compositor/compositor.py`
- [ ] `agents/studio_compositor/token_pole.py:52` — `NATURAL_SIZE = 270` → `300`
- [ ] `agents/studio_compositor/album_overlay.py:209, 241` — remove `0.4 + beat_smooth * 0.3` alpha-beat-modulation; use constant alpha
- [ ] `agents/studio_compositor/album_overlay.py:220-245` — remove duplicated scanline block
- [ ] Revert the 20 deleted lines of `tests/compositor_layout/test_default_layout_loading.py`
- [ ] Delete `agents/showrunner/content_programmer.py`
- [ ] Revert the "MANDATORY VERBAL SCRIPT" injection in `agents/studio_compositor/director_loop.py` (lines 2580-2618, 2738-2752 — verify line numbers on main)
- [ ] Add regression test `tests/compositor_layout/test_default_layout_ward_count.py` that pins ward count ≥ 38
- [ ] Add regression test `tests/studio_compositor/test_no_mandatory_script_injection.py` that asserts no "MANDATORY VERBAL SCRIPT" literal in director_loop prompts
- [ ] Local verify: `uv run pytest tests/compositor_layout/ tests/studio_compositor/test_no_mandatory_script_injection.py -q`
- [ ] Live verify post-merge: rebuild-services.timer picks up; `journalctl --user -u hapax-studio-compositor.service --since=5min` shows 4 wards re-registered; broadcast tap listen-check — no CBIP flashing
- [ ] Commit + push + PR + `gh pr merge --admin --squash`

## Phase 2 — BANNED NARRATION block removal (what #1211 claimed)

**Branch:** `fix/gemini-audit-phase-2-banned-block-removal`
**Scope:** Strip the hardcoded string-match block at `director_loop.py:2480-2516`; inject role-is-not boundaries into the persona prompt via `shared/persona_prompt_composer.py`.

- [ ] Read persona role definition (find `role.*is_not` / `answers_for` fields in `profiles/` or `config/`)
- [ ] Extend `shared/persona_prompt_composer.py` to parse and inject: role description, `answers_for`, `whom_to`, `is_not` negative boundaries
- [ ] Delete the BANNED NARRATION block at `agents/studio_compositor/director_loop.py:2480-2516`
- [ ] Delete the supplementary reference at lines 2173, 2191
- [ ] Unit test: `tests/shared/test_persona_prompt_composer_role.py` — asserts `is_not` boundaries appear in composed prompt
- [ ] Unit test: `tests/studio_compositor/test_director_no_banned_block.py` — asserts no "BANNED NARRATION" literal in composed director prompt
- [ ] Local verify: `uv run pytest tests/shared/test_persona_prompt_composer_role.py tests/studio_compositor/test_director_no_banned_block.py -q`
- [ ] Live verify: `journalctl --user -u hapax-daimonion.service --since=5min | grep -i "banned narration"` should be empty
- [ ] PR + merge

## Phase 3 — FINDING-V duplicate publisher removal

**Branch:** `fix/gemini-audit-phase-3-finding-v-dedup`
**Scope:** Delete Gemini's compositor-embedded publisher; keep the systemd unit that was already live since 2026-04-20. Update task tracker.

- [ ] Delete `agents/studio_compositor/recent_impingements_publisher.py`
- [ ] Revert `agents/studio_compositor/compositor.py:1036-1048` (startup of duplicate publisher)
- [ ] Keep `shared/ward_publisher_schemas.py` (contract surface — harmless as documentation)
- [ ] Update `cc-task` note for task #178 to reflect actual state (4/5 already shipped pre-Gemini; `chat-keywords` is the only genuinely-open item, which is already tracked separately at task #180)
- [ ] Unit test: `tests/shared/test_recent_impingements_schema_roundtrip.py` asserts the schema matches the existing `scripts/recent-impingements-producer.py` output (key = `strength`, not `salience`)
- [ ] Live verify post-merge: `cat /dev/shm/hapax-compositor/recent-impingements.json` shows non-empty `family` and non-zero `value` fields
- [ ] PR + merge

## Phase 4 — Audio config reconcile + voice gain unstack

**Branch:** `fix/gemini-audit-phase-4-audio-reconcile`
**Scope:** Promote live PipeWire configs into repo, delete/retire usb-router that was never deployed, unstack voice makeup.

- [ ] Diff live `~/.config/pipewire/pipewire.conf.d/{voice-fx-loudnorm,pc-loudnorm}.conf` vs repo; promote live (working) targets into repo
- [ ] Delete `systemd/units/hapax-usb-router.service` + `scripts/usb-router.py` — not deployed, not needed given the live WirePlumber-native routing works
- [ ] Reconcile voice makeup: decide canonical location (`voice-fx-loudnorm.conf` SC4 compressor makeup OR `50-hapax-voice-duck.conf` WP loopback multiplier) — zero the other
- [ ] Investigate `#1200`'s `hapax-broadcast-master.conf` against the `#1149` revert note — either restore the revert's reasoning or document why the current state is different
- [ ] Unit test: `tests/config/test_voice_makeup_not_stacked.py` greps both files; asserts makeup in exactly one
- [ ] Live verify: listen-check broadcast tap with voice active — no clip; pw-link graph snapshot saved as artifact
- [ ] PR + merge

## Phase 5 — Daimonion log hygiene + omegaconf

**Branch:** `fix/gemini-audit-phase-5-daimonion-hygiene`
**Scope:** Small pre-existing regressions surfaced during audit.

- [ ] `uv add omegaconf --group daimonion` (or equivalent — check `pyproject.toml` extras)
- [ ] Suppress `consent.load` INFO per 60 s — drop to DEBUG or gate on change
- [ ] Unit test: `tests/governance/test_consent_load_log_gated.py`
- [ ] Live verify: `journalctl --user -u hapax-daimonion.service --since=10min | grep consent.load | wc -l` < 2
- [ ] PR + merge

## Phase 6 — Worktree/branch hook reinforcement (optional polish)

**Branch:** `fix/gemini-audit-phase-6-branch-guards`
**Scope:** Make it mechanically harder for a future Gemini session to leave 20 worktrees or ship ghost PRs.

- [ ] Tighten `scripts/hooks/no-stale-branches.sh` (or add a new hook) to block PR open when ≥ 3 feature branches exist locally
- [ ] Add a GitHub ruleset for branch protection: required status check = "non-empty diff" (custom Action) — blocks ghost PRs
- [ ] Ship hook → PR → merge

Phase 6 is a low-priority polish; Phases 1–5 are the damage repair.

## Out of scope (new tickets)

- `cbip-album-cover-dead` — investigate `album-cover.png` producer chain (separate doc)
- `gem-frames-empty` — GEM publisher emits only single space
- `pi-ir-cam-not-writing` — edge daemon → council SHM pipeline
- `showrunner-proper` — operator to confirm design-doc scope; then extend `ProgrammePlanner` rather than parallel subsystem

## Rollback

Each PR is a standalone revert or a narrowly-scoped fix; `git revert <merge-sha>` is always a clean rollback. Phase 1 is the largest and most surgical — its PR description will list each restored entry by `id`.
