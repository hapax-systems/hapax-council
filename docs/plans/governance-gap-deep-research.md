# Governance Gap Deep Research

**Date:** 2026-03-13
**Method:** Static code analysis, telemetry inspection, systemd state, constitution spec review
**Scope:** hapax-constitution, hapax-council, distro-work

---

## Reading Guide

Each gap follows the same structure:

1. **Intention** — what the system was designed to accomplish
2. **Adequation** — what ideal fulfillment of that intention looks like
3. **Idiomatic Path** — the most elegant, system-native way to get there

---

## Gap 1: drift_detector — The Governance Detection Loop

### Intention

Drift detector is the system's primary reality-check agent. It compares live infrastructure state (from `introspect.generate_manifest()`) against documentation, axiom implications, and sufficiency probes — then produces a structured report of discrepancies. It's the only agent that performs retroactive axiom enforcement: scanning existing code for T0 pattern violations and running all sufficiency probes as part of its check suite.

Its `detect_drift()` function runs six deterministic scans (no LLM) plus an LLM-powered semantic comparison:
- `scan_axiom_violations()` — retroactive T0 pattern enforcement
- `scan_sufficiency_gaps()` — runs all 24 sufficiency probes, converts failures to drift items
- `check_doc_freshness()` — flags docs unchanged >30 days despite system changes
- `check_screen_context_drift()` — validates screen analyzer context file
- `check_project_memory()` — ensures all repos have `## Project Memory` in CLAUDE.md
- `check_document_registry()` — validates cross-repo documentation coordination
- LLM semantic pass — compares manifest vs. docs for goal-capability gaps

The manifest declares `schedule: { type: timer, interval: 6h }`. The actual systemd timer fires weekly (Sunday 03:00). The timer has never fired since the CachyOS migration (2026-03-11) because Sunday hasn't arrived yet. A manual run on 2026-03-12 produced a valid 100+ item drift report — the code is fully functional.

### Adequation

The ideal state is:

1. **Frequency matches the system's rate of change.** Weekly is too slow for a system with daily deploys and timer-driven agents. The manifest's 6h interval is closer to correct, but the real answer is: drift detection should run after every significant state change (deploy, config change, new capability) plus a daily sweep.

2. **Output feeds back into governance.** Currently drift reports go to a JSON file and optional operator notification. They should feed into the precedent store (sufficiency gaps as `insufficient` precedents) and the briefing agent (high-severity drift items as action items).

3. **Axiom scan results are authoritative.** When drift detector finds a T0 violation in existing code, this should be treated as a blocking finding — not just a drift report line item. Currently it's purely informational.

### Idiomatic Path

The system already has the pattern: watchdog script → systemd timer → agent CLI → structured output → notification. The fix is surgical:

**Timer frequency.** Change `drift-detector.timer` from `OnCalendar=Sun *-*-* 03:00:00` to `OnCalendar=*-*-* 03,15:00:00` (twice daily, 03:00 and 15:00). This balances detection latency against LLM cost (the semantic pass uses claude-sonnet). Update the manifest to match.

**Post-deploy trigger.** Add an `ExecStartPost` to deployment-affecting services (or a shared post-deploy hook) that touches a flag file. Add a `drift-detector-on-change.path` systemd path unit watching for that flag. This gives event-driven detection without polling.

**Output integration.** Drift detector already produces `DriftItem` objects with `severity`, `category`, `suggestion`. Add a post-run step in `drift-watchdog` that:
- Filters `axiom-sufficiency-gap` and `axiom-violation` items
- Records them as `insufficient` / `violation` precedents via `PrecedentStore.upsert()`
- Tags with `authority: derived` (lowest tier, operator can override)

This uses existing infrastructure (precedent store, watchdog pattern, notification chain) without new abstractions.

---

## Gap 2: deliberation_eval — The Meta-Cognitive Watchdog

### Intention

Deliberation eval exists to prevent governance theater. When the system runs multi-round deliberations between axiom-interpreting agents (Publius and Brutus), this agent evaluates whether the deliberation was genuine or performative.

It implements three hoop tests from process-tracing methodology:
1. **Position shift** — did at least one agent actually change their position?
2. **Argument tracing** — did agents engage with each other's specific claims?
3. **Counterfactual divergence** — were update conditions tested with at least one marked met?

A deliberation that fails all three hoop tests across multiple rounds is classified as pseudo-deliberation. If 3+ of the last 50 are pseudo, the agent escalates by recording an `edge_case` precedent in the axiom-precedents Qdrant collection.

The manifest declares `schedule: { type: event, trigger: new deliberation record }`. No event listener, systemd unit, or file watcher exists. The agent is a CLI tool only. It ran once manually, extracting metrics from 5 deliberation YAML files in a single batch. The escalation mechanism (precedent recording) has never fired.

### Adequation

The ideal state is:

1. **Automatic evaluation after every deliberation.** The system already writes deliberation results as YAML files to `profiles/deliberations/`. Evaluation should trigger on file creation, not require manual invocation.

2. **Escalation feeds operator review cycle.** Pseudo-deliberation precedents should surface in the daily briefing as governance items. The operator reviews and either promotes the precedent (confirming the deliberation process needs attention) or supersedes it (the hoop test was wrong in this case).

3. **Probe results are current.** The four deliberation probes (hoop test pass rate, activation rate, concession asymmetry, activation trend) should reflect recent data, not stale batch extractions.

### Idiomatic Path

The system already has the filesystem-as-bus pattern and systemd path units. The fix:

**File watcher.** Create `deliberation-eval.path`:
```ini
[Path]
PathChanged=/home/operator/projects/hapax-council/profiles/deliberations
Unit=deliberation-eval.service
```

And `deliberation-eval.service`:
```ini
[Service]
Type=oneshot
WorkingDirectory=/home/operator/projects/hapax-council
ExecStartPre=/home/operator/.local/bin/hapax-env-setup
ExecStart=/home/operator/.local/bin/uv run python -m agents.deliberation_eval
EnvironmentFile=-/run/user/1000/hapax.env
```

This is the filesystem-as-bus pattern the constitution already specifies: agents communicate through files, not direct invocation. The path unit watches for new deliberation YAML files and triggers evaluation.

**Deliberation runner integration.** `scripts/run_deliberations.py` (or whatever creates the YAML files) already writes to `profiles/deliberations/`. No change needed — the path unit picks up the new file automatically.

**Briefing integration.** The briefing agent already aggregates from health, drift, scout, activity, and digest. Add a `governance` section that reads `deliberation-eval.jsonl` for pseudo-deliberation counts and recent precedent store entries with `authority: agent` (pending operator review). This surfaces governance findings without new infrastructure.

---

## Gap 3: ConsentRegistry — Interpersonal Transparency Enforcement

### Intention

The interpersonal_transparency axiom (weight 88, hardcoded, constitutional) states: "No persistent state about non-operator persons without active, revocable consent contracts."

ConsentRegistry (`shared/consent.py`) is fully implemented:
- `ConsentContract` — frozen dataclass with parties, scope (frozenset of permitted data categories), direction, visibility mechanism, revocation status
- `contract_check(person_id, data_category)` — the enforcement boundary check
- `purge_subject(person_id)` — revokes all contracts, retains records for audit
- `load(contracts_dir)` — reads YAML from `axioms/contracts/`

SpeakerIdentifier (`hapax_voice/speaker_id.py`) already has consent-aware methods: `identify_audio()` and `enroll()` both accept an optional `consent_registry` parameter and will block biometric processing if no active contract exists. But ConsentRegistry is never instantiated in the voice daemon, and `axioms/contracts/` contains only `.gitkeep`.

Nine implications define the axiom's scope: T0 blocks on persistence without consent (it-consent-001, it-consent-002, it-revoke-001), T1 reviews on inspection mechanisms and scope enumeration, T2 advisories on transient environmental perception and audit trails.

### Adequation

The ideal state is:

1. **ConsentRegistry is instantiated at daemon startup** and passed to all perception-adjacent code paths. The registry loads from `axioms/contracts/` and is available for the lifetime of the daemon.

2. **Perception backends check consent before persisting.** Implication it-backend-001 (T1): "PerceptionBackends receiving non-operator data must verify active consent contract before updating Behaviors or persisting state." Currently zero backends implement this.

3. **Transient vs. persistent distinction is enforced.** It-environmental-001 (T2): transient perception (VAD, figure on camera) requires no contract if no persistent state is derived. But if the system infers patterns (habitual arrival times, voice frequency) from transient data, that's persistent state requiring consent (it-inference-001, T1).

4. **Revocation triggers purge.** When a contract is revoked, all subject-specific persistent state is purged. Contract records are retained for audit. The operator doesn't need to remember which data stores contain subject data — the system handles it.

### Idiomatic Path

The code is written. The gap is wiring, not implementation.

**Daemon init.** In `__main__.py`, after perception engine creation:
```python
from shared.consent import ConsentRegistry
consent_registry = ConsentRegistry()
consent_registry.load(Path("axioms/contracts"))
```

**Pass to SpeakerIdentifier.** SpeakerIdentifier already accepts the parameter — the call site just needs to provide it. If SpeakerIdentifier is used by a perception backend, the backend's constructor takes `consent_registry` and passes it through.

**Perception backend guard.** The system-idiomatic pattern is a VetoChain predicate. Add a `consent_veto` to the perception pipeline:
```python
Veto(
    name="consent_required",
    predicate=lambda ctx: consent_registry.contract_check(
        ctx.detected_person_id, ctx.data_category
    ) if ctx.detected_person_id != "operator" else True,
    axiom="interpersonal_transparency",
)
```

This follows the same VetoChain pattern used everywhere in the voice daemon. Deny-wins composition means a missing consent contract blocks persistence without affecting other perception.

**Contract YAML format.** The schema already exists in ConsentContract. A contract file looks like:
```yaml
id: consent-alice-2026
parties: [operator, alice]
scope: [presence, coarse_location]
direction: one_way
visibility_mechanism: on_request
created_at: "2026-03-13T00:00:00Z"
```

No new abstractions needed. The system has the right primitives — they just need to be connected.

---

## Gap 4: ExecutorRegistry.dispatch() — The Ignored Governance Result

### Intention

The voice daemon's governance architecture follows a principled pattern: governance chains produce `VetoResult(allowed, denied_by, axiom_ids)`, which is packaged into an immutable `Command` object's `governance_result` field. The Command flows through ScheduleQueue to ExecutorRegistry, which routes it to the correct executor.

The design intent is that `dispatch()` is the final enforcement checkpoint — if governance denied the action, dispatch refuses to execute it. This creates a clean separation: governance decides, dispatch enforces, executors act.

Currently (`executor.py:138`), `dispatch()` calls `executor.execute(command)` unconditionally. A Command with `VetoResult(allowed=False, denied_by=("speech_clear",))` executes anyway.

### Adequation

The ideal state is a single enforcement checkpoint at the dispatch boundary:

1. **dispatch() checks governance_result.allowed before executing.** If False, logs the denial with axiom_ids and denied_by, emits an `actuation_event` with `dispatched=False`, and returns False.

2. **No special cases.** Every Command flows through the same gate. No bypass for "urgent" actions, no override mechanism outside the governance chain itself.

3. **Telemetry on denials.** Denied dispatches should emit OTel spans with `governance.denied=True`, `governance.denied_by`, `governance.axiom_ids`. This makes governance enforcement visible in Langfuse traces.

### Idiomatic Path

This is a 4-line fix in `executor.py:dispatch()`:

```python
def dispatch(self, command: Command, schedule: Schedule | None = None) -> bool:
    if not command.governance_result.allowed:
        log.info(
            "Dispatch denied by governance: action=%s denied_by=%s axiom_ids=%s",
            command.action, command.governance_result.denied_by,
            command.governance_result.axiom_ids,
        )
        return False
    executor = self._action_map.get(command.action)
    # ... rest unchanged
```

This is the most elegant fix in the entire gap analysis. The governance architecture was designed correctly — the enforcement just wasn't wired at the terminal node. No new abstractions, no refactoring, no architectural decisions. The Command is already immutable (frozen dataclass), so there's no TOCTOU risk. The VetoResult is already populated by all three governance pipelines (PipelineGovernor, MC, OBS).

The only design question is whether to emit an ActuationEvent for denied dispatches (for observability) or only for executed ones. The idiomatic answer: emit it with a `denied=True` flag, because the actuation loop already logs dispatch results and the event_log captures both successes and denials.

---

## Gap 5: Hotkey/Wake Word Governance Bypass

### Intention

The PipelineGovernor evaluates EnvironmentState on every perception tick (~0.5s) and produces a directive: "process", "pause", or "withdraw". Its VetoChain includes an `axiom_compliance` predicate that matches management-sensitive window titles against T0 rules (feedback, coaching, performance review, 1-on-1 contexts).

But wake word and hotkey handlers open sessions immediately without evaluating the VetoChain. The governor's wake_word_active flag provides a 3-tick grace period where VetoChain evaluation is skipped entirely. By the time the next ungoverned perception tick fires, the session is already open and the pipeline is running.

The scenario: operator is in a 1-on-1 meeting (Zoom window focused). PipelineGovernor would correctly pause the daemon due to management_governance axiom compliance. But if the operator says the wake word or presses the hotkey, the session opens immediately, bypassing governance.

### Adequation

The ideal state:

1. **Governance evaluation before session open.** Wake word and hotkey handlers should evaluate the VetoChain against current EnvironmentState before opening a session.

2. **Operator override is preserved.** The wake word/hotkey is an explicit operator action. The system should not silently refuse — it should inform the operator why governance blocked the action (via notification or audio feedback) and let the operator explicitly override if needed.

3. **Grace period is governance-aware.** The current 3-tick grace period unconditionally overrides governance. A governance-aware grace period would allow the session but continue evaluating axiom compliance, pausing immediately if the compliance check fails.

### Idiomatic Path

The system already has the right primitives. The PipelineGovernor's `evaluate()` method and the VetoChain are callable at any point. The fix is:

**Pre-open evaluation in wake word handler:**
```python
async def _wake_word_processor(self) -> None:
    while self._running:
        await self._wake_word_signal.wait()
        self._wake_word_signal.clear()
        if self.session.is_active:
            continue

        # Evaluate governance before opening
        state = self.perception.tick()
        veto = self.governor._veto_chain.evaluate(state)
        if not veto.allowed and "axiom_compliance" in veto.denied_by:
            log.warning("Wake word blocked by axiom compliance: %s", veto.denied_by)
            self._acknowledge("denied")  # Audio feedback: governance blocked
            continue

        self._acknowledge("activation")
        self.governor.wake_word_active = True
        # ... rest unchanged
```

Same pattern for `_handle_hotkey()`.

**Design choice: block vs. warn.** The management_governance axiom is weight 85 (softcoded, domain-scoped). The operator's explicit activation (wake word/hotkey) carries implicit override authority. The system-idiomatic resolution: block and notify, with an immediate re-trigger acting as explicit override. If the operator says the wake word twice within 3 seconds after a governance denial, the second attempt opens the session with `governance_result.allowed=True, denied_by=("axiom_compliance_overridden",)`. This preserves operator sovereignty while ensuring the operator knows they're overriding governance.

This mirrors the precedent system's authority hierarchy: operator (1.0) > agent (0.7). An explicit double-activation is an operator-authority decision.

---

## Gap 6: Two Parallel Governance Systems

### Intention

The voice daemon has two independent governance domains:

**PipelineGovernor** (EnvironmentState → directive): Evaluates high-level environment context (activity mode, operator presence, axiom compliance, conversation state) and produces pipeline directives (process/pause/withdraw). Operates on ~0.5s perception ticks.

**MC/OBS Governance** (FusedContext → action): Evaluates beat-level music context (MC) and perception-level visual context (OBS) to select specific actions (vocal throws, scene switches). Operates on MIDI clock ticks (MC) or perception ticks (OBS). Uses its own VetoChain and FallbackChain with domain-specific predicates (speech clarity, energy levels, transport state, dwell time).

These are deliberately separate domains. PipelineGovernor manages session lifecycle; MC/OBS governance manages creative decisions within a session. The architectural question is whether they need a unified enforcement boundary.

### Adequation

The ideal state is **NOT unification** — it's **composition with a shared enforcement gate:**

1. **Domain separation is preserved.** PipelineGovernor and MC/OBS governance solve different problems at different timescales. Merging them would couple session lifecycle to beat-level music decisions. This violates the principle of minimal coupling.

2. **ExecutorRegistry is the shared gate.** All governance decisions flow to execution through `dispatch()`. With Gap 4 fixed (dispatch checks governance_result.allowed), the enforcement boundary exists at the right place — the terminal execution point.

3. **ResourceArbiter mediates contention.** When MC and OBS governance both want to act simultaneously, ResourceArbiter resolves based on priority configuration. This is already fully implemented — it just needs to be instantiated and wired into the actuation loop.

4. **Feedback loop closes.** `wire_feedback_behaviors()` creates Behaviors that let OBS governance react to MC governance's actions (face_cam_mc_bias uses `last_mc_fire`). This cross-domain awareness is feedback, not coupling.

### Idiomatic Path

The fix is wiring, not redesign:

**Instantiate ResourceArbiter in `__main__.py`:**
```python
from agents.hapax_voice.arbiter import ResourceArbiter
from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES

self.arbiter = ResourceArbiter(priorities=DEFAULT_PRIORITIES)
```

**Wire into actuation loop** (`_actuation_loop()`):
```python
for schedule in ready:
    resource = RESOURCE_MAP.get(schedule.command.action)
    if resource:
        claim = ResourceClaim(resource=resource, chain=schedule.command.trigger_source, ...)
        self.arbiter.claim(claim)

for winner in self.arbiter.drain_winners(now):
    self.executor_registry.dispatch(winner.command)
```

**Wire feedback behaviors** in `_setup_mc_actuation()`:
```python
feedback_behaviors = wire_feedback_behaviors(self.executor_registry.actuation_event)
self.perception.behaviors.update(feedback_behaviors)
```

Three wiring calls. No new abstractions. All implementation already exists and is tested.

---

## Gap 7: Sufficiency Probe Coverage — Mechanism vs. Adequacy

### Intention

The sufficiency probe system (24 probes across 5 groups) exists because prohibition enforcement (pattern matching against "must NOT") can't enforce positive obligations ("system MUST"). Probes verify that the system actively provides what axiom implications require.

The 24 probes break into three tiers:
- **Mechanism probes** (e.g., probe-alert-001): "Does the notification chain exist?"
- **Behavioral probes** (e.g., probe-runtime-001): "Did health-monitor.timer fire in the last 20 minutes?"
- **Meta probes** (probe-meta-coverage-001): "Do all registered capabilities have corresponding probes?"

The enforcement gap analysis identified the root problem: **mechanism probes pass while the obligation is unfulfilled.** Probe-alert-001 checks "does ntfy + notify.py exist?" and passes. But nothing checks "are all critical conditions actually generating alerts?" The alerting mechanism exists, but GPU temperature, backup failures, error rate spikes, and cost anomalies have no alert routes. The obligation ("critical alerts via external channels") is unmet despite the mechanism probe passing.

### Adequation

The ideal state:

1. **Sufficiency implications have enumerable scope.** Each obligation defines what it covers, either as an explicit list (`items: [gpu-temp, backup-success, error-rate]`) or a derivation rule (`rule: "every data source with a failure mode must have an alert route"`).

2. **Probes check coverage, not just mechanism.** A coverage-aware probe enumerates what should be covered (from the implication's scope), checks what is covered (from the actual system), and reports the gap.

3. **Capability-probe registry is enforced in CI.** When a new capability is added, CI requires a corresponding entry in `capability-coverage.yaml` with required probes listed. Missing probes block merge.

4. **Meta-probe is recursive.** The meta-probe (`probe-meta-coverage-001`) verifies that all capabilities have probes AND that all probes pass. If a new capability is added without probe coverage, the meta-probe fails, which drift_detector picks up, which surfaces in the briefing.

### Idiomatic Path

The building blocks exist. The `capability-coverage.yaml` registry already maps 6 capabilities to required probes. The meta-probe already checks this mapping. What's missing is the CI enforcement and the scope field on implications.

**Add scope to sufficiency implications.** In `hapax-constitution/axioms/implications/`:
```yaml
- id: ex-alert-001
  tier: T0
  text: "Critical alerts via external channels"
  mode: sufficiency
  scope:
    type: derived
    rule: "Every data source with a failure mode must have an alert route"
    current_coverage:
      - gpu-temperature (health_monitor → ntfy)
      - disk-usage (health_monitor → ntfy)
      - backup-success (backup-local.service → OnFailure → ntfy)
    known_gaps:
      - error-rate-spike
      - cost-anomaly
      - qdrant-latency
```

This doesn't require code changes — it's YAML documentation that makes the scope explicit. The meta-probe can read this and verify coverage.

**CI gate for capability-coverage.** Add a step to `sdlc-axiom-gate.yml` that checks whether changed files add new capabilities (Docker services, systemd units, new data sources) and whether `capability-coverage.yaml` was also updated. This is a diff-based check, not an LLM call.

**Lifecycle hook.** The missing steps 4-6 (register, add probes, verify) become:
1. Developer adds capability → PR includes capability-coverage.yaml entry
2. CI checks: does entry exist? do listed probes exist?
3. If probes don't exist yet, CI blocks with message: "New capability `X` requires probes `Y, Z`"
4. Developer adds probe stubs → CI passes → merge

This follows the existing SDLC axiom gate pattern. No new infrastructure.

---

## Gap 8: LLM Output Enforcement — The Behavioral Boundary

### Intention

The governance system prevents prohibited code patterns (hooks block `class Feedback_Generator`) and prohibited code changes (CI gate blocks T0 violations in PRs). But it doesn't enforce axioms on LLM-generated output at runtime.

A comprehensive runtime enforcement design exists (`2026-03-11-runtime-axiom-enforcement-design.md`, 101KB). It specifies:
- **Pattern checker** (`axiom_pattern_checker.py`) — sub-millisecond regex against output text
- **LLM judge** (`axiom_judge.py`) — semantic evaluation for T1 findings pattern matching can't catch
- **Application enforcer** (`axiom_enforcer.py`) — wraps agent output paths with tier-appropriate enforcement (retry on T0, warn on T1, log on T2+)
- **LiteLLM audit callback** (`axiom_litellm_callback.py`) — universal monitoring at the proxy layer
- **Quarantine** (`profiles/.quarantine/`) — blocked T0 outputs preserved for operator review

None of these modules exist. The design is complete but implementation hasn't started.

Currently, axiom context reaches agents via system prompt injection (`shared/operator.py:get_system_prompt_fragment()`), which embeds full axiom text. This is soft enforcement — the LLM is told about the axioms but nothing verifies it follows them.

### Adequation

The ideal state:

1. **Every agent output path has enforcement proportionate to risk.** Management-adjacent agents (briefing, profiler) need `full` enforcement (pattern + judge). Infrastructure agents (health_monitor, introspect) need `fast` enforcement (pattern only). Sync agents need none (they don't generate prose).

2. **LiteLLM callback provides universal audit trail.** Even when application-level enforcement isn't wired for a particular agent, the proxy-level callback catches and logs axiom violations. Divergence between application-enforced and proxy-audited calls triggers an alert.

3. **Quarantine preserves blocked output.** T0 violations don't silently vanish — they're saved to `.quarantine/` with metadata about which axiom was violated, enabling operator review and precedent creation.

### Idiomatic Path

The design spec is excellent and should be followed as-is. The implementation order should respect the system's incremental deployment pattern:

**Phase 1: Pattern checker + enforcer wrapper.** These are the minimum viable enforcement layer. The pattern checker extends `axiom_patterns.py` (already used by hooks) with output-focused patterns. The enforcer wraps `agent.run()` output — the same way langfuse_config wraps the tracing provider as a side-effect import.

**Phase 2: LiteLLM audit callback.** This requires modifying the Docker compose stack to mount the callback module and adding it to `litellm-config.yaml:success_callback`. It's operationally independent of Phase 1.

**Phase 3: LLM judge.** This is the most expensive component (requires an LLM call per enforcement check on the `full` path). It should be deployed after Phase 1 proves the pattern checker catches the majority of violations, so the judge only handles edge cases.

The key idiomatic principle: **enforcement wraps existing output paths, it doesn't create new ones.** Agents continue using `Agent.run()` and writing to files/Qdrant/notifications. The enforcer intercepts the output at the boundary between "agent produced text" and "text reaches its destination." This is the same boundary pattern as the VetoChain in the voice daemon — governance evaluates, then either allows or blocks at the gate.

---

## Gap 9: Corporate Boundary Enforcement

### Intention

The corporate_boundary axiom (weight 90, softcoded, domain: infrastructure) ensures work data stays in employer systems and home infrastructure remains personal. Key requirements: LLM calls route through LiteLLM proxy, localhost-dependent features degrade gracefully when unavailable, credentials never committed to git.

Three active violations exist:
1. **Gemini Live** (`gemini_live.py:44-64`) — direct Google API WebSocket, bypasses LiteLLM entirely
2. **AsyncOpenAI** (`workspace_analyzer.py:87-93`, `screen_analyzer.py:78-84`) — convention-only enforcement via environment variable, no fallback
3. **Ollama embedding** (`shared/config.py:148-150`) — RuntimeError on connection failure, no graceful degradation

### Adequation

The ideal state:

1. **All LLM calls observable.** Every call to an external LLM provider appears in Langfuse traces, regardless of transport (HTTP REST, WebSocket, local).

2. **Graceful degradation is the default.** When a localhost service (Ollama, Qdrant, LiteLLM) is unavailable, the system degrades to a less capable but functional state. No RuntimeError propagates to the user.

3. **Gemini Live has a documented carveout.** The axiom's enforcement-exceptions registry documents why Gemini Live can't route through LiteLLM (WebSocket transport, native audio streaming, latency requirements) and what compensating control exists.

### Idiomatic Path

**Gemini Live is a genuine architectural exception.** LiteLLM doesn't support WebSocket relay or native audio streaming. Forcing it through the proxy would require building a new transport adapter (estimated 3-week effort) and add ~500ms latency to a latency-sensitive audio path. The idiomatic resolution:

1. Create `axioms/enforcement-exceptions.yaml`:
```yaml
exceptions:
  - id: exc-cb-gemini-live
    axiom_id: corporate_boundary
    implication_id: cb-llm-001
    component: agents/hapax_voice/gemini_live.py
    reason: "Gemini Live requires native WebSocket audio streaming. LiteLLM has no WebSocket relay transport. Routing through proxy would add ~500ms latency to an audio path with 200ms budget."
    compensating_control: "LiteLLM audit callback (Layer 1) monitors API key usage. Gemini Live session metadata logged to Langfuse via OTel span."
    approved_by: operator
    approved_at: "2026-03-13"
    review_interval: "quarterly"
```

2. Record as operator-authority precedent in the precedent store.

**AsyncOpenAI fallback.** Add a shared helper in `shared/llm_client.py`:
```python
async def get_openai_client() -> AsyncOpenAI:
    base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000")
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            resp = await c.get(f"{base_url}/health")
            if resp.status_code == 200:
                return AsyncOpenAI(base_url=base_url, api_key=...)
    except Exception:
        pass
    # Fallback to direct provider
    return AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
```

This follows cb-llm-001: "LiteLLM restriction is auto-detected by probing the proxy health endpoint." The probe exists in the code, the fallback is explicit.

**Ollama graceful degradation.** Wrap the embed functions in `shared/config.py` with try/except that returns `None` instead of raising:
```python
def embed(text: str, ...) -> list[float] | None:
    try:
        ...
    except Exception as exc:
        _log.warning("Embedding unavailable: %s", exc)
        return None
```

Callers already need to handle the case where embedding fails (Qdrant unavailable, model not loaded). Making the failure explicit rather than exceptional follows cb-degrade-001.

---

## Gap 10: Deontic Consistency Checking

### Intention

The governance contract (`governance-contract.md`) specifies that axiom implications should be translatable to deontic logic: sufficiency implications become obligations (O(p)), compatibility implications become prohibitions (F(p)). A consistency checker should detect contradictions — cases where one implication requires what another forbids.

A known contradiction exists: executive_function requires "recurring tasks must be automated" while agent-architecture.md prohibits "agents never invoke each other." These contradict when a recurring task requires agent-to-agent triggering.

A `consistency_check.py` exists in hapax-constitution that loads implications, classifies them as obligations/prohibitions, extracts action phrases, and checks for contradictions using phrase overlap and specific contradiction patterns. It runs successfully but is not integrated into CI.

### Adequation

The ideal state:

1. **Consistency check runs on every constitutional change.** When axioms, implications, or architectural constraints change, the checker validates that no new contradictions are introduced.

2. **Known contradictions have precedent resolutions.** The bounded dispatch precedent (P-1) already resolves the automation-vs-invocation tension: "bounded, operator-approved, single-hop dispatch is permitted." Contradictions are expected — the system needs a way to resolve them, not prevent them.

3. **New contradictions surface as governance items.** Unresolved contradictions should appear in the briefing as items requiring operator adjudication.

### Idiomatic Path

**CI integration.** Add `consistency_check.py` as a step in the hapax-constitution CI pipeline. It already runs cleanly from the command line. The output is structured (list of Conflict objects with severity). CI fails on `error` severity (both T0), warns on `warning` severity (mixed tier).

**Precedent linkage.** When the consistency checker finds a known contradiction that has a precedent resolution, it should report it as `resolved` rather than `error`. Add a `resolutions` field to the contradiction output that references the precedent ID.

**Quarterly review cadence.** Add the consistency check to the quarterly review checklist (it already runs, just needs to be part of the formal governance review). This follows the existing weekly-review pattern but at longer cadence appropriate for constitutional-level changes.

---

## Synthesis: The Pattern Across All Gaps

Every gap in this analysis shares the same root cause: **the governance system was designed as a comprehensive framework but deployed incrementally, and the increment that connects designed components to runtime was never completed.**

The code is written. The tests pass. The architecture is sound. What's missing is wiring — `__init__` calls that instantiate registries, systemd units that trigger agents, dispatch checks that enforce governance results, CI steps that validate coverage.

This is not a design problem. It's a deployment problem. And deployment problems have a deployment-shaped solution: a focused wiring sprint that connects existing components without introducing new abstractions.

The priority order follows a dependency chain:
1. **ExecutorRegistry.dispatch() governance check** (Gap 4) — unlocks all voice daemon enforcement
2. **drift_detector timer fix** (Gap 1) — unlocks the governance detection loop
3. **deliberation_eval file watcher** (Gap 2) — unlocks meta-cognitive governance
4. **ConsentRegistry instantiation** (Gap 3) — unlocks interpersonal_transparency
5. **Feedback behaviors + ResourceArbiter wiring** (Gap 6) — unlocks cross-domain voice governance
6. **Hotkey/wake word governance evaluation** (Gap 5) — closes the session-open bypass
7. **Sufficiency probe scope + CI gate** (Gap 7) — unlocks obligation enforcement scaling
8. **LLM output enforcement Phase 1** (Gap 8) — unlocks behavioral boundary
9. **Corporate boundary exceptions + fallback** (Gap 9) — resolves active violations
10. **Deontic consistency CI** (Gap 10) — unlocks constitutional coherence checking

Gaps 1-6 are wiring tasks (days). Gaps 7-10 are implementation tasks (weeks). The system gets substantially more governed by completing just the first six.
