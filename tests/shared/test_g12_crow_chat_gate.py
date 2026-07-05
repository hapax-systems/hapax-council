from __future__ import annotations

import pytest

from shared.g12_crow_chat_gate import (
    G12CrowChatGateError,
    child_attestation_env,
    main,
    next_action_for_reason,
    validate_g12_crow_chat_attestation,
    validate_relay_dispatch_envelope,
)
from shared.operator_attestation import (
    OperatorAttestationError,
    expected_g12_signed_breakglass_ref,
    expected_operator_attestation_ref,
)

TEST_HMAC_KEY = "test-crow-chat-hmac-key"
TEST_BREAKGLASS_KEY = "test-breakglass-hmac-key"


def test_gate_is_dormant_without_requirement() -> None:
    validate_g12_crow_chat_attestation(task_id=None, lane=None, env={})


def test_valid_crow_chat_attestation_passes_when_required() -> None:
    ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="task-x",
        lane="cx-green",
        hmac_key=TEST_HMAC_KEY,
    )

    validate_g12_crow_chat_attestation(
        task_id="task-x",
        lane="cx-green",
        env={
            "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
            "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY": TEST_HMAC_KEY,
            "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
            "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": ref,
        },
    )


def test_expected_operator_attestation_requires_hmac_key() -> None:
    with pytest.raises(
        OperatorAttestationError,
        match="operator_attestation_hmac_key_required_for_dispatch",
    ):
        expected_operator_attestation_ref(
            origin_surface="crow_chat",
            task_id="task-x",
            lane="cx-green",
            env={},
        )


def test_required_attestation_rejects_wrong_task_lane_binding() -> None:
    wrong_ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="other-task",
        lane="cx-green",
        hmac_key=TEST_HMAC_KEY,
    )

    with pytest.raises(
        G12CrowChatGateError,
        match="operator_attestation_ref_hmac_mismatch",
    ):
        validate_g12_crow_chat_attestation(
            task_id="task-x",
            lane="cx-green",
            env={
                "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
                "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY": TEST_HMAC_KEY,
                "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
                "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": wrong_ref,
            },
        )


def test_required_attestation_rejects_ref_without_crow_chat_origin() -> None:
    ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="task-x",
        lane="cx-green",
        hmac_key=TEST_HMAC_KEY,
    )

    with pytest.raises(
        G12CrowChatGateError,
        match="crow_chat_origin_required_for_dispatch",
    ):
        validate_g12_crow_chat_attestation(
            task_id="task-x",
            lane="cx-green",
            env={
                "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
                "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY": TEST_HMAC_KEY,
                "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": ref,
            },
        )


def test_required_attestation_rejects_malformed_crow_chat_ref_shape() -> None:
    with pytest.raises(
        G12CrowChatGateError,
        match="operator_attestation_ref_shape_invalid",
    ):
        validate_g12_crow_chat_attestation(
            task_id="task-x",
            lane="cx-green",
            env={
                "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
                "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY": TEST_HMAC_KEY,
                "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
                "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": "operator-attestation:bad",
            },
        )


def test_signed_breakglass_ref_satisfies_required_gate() -> None:
    ref = expected_g12_signed_breakglass_ref(
        task_id="task-x",
        lane="cx-green",
        reason="crow-chat attestations unavailable",
        hmac_key=TEST_BREAKGLASS_KEY,
    )

    validate_g12_crow_chat_attestation(
        task_id="task-x",
        lane="cx-green",
        env={
            "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
            "HAPAX_G12_BREAKGLASS_HMAC_KEY": TEST_BREAKGLASS_KEY,
            "HAPAX_G12_SIGNED_BREAKGLASS_REF": ref,
            "HAPAX_G12_SIGNED_BREAKGLASS_REASON": "crow-chat attestations unavailable",
        },
    )


def test_signed_breakglass_ref_requires_bound_reason() -> None:
    ref = expected_g12_signed_breakglass_ref(
        task_id="task-x",
        lane="cx-green",
        reason="crow-chat attestations unavailable",
        hmac_key=TEST_BREAKGLASS_KEY,
    )

    with pytest.raises(
        G12CrowChatGateError,
        match="g12_breakglass_reason_required_for_dispatch",
    ):
        validate_g12_crow_chat_attestation(
            task_id="task-x",
            lane="cx-green",
            env={
                "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
                "HAPAX_G12_BREAKGLASS_HMAC_KEY": TEST_BREAKGLASS_KEY,
                "HAPAX_G12_SIGNED_BREAKGLASS_REF": ref,
            },
        )


def test_signed_breakglass_ref_rejects_invalid_shape() -> None:
    with pytest.raises(
        G12CrowChatGateError,
        match="g12_breakglass_ref_shape_invalid",
    ):
        validate_g12_crow_chat_attestation(
            task_id="task-x",
            lane="cx-green",
            env={
                "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
                "HAPAX_G12_BREAKGLASS_HMAC_KEY": TEST_BREAKGLASS_KEY,
                "HAPAX_G12_SIGNED_BREAKGLASS_REF": "operator-breakglass:bad",
                "HAPAX_G12_SIGNED_BREAKGLASS_REASON": "crow-chat attestations unavailable",
            },
        )


def test_signed_breakglass_ref_rejects_wrong_task_lane_reason_binding() -> None:
    wrong_ref = expected_g12_signed_breakglass_ref(
        task_id="other-task",
        lane="cx-green",
        reason="crow-chat attestations unavailable",
        hmac_key=TEST_BREAKGLASS_KEY,
    )

    with pytest.raises(
        G12CrowChatGateError,
        match="g12_breakglass_ref_hmac_mismatch",
    ):
        validate_g12_crow_chat_attestation(
            task_id="task-x",
            lane="cx-green",
            env={
                "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
                "HAPAX_G12_BREAKGLASS_HMAC_KEY": TEST_BREAKGLASS_KEY,
                "HAPAX_G12_SIGNED_BREAKGLASS_REF": wrong_ref,
                "HAPAX_G12_SIGNED_BREAKGLASS_REASON": "crow-chat attestations unavailable",
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
        signed_breakglass_ref="operator-breakglass:reins:g12:v1:test",
        signed_breakglass_reason="emergency",
    )

    assert env["HAPAX_METHODOLOGY_ORIGIN_SURFACE"] == "crow_chat"
    assert env["HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF"].startswith("operator-attestation:")
    assert env["HAPAX_METHODOLOGY_REQUIRE_CROW_CHAT_ATTESTATION"] == "1"
    assert env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] == "1"
    assert env["HAPAX_G12_SIGNED_BREAKGLASS_REF"].startswith("operator-breakglass:")
    assert env["HAPAX_G12_SIGNED_BREAKGLASS_REASON"] == "emergency"


def test_cli_failure_includes_next_action(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION", "1")

    rc = main(["--task", "task-x", "--lane", "cx-green", "--surface", "unit-test"])

    assert rc == 18
    stderr = capsys.readouterr().err
    assert "crow_chat_origin_required_for_dispatch" in stderr
    assert "next action:" in stderr
    assert "operator-attestation-ref" in stderr


def test_next_action_names_hmac_key_for_missing_secret() -> None:
    assert "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY" in next_action_for_reason(
        "operator_attestation_hmac_key_required_for_dispatch"
    )
