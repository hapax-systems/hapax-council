from __future__ import annotations

import pytest

from shared.ndcvb_api_harness import (
    NDCVB_API_SCHEMA,
    NDCVB_PRODUCT_SURFACE_ID,
    NDCVB_REQUIRED_BATTERY_GATE_COUNT,
    NDCVBApiHarnessError,
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
    assert response["engine_report"]["violations"][0]["reason"] == "ndcvb_dissociated_at_r"


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


def test_forbidden_verdict_language_guard_remains_engine_owned() -> None:
    with pytest.raises(ForbiddenAxisBVerdictError):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=[
                {
                    "correspondent": "sycophancy",
                    "kind": "dissociated",
                    "bound": 0.8,
                    "rationale": "the model is pretending to know the answer",
                }
            ],
            battery_gates=_gates(),
        )


def test_phase0_request_rejects_customer_data_or_raw_payload_fields() -> None:
    for forbidden_key in ("customer_id", "prompt", "raw_payload"):
        with pytest.raises(NDCVBApiHarnessError, match="accepts refs only"):
            package_ndcvb_detection_result(
                request={**_request(), forbidden_key: "must-not-enter"},
                verdicts=["sycophancy: corroborated@0.88"],
                battery_gates=_gates(),
            )


def test_phase0_request_and_battery_shapes_fail_with_harness_errors() -> None:
    with pytest.raises(NDCVBApiHarnessError, match="request keys must be strings"):
        package_ndcvb_detection_result(
            request={**_request(), 3: "non-string-key"},
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=_gates(),
        )

    bad_gates = _gates()
    bad_gates[0] = "not-a-gate"  # type: ignore[assignment]
    with pytest.raises(NDCVBApiHarnessError, match="battery gate must be a mapping"):
        package_ndcvb_detection_result(
            request=_request(),
            verdicts=["sycophancy: corroborated@0.88"],
            battery_gates=bad_gates,  # type: ignore[arg-type]
        )
