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

---

## Section 2: Axiom-Violating Types

Type constructions that, if they existed, would violate constitutional axioms.
These are forbidden by *absence* — the types don't exist — but no mechanism
prevents their creation.

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

### D2.2 Individual Feedback Types

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

### D2.3 Unconsented Person-State Persistence

**Axiom**: interpersonal_transparency (weight 88)
**Enforcement**: **Convention** — ConsentRegistry is advisory

```
# FORBIDDEN: Behavior updated with non-operator identity data without consent check
face_identity_resolver detects person_id="visitor_1"
  → Behavior[OperatorIdentity].update(visitor_data, now)
  # ConsentRegistry.contract_check() was never called
```

`ConsentRegistry.contract_check()` (`shared/consent.py:86-99`) returns `bool`.
Nothing forces callers to check it. A PerceptionBackend can update any Behavior
with any person's data without consulting the registry. The enforcement boundary
is documented ("call at ingestion, not downstream") but not enforced by types.

**The deeper problem**: `Behavior[T]` is parametric over `T`. There is no
`ConsentGatedBehavior[T]` that *requires* a consent check before `update()`.
The consent gate and the behavior update are decoupled — they happen to be
called in sequence by convention, not by construction.

---

## Section 3: Temporal & Causal Invariant Violations

These sequences violate invariants about time, ordering, and causality
that the type system cannot express.

### D3.1 Schedule Executed After Expiry Window

**Invariant**: Schedules have a tolerance window; expired schedules must be discarded
**Enforcement**: **Runtime** — `ScheduleQueue.drain()` discards expired items

```
Schedule(command=cmd, wall_time=100.0, tolerance_ms=50.0)
  → ScheduleQueue.enqueue(schedule)
  → [200ms pass — tolerance exceeded]
  → ScheduleQueue.drain(100.2)
  → schedule discarded (now > wall_time + tolerance_ms/1000)
```

This is correctly enforced by `ScheduleQueue.drain()` (`executor.py:65-91`).
However, direct `ExecutorRegistry.dispatch(schedule.command)` bypasses the
queue entirely — there is no temporal check in `dispatch()`.

```
# FORBIDDEN but possible: bypass queue, dispatch stale command
schedule = Schedule(command=cmd, wall_time=100.0, tolerance_ms=50.0)
# ... 5 seconds later ...
registry.dispatch(schedule.command)  # no staleness check in dispatch()
```

**Enforcement for direct dispatch**: **None**

### D3.2 Feedback Loop Creates Causal Cycle

**Invariant**: Feedback must not create unbounded amplification
**Enforcement**: **Convention** — architectural separation

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

### D3.3 SuppressionField Receives Unbounded Input

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
suppression ∈ [0, 1]. The SuppressionField always produces valid values, but
nothing prevents calling `effective_threshold()` with an arbitrary float.

---

## Section 4: Resource & Contention Violations

### D4.1 ResourceClaim Priority Mismatch

**Invariant**: Claim priority must match the configured priority map
**Enforcement**: **Runtime** — ValueError in `ResourceArbiter.claim()`

```
# Correctly rejected:
ResourceClaim(resource="audio_output", chain="mc", priority=999, command=cmd)
  → arbiter.claim(rc)
  → ValueError("Claim priority 999 != configured 50 for ('audio_output', 'mc')")
```

This is correctly enforced (`arbiter.py:52-57`). The forbidden sequence
fails loud.

### D4.2 ResourceArbiter Bypassed Entirely

**Invariant**: Contending chains must go through arbitration
**Enforcement**: **None** — active gap

```
# FORBIDDEN: governance output dispatched without arbitration
compose_mc_governance → Schedule
  → ScheduleQueue.enqueue(schedule)
  → ScheduleQueue.drain(now) → [schedule]
  → ExecutorRegistry.dispatch(schedule.command)  # no arbiter.claim() called
```

This is exactly what `__main__.py` does today (`__main__.py:296-306`,
`__main__.py:859-879`). The actuation loop drains the ScheduleQueue and
dispatches directly to ExecutorRegistry without consulting ResourceArbiter.
The arbiter exists as a type but is not wired into the runtime pipeline.

### D4.3 Unconfigured Resource-Chain Pair

**Invariant**: Every (resource, chain) pair must have a configured priority
**Enforcement**: **Runtime** — ValueError in `ResourceArbiter.claim()`

```
ResourceClaim(resource="audio_output", chain="new_chain", priority=50, command=cmd)
  → arbiter.claim(rc)
  → ValueError("No priority configured for ('audio_output', 'new_chain')")
```

Correctly enforced. A new governance chain cannot claim resources without
being added to the priority map first.

---

## Section 5: Perception Boundary Violations

### D5.1 Backend Provides Conflicting Behavior Names

**Invariant**: Each Behavior name has exactly one source
**Enforcement**: **Runtime** — ValueError in `PerceptionEngine.register_backend()`

```
backend_a.provides = frozenset({"vad_confidence"})
backend_b.provides = frozenset({"vad_confidence"})
engine.register_backend(backend_a)   # OK
engine.register_backend(backend_b)   # ValueError: Behavior name conflicts
```

Correctly enforced (`perception.py:242-245`). Same pattern in
`ExecutorRegistry.register()` for action handle conflicts.

### D5.2 Backend Writes to Behaviors It Doesn't Declare

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

### D5.3 Behavior Updated Outside Perception Tick

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

---

## Section 6: Composition Violations

### D6.1 FallbackChain Composed with Incompatible Defaults

**Invariant**: `chain_a | chain_b` uses `chain_a`'s default
**Enforcement**: **Type** — generics enforce compatible action types

```
mc_chain: FallbackChain[FusedContext, MCAction]
obs_chain: FallbackChain[FusedContext, OBSScene]

# Type error at composition (different T parameter):
mc_chain | obs_chain  # FallbackChain[FusedContext, MCAction] | FallbackChain[FusedContext, OBSScene]
```

Pyright catches this in basic mode. The generic parameter `T` prevents
composing chains with incompatible action types. Correctly enforced.

### D6.2 VetoChain Composed Across Context Types

**Invariant**: Composed VetoChains must share the same context type
**Enforcement**: **Type** — generics enforce compatible context types

```
chain_a: VetoChain[FusedContext]
chain_b: VetoChain[int]

# Type error:
chain_a | chain_b  # incompatible C parameter
```

Correctly enforced by generics.

### D6.3 with_latest_from Wired to Wrong Behaviors Dict

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

---

## Section 7: Summary — Enforcement Deficit Map

| ID | Forbidden Sequence | Axiom/Invariant | Enforcement | Risk |
|----|--------------------|-----------------|-------------|------|
| D1.1 | Denied Command dispatches | executive_function | **None** | **Critical** |
| D1.2 | Empty VetoChain permits all | executive_function | Convention | High |
| D1.3 | Veto removal relaxes chain | executive_function | Convention | Medium |
| D2.1 | Multi-user identity types | single_user | Convention (hooks) | Low |
| D2.2 | Individual feedback types | management_governance | Convention | Low |
| D2.3 | Unconsented person-state | interpersonal_transparency | Convention | High |
| D3.1 | Stale schedule direct dispatch | exec. function | **None** | Medium |
| D3.2 | Causal feedback cycle | exec. function | Convention | Low |
| D3.3 | Unbounded suppression input | exec. function | Convention | Low |
| D4.1 | Priority mismatch claim | resource safety | Runtime | — |
| D4.2 | Arbiter bypassed entirely | resource safety | **None** | **High** |
| D4.3 | Unconfigured resource-chain | resource safety | Runtime | — |
| D5.1 | Conflicting behavior names | perception integrity | Runtime | — |
| D5.2 | Backend writes undeclared | perception integrity | **None** | Medium |
| D5.3 | Behavior updated outside tick | perception integrity | **None** | Medium |
| D6.1 | Incompatible FallbackChain composition | type safety | Type | — |
| D6.2 | Incompatible VetoChain composition | type safety | Type | — |
| D6.3 | Behaviors dict mismatch | composition integrity | **None** | Medium |

### Active Gaps (Enforcement = None)

Six forbidden sequences execute successfully today:

1. **D1.1** — `dispatch()` ignores `governance_result.allowed`
2. **D3.1** — Direct dispatch bypasses schedule tolerance window
3. **D4.2** — ResourceArbiter exists but is not wired into actuation loop
4. **D5.2** — `contribute()` has unrestricted write access to all behaviors
5. **D5.3** — `Behavior.update()` is public with no ownership model
6. **D6.3** — Behavior dependency mismatch discovered at runtime via KeyError

### Convention-Only Enforcement

Five forbidden sequences are prevented only by documentation and code review:

1. **D1.2** — Empty VetoChain (vacuously permissive)
2. **D1.3** — Veto removal via private attribute access
3. **D2.1** — Multi-user types (hook scanning, not type prevention)
4. **D2.2** — Individual feedback types (absence, not enforcement)
5. **D2.3** — Consent bypass (advisory registry, not gated Behavior)

---

## Section 8: Toward Enforcement

This section does not prescribe solutions. It maps each active gap to the
*kind* of enforcement that could close it, as input for future design work.

| Gap | Enforcement Class | Sketch |
|-----|-------------------|--------|
| D1.1 | Runtime guard | `dispatch()` checks `command.governance_result.allowed`, raises on False |
| D1.2 | Constructor constraint | `VetoChain.__init__` requires non-empty vetoes list |
| D2.3 | Wrapper type | `ConsentGatedBehavior[T]` wraps `Behavior[T]`, requires `contract_check()` before `update()` |
| D4.2 | Architectural wiring | Actuation loop routes through `ResourceArbiter` before `ExecutorRegistry` |
| D5.2 | Scoped write dict | `contribute()` receives a write-only view filtered to `provides` keys |
| D6.3 | Construction-time check | `compose_*_governance()` validates behavior keys match freshness requirements |

These are not commitments. They are the negative space made visible.
