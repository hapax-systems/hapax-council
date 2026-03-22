# Governance Gap Implementation Status

**Created:** 2026-03-13
**Source:** governance-effectiveness-evaluation.md, governance-gap-deep-research.md

## Gaps 1-6: Wiring Tasks (DONE)

### Gap 1: drift_detector timer — twice daily ✅
- `~/.config/systemd/user/drift-detector.timer` → `OnCalendar=*-*-* 03,15:00:00`
- `hapax-council/agents/manifests/drift_detector.yaml` → `interval: 12h`, labels updated
- **Verify:** `systemctl --user daemon-reload && systemctl --user list-timers | grep drift`

### Gap 2: deliberation_eval filesystem event trigger ✅
- Created `~/.config/systemd/user/deliberation-eval.path` (watches profiles/deliberations)
- Created `~/.config/systemd/user/deliberation-eval.service` (runs agents.deliberation_eval)
- **Verify:** `systemctl --user enable deliberation-eval.path && systemctl --user start deliberation-eval.path`

### Gap 3: ConsentRegistry instantiation in voice daemon ✅
- Added to `VoiceDaemon.__init__()` before perception engine init
- Loads from `axioms/contracts/` (empty = conservative default, blocks non-operator biometric)
- **Verify:** Restart voice daemon, check journal for "Loaded N consent contracts"

### Gap 4: ExecutorRegistry dispatch governance guard ✅
- Added `governance_result.allowed` check at top of `dispatch()` in executor.py
- Logs blocked commands with denied_by and axiom_ids
- Added test cases: `test_governance_blocked_command_not_dispatched`, `test_governance_allowed_command_dispatched`
- **Verify:** `cd ~/projects/hapax-council && uv run python -m pytest tests/test_executor.py -v`

### Gap 5: Hotkey/wake word pre-governance evaluation ✅
- Added axiom_compliance veto check in `_wake_word_processor()` before session.open()
- Added same check in `_handle_hotkey()` for "toggle" and "open" branches
- Only blocks on `axiom_compliance` veto (management_governance), not soft vetoes
- **Verify:** Manual test — focus meeting window, say wake word, check journal

### Gap 6: ResourceArbiter + feedback behaviors wiring ✅
- Added `ResourceArbiter` init in `__init__()` after executor_registry
- Added `wire_feedback_behaviors()` call in `_setup_actuation()` after MC/OBS setup
- Replaced direct dispatch in `_actuation_loop()` with arbiter-mediated dispatch
- **Verify:** Restart voice daemon, check journal for "Feedback behaviors wired"

---

## Gaps 7-10: Implementation Tasks (TODO — research dependent)

### Gap 7: Sufficiency probe scope + CI gate
**Status:** NOT STARTED
**Prerequisite:** ImplicationScope dataclass already exists in axiom_registry.py (E-1 framework)
**Work needed:**
1. Add `scope` field to management-governance.yaml implications (type: enumerated/pattern, rule: description)
2. Update sufficiency probes to check coverage against scope rules
3. Add CI step in sdlc-axiom-gate.yml that validates capability-coverage.yaml completeness
**Estimated effort:** 1-2 days

### Gap 8: LLM output enforcement Phase 1
**Status:** NOT STARTED
**Prerequisite:** axiom_patterns.py + axiom_patterns.txt already scan for T0 violations in source code
**Work needed:**
1. Create `shared/axiom_pattern_checker.py` — output-focused regex patterns (different from source patterns)
2. Create `axioms/enforcement-patterns.yaml` — management_governance T0 output patterns
3. Create `shared/axiom_enforcer.py` — wraps agent output paths with pattern check
4. Wire into 2-3 high-risk agents (briefing_agent, profiler)
**Estimated effort:** 3-5 days

### Gap 9: Corporate boundary exceptions + fallback
**Status:** NOT STARTED
**Prerequisite:** axiom_enforcement.py has check_fast/check_full, no exception registry yet
**Work needed:**
1. Create `axioms/enforcement-exceptions.yaml` with Gemini Live carveout (operator-authorized, precedent-linked)
2. Add graceful degradation to `shared/config.py` embed functions (Ollama timeout → fallback)
3. Add shared LLM client helper with proxy health detection
4. Record precedent for Gemini Live exception via axiom_precedents.py
**Estimated effort:** 2-3 days

### Gap 10: Deontic consistency CI integration
**Status:** NOT STARTED
**Prerequisite:** sdlc/consistency_check.py fully implemented, runs standalone
**Work needed:**
1. Add consistency_check.py invocation to hapax-constitution CI workflow
2. Add precedent linkage for resolved contradictions
3. Run and verify output on current axiom state
**Estimated effort:** 1 day

---

## Verification Checklist (Post-Implementation)

- [ ] `systemctl --user list-timers` — drift-detector shows twice daily
- [ ] `systemctl --user status deliberation-eval.path` — active
- [ ] Voice daemon journal — "Loaded N consent contracts", "Feedback behaviors wired"
- [ ] `uv run python -m pytest tests/test_executor.py` — governance guard tests pass
- [ ] Re-run `scripts/call-graph-analysis.py` — verify no new violations
- [ ] Run all sufficiency probes — verify probe-meta-coverage-001 passes
