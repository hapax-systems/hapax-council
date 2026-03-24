# Creativity Activation and "Losing is Fun" Operationalization

**Status:** Design (behavioral mode specification)
**Date:** 2026-03-24
**Builds on:** Fortress Suppression Topology, Fortress Governance Chains, Fortress Metrics

This specification formalizes the "losing is fun" meta-goal as a measurable creativity activation system. Creativity activation is modeled as a neuroception-gated, stress-modulated behavioral mode that interacts with the existing suppression field topology.

---

## 1. Design Principles

1. Creativity does not peak in the absence of stress. The Yerkes-Dodson law (Yerkes & Dodson, 1908) establishes an inverted-U relationship between arousal and performance on complex tasks. Csikszentmihalyi's flow model (1990) identifies optimal experience at the boundary between challenge and skill, corresponding to moderate arousal.

2. Creativity is a distinct behavioral mode gated by perceived safety. Panksepp's affective neuroscience framework (1998) identifies PLAY as one of seven primary-process emotional systems, structurally independent of SEEKING. The PLAY system requires a baseline of safety to activate. Porges' polyvagal theory (2011) provides the mechanism: ventral vagal engagement (social safety) is a prerequisite for exploratory behavior.

3. Under threat, organisms restrict information processing and revert to known-good responses. Staw, Sandelands, and Dutton (1981) document this as the threat-rigidity effect: threat narrows the repertoire of responses and centralizes control. In the fortress context, this maps directly to suppression field behavior.

4. The transition is asymmetric. Threat kills creativity rapidly (attack time: 0.5s); safety restores it slowly (release time: 10.0s). This asymmetry reflects the biological priority of threat detection over opportunity detection (LeDoux, 1996).

5. "Interesting over safe" is operationalized as decision entropy modulated by semantic connections. A creative decision is one that increases policy entropy while maintaining coherence with the fortress narrative.

6. Story over mechanics, but survival-adjusted. Pure novelty is not the objective. Creativity score is multiplied by survival time, penalizing strategies that produce interesting narratives but immediate death.

---

## 2. Creativity Suppression Field

A new `SuppressionField` instance: `creativity_suppression`.

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Target | `max(crisis_suppression.value, military_alert.value, resource_pressure.value)` | Creativity suppresses when any threat-related field is active |
| Attack | 0.5s | Creative momentum has inertia — slower than crisis (0.3s) but still fast |
| Release | 10.0s | Safety must be confirmed before play resumes — twice crisis release (5.0s) |
| Floor | 0.05 | Residual creativity aids threat recovery (Fredrickson's broaden-and-build; Tugade & Fredrickson, 2004) |
| Ceiling | 0.90 | Less aggressive than crisis ceiling (0.95) — some creativity leaks through even under pressure |

The field follows the same exponential attack/release envelope as the existing suppression fields, computed per perception tick.

---

## 3. Creativity Activation Bell Curve

Creativity activation follows a Gaussian curve centered on moderate stress, implementing the Yerkes-Dodson inverted-U for complex tasks.

```python
def creativity_activation(stress: float) -> float:
    """Bell curve: peaks at CAUTIOUS stance, falls off toward NOMINAL and DEGRADED."""
    center = 0.4  # optimal stress for complex creative tasks
    width = 0.2   # standard deviation
    return math.exp(-((stress - center) ** 2) / (2 * width ** 2))
```

Activation values by stimmung stance:

| Stimmung Stance | Stress Range | Activation | Behavioral Mode |
|-----------------|-------------|------------|-----------------|
| NOMINAL (<0.3) | Low | 0.40 | Comfortable — efficient but uncreative |
| CAUTIOUS (0.3–0.6) | Moderate | **0.95** | **Flow zone — creative peak** |
| DEGRADED (0.6–0.85) | High | 0.20 | Threat-rigid — narrowed repertoire |
| CRITICAL (>0.85) | Extreme | 0.05 | Survival — overlearned responses only |

At NOMINAL, the fortress is comfortable enough that there is insufficient arousal to drive creative exploration. At CAUTIOUS, challenge and capability are balanced. At DEGRADED and above, threat-rigidity dominates.

---

## 4. Neuroception Gate

A fast-path safety check (Porges, 2004) evaluated before the suppression field is consulted. Neuroception is the organism's pre-conscious evaluation of environmental safety.

```python
def neuroception_safe(stimmung_worst: float) -> bool:
    """Pre-conscious safety gate. If unsafe, creativity is structurally unavailable."""
    return stimmung_worst < 0.7
```

If `neuroception_safe()` returns `False`, the `CreativityChain` is not instantiated in the evaluation loop. This is a structural gate, not a parametric one: the chain does not exist in the subsumption hierarchy when the gate is closed. No suppression field value can override this.

The threshold of 0.7 corresponds to the boundary between CAUTIOUS and DEGRADED stances. Below this threshold, the organism (fortress) has sufficient ventral vagal engagement to support exploratory behavior.

---

## 5. Creativity Epsilon

The exploration-exploitation parameter is modulated by available creativity:

```python
creativity_available = creativity_activation(stress) * (1.0 - creativity_suppression.value)
creativity_available = max(creativity_floor, min(1.0, creativity_available))
epsilon = base_epsilon * creativity_available
```

Where `base_epsilon = 0.30` and `creativity_floor = 0.05`. Epsilon controls the probability that the fortress planner selects a novel action over a known-good pattern.

Under threat-rigidity (Staw et al., 1981), the `FallbackChain` evaluates fewer candidates:

```python
n_candidates = ceil(total_candidates * (1.0 - rigidity_factor))
rigidity_factor = max(crisis_suppression, military_alert) * 0.8
```

At maximum crisis suppression (1.0), only 20% of candidates are evaluated. This models the narrowing of behavioral repertoire documented in threat-rigidity research.

---

## 6. Semantic Injection Mechanism

Dwarves, squads, rooms, and locations are named after Hapax system concepts. This creates a bidirectional mapping between the fortress narrative and the operator's cognitive environment.

Injection points:

- **Unit nicknames** (`dfhack.units.setNickname`): Named after agents, dimensions, stimmung states.
- **Personality facets and beliefs** (`assign-facets`, `assign-beliefs`): Derived from Hapax profile dimensions.
- **Goals and dreams** (`assign-goals`): Set from active `CompoundGoal` instances.
- **Squad names**: Named after governance chains.
- **Location names**: Named after system concepts (e.g., library = "Archive of Stimmung").
- **Announcements** (`dfhack.gui.makeAnnouncement`): Inject system events as fortress lore.

Profile generation pipeline:

1. Python script queries Logos API endpoints (`/profile`, `/agents`, `/goals`, `/status`).
2. API responses are mapped to Dwarf Fortress personality tokens (facets, beliefs, goals).
3. Output is written to `dfhack-config/hapax/profiles.json`.
4. Lua script applies profiles at embark and on migrant arrival via `onMapLoad` and `onUnitNewActive` hooks.

---

## 7. Creativity Metrics

A composite scorecard quantifies creativity as a multidimensional construct.

```python
creativity_score = (
    w1 * policy_entropy          # behavioral diversity (trivial to compute)
  + w2 * novelty_score           # k-NN distance from prior decisions
  + w3 * narrative_density       # episodes per unit time
  + w4 * causal_depth            # longest chain in event DAG
  + w5 * semantic_injection_rate # decisions referencing external knowledge
  + w6 * compression_progress    # Schmidhuber: learnable surprise
  - w7 * failure_repetition      # penalize boring failures
)

# Survival-adjusted creativity
adjusted = creativity_score * survival_time
```

Individual metric definitions:

- **Policy entropy**: `H(pi) = -sum(p(a) * log(p(a)))` over action distributions per chain. Measures behavioral diversity. Higher entropy indicates a wider range of actions being selected.

- **Novelty score**: `1 - max_similarity(decision, inspiration_set)` via embedding distance. Measures how different each decision is from the set of prior decisions. Computed using cosine distance in the same embedding space as Qdrant collections.

- **Narrative density**: `significant_episodes / game_years`. Counts episodes that pass a significance threshold (causal depth >= 2 or involving named units). Higher density indicates a more eventful fortress history.

- **Causal depth**: Longest chain in the event DAG. Each event records its causal antecedents. Deep causal chains indicate complex emergent narratives.

- **Semantic injection rate**: `decisions_with_external_reference / total_decisions`. Measures how frequently fortress decisions are informed by Hapax system concepts rather than pure game mechanics.

- **Compression progress**: `delta(world_model_loss)` after each episode (Schmidhuber, 2010). Requires a learned world model. Positive compression progress indicates the fortress is generating learnable surprises — novel events that become predictable after observation.

- **Failure repetition**: Counts repeated failure modes (same cause of death, same resource shortage). Penalized because repeated failures indicate the system is not learning.

---

## 8. The Creativity Chain

A new governance chain: `CreativityChain`, placed at Layer 3.5 in the subsumption hierarchy (between Storyteller at Layer 3 and Crisis at Layer 4).

| Property | Value |
|----------|-------|
| Trigger | Perception tick (same cadence as `resource_manager`) |
| Input | `FortressState` + `creativity_available` + `SpatialMemory` novelty scores |
| VetoChain | `neuroception_gate` (hard gate), `creativity_suppression` (soft gate) |
| FallbackChain | See below |
| Output | Commands that modify the fortress for narrative/aesthetic reasons |
| Publishes | No suppression fields (creativity is additive only — it never suppresses other roles) |

FallbackChain candidates, evaluated in order:

1. **`semantic_naming`**: Name a unit, squad, or location using a Hapax system concept. Lowest cost, highest semantic injection rate.
2. **`architectural_experiment`**: Attempt a novel room layout or spatial configuration not in the blueprint library. Moderate cost, high novelty score.
3. **`social_engineering`**: Create interesting dwarf relationships (assign dwarves to shared quarters, workshops, or squads based on personality compatibility or deliberate contrast). Moderate cost, high narrative density.
4. **`aesthetic_enrichment`**: Commission engravings, sculptures, or decorations. Low-moderate cost, contributes to causal depth when engravings reference fortress history.
5. **`no_action`**: Take no creative action this tick. Selected when creativity_available is low or all candidates are vetoed.

The creativity chain is additive: it issues commands alongside other chains, never instead of them. It cannot suppress resource management, military response, or crisis handling.

---

## 9. Maslow Gate

The creativity chain evaluates only when lower Maslow levels are satisfied (Maslow, 1943). This implements a prerequisite chain that gates creative behavior behind physiological, safety, and social needs.

```python
def maslow_gate(state: FortressState) -> bool:
    """Creativity requires lower needs to be met."""
    # Level 0: Physiological
    if state.food_count < state.population * 5:
        return False
    if state.drink_count < state.population * 3:
        return False

    # Level 1: Safety
    if state.active_threats > 0:
        return False
    if state.most_stressed_value >= 100_000:
        return False

    # Level 2: Social
    if state.idle_dwarf_count >= state.population * 0.3:
        return False

    return True
```

All three levels must pass before `creativity_activation()` is computed. A fortress that is starving, under siege, or experiencing mass unemployment does not engage in creative exploration.

The Maslow gate is evaluated before the neuroception gate. The evaluation order is:

1. Maslow gate (prerequisite)
2. Neuroception gate (structural)
3. Creativity suppression field (parametric)
4. Creativity activation curve (modulation)

---

## 10. Integration with Existing Architecture

- `creativity_suppression` is a new `SuppressionField` created alongside the existing four fields in `create_fortress_suppression_fields()`.
- `creativity_activation()` is a pure function located in `agents/fortress/creativity.py`.
- `CreativityChain` follows the same structural pattern as other chains: `VetoChain` + `FallbackChain` + `evaluate()`.
- `SemanticNamingEngine` generates profiles via the Logos API and applies them via DFHack Lua scripts.
- Creativity metrics are logged alongside existing `FortressSessionTracker` chain metrics.
- The creativity suppression field target depends on three existing fields (`crisis_suppression`, `military_alert`, `resource_pressure`), creating a derived dependency rather than an independent signal.
- No existing chain behavior is modified. The creativity chain is purely additive.

---

## References

- Csikszentmihalyi, M. (1990). *Flow: The Psychology of Optimal Experience*. Harper & Row.
- Fredrickson, B. L. (2001). The role of positive emotions in positive psychology: The broaden-and-build theory of positive emotions. *American Psychologist*, 56(3), 218–226.
- LeDoux, J. E. (1996). *The Emotional Brain*. Simon & Schuster.
- Maslow, A. H. (1943). A theory of human motivation. *Psychological Review*, 50(4), 370–396.
- Panksepp, J. (1998). *Affective Neuroscience: The Foundations of Human and Animal Emotions*. Oxford University Press.
- Porges, S. W. (2004). Neuroception: A subconscious system for detecting threats and safety. *Zero to Three*, 24(5), 19–24.
- Porges, S. W. (2011). *The Polyvagal Theory*. W. W. Norton.
- Schmidhuber, J. (2010). Formal theory of creativity, fun, and intrinsic motivation (1990–2010). *IEEE Transactions on Autonomous Mental Development*, 2(3), 230–247.
- Staw, B. M., Sandelands, L. E., & Dutton, J. E. (1981). Threat-rigidity effects in organizational behavior: A multilevel analysis. *Administrative Science Quarterly*, 26(4), 501–524.
- Tugade, M. M., & Fredrickson, B. L. (2004). Resilient individuals use positive emotions to bounce back from negative emotional experiences. *Journal of Personality and Social Psychology*, 86(2), 320–333.
- Yerkes, R. M., & Dodson, J. D. (1908). The relation of strength of stimulus to rapidity of habit-formation. *Journal of Comparative Neurology and Psychology*, 18(5), 459–482.
