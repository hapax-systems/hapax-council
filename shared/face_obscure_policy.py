"""Facial-obscuring policy enum (task #129 — HARD privacy requirement).

Privacy axiom `it-irreversible-broadcast` (T0) forbids identifiable non-operator
faces from reaching any egress tee. The operator extended this constraint on
2026-04-18 to cover their own face as well.

This module defines the three valid policy states that the per-camera face
obscuring stage honors. The default (`ALWAYS_OBSCURE`) is chosen for fail-safe
behavior: if the policy configuration is ever missing, misread, or corrupted,
the system obscures everyone rather than risking a leak.

Spec: `docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md`.
Dossier: `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` §2
(task #129).
"""

from __future__ import annotations

import os
from enum import StrEnum

_ACTIVE_ENV_VAR = "HAPAX_FACE_OBSCURE_ACTIVE"
_POLICY_ENV_VAR = "HAPAX_FACE_OBSCURE_POLICY"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})


class FaceObscurePolicy(StrEnum):
    """Governs which detected faces receive the obscure mask.

    Values are `str` so the enum round-trips cleanly through env vars, JSON
    config, Pydantic models, and Prometheus label values.

    Members:
        ALWAYS_OBSCURE: Obscure every detected face regardless of `is_operator`
            flag. This is the default and the fail-safe choice. Matches the
            operator's 2026-04-18 directive.
        OBSCURE_NON_OPERATOR: Obscure only faces whose ReID match against the
            operator embedding is `False`. Used when the operator explicitly
            opts out of self-obscuring for framing feedback on local preview.
        DISABLED: Skip the obscure stage entirely. Frames pass through
            untouched. Intended for the feature-flag rollback path
            (`HAPAX_FACE_OBSCURE_ACTIVE=0`) and for local-only archival
            recordings the operator flags as non-redistributable. Never the
            runtime default.
    """

    ALWAYS_OBSCURE = "always_obscure"
    OBSCURE_NON_OPERATOR = "obscure_non_operator"
    DISABLED = "disabled"


DEFAULT_POLICY: FaceObscurePolicy = FaceObscurePolicy.ALWAYS_OBSCURE
"""Default policy — obscure everyone. Fail-safe for broadcast egress."""


def parse_policy(value: str | None) -> FaceObscurePolicy:
    """Parse a policy value from env var or config, with fail-safe default.

    An unknown, empty, or `None` value returns `DEFAULT_POLICY`. Parsing is
    case-insensitive and tolerant of hyphens vs underscores so operators can
    use either `always-obscure` or `always_obscure` in config.

    Args:
        value: Raw string from env var or config. May be `None`.

    Returns:
        A valid `FaceObscurePolicy`. Never raises.
    """
    if not value:
        return DEFAULT_POLICY
    normalized = value.strip().lower().replace("-", "_")
    for member in FaceObscurePolicy:
        if member.value == normalized:
            return member
    return DEFAULT_POLICY


def is_feature_active(env: dict[str, str] | None = None) -> bool:
    """Return whether the facial obscure feature is globally enabled.

    Driven by env var `HAPAX_FACE_OBSCURE_ACTIVE`. Default is **ON** — the
    flag only de-activates the stage when explicitly set to a recognized
    false value (`0`, `false`, `off`, etc). Any other value, including
    unset, keeps the stage active. This is the fail-safe default for
    broadcast privacy: misconfiguration can never silently disable the
    obscure pipeline.

    Args:
        env: Optional mapping for testing. Defaults to `os.environ`.

    Returns:
        `True` if the stage should run, `False` only for explicit opt-out.
    """
    source = env if env is not None else os.environ
    raw = source.get(_ACTIVE_ENV_VAR)
    if raw is None:
        return True
    normalized = raw.strip().lower()
    # Any non-recognized-false value (including `_TRUE_VALUES` and garbage) → active.
    # Garbage defaults to ON to preserve the privacy floor.
    return normalized not in _FALSE_VALUES


def resolve_policy(env: dict[str, str] | None = None) -> FaceObscurePolicy:
    """Resolve the active policy from env, honoring the feature flag.

    If the feature flag is OFF, returns `FaceObscurePolicy.DISABLED` so
    downstream callers only need to branch on the policy value. Otherwise,
    parses `HAPAX_FACE_OBSCURE_POLICY` and returns the result (default
    `ALWAYS_OBSCURE`).

    Args:
        env: Optional mapping for testing. Defaults to `os.environ`.

    Returns:
        The effective policy for the current process.
    """
    if not is_feature_active(env):
        return FaceObscurePolicy.DISABLED
    source = env if env is not None else os.environ
    return parse_policy(source.get(_POLICY_ENV_VAR))
