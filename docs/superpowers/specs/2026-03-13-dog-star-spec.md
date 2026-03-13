# Dog Star Spec — Forbidden Type Sequences

**Date**: 2026-03-13
**Branch**: `feat/multi-role-composition`
**Companion to**: `2026-03-13-domain-schema-north-star.md`

---

## Section 0: Purpose & Relationship to North Star

The North Star Spec defines the valid type sequences — what the system *must* support.
The Dog Star Spec defines the forbidden type sequences — what the system *must not*
permit, even though the type system makes them syntactically constructible.

Every entry in this document is a type expression that:
1. **Compiles** — the Python type checker accepts it
2. **Constructs** — the runtime does not reject it at instantiation
3. **Violates** — an axiom, an architectural invariant, or a safety property

The gap between (2) and (3) is the enforcement deficit. Each entry states the
current enforcement level:

| Level | Meaning | Failure Mode |
|-------|---------|--------------|
| **Type** | Constructor signature or generic constraint prevents construction | Cannot occur |
| **Runtime** | `__post_init__`, ValueError, or assertion catches at construction/call time | Fails loud |
| **Convention** | Only code review, documentation, or architectural commentary prevents it | Fails silent |
| **None** | No enforcement exists; the forbidden sequence executes successfully | **Active gap** |

Entries at **Convention** or **None** are the ones that bite.

---

## Section 1: Governance Bypass

These sequences circumvent the governance layer — actions execute without
the safety constraints that governance is supposed to enforce.

### D1.1 Denied Command Dispatches Successfully

**Axiom**: executive_function (weight 95)
**Invariant**: Governance denial must prevent actuation
**Enforcement**: **None** — active gap

```
Command(action="vocal_throw",
        governance_result=VetoResult(allowed=False, denied_by=("speech_clear",)))
  → ExecutorRegistry.dispatch(cmd)
  → Executor.execute(cmd)         # EXECUTES despite allowed=False
  → ActuationEvent emitted        # records a "successful" denied action
  → True returned
```

`ExecutorRegistry.dispatch()` (`executor.py:127-154`) never inspects
`command.governance_result.allowed`. The field is provenance metadata,
not an enforcement boundary. Any caller with access to the registry can
actuate a denied command.

**Why this is dangerous**: The composition pipeline in `mc_governance.py:233-234`
correctly short-circuits on denial. But nothing prevents a second code path —
a CompoundGoal, a hotkey handler, a future agent — from constructing a Command
with `allowed=False` and dispatching it directly. The governance layer is a
suggestion, not a gate.

### D1.2 Empty VetoChain Permits Everything

**Axiom**: executive_function (weight 95)
**Invariant**: Governance must degrade toward safety, not toward permissiveness
**Enforcement**: **Convention** — no runtime check

```
VetoChain()                       # zero vetoes
  → .evaluate(ctx)
  → VetoResult(allowed=True)      # vacuously true — nothing to deny
```

`VetoChain.__init__` (`governance.py:78-79`) accepts `None` or empty list.
The docstring says "adding a veto can only make the system more restrictive,
never less" — but an empty chain is the maximally permissive starting point.
If a composition step fails to add its vetoes (exception swallowed, config
missing), the chain silently permits everything.

### D1.3 Veto Removal Relaxes Governance

**Axiom**: executive_function (weight 95)
**Invariant**: Governance constraints are monotonically increasing
**Enforcement**: **Convention** — private attribute, no immutability

```
chain = VetoChain([speech_clear, energy_sufficient, transport_active])
chain._vetoes.pop(0)              # removes speech_clear
  → .evaluate(ctx)
  → VetoResult(allowed=True)      # speech during performance now allowed
```

`_vetoes` is a mutable `list` behind `__slots__`. There is no `remove()`
method, but the private list is directly accessible. Frozen dataclass pattern
(used by Command, Schedule, Stamped) was not applied to VetoChain.

### D1.4 Hotkey Handlers Bypass All Governance

**Axiom**: executive_function (weight 95)
**Invariant**: Session lifecycle should respect governance constraints
**Enforcement**: **None** — active gap

```
HotkeyServer receives "open"
  → _handle_hotkey("open")            # __main__.py:665-670
  → session.open(trigger="hotkey")    # no VetoChain evaluation
  → _start_pipeline()                 # voice session begins
  → Pipecat pipeline active           # TTS → audio_output
  # No Command constructed. No VetoChain. No FreshnessGuard.
```

Hotkey handlers (`__main__.py:655-682`) call `session.open()` and
`_start_pipeline()` directly. No Command/Schedule is constructed, no
VetoChain is evaluated. The perception loop's governor runs *after*
the session is already open — it can pause/withdraw but cannot prevent
the initial open. A hotkey can start audio output during a conversation
that governance would have blocked.

### D1.5 CompoundGoals Has Unrestricted Daemon Access

**Axiom**: executive_function (weight 95)
**Invariant**: Multi-step workflows should compose governance primitives
**Enforcement**: **Convention** — duck-typed `Any` daemon reference

```
goals = CompoundGoals(daemon)
  → goals._daemon.perception.tick()             # direct perception access
  → goals._daemon.schedule_queue.enqueue(s)     # direct queue access
  → goals._daemon.executor_registry.dispatch(c) # direct executor access
  # No governance in the call path
```

`CompoundGoals.__init__` (`compound_goals.py:25`) accepts `daemon: Any`.
The class is explicitly designed to coordinate subsystems — if expanded to
emit Commands or Schedules, it has no internal governance. Currently skeletal,
but the architectural extension point is ungoverned.

### D1.6 Perception Loop Constructs Commands Without Strict Governance Binding

**Axiom**: executive_function (weight 95)
**Invariant**: Commands should carry accurate governance provenance
**Enforcement**: **Convention** — governance_result field is set but never enforced

```
_perception_loop                          # __main__.py:807-857
  → governor.evaluate(state) → directive  # PipelineGovernor, separate from VetoChain
  → Command(action=directive,
            governance_result=governor.last_veto_result or VetoResult(allowed=True))
  → _frame_gate.apply_command(command)    # reads command.action, ignores governance_result
```

The perception loop (`__main__.py:823-838`) constructs a Command with a
`governance_result` field, but `FrameGate.apply_command()` only reads
`command.action` (the directive string). If `governance_result.allowed` is
False, the directive still applies. The governance_result is informational.

Note: `PipelineGovernor` (`governor.py`) is a *separate governance system*
from the VetoChain/FallbackChain primitives — it predates them and operates
on EnvironmentState rather than FusedContext. Two governance architectures
coexist without a unifying enforcement boundary.

### D1.7 Event Subscriptions Allow Interception

**Invariant**: Governance output should flow through the intended actuation path
**Enforcement**: **None** — Events are public, subscription is unrestricted

```
# Any code with a reference to the governance output Event can intercept:
mc_output.subscribe(lambda ts, schedule: intercept(schedule))
obs_output.subscribe(lambda ts, cmd: reroute(cmd))
```

`Event.subscribe()` (`primitives.py:76-86`) accepts any callback. There is
no subscription ordering, no priority, no way to mark an Event as having a
single canonical consumer. A CompoundGoal or future agent could subscribe to
governance output Events and intercept or duplicate Commands before they
reach the normal execution path.

---

## Section 2: Axiom-Violating Types

Type constructions that would violate constitutional axioms. Some are
forbidden by *absence* (the types don't exist), some are forbidden by
*convention* (the types could be constructed but shouldn't be), and some
are **already present** as de facto violations.

### D2.1 Multi-User Identity Types

**Axiom**: single_user (weight 100)
**Enforcement**: **Convention** — axiom hooks scan for patterns, but no type-level barrier

The following types must never exist:

```python
# FORBIDDEN: any of these type signatures
@dataclass
class User:
    user_id: str
    role: str              # implies multi-user role differentiation

@dataclass
class Session:
    user_id: str           # implies session is user-scoped
    permissions: set[str]  # implies authorization model

class AuthMiddleware:
    def authenticate(self, token: str) -> User: ...

class RoleBasedVetoChain[C](VetoChain[C]):
    def __init__(self, role: str, vetoes: list[Veto[C]]): ...
```

Current enforcement: axiom hooks in `hooks/` scan for keywords (`auth`,
`role`, `permission`, `user_id`) in changed files. This is grep-level
scanning, not type-level prevention. A `Participant` or `Operator` type
with the same semantics would pass the scan.

### D2.2 De Facto Multi-Person Model Already Exists

**Axiom**: single_user (weight 100)
**Enforcement**: **Convention** — justified by interpersonal_transparency axiom

The system already models non-operator persons in three places:

```python
# session.py:39-40 — two-category person model
VoiceLifecycle.is_guest_mode → self.speaker not in ("ryan", None)
  # Creates: operator ("ryan") vs. non-operator (guest)

# speaker_id.py — biometric identity classification
SpeakerIdentifier.identify(audio) → SpeakerResult
  # Returns: "ryan" (≥0.75), "not_ryan" (<0.4), "uncertain"

# shared/consent.py:31 — bilateral party model
ConsentContract.parties: tuple[str, str]  # (operator, subject)
```

This is not a violation of single_user per se — the system is operated
by one user, but it *perceives* multiple persons and must handle them
correctly per interpersonal_transparency. The tension is that the
single_user axiom says "no auth, roles, or collaboration features"
while interpersonal_transparency requires modeling non-operator persons
to enforce consent. The ConsentContract type is the designed resolution.

### D2.3 Individual Feedback Types

**Axiom**: management_governance (weight 85)
**Enforcement**: **Convention** — no type-level barrier

The following types must never exist in the voice domain:

```python
# FORBIDDEN: types that model individual performance
@dataclass
class IndividualFeedback:
    person_id: str
    recommendation: str    # "needs more energy"
    performance_score: float

@dataclass
class CoachingHypothesis:
    subject: str
    observation: str
    suggested_intervention: str

class PersonPerformanceBehavior(Behavior[float]):
    """Tracks an individual's performance metric over time."""
    person_id: str
```

The danger is not that someone writes `IndividualFeedback` — it's that a
`Behavior[dict]` carrying `{"person": "alice", "score": 0.7}` is
indistinguishable from a `Behavior[float]` at the type level. The axiom
violation lives in the *value*, not the *type*.

### D2.4 Management Governance Enforcement Is Keyword-Based

**Axiom**: management_governance (weight 85)
**Enforcement**: **Convention** — regex pattern matching, not structural prevention

```python
# governor.py:41-62 — the enforcement mechanism
_RUNTIME_COMPLIANCE_RULES = [
    ComplianceRule(
        axiom_id="management_governance",
        pattern=re.compile(
            r"feedback|coaching|performance.review|1.on.1|one.on.one",
            re.IGNORECASE,
        ),
    ),
]
```

The PipelineGovernor scans `workspace_context` (LLM-generated text) against
keyword patterns. This is reactive, not preventive:
- Only triggers if the LLM's workspace analysis output contains a keyword
- Paraphrases, synonyms, or indirect references pass through
- The voice pipeline could generate feedback about a guest if the system
  prompt doesn't explicitly forbid it — and the guest system prompt
  (`persona.py:42-48`) restricts tool access but not language generation

---

## Section 3: Consent Boundary Violations

The interpersonal_transparency axiom (weight 88, constitutional) requires
explicit consent before maintaining persistent state about non-operator
persons. The infrastructure exists (`ConsentContract`, `ConsentRegistry`).
The enforcement does not.

### D3.1 Speaker Embedding Extracted Without Consent

**Axiom**: interpersonal_transparency (weight 88)
**Implication**: `it-consent-001` (T0) — no persistent state without contract
**Enforcement**: **None** — active gap

```
Non-operator speaks → wake word triggers session
  → SpeakerIdentifier.identify_audio(audio_bytes)    # speaker_id.py:130-138
  → pyannote extracts speaker embedding from non-operator audio
  → SpeakerResult(label="not_ryan", confidence=0.85)
  # No ConsentRegistry.contract_check() called
  # Embedding is computed from biometric data without consent verification
```

`SpeakerIdentifier` (`speaker_id.py`) extracts pyannote embeddings from
audio to classify speakers. When a non-operator speaks, their voice is
processed through a biometric model. No consent check gates this path.

### D3.2 Speaker Embedding Persisted Without Consent

**Axiom**: interpersonal_transparency (weight 88)
**Implication**: `it-consent-001` (T0) — no persistent state without contract
**Enforcement**: **None** — active gap

```
SpeakerIdentifier.enroll(name, audio)     # speaker_id.py:140-149
  → pyannote extracts embedding
  → np.save(save_path, normalized)        # persisted to disk
  # No ConsentRegistry.contract_check() called
  # Biometric template stored without consent verification
```

The `enroll()` method saves speaker embeddings to disk as numpy arrays.
If used to enroll a non-operator's voice, this creates persistent biometric
state about a specific identified person without a consent contract.

### D3.3 Zero Perception Backends Implement Consent Verification

**Axiom**: interpersonal_transparency (weight 88)
**Implication**: `it-backend-001` (T1) — backends must verify contract at ingestion
**Enforcement**: **None** — active gap (systemic)

```
# REQUIRED by it-backend-001 but not implemented:
class SomeBackend:
    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        if self._detects_non_operator_person():
            if not consent_registry.contract_check(person_id, "biometric"):
                return  # skip update
        behaviors["signal"].update(value, now)

# ACTUAL implementation in ALL backends:
class EveryBackend:
    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        behaviors["signal"].update(value, now)  # no consent check
```

Searched all 7 backends in `agents/hapax_voice/backends/`:
- PipeWireBackend — no consent check (operator-only signals, safe)
- HyprlandBackend — no consent check (operator-only signals, safe)
- WatchBackend — no consent check (wearable data could be guest's watch)
- HealthBackend — no consent check (system metrics, safe)
- CircadianBackend — no consent check (operator profile, safe)
- MidiClockBackend — no consent check (instrument data, safe)
- StreamHealthBackend — no consent check (OBS metrics, safe)

No `ConsentRegistry` instance is created in daemon startup. No call to
`contract_check()` exists in any backend's `contribute()` method. The
`axioms/contracts/` directory contains only `.gitkeep` — zero contracts
exist.

### D3.4 Unconsented Person-State Via Behavior[T]

**Axiom**: interpersonal_transparency (weight 88)
**Enforcement**: **Convention** — ConsentRegistry is advisory, Behavior has no consent gate

```
# FORBIDDEN: Behavior updated with non-operator identity data without consent
face_identity_resolver detects person_id="visitor_1"
  → Behavior[OperatorIdentity].update(visitor_data, now)
  # ConsentRegistry.contract_check() was never called
```

`Behavior[T]` is parametric over `T`. There is no `ConsentGatedBehavior[T]`
that *requires* a consent check before `update()`. The consent gate and the
behavior update are decoupled — they happen to be called in sequence by
convention, not by construction.

### D3.5 Guest Mode Is Behavioral, Not Data-Gated

**Axiom**: interpersonal_transparency (weight 88)
**Enforcement**: **Convention** — guest mode restricts LLM tools, not perception

```
VoiceLifecycle.is_guest_mode = True
  → IntentRouter routes to Gemini (no local tools)  # intent_router.py:51
  → get_tool_schemas(guest_mode=True) → None         # tools.py:229-232
  # BUT: perception continues running
  # Face detection still runs every 8 seconds
  # EnvironmentState still populated with face_count
  # Workspace analysis could still derive person context
```

Guest mode restricts what the LLM *can do* (tool access). It does not
restrict what the perception layer *collects*. Face detection, VAD, and
workspace analysis continue to produce data about the non-operator guest.
The environmental exception (`it-environmental-001`) permits transient
perception — but if any downstream code logs face_count to event streams
or Qdrant, the transient becomes persistent without a consent check.

### D3.6 Conversation Detection Creates Implied Person State

**Axiom**: interpersonal_transparency (weight 88)
**Implication**: `it-environmental-001` (T2) — transient perception permitted if no persistent state derived
**Enforcement**: **Convention** — boundary between transient and persistent is not type-enforced

```
FaceDetector.detect(frame) → FaceResult(detected=True, count=2)
  → PresenceDetector.record_face_event(True, 2)
  → PerceptionEngine.tick() → EnvironmentState(face_count=2, conversation_detected=True)
  → PipelineGovernor.evaluate(state) → directive="pause"
  → EventLog.emit("perception_tick", face_count=2, directive="pause")  # PERSISTENT
```

The environmental exception says transient perception (face in camera feed)
doesn't require consent *if no persistent state about a specific identified
person is derived or stored*. But `EventLog.emit()` writes to disk. If the
event log records `face_count=2` with timestamps, this creates a temporal
record of non-operator presence — arguably persistent state about "someone
was here at time T."

---

## Section 4: Type System Escape Hatches

Places where Python's runtime type erasure creates gaps between the declared
types and what actually flows through the system.

### D4.1 Behavior[T] Has No Runtime Type Enforcement

**Invariant**: Behavior[float] should only contain float values
**Enforcement**: **None** — Python generics are erased at runtime

```python
# Compiles AND constructs without error:
b: Behavior[float] = Behavior("not a float", watermark=0.0)
b.update({"dict": "value"}, time.monotonic())
# Downstream: ctx.get_sample("audio_energy_rms").value >= 0.3
# → TypeError: '>=' not supported between 'dict' and 'float'
```

`Behavior.__init__` (`primitives.py:35-37`) accepts any `initial: T`.
Python 3.12 generics provide no runtime enforcement. A Behavior declared
as `Behavior[float]` can hold a string, dict, or None. The error surfaces
when a governance predicate does arithmetic on the value — far from the
source of the type violation.

### D4.2 FusedContext.samples Is an Unschema'd Dict

**Invariant**: FusedContext should contain exactly the samples governance requires
**Enforcement**: **None** — dict[str, Stamped] with no key validation

```python
FusedContext(trigger_time=t, trigger_value=None, samples={})
  → governance predicate calls ctx.get_sample("audio_energy_rms")
  → KeyError  # no early validation, fails at use site
```

`FusedContext.samples` (`governance.py:26`) is `dict[str, Stamped]` — any
string keys, any `Stamped` values. No schema declares which keys are
required for which governance chain. The mismatch between what a chain
*expects* and what `with_latest_from` *provides* is discovered at runtime
via KeyError in the middle of governance evaluation.

### D4.3 Command.action Is a Bare String

**Invariant**: Command actions should be from a known set
**Enforcement**: **None** — string, not enum

```python
Command(action="governance_internal_fork")     # compiles and constructs
  → ExecutorRegistry.dispatch(cmd)
  → self._action_map.get("governance_internal_fork")
  → None                                        # no executor, returns False
  # But: no error, no log at default level, silent failure
```

`Command.action` (`commands.py:27`) is `str`, not an enum or union of
known action types. `ExecutorRegistry.dispatch()` does a dict lookup and
silently returns False for unknown actions (log.debug only). A typo in
an action name produces silent inaction rather than a loud error.

### D4.4 Command.params and ActuationEvent.params Are dict[str, Any]

**Invariant**: Action parameters should match the executor's expected schema
**Enforcement**: **None** — untyped dictionaries

```python
# OBS executor expects params={"transition": "cut"|"dissolve"|"fade"}
Command(action="face_cam", params={"transition": 42, "extra": "ignored"})
  → OBSExecutor.execute(cmd)
  → cmd.params.get("transition", "dissolve")  # gets 42, passes to OBS
```

Both `Command.params` (`commands.py:28`) and `ActuationEvent.params`
(`actuation_event.py:26`) are `dict[str, Any]`. No per-action schema
validates that the right keys with the right types are present. Executors
use `.get()` with defaults, masking missing or wrong-typed parameters.

### D4.5 ResourceClaim.command Is Typed as object

**Invariant**: ResourceClaim should carry a Command
**Enforcement**: **None** — typed as `object`

```python
ResourceClaim(resource="audio_output", chain="mc", priority=50,
              command="not a command")  # accepts any object
  → arbiter.drain_winners() → [claim]
  → executor.dispatch(claim.command)   # AttributeError: str has no .action
```

`ResourceClaim.command` (`arbiter.py:27`) is `object` with a comment saying
"Command or any action descriptor." The type system does not prevent passing
arbitrary objects. If the arbiter were wired in (it's not — see D6.2), the
type mismatch would surface at dispatch time.

### D4.6 FusedContext.trigger_value Is Untyped

**Invariant**: Trigger value should carry the Event's type parameter
**Enforcement**: **None** — typed as `object`, type info from Event[T] is lost

```python
Event[float].emit(now, 42.0)
  → with_latest_from callback receives (timestamp: float, value: object)
  → FusedContext(trigger_value=value)  # object, not float
```

`with_latest_from` (`combinator.py:29`) receives `value: object` from the
Event callback. The combinator erases the Event's generic type parameter.
No predicate currently reads `trigger_value`, so this is latent rather than
active — but it means the type chain from Event[T] to FusedContext is broken.

---

## Section 5: Temporal & Causal Invariant Violations

These sequences violate invariants about time, ordering, and causality
that the type system cannot express.

### D5.1 Schedule Executed After Expiry Window

**Invariant**: Schedules have a tolerance window; expired schedules must be discarded
**Enforcement**: **Runtime** in ScheduleQueue; **None** for direct dispatch

```
Schedule(command=cmd, wall_time=100.0, tolerance_ms=50.0)
  → ScheduleQueue.enqueue(schedule)
  → [200ms pass — tolerance exceeded]
  → ScheduleQueue.drain(100.2)
  → schedule discarded (now > wall_time + tolerance_ms/1000)  ✓
```

Correctly enforced by `ScheduleQueue.drain()` (`executor.py:65-91`).
However, direct `ExecutorRegistry.dispatch(schedule.command)` bypasses the
queue entirely — there is no temporal check in `dispatch()`.

```
# FORBIDDEN but possible: bypass queue, dispatch stale command
schedule = Schedule(command=cmd, wall_time=100.0, tolerance_ms=50.0)
# ... 5 seconds later ...
registry.dispatch(schedule.command)  # no staleness check in dispatch()
```

**Enforcement for direct dispatch**: **None**

### D5.2 Feedback Loop Creates Causal Cycle

**Invariant**: Feedback must not create unbounded amplification
**Enforcement**: **Convention** — architectural separation at physical layer

```
# FORBIDDEN: positive feedback loop
ActuationEvent(action="vocal_throw")
  → last_mc_fire Behavior updates
  → _mc_fired_recently(ctx) → True
  → OBS selects face_cam_mc_bias
  → [hypothetical] face_cam triggers MC energy spike
  → MC fires again
  → last_mc_fire updates
  → ...                           # unbounded cycle
```

The current architecture prevents this because OBS scene selection does not
feed back into audio energy (the causal chain is broken at the physical
layer — camera selection doesn't change microphone input). But the type
system does not enforce this. A future Behavior that reads OBS state and
writes to audio energy would close the loop with no type error.

### D5.3 SuppressionField Receives Unbounded Input

**Invariant**: Suppression values must be in [0.0, 1.0]
**Enforcement**: **Convention** for `effective_threshold()`; **Runtime** for `SuppressionField`

```
# SuppressionField correctly clamps (suppression.py:35-38):
SuppressionField(initial=2.0)     # clamped to 1.0 ✓
sf.set_target(5.0, now)           # clamped to 1.0 ✓

# BUT effective_threshold is a bare function with no input validation:
effective_threshold(base=0.3, suppression=2.0)
  → 0.3 + 2.0 × 0.7 = 1.7       # threshold > 1.0, physically meaningless
```

`effective_threshold()` (`suppression.py:93-101`) trusts its caller to pass
suppression in [0, 1]. The SuppressionField always produces valid values, but
nothing prevents calling `effective_threshold()` with an arbitrary float.

---

## Section 6: Resource & Contention Violations

### D6.1 ResourceClaim Priority Mismatch

**Invariant**: Claim priority must match the configured priority map
**Enforcement**: **Runtime** — ValueError in `ResourceArbiter.claim()`

```
ResourceClaim(resource="audio_output", chain="mc", priority=999, command=cmd)
  → arbiter.claim(rc)
  → ValueError("Claim priority 999 != configured 50 for ('audio_output', 'mc')")
```

Correctly enforced (`arbiter.py:52-57`). The forbidden sequence fails loud.

### D6.2 ResourceArbiter Bypassed Entirely

**Invariant**: Contending chains must go through arbitration
**Enforcement**: **None** — active gap

```
compose_mc_governance → Schedule
  → _on_mc_schedule → schedule_queue.enqueue(schedule)     # __main__.py:298
  → _actuation_loop → schedule_queue.drain(now) → [schedule]
  → executor_registry.dispatch(schedule.command)            # __main__.py:868
  # No arbiter.claim() called anywhere in this path

compose_obs_governance → Command
  → _on_obs_command → executor_registry.dispatch(cmd)      # __main__.py:328
  # No arbiter.claim() called anywhere in this path
```

This is what `__main__.py` does today. Both governance chains dispatch
directly to `ExecutorRegistry` without consulting `ResourceArbiter`.
The arbiter and its priority map (`resource_config.py:20-29`) exist as
fully tested types but are not instantiated or wired at runtime. If MC
and OBS fire simultaneously on the same resource (audio_output), both
execute — the arbiter that would resolve this contention is not in the
call path.

### D6.3 Unconfigured Resource-Chain Pair

**Invariant**: Every (resource, chain) pair must have a configured priority
**Enforcement**: **Runtime** — ValueError in `ResourceArbiter.claim()`

Correctly enforced. A new governance chain cannot claim resources without
being added to the priority map first.

---

## Section 7: Perception Boundary Violations

### D7.1 Backend Provides Conflicting Behavior Names

**Invariant**: Each Behavior name has exactly one source
**Enforcement**: **Runtime** — ValueError in `PerceptionEngine.register_backend()`

Correctly enforced (`perception.py:242-245`). Same pattern in
`ExecutorRegistry.register()` for action handle conflicts.

### D7.2 Backend Writes to Behaviors It Doesn't Declare

**Invariant**: A backend should only write to Behaviors in its `provides` set
**Enforcement**: **None** — `contribute()` receives the full dict

```
class RogueBackend:
    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"my_signal"})

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        # FORBIDDEN: writes to a behavior owned by another backend
        behaviors["vad_confidence"].update(0.0, time.monotonic())
```

`PerceptionBackend.contribute()` (`perception.py:62`) receives the entire
`behaviors` dict. Nothing prevents a backend from writing to keys outside
its declared `provides` set. The `provides` declaration is advisory —
it controls conflict detection at registration, not write access at runtime.

### D7.3 Behavior Updated Outside Perception Tick

**Invariant**: Behavior updates should flow through the perception pipeline
**Enforcement**: **None** — `Behavior.update()` is public

```
# FORBIDDEN: ad-hoc Behavior mutation from arbitrary code
engine.behaviors["vad_confidence"].update(1.0, time.monotonic())
```

Any code with a reference to the engine's behaviors dict can update any
Behavior at any time. There is no ownership model — `Behavior.update()` is
a public method. The monotonic watermark prevents regression but not
unauthorized writes.

### D7.4 Backend Creates New Behaviors Not in Registry

**Invariant**: The behaviors dict should be a closed set defined at registration
**Enforcement**: **None** — backends can add keys to the dict

```
class InjectingBackend:
    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        behaviors["injected_signal"] = Behavior(999.0)  # new key, no registration
```

Backends receive a mutable dict. They can assign new keys, not just update
existing Behaviors. `PerceptionEngine` does not freeze the dict or check for
new keys after `contribute()` returns. A backend could inject signals that
governance reads via `with_latest_from` without ever declaring them in
`provides`.

---

## Section 8: Composition Violations

### D8.1 FallbackChain Composed with Incompatible Defaults

**Invariant**: `chain_a | chain_b` uses `chain_a`'s default
**Enforcement**: **Type** — generics enforce compatible action types

Pyright catches this in basic mode. The generic parameter `T` prevents
composing chains with incompatible action types. Correctly enforced.

### D8.2 VetoChain Composed Across Context Types

**Invariant**: Composed VetoChains must share the same context type
**Enforcement**: **Type** — generics enforce compatible context types

Correctly enforced by generics.

### D8.3 with_latest_from Wired to Wrong Behaviors Dict

**Invariant**: Governance chain must sample the behaviors its vetoes/candidates reference
**Enforcement**: **None** — the dict is passed by reference, contents unchecked

```
# FORBIDDEN: MC governance wired to empty behaviors dict
mc_output = compose_mc_governance(
    trigger=tick,
    behaviors={},   # missing audio_energy_rms, vad_confidence, etc.
)
# Compiles and constructs. Fails only when FusedContext.get_sample()
# raises KeyError during the first tick.
```

The mismatch between declared behavior dependencies (in FreshnessGuard
requirements, veto predicates, candidate predicates) and the actual behaviors
dict is discovered at runtime via KeyError, not at construction time.

### D8.4 Feedback Loop Not Wired at Runtime

**Invariant**: Actuation events should feed back into governance via Behaviors
**Enforcement**: **None** — `wire_feedback_behaviors()` exists but is not called

```
# feedback.py:18-48 — function exists
wire_feedback_behaviors(actuation_event, watermark=0.0) → dict[str, Behavior]
  # Returns: last_mc_fire, mc_fire_count, last_obs_switch, last_tts_end

# __main__.py — function is never called
# ExecutorRegistry.actuation_event is never wired to feedback Behaviors
# Feedback Behaviors referenced by OBS governance (_mc_fired_recently)
# will raise KeyError or return sentinel 0.0 forever
```

The entire feedback loop described in the North Star (Section 2.3) is
implemented as types but not wired at runtime. The OBS `face_cam_mc_bias`
candidate calls `_mc_fired_recently(ctx)` which reads `last_mc_fire` from
FusedContext — this will be KeyError if feedback Behaviors are not in the
dict, or 0.0 (sentinel) if present but never updated.

---

## Section 9: Concurrency Violations

The daemon runs multiple async tasks sharing mutable state. Sync callbacks
from external threads (MIDI, Hyprland IPC, hotkey server) cross into the
async domain without synchronization. The codebase has **one**
synchronization primitive: `asyncio.Event` for wake word signaling.

### D9.1 Behavior.update() Is Not Thread-Safe

**Invariant**: Concurrent writes to a Behavior must not corrupt state
**Enforcement**: **None** — no locking

```
# Thread A (_perception_loop, async):
_b_vad_confidence.update(0.7, 1000.5)      # perception.py:272
  → self._value = 0.7
  # context switch mid-write

# Thread B (Hyprland IPC callback, sync):
_b_active_window.update(window_info, 1000.6)  # perception.py:335
  → self._value = window_info
  # B completes

# Thread A resumes:
  → self._watermark = 1000.5
  # value and watermark from different "transactions"
```

`Behavior.__init__` and `update()` (`primitives.py:35-56`) mutate two
fields (`_value`, `_watermark`) without atomicity. Within the asyncio
event loop, tasks don't preempt each other at Python statements (GIL +
cooperative scheduling). But sync callbacks from external threads
(MIDI `_on_message`, Hyprland IPC) do preempt, creating actual races.

**Specific hazard**: `MidiClockBackend` uses an internal `threading.Lock`
to protect its own state, but when its data flows into `Behavior.update()`
via `contribute()`, the Behavior itself is unprotected.

### D9.2 ScheduleQueue Enqueue/Drain Race

**Invariant**: ScheduleQueue must not lose or duplicate entries
**Enforcement**: **None** — no locking

```
# MC governance callback (triggered by Event.emit from MIDI thread):
_on_mc_schedule → schedule_queue.enqueue(schedule)
  → bisect.insort(self._items, schedule)     # modifies list in place

# Concurrently, _actuation_loop (async):
schedule_queue.drain(now)
  → iterates self._items
  → self._items = remaining                   # reassigns list reference
```

`ScheduleQueue._items` (`executor.py:59`) is a mutable list accessed by
`enqueue()` (insert) and `drain()` (iterate + reassign). If the MC
governance pipeline is triggered by a MIDI clock event on a separate thread,
`enqueue()` can modify the list while `drain()` is iterating it.

### D9.3 Event Subscriber List Mutation During Emit

**Invariant**: Event emission must deliver to all current subscribers
**Enforcement**: **None** — no copy-on-iterate, no locking

```
# During Event.emit() iteration (primitives.py:88-94):
for cb in self._subscribers:
    cb(timestamp, value)
    # Inside cb: another Event.subscribe() or unsubscribe() modifies _subscribers
    # Iterator invalidated
```

`Event.emit()` iterates `_subscribers` directly. If a callback triggers
a subscription change (subscribe/unsubscribe) on the same or another Event
in the call chain, the list mutates during iteration.

### D9.4 Session State Torn Reads

**Invariant**: Session state reads must be consistent across fields
**Enforcement**: **None** — no atomic snapshot

```
# _perception_loop (async):
if self.session.is_active:       # reads state
  # context switch — hotkey handler closes session
  if self.session.is_paused:     # reads _paused — session is now closed
    # inconsistent: checked is_active=True, is_paused after close
```

`SessionManager` fields (`session.py:15-97`) — `state`, `_paused`,
`session_id`, `speaker`, `_opened_at` — are read by 6+ async tasks and
written by hotkey handlers and the perception loop. No atomic snapshot
mechanism exists. Readers can observe partially-updated state.

### D9.5 PerceptionEngine.latest Read During Write

**Invariant**: `perception.latest` should be a consistent EnvironmentState
**Enforcement**: **None** — simple attribute assignment

```
# _perception_loop (async):
self.latest = state                          # perception.py:312

# _proactive_delivery_loop (async, concurrent):
presence = self.perception.latest.presence_score  # __main__.py:761
# Could read stale latest or catch mid-assignment (reference swap is atomic in
# CPython, but not guaranteed by Python spec)
```

`PerceptionEngine.latest` (`perception.py:223`) is read by the proactive
delivery loop while being written by the perception loop. In CPython,
attribute assignment is atomic (GIL), so this is safe *in practice*. But
it is not safe *by specification* — and a different Python implementation
(PyPy, GraalPy) could expose the race.

### D9.6 Gemini Session TOCTOU

**Invariant**: Null checks on _gemini_session must hold through usage
**Enforcement**: **None** — check and use are not atomic

```
# _audio_loop (async):
if self._gemini_session is not None:       # __main__.py:463 — check
    # await yields control
    await self._gemini_session.send_audio(frame)  # session may be None now

# _stop_pipeline (async, concurrent):
self._gemini_session = None                # __main__.py:590
```

The None check and the method call on `_gemini_session` are separated by
an `await` point. Another task can set `_gemini_session = None` between
the check and the use.

---

## Section 10: Corporate Boundary Violations

### D10.1 Gemini Live Bypasses LiteLLM

**Axiom**: corporate_boundary (weight 90)
**Enforcement**: **None** — direct Google client

```python
# gemini_live.py:44-64
from google import genai
self._client = genai.Client(api_key=api_key)  # direct to Google, not LiteLLM
```

The Gemini Live speech-to-speech session uses the Google generative AI
client directly. This bypasses LiteLLM entirely — no observability, no
corporate provider routing, no Langfuse tracing. On a corporate network,
this would use a non-sanctioned API path.

### D10.2 AsyncOpenAI Client May Bypass LiteLLM

**Axiom**: corporate_boundary (weight 90)
**Enforcement**: **Convention** — depends on environment variable

```python
# workspace_analyzer.py:87-93, screen_analyzer.py:78-84
base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000")
self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
```

The workspace and screen analyzers instantiate `AsyncOpenAI` with a
`base_url` that defaults to `localhost:4000` (LiteLLM). If `LITELLM_BASE_URL`
is set to a direct OpenAI endpoint — or if LiteLLM is down and the client
falls through — the call goes direct. The convention works when `.envrc`
is correct, but there's no type-level guarantee that all LLM calls route
through the gateway.

### D10.3 Ollama Embedding Fails Hard Instead of Degrading

**Axiom**: corporate_boundary (weight 90)
**Enforcement**: **Runtime** — raises RuntimeError

```python
# shared/config.py:148-150
client = _get_ollama_client()
result = client.embed(model=model_name, input=prefixed)
# If Ollama is unreachable: RuntimeError, not graceful degradation
```

The corporate_boundary axiom says "degrade gracefully when home-only
services are unreachable." The Ollama embedding path raises `RuntimeError`
on connection failure — no fallback, no degradation, crash propagation.

---

## Section 11: Summary — Enforcement Deficit Map

### Active Gaps (Enforcement = None)

| ID | Forbidden Sequence | Axiom/Invariant | Risk |
|----|--------------------|-----------------|------|
| D1.1 | Denied Command dispatches | executive_function | **Critical** |
| D1.4 | Hotkey bypasses all governance | executive_function | **High** |
| D1.5 | CompoundGoals unrestricted access | executive_function | Medium |
| D1.7 | Event subscription interception | actuation integrity | Medium |
| D3.1 | Speaker embedding without consent | interpersonal_transparency | **Critical** |
| D3.2 | Speaker embedding persisted without consent | interpersonal_transparency | **Critical** |
| D3.3 | Zero backends implement consent | interpersonal_transparency | **Critical** |
| D4.1 | Behavior[T] no runtime type check | type safety | Medium |
| D4.2 | FusedContext unschema'd samples | composition integrity | Medium |
| D4.3 | Command.action bare string | actuation integrity | Low |
| D4.4 | params dict[str, Any] escape hatch | type safety | Low |
| D4.5 | ResourceClaim.command typed object | type safety | Low |
| D5.1 | Direct dispatch bypasses tolerance | temporal safety | Medium |
| D6.2 | ResourceArbiter not wired | resource safety | **High** |
| D7.2 | Backend writes undeclared behaviors | perception integrity | Medium |
| D7.3 | Behavior updated outside tick | perception integrity | Medium |
| D7.4 | Backend injects unregistered signals | perception integrity | Medium |
| D8.3 | Behaviors dict mismatch | composition integrity | Medium |
| D8.4 | Feedback loop not wired | composition integrity | Medium |
| D9.1 | Behavior.update() thread race | concurrency | **High** |
| D9.2 | ScheduleQueue enqueue/drain race | concurrency | **High** |
| D9.3 | Event subscriber mutation during emit | concurrency | Medium |
| D9.4 | Session state torn reads | concurrency | Medium |
| D9.6 | Gemini session TOCTOU | concurrency | Medium |
| D10.1 | Gemini Live bypasses LiteLLM | corporate_boundary | Medium |

### Convention-Only Enforcement

| ID | Forbidden Sequence | Axiom/Invariant | Risk |
|----|--------------------|-----------------|------|
| D1.2 | Empty VetoChain permits all | executive_function | High |
| D1.3 | Veto removal relaxes chain | executive_function | Medium |
| D1.6 | Two parallel governance systems | executive_function | Medium |
| D2.1 | Multi-user identity types | single_user | Low |
| D2.3 | Individual feedback types | management_governance | Low |
| D2.4 | Keyword-based management enforcement | management_governance | Low |
| D3.4 | Consent gate not in type system | interpersonal_transparency | High |
| D3.5 | Guest mode behavioral not data-gated | interpersonal_transparency | High |
| D3.6 | Transient/persistent boundary untyped | interpersonal_transparency | Medium |
| D5.2 | Feedback causal cycle | exec. function | Low |
| D5.3 | Unbounded suppression input | exec. function | Low |
| D10.2 | AsyncOpenAI depends on env var | corporate_boundary | Low |

### Correctly Enforced (Type or Runtime)

| ID | Forbidden Sequence | Enforcement |
|----|--------------------|-------------|
| D6.1 | ResourceClaim priority mismatch | Runtime (ValueError) |
| D6.3 | Unconfigured resource-chain pair | Runtime (ValueError) |
| D7.1 | Conflicting behavior names | Runtime (ValueError) |
| D8.1 | Incompatible FallbackChain compose | Type (generics) |
| D8.2 | Incompatible VetoChain compose | Type (generics) |
| — | FallbackChain without default | Type (required param) |
| — | Behavior watermark regression | Runtime (ValueError) |
| — | SuppressionField out-of-range init | Runtime (clamping) |
| — | GovernanceBinding invalid source | Runtime (__post_init__) |

---

## Section 12: Toward Enforcement

This section does not prescribe solutions. It maps each critical gap to the
*kind* of enforcement that could close it, as input for future design work.

| Gap | Enforcement Class | Sketch |
|-----|-------------------|--------|
| D1.1 | Runtime guard | `dispatch()` checks `governance_result.allowed`, raises on False |
| D1.2 | Constructor constraint | `VetoChain.__init__` requires non-empty vetoes list |
| D1.4 | Architectural | Hotkey path constructs Command + evaluates VetoChain before session.open() |
| D3.1–3.3 | Wrapper type | `ConsentGatedBehavior[T]` wraps `Behavior[T]`, requires consent before update for person-linked data |
| D3.5 | Architectural | Perception backends check ConsentRegistry when non-operator detected |
| D4.1 | Runtime validation | `Behavior.update()` optionally validates value against declared type |
| D4.2 | Schema type | `BehaviorSchema` declares required keys; `compose_*_governance` validates at construction |
| D6.2 | Architectural wiring | Actuation loop routes through `ResourceArbiter` before `ExecutorRegistry` |
| D7.2 | Scoped write dict | `contribute()` receives a write-only view filtered to `provides` keys |
| D8.4 | Architectural wiring | `wire_feedback_behaviors()` called in daemon init, behaviors merged into engine |
| D9.1–9.2 | Synchronization | `asyncio.Lock` around shared mutable state; sync callbacks use `loop.call_soon_threadsafe()` |
| D10.1 | Proxy pattern | Gemini Live routes through LiteLLM proxy or custom wrapper with Langfuse tracing |

These are not commitments. They are the negative space made visible.
