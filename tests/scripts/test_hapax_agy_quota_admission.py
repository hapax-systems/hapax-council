"""Tests for ``scripts/hapax-agy-quota-admission``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-agy-quota-admission"


def _load_module() -> ModuleType:
    loader = SourceFileLoader("hapax_agy_quota_admission_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def _completed(
    stdout: str, *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        [str(REPO_ROOT / "scripts" / "hapax-agy-reviewer")],
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_agy_quota_admission_writes_short_lived_safe_receipt(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    receipt_dir = tmp_path / "receipts"
    module = _load_module()

    def fake_run(cmd, **kwargs):
        assert cmd == [str(REPO_ROOT / "scripts" / "hapax-agy-reviewer"), "--print-timeout", "3m0s"]
        assert kwargs["cwd"] == REPO_ROOT
        assert "route admission smoke" in kwargs["input"]
        assert "AGY_BIN" not in kwargs["env"]
        assert "HAPAX_AGY_BIN" not in kwargs["env"]
        return _completed("```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("AGY_BIN", "/tmp/fake-agy")
    monkeypatch.setenv("HAPAX_AGY_BIN", "/tmp/fake-hapax-agy")

    rc = module.main(
        [
            "--receipt-dir",
            str(receipt_dir),
            "--now",
            "2026-07-07T13:00:00Z",
            "--evidence-ref",
            "agy-gemini31pro-smoke-20260707t1300z",
            "--json",
        ]
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["route_id"] == "agy.review.direct"
    assert summary["supported_tool"] == "hapax-agy-reviewer"
    assert summary["model"] == "gemini-3.1-pro-preview"
    path = Path(summary["path"])
    receipt = path.read_text(encoding="utf-8")
    assert "schema: hapax.agy_quota_admission.v1" in receipt
    assert "status: quota_available" in receipt
    assert "secret_source: agy:operator-session" in receipt
    assert "secret_value_persisted: false" in receipt
    assert "prompt_or_output_persisted: false" in receipt
    assert "billing_mode: operator_session_subscription" in receipt
    assert "smoke_command: scripts/hapax-agy-reviewer" in receipt
    assert "smoke_returncode: 0" in receipt
    assert "smoke_stdout_validated: true" in receipt
    assert "positive_admission: true" in receipt
    assert path.stat().st_mode & 0o777 == 0o600


def test_agy_quota_admission_rejects_failed_reviewer_smoke(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()

    def fake_run(cmd, **kwargs):
        return _completed("", returncode=17, stderr="boom sk-abc123\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    rc = module.main(
        [
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "agy-gemini31pro-smoke-20260707t1300z",
        ]
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "sanctioned agy reviewer smoke failed" in err
    assert "stderr_excerpt=boom <redacted>" in err
    assert "next_action=run scripts/hapax-agy-reviewer" in err
    assert "sk-abc123" not in err
    assert not list(tmp_path.glob("*.yaml"))


def test_agy_quota_admission_rejects_invalid_reviewer_stdout(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()

    def fake_run(cmd, **kwargs):
        return _completed("not yaml\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    rc = module.main(
        [
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "agy-gemini31pro-smoke-20260707t1300z",
        ]
    )

    assert rc == 2
    assert "sanctioned agy reviewer smoke produced invalid stdout" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.yaml"))


def test_agy_quota_admission_rejects_reviewer_command_override(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--receipt-dir",
            str(tmp_path),
            "--reviewer-command",
            str(tmp_path / "hapax-agy-reviewer"),
            "--evidence-ref",
            "agy-gemini31pro-smoke-20260707t1300z",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )

    assert result.returncode == 2
    assert "unrecognized arguments: --reviewer-command" in result.stderr
    assert not list(tmp_path.glob("*.yaml"))


def test_agy_quota_admission_rejects_agy_bin_override(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--receipt-dir",
            str(tmp_path),
            "--agy-bin",
            str(tmp_path / "agy"),
            "--evidence-ref",
            "agy-gemini31pro-smoke-20260707t1300z",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )

    assert result.returncode == 2
    assert "unrecognized arguments: --agy-bin" in result.stderr
    assert not list(tmp_path.glob("*.yaml"))


def test_agy_quota_admission_rejects_secretish_evidence_ref(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--receipt-dir",
            str(tmp_path),
            "--evidence-ref",
            "api-key-secret-token",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )

    assert result.returncode == 2
    assert "unsafe evidence-ref" in result.stderr
    assert not list(tmp_path.glob("*.yaml"))
