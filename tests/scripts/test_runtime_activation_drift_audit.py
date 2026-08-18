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
    for name in ("hapax-request-decompose.timer", "hapax-cc-task-offer-ready.timer"):
        unit = tmp_path / name
        unit.write_text(
            "[Timer]\nOnUnitActiveSec=300\n\n[Install]\nWantedBy=timers.target\n", encoding="utf-8"
        )

        parsed = audit.parse_unit_file(unit)

        assert parsed.critical is True


def test_missing_critical_unit_is_critical(tmp_path: Path) -> None:
    unit = tmp_path / "hapax-operator-current-state.timer"
    unit.write_text("[Install]\nWantedBy=timers.target\n", encoding="utf-8")
    specs = [audit.parse_unit_file(unit)]

    findings = audit.classify_unit_findings(specs, {})

    assert [(f.severity, f.kind, f.subject) for f in findings] == [
        ("critical", "unit_missing", "hapax-operator-current-state.timer")
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


def test_every_critical_timer_is_enableable_and_preset_declared() -> None:
    # Two independent inventories decide whether a critical timer actually runs:
    # CRITICAL_UNITS here (what the drift audit demands be active) and
    # systemd/user-preset.d/hapax.preset (what the governed deploy enables). When
    # they disagree, a timer is "critical" in the audit's eyes yet nothing ever
    # enables it -- and a timer with no [Install] section cannot be enabled at all,
    # so `systemctl --user enable` is a silent no-op and it stays dormant.
    #
    # This is not hypothetical: hapax-p0-incident-reaper.timer sat uninstalled on
    # the host for six weeks (2026-07-05 -> 2026-08-18) while its unit file, its
    # CLI entry point, its tests and its CRITICAL_UNITS membership all existed. The
    # P0 incident intake therefore ran mint-only with no drain half, and resolved
    # incidents accreted in state.json instead of draining. Auditing the same
    # question found hapax-operator-current-state.timer and
    # hapax-relay-to-cc-tasks.timer critical-but-not-preset-declared.
    #
    # Timers only: critical *services* are enabled through install-units.sh's
    # AUTO_ENABLE_SERVICES list, a deliberately different mechanism (starting a
    # daemon is not the same commitment as arming a timer). CRITICAL_UNITS holds
    # 14 entries: 11 timers (pinned here) + 3 services.
    #
    # Recheck the live host against this inventory:
    #   for u in $(uv run python -c "import importlib.util,sys; \
    #       s=importlib.util.spec_from_file_location('a','scripts/audit-runtime-activation-drift.py'); \
    #       a=importlib.util.module_from_spec(s); sys.modules['a']=a; s.loader.exec_module(a); \
    #       print(' '.join(sorted(a.CRITICAL_UNITS)))"); do \
    #     printf '%-42s %s\n' "$u" "$(systemctl --user is-enabled "$u" 2>&1)"; done
    repo_root = Path(__file__).resolve().parents[2]
    units_dir = repo_root / "systemd" / "units"
    preset = (repo_root / "systemd" / "user-preset.d" / "hapax.preset").read_text(encoding="utf-8")
    preset_enabled = {
        line.split(None, 1)[1].strip()
        for line in preset.splitlines()
        if line.strip().startswith("enable ")
    }

    missing_unit_file: list[str] = []
    not_installable: list[str] = []
    not_preset_declared: list[str] = []

    critical_timers = sorted(name for name in audit.CRITICAL_UNITS if name.endswith(".timer"))
    assert critical_timers, "CRITICAL_UNITS declares no timers — inventory lost?"

    for name in critical_timers:
        unit_path = units_dir / name
        if not unit_path.is_file():
            missing_unit_file.append(name)
        elif not audit.parse_unit_file(unit_path).installable:
            # Only meaningful when the file exists; a missing file is reported by
            # its own list rather than short-circuiting the preset check below,
            # so one missing unit never hides a second, unrelated preset gap.
            not_installable.append(name)
        if name not in preset_enabled:
            not_preset_declared.append(name)

    assert missing_unit_file == [], (
        f"CRITICAL_UNITS timers with no unit file in systemd/units/: {missing_unit_file}"
    )
    assert not_installable == [], (
        "CRITICAL_UNITS timers with no [Install] section — `systemctl --user enable` "
        f"is a silent no-op for these, so they can never arm: {not_installable}"
    )
    assert not_preset_declared == [], (
        "CRITICAL_UNITS timers absent from systemd/user-preset.d/hapax.preset — the "
        "drift audit demands they be active but the governed deploy never enables "
        f"them: {not_preset_declared}"
    )


def test_parse_unit_file_reports_not_installable_without_install_section(tmp_path: Path) -> None:
    # Negative control for the assertion above. That test expresses its whole
    # [Install] invariant through parse_unit_file(...).installable, so if this
    # helper ever started treating a missing [Install] as installable (or returned
    # a truthy default), the invariant would degrade to always-true and go on
    # passing silently. The existing positive control only pins the True side.
    without_install = tmp_path / "hapax-no-install.timer"
    without_install.write_text(
        "[Unit]\nDescription=fixture\n\n[Timer]\nOnUnitActiveSec=5min\n",
        encoding="utf-8",
    )
    with_install = tmp_path / "hapax-with-install.timer"
    with_install.write_text(
        "[Unit]\nDescription=fixture\n\n[Timer]\nOnUnitActiveSec=5min\n\n"
        "[Install]\nWantedBy=timers.target\n",
        encoding="utf-8",
    )

    assert audit.parse_unit_file(without_install).installable is False
    assert audit.parse_unit_file(with_install).installable is True


def test_preset_enable_lines_all_name_real_units() -> None:
    # The reverse direction of test_every_critical_timer_is_enableable_and_preset_declared.
    # That test walks CRITICAL_UNITS -> preset; without this one, an `enable` line
    # naming a unit file that no longer exists (renamed, retired, typo) stays green
    # forever — and systemd silently ignores a preset directive for a unit it cannot
    # find, so that failure is exactly as invisible as the one being fixed.
    #
    # Not hypothetical either: this pass found `enable
    # hapax-visual-pool-snapshot-harvester.timer` still in the preset for a unit
    # retired 2026-05-14 whose file was deleted from systemd/units/ (it is listed in
    # install-units.sh DECOMMISSIONED_UNITS).
    repo_root = Path(__file__).resolve().parents[2]
    units_dir = repo_root / "systemd" / "units"
    preset = (repo_root / "systemd" / "user-preset.d" / "hapax.preset").read_text(encoding="utf-8")

    orphaned = sorted(
        name
        for name in (
            line.split(None, 1)[1].strip()
            for line in preset.splitlines()
            if line.strip().startswith("enable ")
        )
        if not (units_dir / name).is_file()
    )

    assert orphaned == [], (
        "systemd/user-preset.d/hapax.preset enables units with no file in "
        f"systemd/units/ — systemd ignores these directives silently: {orphaned}"
    )
