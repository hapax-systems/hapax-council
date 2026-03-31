"""Surprise computation — compare protention predictions against observed state.

Surprise = high-confidence prediction that was wrong.
Confirmation = high-confidence prediction that was right (surprise=0).
Fields not predicted have no surprise score.
"""

from __future__ import annotations

from agents.temporal_models import ProtentionEntry, SurpriseField


def compute_surprise(
    current: dict[str, object], last_protention: list[ProtentionEntry]
) -> list[SurpriseField]:
    """Compare current state against previous protention predictions."""
    if not last_protention:
        return []

    surprises: list[SurpriseField] = []
    flow_score = float(current.get("flow_score", 0.0))
    flow_state = "active" if flow_score >= 0.6 else ("warming" if flow_score >= 0.3 else "idle")
    activity = current.get("production_activity", "")

    for pred in last_protention:
        sf = _match_prediction(pred, flow_state, activity, current)
        if sf is not None:
            surprises.append(sf)

    seen: dict[str, SurpriseField] = {}
    for s in surprises:
        if s.field not in seen or s.surprise > seen[s.field].surprise:
            seen[s.field] = s
    return list(seen.values())


def _match_prediction(
    pred: ProtentionEntry,
    flow_state: str,
    activity: str,
    current: dict[str, object],
) -> SurpriseField | None:
    """Match a single prediction against observed state."""
    if pred.predicted_state in ("entering_deep_work", "flow_continuing"):
        m = flow_state == "active"
        return SurpriseField(
            field="flow_state",
            observed=flow_state,
            expected="active",
            surprise=0.0 if m else pred.confidence,
            note="" if m else f"predicted {pred.predicted_state}",
        )
    if pred.predicted_state in ("flow_breaking", "flow_ending"):
        m = flow_state != "active"
        return SurpriseField(
            field="flow_state",
            observed=flow_state,
            expected="idle",
            surprise=0.0 if m else pred.confidence,
            note="" if m else "flow persisted despite prediction",
        )
    if pred.predicted_state == "break_likely":
        m = activity in ("", "idle", "browsing")
        return SurpriseField(
            field="activity",
            observed=activity or "idle",
            expected="break",
            surprise=0.0 if m else pred.confidence,
            note="" if m else f"still {activity}",
        )
    if pred.predicted_state == "stress_rising":
        hr = int(current.get("heart_rate_bpm", 0))
        m = hr > 85
        return SurpriseField(
            field="heart_rate",
            observed=str(hr),
            expected=">85",
            surprise=0.0 if m else pred.confidence,
            note="" if m else "HR stabilized",
        )
    if pred.predicted_state == "sustained_activity":
        words = pred.basis.split() if pred.basis else []
        expected_act = words[-2] if len(words) >= 3 else ""
        m = (activity == expected_act) if expected_act else True
        return SurpriseField(
            field="activity",
            observed=activity or "idle",
            expected="sustained",
            surprise=0.0 if m else pred.confidence * 0.5,
            note="" if m else "activity changed unexpectedly",
        )
    if pred.predicted_state == "operator_departing":
        pp = float(current.get("presence_probability", 1.0))
        m = pp < 0.3
        return SurpriseField(
            field="presence",
            observed=f"p={pp:.2f}",
            expected="departing",
            surprise=0.0 if m else pred.confidence,
            note="" if m else "operator stayed",
        )
    if pred.predicted_state == "operator_returning":
        pp = float(current.get("presence_probability", 0.0))
        m = pp >= 0.7
        return SurpriseField(
            field="presence",
            observed=f"p={pp:.2f}",
            expected="returning",
            surprise=0.0 if m else pred.confidence,
            note="" if m else "operator still away",
        )
    if pred.predicted_state not in ("flow_likely", "sustained_activity"):
        if activity and activity != pred.predicted_state:
            return SurpriseField(
                field="activity",
                observed=activity,
                expected=pred.predicted_state,
                surprise=pred.confidence * 0.7,
                note=f"predicted {pred.predicted_state}, got {activity}",
            )
    return None
