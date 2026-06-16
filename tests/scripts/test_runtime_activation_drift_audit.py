"""Tests for the runtime activation drift audit."""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit-runtime-activation-drift.py"
spec = importlib.util.spec_from_file_location("runtime_activation_drift_audit", SCRIPT)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)


def test_parse_unit_file_marks_installable_and_critical(tmp_path: Path) -> None:
    unit = tmp_path / "hapax-operator-current-state.timer"
    unit.write_text(
        "[Unit]\nDescription=fixture\n\n[Timer]\nOnUnitActiveSec=5min\n\n"
        "[Install]\nWantedBy=timers.target\n",
        encoding="utf-8",
    )

    parsed = audit.parse_unit_file(unit)

    assert parsed.installable is True
    assert parsed.critical is True
    assert parsed.kind == "timer"


def test_hapax_coordinator_service_is_critical_unit(tmp_path: Path) -> None:
    unit = tmp_path / "hapax-coordinator.service"
    unit.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")

    parsed = audit.parse_unit_file(unit)

    assert parsed.critical is True


def test_governed_intake_drain_timers_are_critical_units(tmp_path: Path) -> None:
    for name in (
        "hapax-request-decompose.service",
        "hapax-request-decompose.timer",
        "hapax-cc-task-offer-ready.service",
        "hapax-cc-task-offer-ready.timer",
    ):
        unit = tmp_path / name
        text = (
            "[Service]\nType=oneshot\nExecStart=/bin/true\n"
            if name.endswith(".service")
            else "[Timer]\nOnUnitActiveSec=300\n\n[Install]\nWantedBy=timers.target\n"
        )
        unit.write_text(text, encoding="utf-8")

        parsed = audit.parse_unit_file(unit)

        assert parsed.critical is True


def test_repo_unit_specs_include_dropin_conf_files(tmp_path: Path) -> None:
    service = tmp_path / "hapax-v4l2-bridge.service"
    service.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    dropin_dir = tmp_path / "hapax-v4l2-bridge.service.d"
    dropin_dir.mkdir()
    (dropin_dir / "darkplaces-runtime-gate.conf").write_text(
        "[Unit]\nConditionPathExists=!%h/.config/hapax/enable-darkplaces-runtime\n",
        encoding="utf-8",
    )

    specs = audit.repo_unit_specs(tmp_path)

    assert [spec.name for spec in specs] == [
        "hapax-v4l2-bridge.service",
        "hapax-v4l2-bridge.service.d/darkplaces-runtime-gate.conf",
    ]
    assert specs[1].kind == "dropin"


def test_dropin_content_drift_is_reported(tmp_path: Path) -> None:
    dropin_dir = tmp_path / "hapax-v4l2-bridge.service.d"
    dropin_dir.mkdir()
    dropin = dropin_dir / "darkplaces-runtime-gate.conf"
    dropin.write_text(
        "[Unit]\nConditionPathExists=!%h/.config/hapax/enable-darkplaces-runtime\n",
        encoding="utf-8",
    )
    spec = audit.parse_dropin_file(dropin)

    findings = audit.classify_dropin_content_findings(
        [spec],
        unit_text_loader=lambda _unit: "[Service]\nExecStart=/bin/true\n",
    )

    assert [(f.severity, f.kind, f.subject) for f in findings] == [
        (
            "warning",
            "dropin_content_drift",
            "hapax-v4l2-bridge.service.d/darkplaces-runtime-gate.conf",
        )
    ]


def test_dropin_content_present_passes(tmp_path: Path) -> None:
    dropin_dir = tmp_path / "hapax-v4l2-bridge.service.d"
    dropin_dir.mkdir()
    dropin = dropin_dir / "darkplaces-runtime-gate.conf"
    text = "[Unit]\nConditionPathExists=!%h/.config/hapax/enable-darkplaces-runtime\n"
    dropin.write_text(text, encoding="utf-8")
    spec = audit.parse_dropin_file(dropin)

    findings = audit.classify_dropin_content_findings(
        [spec],
        unit_text_loader=lambda _unit: f"# {dropin}\n{text}",
    )

    assert findings == []


def test_missing_critical_unit_is_critical(tmp_path: Path) -> None:
    unit = tmp_path / "hapax-operator-current-state.timer"
    unit.write_text("[Install]\nWantedBy=timers.target\n", encoding="utf-8")
    specs = [audit.parse_unit_file(unit)]

    findings = audit.classify_unit_findings(specs, {})

    assert [(f.severity, f.kind, f.subject) for f in findings] == [
        ("critical", "unit_missing", "hapax-operator-current-state.timer")
    ]


def test_missing_timer_paired_service_is_reported_even_when_not_installable(tmp_path: Path) -> None:
    service = tmp_path / "hapax-request-decompose.service"
    timer = tmp_path / "hapax-request-decompose.timer"
    service.write_text("[Service]\nType=oneshot\nExecStart=/bin/true\n", encoding="utf-8")
    timer.write_text(
        "[Timer]\nOnUnitActiveSec=300\n\n[Install]\nWantedBy=timers.target\n", encoding="utf-8"
    )
    specs = [audit.parse_unit_file(service), audit.parse_unit_file(timer)]
    runtime = {
        "hapax-request-decompose.timer": audit.RuntimeUnit(
            name="hapax-request-decompose.timer",
            file_state="enabled",
            active_state="active",
            sub_state="waiting",
        )
    }

    findings = audit.classify_unit_findings(specs, runtime)

    assert [(f.severity, f.kind, f.subject, f.detail) for f in findings] == [
        (
            "critical",
            "unit_missing",
            "hapax-request-decompose.service",
            f"timer-paired repo service absent from user manager ({service})",
        )
    ]


def test_disabled_noncritical_unit_is_warning(tmp_path: Path) -> None:
    unit = tmp_path / "example.timer"
    unit.write_text("[Install]\nWantedBy=timers.target\n", encoding="utf-8")
    specs = [audit.parse_unit_file(unit)]
    runtime = {
        "example.timer": audit.RuntimeUnit(
            name="example.timer",
            file_state="disabled",
            active_state="inactive",
            sub_state="dead",
        )
    }

    findings = audit.classify_unit_findings(specs, runtime)

    assert [(f.severity, f.kind, f.subject) for f in findings] == [
        ("warning", "unit_not_enabled", "example.timer")
    ]


def test_timer_driven_service_disabled_is_not_a_finding(tmp_path: Path) -> None:
    service = tmp_path / "example.service"
    timer = tmp_path / "example.timer"
    service.write_text("[Install]\nWantedBy=default.target\n", encoding="utf-8")
    timer.write_text("[Install]\nWantedBy=timers.target\n", encoding="utf-8")
    specs = [audit.parse_unit_file(service), audit.parse_unit_file(timer)]
    runtime = {
        "example.service": audit.RuntimeUnit(
            name="example.service",
            file_state="disabled",
            active_state="inactive",
            sub_state="dead",
        ),
        "example.timer": audit.RuntimeUnit(
            name="example.timer",
            file_state="enabled",
            active_state="active",
            sub_state="waiting",
        ),
    }

    assert audit.classify_unit_findings(specs, runtime) == []


def test_critical_timer_driven_oneshot_service_inactive_is_not_a_finding(tmp_path: Path) -> None:
    service = tmp_path / "hapax-request-decompose.service"
    timer = tmp_path / "hapax-request-decompose.timer"
    service.write_text("[Service]\nType=oneshot\nExecStart=/bin/true\n", encoding="utf-8")
    timer.write_text(
        "[Timer]\nOnUnitActiveSec=300\n\n[Install]\nWantedBy=timers.target\n", encoding="utf-8"
    )
    specs = [audit.parse_unit_file(service), audit.parse_unit_file(timer)]
    runtime = {
        "hapax-request-decompose.service": audit.RuntimeUnit(
            name="hapax-request-decompose.service",
            file_state="static",
            active_state="inactive",
            sub_state="dead",
        ),
        "hapax-request-decompose.timer": audit.RuntimeUnit(
            name="hapax-request-decompose.timer",
            file_state="enabled",
            active_state="active",
            sub_state="waiting",
        ),
    }

    assert audit.classify_unit_findings(specs, runtime) == []


def test_failed_unit_is_a_finding_even_when_timer_driven(tmp_path: Path) -> None:
    service = tmp_path / "example.service"
    timer = tmp_path / "example.timer"
    service.write_text("[Install]\nWantedBy=default.target\n", encoding="utf-8")
    timer.write_text("[Install]\nWantedBy=timers.target\n", encoding="utf-8")
    specs = [audit.parse_unit_file(service), audit.parse_unit_file(timer)]
    runtime = {
        "example.service": audit.RuntimeUnit(
            name="example.service",
            file_state="disabled",
            active_state="failed",
            sub_state="failed",
        ),
        "example.timer": audit.RuntimeUnit(
            name="example.timer",
            file_state="enabled",
            active_state="active",
            sub_state="waiting",
        ),
    }

    findings = audit.classify_unit_findings(specs, runtime)

    assert [(f.severity, f.kind, f.subject) for f in findings] == [
        ("warning", "unit_failed", "example.service")
    ]


def test_parse_units_output_handles_separate_failure_bullet() -> None:
    rows = audit.parse_units_output(
        "● hapax-obsidian-publish-sync.service loaded failed failed Hapax Obsidian Publish sync\n"
    )

    assert rows["hapax-obsidian-publish-sync.service"].active_state == "failed"
    assert rows["hapax-obsidian-publish-sync.service"].sub_state == "failed"


def test_stale_artifact_is_critical(tmp_path: Path) -> None:
    for _, relative_path, _ in audit.CRITICAL_ARTIFACTS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    stale_path = tmp_path / "operator-current-state.json"
    stale_time = datetime(2026, 5, 18, 12, 0, tzinfo=UTC).timestamp()
    stale_path.touch()

    os.utime(stale_path, (stale_time, stale_time))

    findings = audit.classify_artifact_findings(tmp_path, datetime(2026, 5, 18, 12, 20, tzinfo=UTC))

    assert ("critical", "artifact_stale", "operator_current_state") in [
        (f.severity, f.kind, f.subject) for f in findings
    ]


def test_fresh_artifacts_have_no_findings(tmp_path: Path) -> None:
    now = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    for _, relative_path, _ in audit.CRITICAL_ARTIFACTS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        timestamp = (now - timedelta(seconds=30)).timestamp()

        os.utime(path, (timestamp, timestamp))

    assert audit.classify_artifact_findings(tmp_path, now) == []


def test_critical_request_intake_unit_content_drift_is_critical(tmp_path: Path) -> None:
    unit = tmp_path / "hapax-request-intake-consumer.service"
    unit.write_text(
        "[Unit]\n"
        "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/scripts/request-intake-consumer\n"
        "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/scripts/request-fulfillment-reconciler\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "Environment=HAPAX_REQUEST_RECEIPTS=%h/.cache/hapax/request-receipts\n"
        "Environment=HAPAX_REQUEST_INTAKE_STATE=%h/.cache/hapax/request-intake-state.json\n"
        "Environment=HAPAX_REQUEST_FULFILLMENT_REPORT=%h/.cache/hapax/request-fulfillment-reconciler.json\n"
        "Environment=HAPAX_AGENT_NAME=request-intake-consumer\n"
        "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/request-intake-consumer --write-receipt --write-state --write-planning-feed\n"
        "ExecStartPost=%h/.local/bin/uv --directory %h/.cache/hapax/source-activation/worktree run python scripts/request-fulfillment-reconciler --apply --write-report --report-path %h/.cache/hapax/request-fulfillment-reconciler.json --quiet\n",
        encoding="utf-8",
    )
    runtime = {
        unit.name: audit.RuntimeUnit(
            name=unit.name,
            file_state="static",
            active_state="inactive",
            sub_state="dead",
        )
    }
    stale_runtime_text = (
        "[Unit]\n"
        "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/scripts/request-intake-consumer\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "Environment=HAPAX_REQUEST_RECEIPTS=%h/.cache/hapax/request-receipts\n"
        "Environment=HAPAX_REQUEST_INTAKE_STATE=%h/.cache/hapax/request-intake-state.json\n"
        "Environment=HAPAX_AGENT_NAME=request-intake-consumer\n"
        "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/request-intake-consumer --write-receipt --write-state --write-planning-feed\n"
    )

    findings = audit.classify_unit_content_findings(
        tmp_path,
        runtime,
        unit_text_loader=lambda _name: stale_runtime_text,
    )

    assert [
        (finding.severity, finding.kind, finding.subject, finding.detail) for finding in findings
    ] == [
        (
            "critical",
            "critical_unit_content_drift",
            "hapax-request-intake-consumer.service",
            "installed unit is missing required contract fulfillment_report_environment",
        ),
        (
            "critical",
            "critical_unit_content_drift",
            "hapax-request-intake-consumer.service",
            "installed unit is missing required contract fulfillment_reconciler_exec_start_post",
        ),
    ]


def test_critical_request_intake_unit_content_match_has_no_findings(tmp_path: Path) -> None:
    unit = tmp_path / "hapax-request-intake-consumer.service"
    unit_text = (
        "[Service]\n"
        "Environment=HAPAX_REQUEST_FULFILLMENT_REPORT=%h/.cache/hapax/request-fulfillment-reconciler.json\n"
        "ExecStartPost=%h/.local/bin/uv --directory %h/.cache/hapax/source-activation/worktree run python scripts/request-fulfillment-reconciler --apply --write-report --report-path %h/.cache/hapax/request-fulfillment-reconciler.json --quiet\n"
    )
    unit.write_text(unit_text, encoding="utf-8")
    runtime = {
        unit.name: audit.RuntimeUnit(
            name=unit.name,
            file_state="static",
            active_state="inactive",
            sub_state="dead",
        )
    }

    findings = audit.classify_unit_content_findings(
        tmp_path,
        runtime,
        unit_text_loader=lambda _name: unit_text,
    )

    assert findings == []


def test_security_signal_artifact_matches_systemd_state_contract() -> None:
    artifacts = {label: relative_path for label, relative_path, _ in audit.CRITICAL_ARTIFACTS}

    assert artifacts["security_signal_intake_state"] == Path("security-signal-intake-state.json")
