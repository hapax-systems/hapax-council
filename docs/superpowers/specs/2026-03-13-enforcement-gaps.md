# Enforcement Gaps — Dog Star Audit Findings

**Date**: 2026-03-13
**Branch**: `feat/multi-role-composition`
**Derived from**: Dog Star research (5 parallel agents, ~400k tokens of analysis)
**Companion to**: `2026-03-13-dog-star-spec.md` (forbidden type sequences)

This document catalogs **implementation-level** findings: places where the
codebase fails to enforce constraints defined in the Dog Star spec or
architectural invariants from the North Star spec. These are bug reports
and technical debt, not domain constraints.

---

## Category 1: Governance Wiring Gaps

Things that are built and tested but not connected at runtime.

### G1.1 ExecutorRegistry.dispatch() ignores governance_result

`executor.py:127-154` — `dispatch()` never inspects
`command.governance_result.allowed`. A Command constructed with
`VetoResult(allowed=False)` executes successfully.

**Dog Star ref**: F2.1
**Fix class**: Runtime guard — add `if not command.governance_result.allowed: return False`

### G1.2 ResourceArbiter not instantiated

`arbiter.py` — fully implemented, `resource_config.py` — priority map defined,
`__main__.py` — neither instantiated nor called. MC and OBS governance chains
dispatch directly to ExecutorRegistry without contention resolution.

**Dog Star ref**: F2.5
**Fix class**: Wire into actuation loop between ScheduleQueue.drain() and dispatch()

### G1.3 wire_feedback_behaviors() never called

`feedback.py:18-48` — implemented and tested. Creates last_mc_fire,
mc_fire_count, last_obs_switch, last_tts_end Behaviors from actuation events.
Never called in `__main__.py`. OBS governance's `_mc_fired_recently()` reads
`last_mc_fire` which will be missing or sentinel.

**Dog Star ref**: F2.6
**Fix class**: Call in daemon init, merge returned dict into perception.behaviors

### G1.4 Hotkey and wake word bypass governance for session lifecycle

`__main__.py:655-682` (hotkeys), `__main__.py:632-653` (wake word) — both
call `session.open()` and `_start_pipeline()` without evaluating a VetoChain.
The perception loop's PipelineGovernor runs after the session is already open.

**Dog Star ref**: F2.7
**Fix class**: Construct Command, evaluate VetoChain before session.open()

### G1.5 Two parallel governance systems

PipelineGovernor (`governor.py`) operates on EnvironmentState with its own
VetoChain + FallbackChain. MC/OBS governance (`mc_governance.py`,
`obs_governance.py`) operates on FusedContext with their own VetoChain +
FallbackChain. These are independent systems sharing the same primitive types
but with no unified enforcement boundary.

**Dog Star ref**: Not a forbidden type — architectural debt
**Fix class**: Decision needed — unify or explicitly document as separate domains

---

## Category 2: Consent Enforcement Gaps

Infrastructure exists but is not wired into perception or session management.

### G2.1 SpeakerIdentifier has no consent check

`speaker_id.py:130-138` — `identify_audio()` extracts pyannote embeddings
from any audio. No call to `ConsentRegistry.contract_check()`.

`speaker_id.py:140-149` — `enroll()` saves embeddings to disk via `np.save()`.
No consent check before persistence.

**Dog Star ref**: F3.1, F3.2
**Fix class**: Check consent before processing non-operator audio

### G2.2 No ConsentRegistry instantiated at runtime

`shared/consent.py` — `ConsentRegistry` and `load_contracts()` exist.
`__main__.py` — no ConsentRegistry is created, no contracts loaded,
`axioms/contracts/` contains only `.gitkeep`.

**Dog Star ref**: F3.3
**Fix class**: Instantiate in daemon init, pass to backends that handle person data

### G2.3 Guest mode restricts tools but not perception

`session.py:39-40` — `is_guest_mode` property. `tools.py:229-232` —
`get_tool_schemas(guest_mode=True)` returns None. But `PerceptionEngine.tick()`
runs identically for operator and guest sessions — face detection, VAD, all
backends contribute the same signals.

**Dog Star ref**: F3.5
**Fix class**: Scope perception backends when guest detected, or ensure no
person-linked data persists from guest perception

### G2.4 Zero backends implement it-backend-001

Axiom implication `it-backend-001` (T1): "PerceptionBackends must verify
contract at ingestion boundary." All 7 backends update Behaviors without
any consent check. Most backends produce operator-only or environmental
signals (safe). WatchBackend and potential future face/speaker backends
are the concern.

**Dog Star ref**: F3.3
**Fix class**: Add consent check to backends that could ingest person-linked data

---

## Category 3: Type System Escape Hatches

Places where Python's runtime type erasure creates semantic gaps.

### G3.1 Behavior[T] generic parameter not enforced at runtime

`primitives.py:26-56` — `Behavior[float]` can hold any type. Python 3.12
generics provide no runtime enforcement. A backend could write a string
into a Behavior declared as `Behavior[float]`.

**Impact**: Governance predicates doing arithmetic on `.value` get TypeError
at the predicate call site, not at the Behavior update.

### G3.2 FusedContext.samples is an unschema'd dict

`governance.py:21-34` — `samples: dict[str, Stamped]` with no declared
key set. Mismatch between what governance expects and what with_latest_from
provides is discovered at runtime via KeyError.

**Impact**: Missing required Behavior in the behaviors dict causes KeyError
during governance evaluation, not at compose time.

### G3.3 Command.action is a bare string

`commands.py:27` — `action: str`, not an enum. `ExecutorRegistry.dispatch()`
does a dict lookup and silently returns False for unknown actions
(log.debug only). Typos produce silent inaction.

### G3.4 dict[str, Any] escape hatches

`Command.params` (`commands.py:28`), `ActuationEvent.params`
(`actuation_event.py:26`), `ResourceClaim.command` (`arbiter.py:27` — typed
as `object`), `FusedContext.trigger_value` (`governance.py:25` — typed as
`object`). These are places where the type system provides no schema
validation for structured data.

---

## Category 4: Concurrency Hazards

The daemon runs multiple async tasks sharing mutable state. Sync callbacks
from external threads (MIDI, Hyprland IPC) cross into async without
synchronization. One synchronization primitive exists: `asyncio.Event`
for wake word signaling. `MidiClockBackend` has an internal `threading.Lock`.

### G4.1 Behavior.update() not thread-safe

`primitives.py:51-56` — mutates `_value` and `_watermark` without atomicity.
Within the asyncio event loop, cooperative scheduling prevents races between
async tasks. But sync callbacks from MIDI or Hyprland threads can preempt.

**Practical risk**: Low in current code — MIDI backend's Lock protects its
own state, and Hyprland events are IPC-driven within the event loop. Risk
increases if future backends use threads.

### G4.2 ScheduleQueue enqueue/drain race

`executor.py:49-96` — `_items` list modified by `enqueue()` (bisect.insort)
and `drain()` (iterate + reassign). If MC governance fires from a sync
callback thread while `_actuation_loop` is draining, the list mutates during
iteration.

**Practical risk**: Low — MC governance fires from Event.emit() which runs
in the asyncio loop, not from the MIDI thread directly.

### G4.3 Event subscriber list mutation during emit

`primitives.py:88-94` — `emit()` iterates `_subscribers` directly. If a
callback triggers subscribe/unsubscribe on any Event, the list mutates
during iteration. Python list iteration handles appends but not removals
during iteration.

### G4.4 Session state torn reads

`session.py` — multiple fields (`state`, `_paused`, `session_id`, `speaker`)
read by 6+ async tasks, written by hotkey handlers and perception loop. No
atomic snapshot. Readers can observe partially-updated state.

### G4.5 Gemini session TOCTOU

`__main__.py:463-465` — `_gemini_session` None-checked then used across an
`await` point. Another task can set it to None between check and use.

---

## Category 5: Perception Boundary Gaps

### G5.1 Backend contribute() has unrestricted write access

`perception.py:62` — `contribute()` receives the full `behaviors` dict.
A backend can write to keys outside its declared `provides` set. The
`provides` declaration controls conflict detection at registration, not
write access at runtime.

### G5.2 Backends can inject new keys

`contribute()` receives a mutable dict. Backends can add new keys, not
just update existing Behaviors. No post-contribute validation checks for
unexpected keys.

### G5.3 Behavior.update() is public

Any code with a reference to `engine.behaviors` can update any Behavior
at any time. No ownership model. Monotonic watermark prevents regression
but not unauthorized writes.

---

## Category 6: Corporate Boundary Gaps

### G6.1 Gemini Live uses direct Google client

`gemini_live.py:44-64` — `google.genai.Client(api_key=api_key)`. Bypasses
LiteLLM entirely — no observability, no corporate routing, no Langfuse tracing.

**Dog Star ref**: F4.1

### G6.2 AsyncOpenAI base_url depends on environment variable

`workspace_analyzer.py:87-93`, `screen_analyzer.py:78-84` — defaults to
LiteLLM at `:4000` but can be overridden. Convention-only enforcement.

### G6.3 Ollama embedding fails hard

`shared/config.py:148-150` — `RuntimeError` on connection failure. Should
degrade gracefully per corporate_boundary axiom.

**Dog Star ref**: F4.2

---

## Summary

| Category | Count | Critical | Dog Star Refs |
|----------|-------|----------|---------------|
| Governance wiring | 5 | G1.1, G1.2, G1.3, G1.4 | F2.1, F2.5, F2.6, F2.7 |
| Consent enforcement | 4 | G2.1, G2.2 | F3.1–F3.3, F3.5 |
| Type escape hatches | 4 | — | — |
| Concurrency | 5 | — | — |
| Perception boundary | 3 | — | — |
| Corporate boundary | 3 | G6.1 | F4.1, F4.2 |

**Immediate action items** (from user):
1. Wire consent boundary for speaker_id (G2.1, G2.2)
2. Wire ResourceArbiter into actuation loop (G1.2)
3. Wire wire_feedback_behaviors (G1.3)
4. Decide PipelineGovernor vs VetoChain unification (G1.5)
