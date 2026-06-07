"""Surprise computation — the single, learned surprise currency.

Surprise is read from the one system-wide source of truth: the
`InformationDensityField` `BayesianSurpriseModel` posterior (KL divergence over
a Normal-Inverse-Gamma online model, persisted per-source to
``/dev/shm/hapax-density-field/state.json``). A protention prediction only
selects *which* field — and therefore which density source — to report surprise
for; the surprise value itself is never computed here.

This replaces the former hardcoded ``predicted_state`` -> expected-value rule
table (an expert-system artifact that forked the surprise SSOT and computed
surprise from prediction confidence). See
REQ-20260605-temporal-surprise-idf-posterior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agents.temporal_models import ProtentionEntry, SurpriseField
from shared.information_density import InformationDensityField

# Routing table (NOT a rule table): maps a protention prediction to the
# perception field it concerns. It carries no thresholds and no expected
# outcomes — it only names the field whose density-source posterior to read.
_PREDICTION_FIELD: dict[str, str] = {
    "entering_deep_work": "flow_state",
    "flow_continuing": "flow_state",
    "flow_breaking": "flow_state",
    "flow_ending": "flow_state",
    "flow_likely": "flow_state",
    "break_likely": "activity",
    "sustained_activity": "activity",
    "stress_rising": "heart_rate",
    "operator_departing": "presence",
    "operator_returning": "presence",
}
_DEFAULT_FIELD = "activity"

# Each field's InformationDensityField source — the BayesianSurpriseModel
# posterior that IS the surprise for that field. heart_rate and presence map to
# dedicated sources; flow_state and activity have no dedicated source yet and
# route through the closest live physical work-state posterior, desk.activity.
# Follow-up: dedicated perception.flow_score / activity sources
# (REQ-20260606-source-observations-producer,
# REQ-20260606-parametric-surprise-temporal).
_FIELD_SOURCE: dict[str, str] = {
    "flow_state": "desk.activity",
    "activity": "desk.activity",
    "heart_rate": "biometric.heart_rate",
    "presence": "perception.presence",
}


def _observed_value(field: str, current: Mapping[str, object]) -> str:
    """Render the current observed value of a field for display only.

    Display-only: this never influences the surprise value (which comes from
    the IDF posterior). No thresholds, no expected outcomes.
    """
    renderers: dict[str, object] = {
        "flow_state": lambda c: f"{float(c.get('flow_score', 0.0) or 0.0):.2f}",
        "activity": lambda c: str(c.get("production_activity", "") or "idle"),
        "heart_rate": lambda c: str(int(c.get("heart_rate_bpm", 0) or 0)),
        "presence": lambda c: f"p={float(c.get('presence_probability', 1.0) or 0.0):.2f}",
    }
    render = renderers.get(field)
    return render(current) if render else ""  # type: ignore[operator]


def _clamp_unit(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def compute_surprise(
    current: Mapping[str, object],
    last_protention: Sequence[ProtentionEntry],
    density_state: Mapping[str, object] | None = None,
) -> list[SurpriseField]:
    """Report surprise for predicted fields, sourced from the IDF posterior.

    For each prediction, the field it concerns is looked up and the matching
    density source's Bayesian-surprise posterior is read from ``density_state``
    (defaulting to the live density-field SHM). Predictions whose source has no
    posterior available produce no surprise — there is no rule-table fallback.
    """
    if not last_protention:
        return []

    if density_state is None:
        density_state = InformationDensityField.read_shm()
    sources: Mapping[str, object] = {}
    if density_state:
        raw_sources = density_state.get("sources")
        if isinstance(raw_sources, Mapping):
            sources = raw_sources
    if not sources:
        return []

    surprises: list[SurpriseField] = []
    for pred in last_protention:
        field = _PREDICTION_FIELD.get(pred.predicted_state, _DEFAULT_FIELD)
        source_id = _FIELD_SOURCE.get(field)
        source = sources.get(source_id) if source_id else None
        if not isinstance(source, Mapping):
            continue
        try:
            surprise = _clamp_unit(float(source.get("surprise", 0.0) or 0.0))
        except (TypeError, ValueError):
            # Corrupt/non-numeric SHM value — skip rather than crash. No rule
            # fallback: an unreadable posterior simply yields no surprise.
            continue
        surprises.append(
            SurpriseField(
                field=field,
                observed=_observed_value(field, current),
                expected=pred.predicted_state,
                surprise=surprise,
                note=source_id,
            )
        )

    # Collapse to one entry per field, keeping the highest surprise.
    seen: dict[str, SurpriseField] = {}
    for s in surprises:
        if s.field not in seen or s.surprise > seen[s.field].surprise:
            seen[s.field] = s
    return list(seen.values())
