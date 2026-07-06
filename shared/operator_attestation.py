"""Operator attestation identifiers shared by dispatch gates."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Mapping

OPERATOR_ATTESTATION_RULING = "RULING-REINS-OPERATOR-ATTESTATION-20260701"
OPERATOR_ATTESTATION_VERSION = "v1"
OPERATOR_ATTESTATION_HMAC_ENV = "HAPAX_OPERATOR_ATTESTATION_HMAC_KEY"
CROW_CHAT_OPERATOR_HMAC_ENV = "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY"
G12_BREAKGLASS_HMAC_ENV = "HAPAX_G12_BREAKGLASS_HMAC_KEY"

_OPERATOR_HMAC_ENVS = (CROW_CHAT_OPERATOR_HMAC_ENV, OPERATOR_ATTESTATION_HMAC_ENV)
_BREAKGLASS_HMAC_ENVS = (G12_BREAKGLASS_HMAC_ENV, OPERATOR_ATTESTATION_HMAC_ENV)


class OperatorAttestationError(ValueError):
    """Raised when an attestation ref cannot be produced or verified."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _env_secret(
    env: Mapping[str, str] | None,
    names: tuple[str, ...],
    *,
    missing_reason: str,
) -> str:
    env = os.environ if env is None else env
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value
    raise OperatorAttestationError(missing_reason)


def _canonical_json(payload: Mapping[str, str]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _digest(payload: Mapping[str, str], hmac_key: str) -> str:
    return hmac.new(
        hmac_key.encode("utf-8"),
        _canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def expected_operator_attestation_ref(
    *,
    origin_surface: str,
    task_id: str,
    lane: str,
    ruling: str = OPERATOR_ATTESTATION_RULING,
    hmac_key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return the Crow-chat operator attestation ref bound to origin, task, lane, and ruling."""

    origin = origin_surface.strip()
    key = (hmac_key or "").strip() or _env_secret(
        env,
        _OPERATOR_HMAC_ENVS,
        missing_reason="operator_attestation_hmac_key_required_for_dispatch",
    )
    payload = {
        "origin_surface": origin,
        "task_id": task_id.strip(),
        "lane": lane.strip(),
        "ruling": ruling.strip(),
        "version": OPERATOR_ATTESTATION_VERSION,
    }
    return f"operator-attestation:reins:{origin}:{OPERATOR_ATTESTATION_VERSION}:{_digest(payload, key)}"


def verify_operator_attestation_ref(
    *,
    origin_surface: str,
    task_id: str,
    lane: str,
    attestation_ref: str,
    ruling: str = OPERATOR_ATTESTATION_RULING,
    env: Mapping[str, str] | None = None,
) -> None:
    expected = expected_operator_attestation_ref(
        origin_surface=origin_surface,
        task_id=task_id,
        lane=lane,
        ruling=ruling,
        env=env,
    )
    expected_prefix = (
        f"operator-attestation:reins:{origin_surface.strip()}:{OPERATOR_ATTESTATION_VERSION}:"
    )
    if not attestation_ref.startswith(expected_prefix):
        raise OperatorAttestationError("operator_attestation_ref_shape_invalid")
    if not hmac.compare_digest(attestation_ref, expected):
        raise OperatorAttestationError("operator_attestation_ref_hmac_mismatch")


def expected_g12_signed_breakglass_ref(
    *,
    task_id: str,
    lane: str,
    reason: str,
    ruling: str = OPERATOR_ATTESTATION_RULING,
    hmac_key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    key = (hmac_key or "").strip() or _env_secret(
        env,
        _BREAKGLASS_HMAC_ENVS,
        missing_reason="g12_breakglass_hmac_key_required_for_dispatch",
    )
    payload = {
        "kind": "g12_signed_breakglass",
        "lane": lane.strip(),
        "reason": reason.strip(),
        "ruling": ruling.strip(),
        "task_id": task_id.strip(),
        "version": OPERATOR_ATTESTATION_VERSION,
    }
    return f"operator-breakglass:reins:g12:{OPERATOR_ATTESTATION_VERSION}:{_digest(payload, key)}"


def verify_g12_signed_breakglass_ref(
    *,
    task_id: str,
    lane: str,
    reason: str,
    breakglass_ref: str,
    ruling: str = OPERATOR_ATTESTATION_RULING,
    env: Mapping[str, str] | None = None,
) -> None:
    if not reason.strip():
        raise OperatorAttestationError("g12_breakglass_reason_required_for_dispatch")
    expected = expected_g12_signed_breakglass_ref(
        task_id=task_id,
        lane=lane,
        reason=reason,
        ruling=ruling,
        env=env,
    )
    expected_prefix = f"operator-breakglass:reins:g12:{OPERATOR_ATTESTATION_VERSION}:"
    if not breakglass_ref.startswith(expected_prefix):
        raise OperatorAttestationError("g12_breakglass_ref_shape_invalid")
    if not hmac.compare_digest(breakglass_ref, expected):
        raise OperatorAttestationError("g12_breakglass_ref_hmac_mismatch")
