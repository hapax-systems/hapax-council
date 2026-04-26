# hapax-refusals

**Surface-floored RefusalGate as a drop-in re-roll wrapper for any LLM
emission point.**

`hapax-refusals` extracts the R-Tuning post-emission verifier and the
refusal-as-data registry that sit between the Hapax LLM tier and every
narration surface in the upstream operating environment. The library
ships:

- A **calibrated per-surface posterior floor taxonomy** (0.60 director
  → 0.90 grounding-act).
- **`RefusalGate`** — scans an LLM emission for declarative
  assertions, matches them against a registered set of `ClaimSpec`
  posteriors, and rejects any below-floor or unmatched assertion.
- **`refuse_and_reroll`** — the **CORE export**: a re-roll-on-refuse
  wrapper around any callable LLM call. Pass the wrapper your
  one-shot LLM function and it returns a bounded re-roll loop with a
  stricter prompt addendum on each retry.
- **`RefusalEvent` + `RefusalRegistry`** — append-only JSONL log of
  every refusal as structured data, not narrative.

Constitutional fit (Hapax provenance): refusals are first-class
**data**, not apologies. Every gate firing becomes a citable record;
downstream calibration work reads the log directly.

## Why this shape

R-Tuning (Zhang et al., NAACL 2024 — arXiv 2311.09677) trains models
to refuse rather than over-commit. `hapax-refusals` implements the
**post-hoc verifier branch**: the model emits, we check, we reject +
re-roll if the emission asserts something the upstream sensor pipeline
hasn't actually established with enough posterior confidence.

The asymmetric per-surface floors are calibrated to surface
brittleness:

| Surface              | Floor | Rationale                                  |
|----------------------|-------|--------------------------------------------|
| `director`           |  0.60 | Audible to viewers; retraction is costly   |
| `spontaneous_speech` |  0.70 | Unprompted emission; self-initiated bar    |
| `autonomous_narrative` |  0.75 | Director-over-director; compounding cost  |
| `voice_persona`      |  0.80 | Direct conversation; max-intimacy cost     |
| `grounding_act`      |  0.90 | T4 Jemeinigkeit requires conviction        |

Numeric posteriors (rather than verbal qualifiers) outperform "likely"
/ "possibly" by ~50 % on ECE — Tian et al., EMNLP 2023.

## Install

```sh
uv pip install hapax-refusals
# or
pip install hapax-refusals
```

`hapax-refusals` depends only on `pydantic >= 2.10`. Optional
`prometheus-client` integration is available via the `metrics` extra:

```sh
pip install 'hapax-refusals[metrics]'
```

## Quick start — wrap an LLM call

```python
from hapax_refusals import (
    ClaimSpec,
    RefusalGate,
    refuse_and_reroll,
)

# 1. Describe the calibrated claims your sensor pipeline currently asserts.
available_claims = [
    ClaimSpec(
        name="vinyl_is_playing",
        posterior=0.42,            # below the director 0.60 floor
        proposition="Vinyl is currently playing.",
    ),
    ClaimSpec(
        name="operator_is_present",
        posterior=0.91,            # above every floor
        proposition="The operator is at the desk.",
    ),
]

# 2. Construct a gate for the surface.
gate = RefusalGate(surface="director")

# 3. Wrap your one-shot LLM call.
def call_llm(addendum: str | None) -> str:
    system = base_system_prompt
    if addendum:
        system += "\n\n" + addendum
    return litellm.completion(
        model="claude-opus-4",
        messages=[{"role": "system", "content": system}, ...],
    ).choices[0].message.content

text, result, attempts = refuse_and_reroll(
    call_llm,
    gate=gate,
    available_claims=available_claims,
    max_rerolls=1,
)

if not result.accepted:
    # The gate could not find a clean emission. Caller decides:
    # drop the emission, fall through, or escalate.
    log.warning("dropped after %d attempts: %r",
                attempts, result.rejected_propositions)
    text = ""
```

## Surface-floor utilities

```python
from hapax_refusals import floor_for, SURFACE_FLOORS

assert floor_for("director") == 0.60
assert floor_for("grounding_act") == 0.90

# The dict is sorted by floor, ascending — useful for picking a
# default surface.
for name, floor in SURFACE_FLOORS.items():
    print(f"{name:>22s}  {floor:.2f}")
```

## Refusal-as-data registry

Every gate firing logs a structured event to an append-only JSONL
file. Default path: `/dev/shm/hapax-refusals/log.jsonl` (RAM-only,
fast, fail-cheap). Override with `HAPAX_REFUSALS_LOG_PATH`.

```python
from hapax_refusals import RefusalEvent, RefusalRegistry
from datetime import UTC, datetime

registry = RefusalRegistry()
registry.append(RefusalEvent(
    timestamp=datetime.now(UTC),
    axiom="claim_below_floor",
    surface="refusal_gate:director",
    reason="vinyl_is_playing posterior 0.42 < director floor 0.60",
))
```

The log has no rotation, no aggregation, no rollover. Consumers
(dashboards, omg.lol publishers, calibration sweeps) read from it.

## Modules

| Module | Purpose |
|---|---|
| `hapax_refusals.gate`      | `RefusalGate`, `RefusalResult`, `refuse_and_reroll`, `claim_discipline_score`. |
| `hapax_refusals.claim`     | `ClaimSpec` — minimal claim model (`name`, `posterior`, `proposition`). |
| `hapax_refusals.surface`   | `SURFACE_FLOORS`, `NarrationSurface`, `floor_for`. |
| `hapax_refusals.registry`  | `RefusalEvent`, `RefusalRegistry`, `REASON_MAX_CHARS`. |

## License — PolyForm Strict 1.0.0

This package is published under the **PolyForm Strict License 1.0.0**
(`LicenseRef-PolyForm-Strict-1.0.0`, see `LICENSE.txt`). PolyForm
Strict permits use, study, and verification of the software but
**reserves all modification, distribution, and commercial rights to
the licensor.** Read the license before adopting.

If you need a more permissive grant for a specific use, the licensor
may negotiate one — open an issue on the upstream `hapax-council`
repository.

## Authorship

Co-authored by **Hapax (Oudepode)** and **Claude Code (Anthropic)**.
The operator's contribution is structurally unsettled — not a bug, a
feature: per the methodology, that authorship indeterminacy is the
7th polysemic-surface channel, not a citation gap. See `CITATION.cff`
for the dual-authorship metadata.

## Constitutional fit

`hapax-refusals` is a **single-operator** library. It carries no
auth, no roles, no multi-user code paths. The "surface" axis is a
narration-context axis, not an access-control axis.

This matches Hapax's constitutional axioms (`single_user`,
`executive_function`, `interpersonal_transparency`). Downstream users
inherit the same shape: build LLM emission paths that surface
calibrated refusals as data.

## See also

- `hapax-council` — full operating environment this package was
  extracted from.
- `hapax-swarm` — sibling PyPI package: filesystem-as-bus
  multi-session coordination.
- `hapax-velocity-meter` — sibling PyPI package: development velocity
  measured from any git history.

## References

- Zhang et al., **R-Tuning: Instructing LLMs to Say "I Don't Know"**,
  NAACL 2024 (arXiv 2311.09677).
- Tian et al., **Just Ask for Calibration**, EMNLP 2023.
- Hapax universal-Bayesian-claim-confidence research note,
  `docs/research/2026-04-24-universal-bayesian-claim-confidence.md` in
  the upstream repo.
