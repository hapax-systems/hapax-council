"""Creativity activation — bell curve, neuroception gate, Maslow gate.

Formalizes "losing is fun" as a measurable behavioral mode.
See docs/superpowers/specs/2026-03-24-creativity-activation.md.
"""

from __future__ import annotations

import math

from agents.fortress.schema import FastFortressState


def creativity_activation(stress: float, center: float = 0.4, width: float = 0.2) -> float:
    """Gaussian bell curve: peaks at moderate stress, falls off toward safety and danger."""
    return math.exp(-((stress - center) ** 2) / (2 * width**2))


def neuroception_safe(normalized_stress: float, threshold: float = 0.7) -> bool:
    """Pre-conscious safety gate. If unsafe, creativity is structurally unavailable."""
    return normalized_stress < threshold


def maslow_gate(
    state: FastFortressState,
    food_per_capita: int = 5,
    drink_per_capita: int = 3,
    idle_ratio: float = 0.3,
    stress_threshold: int = 100_000,
) -> bool:
    """Maslow hierarchy prerequisite: lower needs must be satisfied."""
    pop = max(1, state.population)
    if state.food_count < pop * food_per_capita:
        return False
    if state.drink_count < pop * drink_per_capita:
        return False
    if state.active_threats > 0:
        return False
    if state.most_stressed_value > stress_threshold:
        return False
    return not state.idle_dwarf_count > pop * idle_ratio


def creativity_available(
    stress: float,
    suppression_value: float,
    floor: float = 0.05,
    center: float = 0.4,
    width: float = 0.2,
) -> float:
    """Composite creativity signal: activation * (1 - suppression), clamped."""
    activation = creativity_activation(stress, center, width)
    raw = activation * (1.0 - suppression_value)
    return max(floor, min(1.0, raw))


def creativity_epsilon(
    stress: float,
    suppression_value: float,
    base_epsilon: float = 0.30,
    floor: float = 0.05,
) -> float:
    """Exploration rate modulated by creativity signal."""
    available = creativity_available(stress, suppression_value, floor)
    return base_epsilon * available


def rigidity_factor(crisis_suppression: float, military_alert: float) -> float:
    """How much threat narrows the decision repertoire."""
    return max(crisis_suppression, military_alert) * 0.8


def n_candidates_under_rigidity(
    total: int,
    crisis_suppression: float,
    military_alert: float,
) -> int:
    """Number of FallbackChain candidates to evaluate under threat-rigidity."""
    rf = rigidity_factor(crisis_suppression, military_alert)
    return max(1, math.ceil(total * (1.0 - rf)))
