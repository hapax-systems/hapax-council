"""Fail-closed G12 Crow-chat attestation gate for bypass-prone dispatch surfaces."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from shared.operator_attestation import (
    CROW_CHAT_OPERATOR_HMAC_ENV,
    G12_BREAKGLASS_HMAC_ENV,
    OPERATOR_ATTESTATION_HMAC_ENV,
    OperatorAttestationError,
    verify_g12_signed_breakglass_ref,
    verify_operator_attestation_ref,
)

G12_REQUIRE_ENV = "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"
METHODOLOGY_REQUIRE_ENV = "HAPAX_METHODOLOGY_REQUIRE_CROW_CHAT_ATTESTATION"
ORIGIN_SURFACE_ENV = "HAPAX_METHODOLOGY_ORIGIN_SURFACE"
OPERATOR_ATTESTATION_REF_ENV = "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF"
SIGNED_BREAKGLASS_REF_ENV = "HAPAX_G12_SIGNED_BREAKGLASS_REF"
SIGNED_BREAKGLASS_REASON_ENV = "HAPAX_G12_SIGNED_BREAKGLASS_REASON"
TRUTHY = {"1", "true", "yes", "on"}


class G12CrowChatGateError(ValueError):
    """Raised when a required G12 Crow-chat attestation is missing or mismatched."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUTHY


def gate_required(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return _truthy(env.get(G12_REQUIRE_ENV)) or _truthy(env.get(METHODOLOGY_REQUIRE_ENV))


def child_attestation_env(
    *,
    origin_surface: str | None,
    operator_attestation_ref: str | None,
    require_crow_chat_attestation: bool,
    signed_breakglass_ref: str | None = None,
    signed_breakglass_reason: str | None = None,
) -> dict[str, str]:
    """Return env vars a validated methodology dispatch must propagate to child gates."""

    env: dict[str, str] = {}
    origin = (origin_surface or "").strip()
    ref = (operator_attestation_ref or "").strip()
    breakglass_ref = (signed_breakglass_ref or "").strip()
    breakglass_reason = (signed_breakglass_reason or "").strip()
    if origin:
        env[ORIGIN_SURFACE_ENV] = origin
    if ref:
        env[OPERATOR_ATTESTATION_REF_ENV] = ref
    if breakglass_ref:
        env[SIGNED_BREAKGLASS_REF_ENV] = breakglass_ref
    if breakglass_reason:
        env[SIGNED_BREAKGLASS_REASON_ENV] = breakglass_reason
    if require_crow_chat_attestation:
        env[METHODOLOGY_REQUIRE_ENV] = "1"
        env[G12_REQUIRE_ENV] = "1"
    return env


def validate_g12_crow_chat_attestation(
    *,
    task_id: str | None,
    lane: str | None,
    env: Mapping[str, str] | None = None,
    require: bool | None = None,
    origin_surface: str | None = None,
    operator_attestation_ref: str | None = None,
    signed_breakglass_ref: str | None = None,
    signed_breakglass_reason: str | None = None,
) -> None:
    env = os.environ if env is None else env
    if require is None:
        require = gate_required(env)
    if not require:
        return

    task = (task_id or "").strip()
    normalized_lane = (lane or "").strip()
    if not task:
        raise G12CrowChatGateError("operator_attestation_task_required_for_dispatch")
    if not normalized_lane:
        raise G12CrowChatGateError("operator_attestation_lane_required_for_dispatch")

    breakglass_ref = (signed_breakglass_ref or env.get(SIGNED_BREAKGLASS_REF_ENV) or "").strip()
    breakglass_reason = (
        signed_breakglass_reason or env.get(SIGNED_BREAKGLASS_REASON_ENV) or ""
    ).strip()
    if breakglass_ref:
        try:
            verify_g12_signed_breakglass_ref(
                task_id=task,
                lane=normalized_lane,
                reason=breakglass_reason,
                breakglass_ref=breakglass_ref,
                env=env,
            )
        except OperatorAttestationError as exc:
            raise G12CrowChatGateError(exc.reason) from exc
        return

    origin = (origin_surface or env.get(ORIGIN_SURFACE_ENV) or "").strip()
    ref = (operator_attestation_ref or env.get(OPERATOR_ATTESTATION_REF_ENV) or "").strip()
    if origin != "crow_chat":
        raise G12CrowChatGateError("crow_chat_origin_required_for_dispatch")
    if not ref:
        raise G12CrowChatGateError("operator_attestation_ref_required_for_crow_chat")

    try:
        verify_operator_attestation_ref(
            origin_surface=origin,
            task_id=task,
            lane=normalized_lane,
            attestation_ref=ref,
            env=env,
        )
    except OperatorAttestationError as exc:
        raise G12CrowChatGateError(exc.reason) from exc


def next_action_for_reason(reason: str) -> str:
    actions = {
        "operator_attestation_task_required_for_dispatch": (
            "rerun through hapax-methodology-dispatch with --task <cc-task-id>; "
            "taskless mutable launches are refused while G12 attestation enforcement is on"
        ),
        "operator_attestation_lane_required_for_dispatch": (
            "rerun with the target lane so the attestation can bind to task_id and lane"
        ),
        "crow_chat_origin_required_for_dispatch": (
            "rerun with --origin-surface crow_chat plus a Crow-chat-issued "
            "--operator-attestation-ref, or provide HAPAX_G12_SIGNED_BREAKGLASS_REF "
            "and HAPAX_G12_SIGNED_BREAKGLASS_REASON"
        ),
        "operator_attestation_ref_required_for_crow_chat": (
            "obtain the Crow-chat operator_attestation_ref bound to this task/lane "
            "and pass it via --operator-attestation-ref or HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF"
        ),
        "operator_attestation_hmac_key_required_for_dispatch": (
            f"load the governed attestation HMAC key into {CROW_CHAT_OPERATOR_HMAC_ENV} "
            f"or {OPERATOR_ATTESTATION_HMAC_ENV} for the dispatcher/launcher process, "
            "then rerun with the same Crow-chat ref"
        ),
        "operator_attestation_ref_shape_invalid": (
            "rerun with a v1 operator-attestation ref issued by Crow-chat for this task/lane"
        ),
        "operator_attestation_ref_hmac_mismatch": (
            "re-issue the Crow-chat attestation for the exact task_id/lane/ruling in this dispatch"
        ),
        "single_lane_required_for_attested_dispatch": (
            "split the broadcast into one attested dispatch per lane; the ref binds one task to one lane"
        ),
        "g12_breakglass_hmac_key_required_for_dispatch": (
            f"load the governed breakglass HMAC key into {G12_BREAKGLASS_HMAC_ENV} "
            f"or {OPERATOR_ATTESTATION_HMAC_ENV}, then rerun with a signed breakglass ref"
        ),
        "g12_breakglass_reason_required_for_dispatch": (
            f"set {SIGNED_BREAKGLASS_REASON_ENV} to the emergency reason bound into the signed ref"
        ),
        "g12_breakglass_ref_shape_invalid": (
            "rerun with a v1 operator-breakglass:reins:g12 ref bound to this task/lane/reason"
        ),
        "g12_breakglass_ref_hmac_mismatch": (
            "re-issue the signed breakglass ref for the exact task_id/lane/reason in this dispatch"
        ),
    }
    return actions.get(
        reason,
        "rerun with a Crow-chat-issued attestation bound to this task/lane or a signed breakglass ref",
    )


def validate_relay_dispatch_envelope(
    *,
    message_type: str,
    authority_item: str | None,
    subject: str | None,
    recipients: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> None:
    """Validate an MQ/FIFO dispatch send before it becomes durable."""

    env = os.environ if env is None else env
    if message_type != "dispatch" or not gate_required(env):
        return
    if len(recipients) != 1:
        raise G12CrowChatGateError("single_lane_required_for_attested_dispatch")
    _ = subject  # Human-readable subject is not authority; task binding is authority_item only.
    task_id = (authority_item or "").strip()
    validate_g12_crow_chat_attestation(task_id=task_id, lane=recipients[0], env=env, require=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--surface", default="dispatch")
    args = parser.parse_args(argv)
    try:
        validate_g12_crow_chat_attestation(task_id=args.task, lane=args.lane)
    except G12CrowChatGateError as exc:
        print(
            f"{args.surface}: g12 crow-chat attestation blocked: {exc.reason}; "
            f"next action: {next_action_for_reason(exc.reason)}",
            file=sys.stderr,
        )
        return 18
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
