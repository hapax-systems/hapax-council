from __future__ import annotations

import pytest

from shared.g12_crow_chat_gate import (
    G12CrowChatGateError,
    child_attestation_env,
    validate_g12_crow_chat_attestation,
    validate_relay_dispatch_envelope,
)
from shared.operator_attestation import expected_operator_attestation_ref


def test_gate_is_dormant_without_requirement() -> None:
    validate_g12_crow_chat_attestation(task_id=None, lane=None, env={})


def test_valid_crow_chat_attestation_passes_when_required() -> None:
    ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="task-x",
        lane="cx-green",
    )

    validate_g12_crow_chat_attestation(
        task_id="task-x",
        lane="cx-green",
        env={
            "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
            "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
            "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": ref,
        },
    )


def test_required_attestation_rejects_wrong_task_lane_binding() -> None:
    wrong_ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="other-task",
        lane="cx-green",
    )

    with pytest.raises(
        G12CrowChatGateError,
        match="operator_attestation_ref_task_lane_mismatch",
    ):
        validate_g12_crow_chat_attestation(
            task_id="task-x",
            lane="cx-green",
            env={
                "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
                "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
                "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": wrong_ref,
            },
        )


def test_relay_dispatch_requires_single_lane_when_attested() -> None:
    with pytest.raises(G12CrowChatGateError, match="single_lane_required_for_attested_dispatch"):
        validate_relay_dispatch_envelope(
            message_type="dispatch",
            authority_item="task-x",
            subject="dispatch task-x",
            recipients=["cx-green", "cx-red"],
            env={"HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1"},
        )


def test_relay_dispatch_requires_authority_item_task_binding() -> None:
    with pytest.raises(
        G12CrowChatGateError,
        match="operator_attestation_task_required_for_dispatch",
    ):
        validate_relay_dispatch_envelope(
            message_type="dispatch",
            authority_item=None,
            subject="task-x",
            recipients=["cx-green"],
            env={"HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1"},
        )


def test_child_attestation_env_sets_both_enforcement_switches() -> None:
    env = child_attestation_env(
        origin_surface="crow_chat",
        operator_attestation_ref="operator-attestation:reins:crow_chat:test",
        require_crow_chat_attestation=True,
    )

    assert env["HAPAX_METHODOLOGY_ORIGIN_SURFACE"] == "crow_chat"
    assert env["HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF"].startswith("operator-attestation:")
    assert env["HAPAX_METHODOLOGY_REQUIRE_CROW_CHAT_ATTESTATION"] == "1"
    assert env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] == "1"
