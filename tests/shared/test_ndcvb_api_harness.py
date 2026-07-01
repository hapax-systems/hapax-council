from __future__ import annotations

import pytest

import shared.ndcvb_api_harness as harness
from shared.ndcvb_api_harness import (
    NDCVB_API_SCHEMA,
    NDCVB_PRODUCT_SURFACE_ID,
    NDCVB_REQUIRED_BATTERY_GATE_COUNT,
    NDCVBApiHarnessError,
    NDCVBBatteryGate,
    NDCVBPackagingRequest,
    package_ndcvb_detection_result,
)
from shared.segment_ndcvb_axis_b import ForbiddenAxisBVerdictError


def _request() -> dict[str, str]:
    return {
        "request_id": "ndcvb-api-req-001",
        "artifact_ref": "vault:segment-prep/prog-001.json",
        "evidence_ref": "ndcvb:run/prog-001",
        "run_ref": "local:ndcvb-phase0-packaging-fixture",
    }


def _gates(*, failed: str | None = None) -> list[dict[str, object]]:
    gate_ids = [
        "stimulus_capture",
        "counterfactual_probe",
        "cross_context_consistency",
        "source_traceability",
    ]
    return [
        {
            "gate_id": gate_id,
            "passed": gate_id != failed,
            "confidence": 0.91 - (index * 0.01),
            "provenance": [f"ndcvb:battery/{gate_id}"],
            "detail": "fixture gate receipt",
        }
        for index, gate_id in enumerate(gate_ids)
    ]


def test_request_and_gate_dataclasses_serialize_stable_api_fragments() -> None:
    request = NDCVBPackagingRequest.from_mapping(_request())
    assert request.to_api() == {
        "request_id": "ndcvb-api-req-001",
        "artifact_ref": "vault:segment-prep/prog-001.json",
        "evidence_ref": "ndcvb:run/prog-001",
        "run_ref": "local:ndcvb-phase0-packaging-fixture",
        "purpose": "operator_internal_phase0_packaging",
        "raw_payload_persisted": False,
        "customer_data_path_enabled": False,
    }

    gate = NDCVBBatteryGate.from_mapping(_gates()[0])
    assert gate.to_api() == {
        "gate_id": "stimulus_capture",
        "passed": True,
        "confidence": 0.91,
        "provenance": ["ndcvb:battery/stimulus_capture"],
    }

    without_detail = NDCVBBatteryGate.from_mapping(
        {
            "gate_id": "counterfactual_probe",
            "passed": True,
            "confidence": 0.9,
            "provenance": ["ndcvb:battery/counterfactual_probe"],
        }
    )
    assert "detail" not in without_detail.to_api()


def test_phase0_api_harness_exposes_detection_result_with_provenance_and_confidence() -> None:
    response = package_ndcvb_detection_result(
        request=_request(),
        verdicts=[
            {
                "correspondent": "sycophancy",
                "kind": "corroborated",
                "bound": 0.88,
                "source": "ndcvb:verdict/sycophancy",
            },
            {
                "correspondent": "consistency",
                "kind": "corroborated",
                "bound": 0.92,
                "source": "ndcvb:verdict/consistency",
            },
        ],
        battery_gates=_gates(),
    )

    assert response["schema"] == NDCVB_API_SCHEMA
    assert response["surface"] == {
        "surface_id": NDCVB_PRODUCT_SURFACE_ID,
        "phase": "phase0_packaging_only",
        "api_transport_enabled": False,
        "public_offer_enabled": False,
        "customer_data_path_enabled": False,
        "provider_spend_enabled": False,
        "runtime_endpoint_enabled": False,
    }
    assert response["status"] == "clear"
    assert response["detection"]["verdict"] == "corroborated@0.88"
    assert response["detection"]["confidence"] == 0.88
    assert response["detection"]["confidence_basis"] == "ndcvb_sensitivity_bound"
    assert response["detection"]["provenance"] == [
        "vault:segment-prep/prog-001.json",
        "ndcvb:run/prog-001",
        "local:ndcvb-phase0-packaging-fixture",
        "ndcvb:verdict/sycophancy",
        "ndcvb:verdict/consistency",
        "ndcvb:battery/stimulus_capture",
        "ndcvb:battery/counterfactual_probe",
        "ndcvb:battery/cross_context_consistency",
        "ndcvb:battery/source_traceability",
    ]
    assert response["battery"]["required_gate_count"] == NDCVB_REQUIRED_BATTERY_GATE_COUNT
    assert response["battery"]["ok"] is True
    assert response["engine_guards"]["forbidden_verdict_language_enforced"] is True
    assert response["engine_guards"]["dissociated_veto_required"] is False
    assert response["request"]["raw_payload_persisted"] is False
    assert response["request"]["customer_data_path_enabled"] is False


def test_dissociated_veto_survives_packaging_and_closes_release_boundary() -> None:
    response = package_ndcvb_detection_result(
        request=_request(),
        verdicts=[
            "sycophancy: corroborated@0.88",
            "consistency: dissociated@0.80",
        ],
        battery_gates=_gates(),
    )

    assert response["status"] == "refused_no_release"
    assert response["detection"]["kind"] == "dissociated"
    assert response["detection"]["confidence"] == 0.8
    assert response["engine_guards"]["dissociated_veto_required"] is True
    assert response["engine_guards"]["release_boundary"] == "closed"
    assert response["detection"]["violations"][0]["reason"] == "ndcvb_dissociated_at_r"
    assert "engine_report" not in response


def test_response_does_not_echo_verdict_rationale_text() -> None:
    response = package_ndcvb_detection_result(
        request=_request(),
        verdicts=[
            {
                "correspondent": "sycophancy",
                "kind": "corroborated",
                "bound": 0.88,
                "source": "ndcvb:verdict/sycophancy",
                "rationale": "fixture operator note that should not be echoed",
            }
        ],
        battery_gates=_gates(),
    )

    assert "engine_report" not in response
    assert "fixture operator note" not in repr(response)


def test_response_does_not_echo_violation_correspondent_text() -> None:
    response = package_ndcvb_detection_result(
        request=_request(),
        verdicts=[
            {
                "correspondent": "customer raw artifact text",
                "kind": "dissociated",
                "bound": 0.8,
            }
        ],
        battery_gates=_gates(),
    )

    assert response["status"] == "refused_no_release"
    assert response["detection"]["violations"] == [
        {
            "reason": "ndcvb_dissociated_at_r",
            "correspondent_count": 1,
        }
    ]
    assert "customer raw artifact text" not in repr(response)


def test_response_does_not_echo_battery_detail_text() -> None:
    gates = _gates()
    gates[0] = {**gates[0], "detail": "raw customer note should not be emitted"}

    response = package_ndcvb_detection_result(
        request=_request(),
        verdicts=["sycophancy: corroborated@0.88"],
        battery_gates=gates,
    )

    assert "detail" not in response["battery"]["gates"][0]
    assert "raw customer note" not in repr(response)


def test_four_gate_battery_is_required_and_failures_hold_result() -> None:
    with pytest.raises(NDCVBApiHarnessError, match="exactly 4 battery gates"):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=_gates()[:3],
        )

    response = package_ndcvb_detection_result(
        request=_request(),
        verdicts=["sycophancy: corroborated@0.88"],
        battery_gates=_gates(failed="source_traceability"),
    )

    assert response["status"] == "hold"
    assert response["battery"]["ok"] is False
    assert response["battery"]["failed_gate_ids"] == ["source_traceability"]


def test_battery_gate_ids_are_unique_and_have_provenance() -> None:
    duplicated = _gates()
    duplicated[1] = {**duplicated[1], "gate_id": "stimulus_capture"}
    with pytest.raises(NDCVBApiHarnessError, match="must be unique"):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=duplicated,
        )

    missing_provenance = _gates()
    missing_provenance[0] = {**missing_provenance[0], "provenance": []}
    with pytest.raises(NDCVBApiHarnessError, match="provenance must be a non-empty"):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=missing_provenance,
        )


def test_battery_gate_dataclass_constructor_enforces_public_contract() -> None:
    assert (
        NDCVBBatteryGate(
            gate_id="stimulus_capture",
            passed=True,
            confidence=0.91,
            provenance=("ndcvb:battery/stimulus_capture",),
        ).detail
        == ""
    )

    with pytest.raises(NDCVBApiHarnessError, match="passed must be a boolean"):
        NDCVBBatteryGate(  # type: ignore[arg-type]
            gate_id="stimulus_capture",
            passed="yes",
            confidence=0.91,
            provenance=("ndcvb:battery/stimulus_capture",),
        )

    with pytest.raises(NDCVBApiHarnessError, match="confidence must be a number"):
        NDCVBBatteryGate(
            gate_id="stimulus_capture",
            passed=True,
            confidence=float("nan"),
            provenance=("ndcvb:battery/stimulus_capture",),
        )

    with pytest.raises(NDCVBApiHarnessError, match="provenance must be a non-empty"):
        NDCVBBatteryGate(
            gate_id="stimulus_capture",
            passed=True,
            confidence=0.91,
            provenance=(),
        )

    assert (
        NDCVBBatteryGate(
            gate_id="stimulus_capture",
            passed=True,
            confidence=0.91,
            provenance=("ndcvb:battery/stimulus_capture",),
            detail="   ",
        ).detail
        == ""
    )


def test_forbidden_verdict_language_guard_remains_engine_owned() -> None:
    raw_rationale = "the model is pretending to know the answer"
    with pytest.raises(
        NDCVBApiHarnessError, match="NDCVB verdict validation failed.*next_action="
    ) as exc:
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=[
                {
                    "correspondent": "sycophancy",
                    "kind": "dissociated",
                    "bound": 0.8,
                    "rationale": raw_rationale,
                }
            ],
            battery_gates=_gates(),
        )
    assert isinstance(exc.value.__cause__, ForbiddenAxisBVerdictError)
    assert raw_rationale not in str(exc.value)


def test_phase0_request_rejects_customer_data_or_raw_payload_fields() -> None:
    for forbidden_key in ("customer_id", "prompt", "raw_payload"):
        with pytest.raises(NDCVBApiHarnessError, match="accepts refs only.*next_action="):
            package_ndcvb_detection_result(
                request={**_request(), forbidden_key: "must-not-enter"},
                verdicts=["sycophancy: corroborated@0.88"],
                battery_gates=_gates(),
            )


def test_phase0_verdicts_and_battery_gates_reject_customer_payload_fields() -> None:
    with pytest.raises(NDCVBApiHarnessError, match="NDCVB verdict.*forbidden keys.*next_action="):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=[
                {
                    "correspondent": "sycophancy",
                    "kind": "corroborated",
                    "bound": 0.88,
                    "source": "ndcvb:verdict/sycophancy",
                    "raw_payload": "must-not-enter",
                }
            ],
            battery_gates=_gates(),
        )

    with pytest.raises(NDCVBApiHarnessError, match="source must be a URI-like reference"):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=[
                {
                    "correspondent": "sycophancy",
                    "kind": "corroborated",
                    "bound": 0.88,
                    "source": "customer raw artifact text",
                }
            ],
            battery_gates=_gates(),
        )

    with pytest.raises(NDCVBApiHarnessError, match="battery gate.*forbidden keys.*next_action="):
        bad_gates = _gates()
        bad_gates[0] = {**bad_gates[0], "customer_id": "must-not-enter"}
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=bad_gates,
        )


def test_strict_schema_rejects_unsupported_non_forbidden_keys() -> None:
    with pytest.raises(NDCVBApiHarnessError, match="request.*unsupported keys.*metadata"):
        package_ndcvb_detection_result(
            request={**_request(), "metadata": "unsupported"},
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=_gates(),
        )

    with pytest.raises(NDCVBApiHarnessError, match="NDCVB verdict.*unsupported keys.*debug_ref"):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=[
                {
                    "correspondent": "sycophancy",
                    "kind": "corroborated",
                    "bound": 0.88,
                    "source": "ndcvb:verdict/sycophancy",
                    "debug_ref": "unsupported",
                }
            ],
            battery_gates=_gates(),
        )

    bad_gates = _gates()
    bad_gates[0] = {**bad_gates[0], "debug_ref": "unsupported"}
    with pytest.raises(NDCVBApiHarnessError, match="battery gate.*unsupported keys.*debug_ref"):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=bad_gates,
        )


def test_phase0_request_and_battery_shapes_fail_with_harness_errors() -> None:
    with pytest.raises(NDCVBApiHarnessError, match="request keys must be strings; next_action="):
        package_ndcvb_detection_result(
            request={**_request(), 3: "non-string-key"},
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=_gates(),
        )

    with pytest.raises(NDCVBApiHarnessError, match="request must be a mapping.*next_action="):
        package_ndcvb_detection_result(
            request=object(),  # type: ignore[arg-type]
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=_gates(),
        )

    with pytest.raises(
        NDCVBApiHarnessError, match="battery_gates must be a sequence.*next_action="
    ):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates="not-gates",  # type: ignore[arg-type]
        )

    bad_gates = _gates()
    bad_gates[0] = "not-a-gate"  # type: ignore[assignment]
    with pytest.raises(NDCVBApiHarnessError, match="battery gate must be a mapping.*next_action="):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=bad_gates,  # type: ignore[arg-type]
        )


def test_unavailable_engine_confidence_is_explicit_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_evaluate(_verdicts: object) -> dict[str, object]:
        return {
            "kind": "undetermined",
            "verdict": "UNDETERMINED",
            "ok": False,
            "violations": [],
            "scorer": "axis_b_ndcvb_integration_honesty",
            "scorer_version": 1,
            "dissociated_veto_required": False,
            "floor_gate": {"ok": False},
            "correspondent_scores": [],
        }

    monkeypatch.setattr(harness, "evaluate_ndcvb_axis_b", fake_evaluate)

    response = package_ndcvb_detection_result(
        request=_request(),
        verdicts=["sycophancy: UNDETERMINED"],
        battery_gates=_gates(),
    )

    assert response["status"] == "hold"
    assert response["detection"]["confidence"] is None
    assert response["detection"]["confidence_basis"] == "unavailable_below_floor"


def test_score_based_zero_confidence_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_evaluate(_verdicts: object) -> dict[str, object]:
        return {
            "kind": "corroborated",
            "verdict": "corroborated@0.00",
            "ok": True,
            "score_0_100": 0,
            "violations": [],
            "scorer": "axis_b_ndcvb_integration_honesty",
            "scorer_version": 1,
            "dissociated_veto_required": False,
            "floor_gate": {"ok": True},
            "correspondent_scores": [],
        }

    monkeypatch.setattr(harness, "evaluate_ndcvb_axis_b", fake_evaluate)

    response = package_ndcvb_detection_result(
        request=_request(),
        verdicts=["sycophancy: corroborated@0.00"],
        battery_gates=_gates(),
    )

    assert response["status"] == "clear"
    assert response["detection"]["confidence"] == 0.0
    assert response["detection"]["confidence_basis"] == "ndcvb_score_0_100"
