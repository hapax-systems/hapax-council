# Dog Star Spec — Forbidden Type Sequences

**Date**: 2026-03-13
**Branch**: `feat/multi-role-composition`
**Companion to**: `2026-03-13-domain-schema-north-star.md`

---

## Section 0: Prose Constraint & Notation

Every declarative sentence in this document is a projection of a **forbidden**
type sequence. Where the North Star decomposes prose into valid type chains,
the Dog Star decomposes prose into type chains that must not be constructible.

The same notation applies:

| Notation | Meaning |
|----------|---------|
| `T → U` | Function or transform |
| `T × U` | Product / tuple |
| `T \| None` | Option type |
| `Behavior[T]` | Continuously-available value with monotonic watermark |
| `Event[T]` | Discrete occurrence stream with pub/sub signaling |
| `Stamped[T]` | Immutable snapshot of a value with its freshness watermark |
| `T ⊘` | **Forbidden** — this type or composition must not exist |
| `T → ✗` | **Blocked** — this transition must not complete |

Each forbidden sequence is derived from an axiom and tagged with enforcement:

| Marker | Meaning |
|--------|---------|
| `[enforced]` | Type system or runtime prevents this construction |
| `[gap]` | No enforcement exists — the forbidden sequence executes successfully |
| `[convention]` | Only code review prevents this |

### Decomposition Example

> "The system must not dispatch a governance-denied Command."

```
Command(governance_result=VetoResult(allowed=False))
  → ExecutorRegistry.dispatch(cmd) → ✗
```

This is forbidden by executive_function. Currently `[gap]` — dispatch does
not inspect `governance_result.allowed`.

---

## Section 1: single_user — Forbidden Identity Compositions

**Axiom**: single_user (weight 100, constitutional)
**Principle**: One operator. No auth, roles, or collaboration features.

### F1.1 User-Parameterized Governance ⊘

No governance primitive may be parameterized by user identity.

```
User × Role → VetoChain[C] ⊘
User × Permission → FallbackChain[C, T] ⊘
Session × user_id → Executor ⊘
```

**Why forbidden**: Governance chains evaluate perception state, not caller
identity. If a VetoChain accepted a Role parameter, the system would need
an authorization model to determine which role is active — this is multi-user
infrastructure regardless of how many users exist.

**Status**: `[enforced]` — no User, Role, or Permission types exist. Axiom
hooks scan for `auth`, `role`, `permission`, `user_id` in changed files.

### F1.2 Per-User Perception ⊘

No Behavior may be scoped to a user identity.

```
Behavior[T] × user_id → Stamped[T] ⊘
PerceptionBackend × user_id → dict[str, Behavior] ⊘
EnvironmentState × user_id ⊘
```

**Why forbidden**: Perception is environmental — it reads the room, not
the person. A per-user Behavior would require identity resolution before
every sample, creating an authentication dependency in the perception hot path.

**Status**: `[enforced]` — Behavior has no user_id field, PerceptionBackend
protocol has no identity parameter.

### F1.3 User-Scoped Actuation ⊘

No Executor may filter actions by caller identity.

```
Executor.execute(command: Command, caller: User) ⊘
ExecutorRegistry.dispatch(command, session: Session) ⊘
```

**Why forbidden**: The Executor protocol (`executor.py:23`) takes a Command.
The Command carries provenance (trigger_source, governance_result) but not
identity. Adding identity to the execution path would require an auth check
at the actuation boundary.

**Status**: `[enforced]` — Executor protocol signature accepts only Command.

### F1.4 The Consent Tension

ConsentContract has `parties: tuple[str, str]` — a binary model with operator
and subject. This is **not** a single_user violation. The system is *operated*
by one user but *perceives* multiple persons. The interpersonal_transparency
axiom requires modeling non-operator persons specifically to enforce consent.
The constraint is: person-modeling may only exist *in service of consent
enforcement*, never as a feature, collaboration model, or role system.

```
ConsentContract(parties=(operator, subject)) → ConsentRegistry  ✓
ConsentContract(parties=(user_a, user_b)) → CollaborationSpace ⊘
```

---

## Section 2: executive_function — Forbidden Governance Degradations

**Axiom**: executive_function (weight 95, constitutional)
**Principle**: Degrade toward safety. Errors include next actions. Routine work automated.

### F2.1 Denied Command Actuates ⊘

A Command whose governance_result records denial must not reach an Executor.

```
Command(governance_result=VetoResult(allowed=False))
  → ExecutorRegistry.dispatch(cmd) → ✗
  → Executor.execute(cmd) → ✗
```

**Why forbidden**: The VetoChain exists to prevent unsafe actuation. If a
denied Command can be dispatched by any code path that holds a registry
reference, governance is advisory rather than enforcing. The deny-wins
property of VetoChain is meaningless if the denial can be ignored downstream.

**Status**: `[gap]` — `ExecutorRegistry.dispatch()` (`executor.py:127`) does
not inspect `command.governance_result.allowed`. The field is provenance
metadata, not an enforcement gate.

### F2.2 Empty VetoChain Evaluates ⊘

A VetoChain with zero vetoes must not produce VetoResult(allowed=True).

```
VetoChain([]) → .evaluate(ctx) → VetoResult(allowed=True) ⊘
```

**Why forbidden**: An empty chain is vacuously permissive — it allows
everything because nothing can deny. This violates the principle that
governance must degrade toward safety. If a composition step fails to add
vetoes (exception swallowed, config missing), the chain silently becomes
maximally permissive.

**Status**: `[convention]` — `VetoChain.__init__` (`governance.py:78`)
accepts None or empty list.

### F2.3 Governance Constraints Removed After Construction ⊘

A VetoChain's constraint set must be monotonically non-decreasing.

```
VetoChain([v1, v2, v3])
  → chain._vetoes.pop(0) → ✗
  → chain._vetoes.clear() → ✗
  → chain._vetoes = [] → ✗
```

**Why forbidden**: The docstring states "adding a veto can only make the
system more restrictive, never less." Removing a veto relaxes governance.
The VetoChain should be append-only.

**Status**: `[convention]` — `_vetoes` is a mutable list behind `__slots__`.
No `remove()` method exists, but private attribute access permits mutation.
Contrast with Command, Schedule, Stamped which are frozen dataclasses.

### F2.4 Stale Perception Produces Action ⊘

Governance must not produce a Command from stale perception data.

```
FreshnessResult(fresh_enough=False)
  → FallbackChain.select(ctx) → ✗
  → Command(...) → ✗
```

**Why forbidden**: Acting on stale data means acting on a state that may
no longer hold. The FreshnessGuard exists to reject decisions made on data
past its staleness threshold.

**Status**: `[enforced]` — `compose_mc_governance` (`mc_governance.py:227-229`)
and `compose_obs_governance` (`obs_governance.py:274-276`) both short-circuit
on `not freshness_result.fresh_enough`, emitting None.

### F2.5 Actuation Without Arbitration ⊘

When multiple governance chains claim the same physical resource, actuation
must not proceed without contention resolution.

```
compose_mc_governance → Schedule(resource="audio_output")
compose_obs_governance → Command(resource="audio_output")
  → ExecutorRegistry.dispatch(mc_cmd) → ✗ (without arbiter)
  → ExecutorRegistry.dispatch(obs_cmd) → ✗ (without arbiter)
```

The required sequence:

```
ResourceClaim(resource, chain, priority, command)
  → ResourceArbiter.claim(rc)
  → ResourceArbiter.drain_winners() → list[ResourceClaim]
  → ExecutorRegistry.dispatch(winner.command) ✓
```

**Why forbidden**: Two chains firing into the same physical resource (e.g.,
audio_output) simultaneously produces undefined behavior at the hardware level.
The ResourceArbiter exists precisely to resolve this.

**Status**: `[gap]` — ResourceArbiter is implemented (`arbiter.py`) and tested
but never instantiated or called in `__main__.py`. Both MC and OBS governance
dispatch directly to ExecutorRegistry.

### F2.6 Feedback Loop Unwired ⊘

Governance chains that read feedback Behaviors must have those Behaviors
wired to the actuation event stream.

```
compose_obs_governance reads ctx.get_sample("last_mc_fire")
  → wire_feedback_behaviors(actuation_event) not called → ✗
  → "last_mc_fire" missing from behaviors dict
  → KeyError or sentinel 0.0 forever
```

**Why forbidden**: The OBS `face_cam_mc_bias` candidate
(`obs_governance.py:174-178`) calls `_mc_fired_recently(ctx)` which reads
`last_mc_fire`. If feedback Behaviors are not wired, this cross-chain
coordination — the entire reason for the feedback loop design — silently
fails. The governance chain operates on incomplete state.

**Status**: `[gap]` — `wire_feedback_behaviors()` (`feedback.py:18`) exists
and is tested but is never called in `__main__.py`. `ExecutorRegistry.actuation_event`
is never connected to feedback Behaviors.

### F2.7 Session Lifecycle Without Governance ⊘

Session open/close must pass through governance evaluation.

```
HotkeyServer → "open" → session.open() → _start_pipeline() ⊘ (without governance)
WakeWordDetector → session.open() → _start_pipeline() ⊘ (without governance)
```

The required sequence:

```
trigger → Command(action="open_session") → VetoChain.evaluate(ctx) → VetoResult(allowed=True)
  → session.open() ✓
```

**Why forbidden**: Opening a voice session starts audio I/O and LLM inference.
During a detected conversation (`conversation_detected=True`), governance
should block session open to prevent the system from interjecting. Currently,
hotkeys and wake words open sessions directly — the perception loop's
PipelineGovernor can pause/withdraw *after* the session starts, but cannot
prevent the initial open.

**Status**: `[gap]` — `_handle_hotkey` (`__main__.py:655-682`) and
`_wake_word_processor` (`__main__.py:632-653`) call `session.open()` without
constructing a Command or evaluating a VetoChain.

---

## Section 3: interpersonal_transparency — Forbidden Person-Data Flows

**Axiom**: interpersonal_transparency (weight 88, constitutional)
**Principle**: No persistent state about non-operator persons without active consent.

### F3.1 Biometric Processing Without Consent ⊘

No biometric data from a non-operator person may be processed without
a consent contract check.

```
AudioBytes × person_id ≠ operator
  → SpeakerIdentifier.identify_audio(audio) → ✗ (without contract_check)
  → pyannote.embed(audio) → ✗ (without contract_check)
```

The required sequence:

```
AudioBytes × person_id
  → ConsentRegistry.contract_check(person_id, "biometric") → True
  → SpeakerIdentifier.identify_audio(audio) ✓
```

**Why forbidden**: Extracting a speaker embedding from audio is biometric
processing. The interpersonal_transparency axiom requires consent before
maintaining persistent state about non-operator persons. A speaker embedding
is a biometric template — even if not saved to disk, computing it processes
personal data.

**Status**: `[gap]` — `SpeakerIdentifier.identify_audio()` (`speaker_id.py:130-138`)
has no consent check. Pyannote embeddings are extracted from any audio that
triggers speaker identification.

### F3.2 Biometric Persistence Without Consent ⊘

No biometric template may be persisted to disk without a consent contract.

```
SpeakerEmbedding × person_id ≠ operator
  → np.save(path, embedding) → ✗ (without contract_check)
```

The required sequence:

```
SpeakerEmbedding × person_id
  → ConsentRegistry.contract_check(person_id, "biometric") → True
  → ConsentContract.scope contains "biometric" → True
  → np.save(path, embedding) ✓
```

**Why forbidden**: `SpeakerIdentifier.enroll()` (`speaker_id.py:140-149`)
saves numpy arrays to disk. This is the most literal violation of
"no persistent state without active consent" — biometric data written to
the filesystem with no consent check.

**Status**: `[gap]` — no consent check in `enroll()`.

### F3.3 Person-Linked Behavior Without Consent Gate ⊘

No Behavior carrying data about an identified non-operator person may be
updated without passing through a consent gate.

```
PerceptionBackend.contribute(behaviors)
  → Behavior[PersonLinkedData].update(visitor_data, now) → ✗ (without consent)
```

The required sequence:

```
PerceptionBackend.contribute(behaviors)
  → ConsentRegistry.contract_check(person_id, data_category) → True
  → Behavior[PersonLinkedData].update(data, now) ✓
```

**Why forbidden**: `Behavior[T]` is parametric over T. Nothing in the type
system distinguishes `Behavior[float]` (audio energy — environmental) from
`Behavior[PersonIdentity]` (who is present — person-linked). The consent
gate must be called at the ingestion boundary, before Behavior update.

Implication `it-backend-001` (T1) requires this. Zero backends implement it.

**Status**: `[gap]` — no `ConsentRegistry` instance is created in daemon
startup. No call to `contract_check()` exists in any backend. The
`axioms/contracts/` directory contains only `.gitkeep`.

### F3.4 Transient Perception Becoming Persistent ⊘

Environmental perception (transient) must not become persistent state about
an identified person without consent.

```
FaceResult(count=2) → EnvironmentState(face_count=2)          ✓ (transient)
EnvironmentState(face_count=2) → EventLog.emit("face_count=2") ⊘ (persistent)
EnvironmentState × person_id → Qdrant.upsert(person_vector)   ⊘ (persistent)
EnvironmentState × person_id → profiles/person.md              ⊘ (persistent)
```

**Why forbidden**: Implication `it-environmental-001` (T2) says transient
perception doesn't require consent *if no persistent state about a specific
identified person is derived or stored*. The boundary between transient and
persistent is where consent enforcement must engage. Currently this boundary
is not typed — nothing in the system distinguishes a transient read from a
persistent write.

**Status**: `[convention]` — no type-level boundary between transient
perception and persistent storage. Event logs currently record perception
ticks with `face_count` and timestamps, which could be interpreted as
temporal records of non-operator presence.

### F3.5 Guest Data Collection Without Data Gate ⊘

Guest mode must restrict perception collection, not only LLM tool access.

```
VoiceLifecycle.is_guest_mode = True
  → PerceptionEngine.tick() → EnvironmentState  ⊘ (same collection as operator)
  → FaceDetector.detect(frame)                   ⊘ (same collection as operator)
```

The required sequence:

```
VoiceLifecycle.is_guest_mode = True
  → PerceptionEngine.tick() with consent-scoped backends ✓
  → FaceDetector skipped or results not persisted ✓
```

**Why forbidden**: Guest mode (`session.py:39-40`) disables LLM tools
(`tools.py:229-232`) and routes to a restricted prompt. But perception
continues — face detection runs every 8 seconds, VAD processes all audio.
The guest restriction is behavioral (what the LLM can do) not data-gated
(what the system collects). Per interpersonal_transparency, collection
itself requires justification.

**Status**: `[convention]` — guest mode is a flag that affects LLM routing,
not perception scope.

---

## Section 4: corporate_boundary — Forbidden Provider Paths

**Axiom**: corporate_boundary (weight 90, domain: infrastructure)
**Principle**: All API calls through sanctioned providers. Degrade gracefully.

### F4.1 Direct Provider API Call ⊘

No LLM call may bypass the LiteLLM gateway.

```
google.genai.Client(api_key) → direct Google API ⊘
openai.AsyncOpenAI(base_url=direct_endpoint) ⊘
ollama.Client() → direct Ollama ⊘ (when corporate_boundary active)
```

The required sequence:

```
shared.config.get_model(alias) → model_name
  → litellm.completion(model=model_name, ...) ✓
  → LiteLLM routes to configured provider ✓
```

**Why forbidden**: LiteLLM provides: (a) corporate provider routing —
employer-sanctioned APIs only, (b) Langfuse observability — all calls
traced, (c) fallback/retry — provider failures handled uniformly. Direct
client instantiation bypasses all three.

**Status**: `[gap]` — Gemini Live (`gemini_live.py:44-64`) uses `google.genai`
directly. Workspace/screen analyzers use `AsyncOpenAI` with a `base_url`
that defaults to LiteLLM but can be overridden via environment variable.

### F4.2 Home Service Failure Crashes ⊘

Home-only service unavailability must degrade, not crash.

```
OllamaClient.embed(model, input)
  → ConnectionError → RuntimeError ⊘
```

The required sequence:

```
OllamaClient.embed(model, input)
  → ConnectionError → fallback or graceful None ✓
```

**Why forbidden**: The axiom says "degrade gracefully when home-only services
are unreachable." `shared/config.py:148-150` raises `RuntimeError` on Ollama
connection failure — no fallback, no degradation.

**Status**: `[gap]` — Ollama embedding path raises on failure.

---

## Section 5: management_governance — Forbidden Feedback Compositions

**Axiom**: management_governance (weight 85, domain: management)
**Principle**: LLMs prepare, humans deliver. No generated feedback about individuals.

### F5.1 Person-Linked Feedback Types ⊘

No type may compose person identity with evaluative language.

```
person_id × recommendation: str ⊘
person_id × performance_score: float ⊘
person_id × coaching_hypothesis: str ⊘
Behavior[T] × person_id × "improvement" ⊘
```

**Why forbidden**: The axiom prohibits generating "feedback language, coaching
hypotheses, or recommendations about individual team members." This is not
about preventing a specific class name — it's about preventing the *composition*
of person identity with evaluative content at the type level. A
`Behavior[dict]` carrying `{"person": "alice", "score": 0.7}` violates
the axiom even though no `IndividualFeedback` type exists.

**Status**: `[convention]` — no such types exist. PipelineGovernor
(`governor.py:41-62`) scans workspace_context against keyword patterns
(`feedback|coaching|performance.review`) but this is reactive string
matching, not structural type prevention.

### F5.2 Voice Pipeline Generates Individual Feedback ⊘

The voice pipeline must not produce evaluative language about identified persons.

```
VoiceSession × guest_present
  → LLM.generate("evaluate this person's performance") → ✗
  → TTS.synthesize(feedback_about_individual) → ✗
```

**Why forbidden**: The voice pipeline has access to LLM inference and TTS
output. If a guest is present and the operator asks the system to "give me
feedback on how they're doing," the system must refuse — the axiom applies
to LLM-generated feedback, not just stored types.

**Status**: `[convention]` — guest system prompt restricts tool access but
does not explicitly prohibit feedback generation about the guest or others.
Compliance rule keyword matching in PipelineGovernor provides partial coverage.

---

## Section 6: Cross-Axiom Compositions

Some forbidden sequences arise from the *interaction* of multiple axioms.

### F6.1 Consent Infrastructure Becomes Collaboration ⊘

**Axioms**: single_user (100) × interpersonal_transparency (88)

```
ConsentContract(parties=(operator, subject))
  → subject.inspect_data() → Dashboard[subject_view] ⊘
  → subject.configure_preferences() ⊘
  → subject.grant_permissions() ⊘
```

The consent contract gives subjects *inspection access* to their data
(`it-inspect-001`). This must not become a collaboration interface.
Inspection is read-only, operator-mediated — the subject asks the operator,
the operator queries the system. No direct subject-facing UI, API, or
self-service portal.

**Status**: `[convention]` — consent infrastructure is server-side only.
No subject-facing interface exists.

### F6.2 Environmental Perception Feeds Individual Evaluation ⊘

**Axioms**: interpersonal_transparency (88) × management_governance (85)

```
EnvironmentState(face_count=2, conversation_detected=True)
  → LLM.analyze("who is underperforming in this conversation") → ✗
  → Behavior[PersonEvaluation] → ✗
```

Transient environmental perception (face count, conversation detection)
must not feed into person-linked evaluative analysis. The environmental
exception (`it-environmental-001`) permits transient perception — but
routing that perception into management_governance-violating analysis
compounds both axioms.

**Status**: `[convention]` — no such analysis exists. PipelineGovernor
compliance rules provide partial keyword coverage.

---

## Section 7: Glossary of Forbidden Types

Types that must not exist in the system. This is the complement of the
North Star's Section 7 glossary.

| Forbidden Type | Violates | Status |
|----------------|----------|--------|
| `User` | single_user | `[enforced]` — does not exist, hooks scan |
| `Role` | single_user | `[enforced]` — does not exist, hooks scan |
| `Permission` | single_user | `[enforced]` — does not exist, hooks scan |
| `AuthMiddleware` | single_user | `[enforced]` — does not exist, hooks scan |
| `IndividualFeedback` | management_governance | `[convention]` — does not exist |
| `CoachingHypothesis` | management_governance | `[convention]` — does not exist |
| `PersonPerformanceBehavior` | management_governance | `[convention]` — does not exist |
| `PersonEvaluation` | management_governance × interpersonal_transparency | `[convention]` |
| `CollaborationSpace` | single_user | `[convention]` — does not exist |
| `DirectProviderClient` | corporate_boundary | `[gap]` — Gemini Live uses one |
| `UnconsentedPersonBehavior` | interpersonal_transparency | `[gap]` — speaker_id does this |

---

## Section 8: Relationship to Enforcement Gaps

This spec defines *what must not be constructible*. A companion document,
`2026-03-13-enforcement-gaps.md`, catalogs the code-level findings about
*where the current implementation fails to enforce* these constraints:

- Governance bypass paths (dispatch ignoring allowed, hotkey bypass, etc.)
- Type system escape hatches (Behavior[T] runtime erasure, dict[str, Any])
- Concurrency hazards (thread races on shared mutable state)
- Wiring gaps (ResourceArbiter, feedback loop, consent registry not connected)

Those are implementation deficits, not domain constraints. The Dog Star
defines the shape of the forbidden space; the enforcement gaps doc maps
where the boundary is porous.
