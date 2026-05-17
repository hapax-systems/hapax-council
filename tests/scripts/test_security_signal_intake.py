from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "security-signal-intake"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-security-signal-intake.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-security-signal-intake.timer"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"

loader = importlib.machinery.SourceFileLoader("security_signal_intake", str(SCRIPT))
spec = importlib.util.spec_from_loader("security_signal_intake", loader)
assert spec and spec.loader
security_signal_intake = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = security_signal_intake
spec.loader.exec_module(security_signal_intake)


def _frontmatter(text: str) -> dict:
    _, frontmatter, _ = text.split("---", 2)
    loaded = yaml.safe_load(frontmatter)
    assert isinstance(loaded, dict)
    return loaded


def test_dependabot_signal_renders_full_request_shape() -> None:
    alert = {
        "number": 103,
        "html_url": "https://github.example/security/dependabot/103",
        "dependency": {
            "package": {"name": "pipecat-ai", "ecosystem": "pip"},
            "manifest_path": "uv.lock",
            "scope": "runtime",
        },
        "security_advisory": {
            "severity": "high",
            "ghsa_id": "GHSA-3363-2ph6-35wh",
            "cve_id": "CVE-2026-44716",
        },
        "security_vulnerability": {
            "vulnerable_version_range": ">= 0.0.90, < 1.2.0",
            "first_patched_version": {"identifier": "1.2.0"},
        },
    }

    signal = security_signal_intake.dependabot_signal("hapax-systems/hapax-council", alert)
    text = security_signal_intake.render_request(signal, datetime(2026, 5, 17, 22, 0, tzinfo=UTC))
    frontmatter = _frontmatter(text)

    assert frontmatter["type"] == "hapax-request"
    assert frontmatter["status"] == "captured"
    assert frontmatter["request_id"] == "REQ-GH-DEPENDABOT-HAPAX-SYSTEMS-HAPAX-COUNCIL-000103"
    assert frontmatter["source_signal_id"] == "github:hapax-systems/hapax-council:dependabot:103"
    assert frontmatter["priority_hint"] == "p0"
    assert frontmatter["planning_case_hint"] == "CASE-SDLC-SECURITY-REMEDIATION-001"
    assert "planning_case" not in frontmatter
    assert "pipecat-ai" in text
    assert "First patched version: 1.2.0" in text


def test_secret_scanning_request_never_persists_secret_value() -> None:
    alert = {
        "number": 1,
        "html_url": "https://github.example/security/secret-scanning/1",
        "secret_type": "aws_temporary_access_key_id",
        "secret_type_display_name": "Amazon AWS Temporary Access Key ID",
        "secret": "SHOULD-NOT-APPEAR",
        "validity": "unknown",
        "publicly_leaked": True,
    }

    signal = security_signal_intake.secret_scanning_signal("hapax-systems/hapax-council", alert)
    text = security_signal_intake.render_request(signal, datetime(2026, 5, 17, 22, 0, tzinfo=UTC))
    frontmatter = _frontmatter(text)

    assert "SHOULD-NOT-APPEAR" not in text
    assert "intentionally omitted" in text
    assert frontmatter["priority_hint"] == "p0"
    assert "no-secret-disclosure" in frontmatter["principle_flags"]


def test_existing_signal_ids_scan_active_and_closed(tmp_path: Path) -> None:
    active = tmp_path / "active"
    closed = tmp_path / "closed"
    active.mkdir()
    closed.mkdir()
    (active / "REQ-A.md").write_text(
        '---\ntype: hapax-request\nsource_signal_id: "github:repo:dependabot:1"\n---\n',
        encoding="utf-8",
    )
    (closed / "REQ-B.md").write_text(
        "---\ntype: hapax-request\nsource_signal_id: github:repo:code-scanning:2\n---\n",
        encoding="utf-8",
    )

    assert security_signal_intake.existing_signal_ids((active, closed)) == {
        "github:repo:dependabot:1",
        "github:repo:code-scanning:2",
    }


def test_write_requests_is_idempotent_by_source_signal_id(tmp_path: Path) -> None:
    requests_dir = tmp_path / "requests" / "active"
    requests_dir.mkdir(parents=True)
    signal = security_signal_intake.Signal(
        kind="github-code-scanning-alert",
        source_signal_id="github:repo:code-scanning:9",
        request_id="REQ-GH-CODE-SCANNING-REPO-000009",
        title="Remediate code scanning alert",
        priority_hint="p1",
        risk_guess="medium",
        severity="medium",
        source_url="https://example.invalid/9",
        surfaces=("github-security",),
        principle_flags=("evidence-backed-remediation",),
        tags=("hapax-request", "security"),
        evidence_lines=("Alert: https://example.invalid/9",),
        constraints=("Test constraint",),
        generated_from="code-scanning",
    )

    now = datetime(2026, 5, 17, 22, 0, tzinfo=UTC)
    first = security_signal_intake.write_requests(
        [signal], requests_dir=requests_dir, generated_at=now, write=True
    )
    second = security_signal_intake.write_requests(
        [signal], requests_dir=requests_dir, generated_at=now, write=True
    )

    assert first[0].status == "created"
    assert second[0].status == "skipped_existing"
    assert len(list(requests_dir.glob("*.md"))) == 1


def test_actions_failure_signal_groups_recurring_non_pr_failures() -> None:
    now = datetime(2026, 5, 17, 22, 0, tzinfo=UTC)
    runs = [
        {
            "name": "Auto-Fix CI Failures",
            "event": "workflow_run",
            "head_branch": "main",
            "conclusion": "failure",
            "created_at": "2026-05-17T21:50:00Z",
            "html_url": f"https://example.invalid/run/{index}",
            "head_sha": f"sha{index}",
        }
        for index in range(3)
    ]
    runs.append(
        {
            "name": "CI",
            "event": "pull_request",
            "head_branch": "feature",
            "conclusion": "failure",
            "created_at": "2026-05-17T21:50:00Z",
            "html_url": "https://example.invalid/pr",
        }
    )

    signals = security_signal_intake.actions_failure_signals(
        "hapax-systems/hapax-council",
        runs,
        now=now,
        lookback_hours=24,
        min_count=3,
    )

    assert len(signals) == 1
    assert signals[0].kind == "github-actions-recurring-failure"
    assert "Auto-Fix CI Failures" in signals[0].title
    assert "Recent failures in window: 3" in signals[0].evidence_lines


def test_security_signal_intake_systemd_units_are_scheduled_and_preset_enabled() -> None:
    service_text = SERVICE.read_text(encoding="utf-8")
    timer_text = TIMER.read_text(encoding="utf-8")
    preset_text = PRESET.read_text(encoding="utf-8")

    assert (
        "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/scripts/security-signal-intake"
        in service_text
    )
    assert "HAPAX_AGENT_NAME=security-signal-intake" in service_text
    assert "scripts/security-signal-intake --write" in service_text
    assert "--state-path %h/.cache/hapax/security-signal-intake-state.json" in service_text
    assert "OnBootSec=5min" in timer_text
    assert "OnUnitActiveSec=30min" in timer_text
    assert "Persistent=true" in timer_text
    assert "enable hapax-security-signal-intake.timer" in preset_text
