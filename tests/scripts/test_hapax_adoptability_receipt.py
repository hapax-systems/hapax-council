"""scripts/hapax-adoptability-receipt — the A3 producer, with the runtime and gh stubbed.

The container leg and the repository leg are driven through an injected runner so the
checks, the outcome, the signature and the refusals are pinned without podman, docker
or GitHub. One test closes the loop: a receipt this producer writes clears
shared.adoptability_gate.release_refusals for the row that references it.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from shared import adoptability_gate as gate
from shared import public_gate_receipts as pgr

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-adoptability-receipt"
SECRET = "receipt-test-secret"  # pragma: allowlist secret
INSTALL_LINE = "curl -fsSL https://example.org/tool/install.sh | sh"
NOW = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)


def _load():
    loader = importlib.machinery.SourceFileLoader("hapax_adoptability_receipt", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


receipt_mod = _load()


def _manifest(tmp_path: Path, **overrides) -> Path:
    data = {
        "artifact_id": "tool",
        "repo": "acme/tool",
        "install_line": INSTALL_LINE,
        "zero_config_command": "tool status",
        "zero_config_pattern": "detected",
        "first_value_command": "tool status --json",
        "first_value_pattern": '"state"',
        "ttfv_budget_seconds": 60,
        "compare": "v0.1.0...v0.2.0",
    }
    data.update(overrides)
    path = tmp_path / "artifact.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


class FakeRunner:
    """Answers the runtime, gh and curl invocations the producer makes."""

    def __init__(
        self,
        *,
        install_rc: int = 0,
        zc_rc: int = 0,
        zc_out: str = "detected: claude-code (tmux)",
        fv_rc: int = 0,
        fv_out: str = '{"state": "idle"}',
        ttfv_ns: int = 41_000_000_000,
        runtime_rc: int = 0,
        repo: dict | None = None,
        release: dict | None = None,
        compare_rc: int = 0,
    ) -> None:
        self.install_rc = install_rc
        self.zc_rc, self.zc_out = zc_rc, zc_out
        self.fv_rc, self.fv_out = fv_rc, fv_out
        self.ttfv_ns = ttfv_ns
        self.runtime_rc = runtime_rc
        self.repo = (
            repo
            if repo is not None
            else {
                "private": False,
                "visibility": "public",
                "has_issues": True,
                "archived": False,
                "license": {"spdx_id": "Apache-2.0"},
            }
        )
        self.release = release if release is not None else {"tag_name": "v0.2.0", "body": "Notes."}
        self.compare_rc = compare_rc
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(cmd))
        head = cmd[0]
        if head in ("podman", "docker"):
            if self.runtime_rc:
                return subprocess.CompletedProcess(cmd, self.runtime_rc, "", "runtime exploded")
            lines = [f"INSTALL_RC={self.install_rc}"]
            if self.install_rc == 0:
                lines += [
                    f"ZC_RC={self.zc_rc}",
                    f"FV_RC={self.fv_rc}",
                    f"TTFV_NS={self.ttfv_ns}",
                    "ZC_BEGIN",
                    self.zc_out,
                    "ZC_END",
                    "FV_BEGIN",
                    self.fv_out,
                    "FV_END",
                ]
            return subprocess.CompletedProcess(cmd, 0, "\n".join(lines) + "\n", "")
        if head == "gh":
            endpoint = cmd[2]
            if endpoint.endswith("/releases/latest"):
                return (
                    subprocess.CompletedProcess(cmd, 0, json.dumps(self.release), "")
                    if self.release
                    else subprocess.CompletedProcess(cmd, 1, "", "404")
                )
            if "/compare/" in endpoint:
                return subprocess.CompletedProcess(
                    cmd, self.compare_rc, "{}" if not self.compare_rc else "", ""
                )
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.repo), "")
        if head == "curl":
            return subprocess.CompletedProcess(cmd, self.compare_rc, "", "")
        raise AssertionError(f"unexpected command {cmd}")


def _produce(tmp_path: Path, runner: FakeRunner, *, manifest: Path | None = None, **kwargs):
    return receipt_mod.produce(
        manifest or _manifest(tmp_path),
        out=tmp_path / "receipt.json",
        runtime_arg=None,
        ttl_seconds=3600,
        runner=runner,
        which=kwargs.pop("which", lambda name: "/usr/bin/podman" if name == "podman" else None),
        secret=kwargs.pop("secret", SECRET),
        now=NOW,
    )


def test_passing_run_writes_a_signed_receipt_the_release_gate_accepts(tmp_path: Path) -> None:
    rc, target, receipt = _produce(tmp_path, FakeRunner())
    assert rc == 0 and target is not None and receipt is not None
    written = json.loads(target.read_text())
    assert written["outcome"] == "pass"
    assert written["gate"] == "adoptability"
    assert written["runtime"] == "podman"
    assert written["checks"]["ttfv"]["seconds"] == 41.0
    assert pgr._mapping_has_trusted_authority_signature(written, SECRET)
    assert not pgr._mapping_has_trusted_authority_signature(written, "other")
    row = {
        "tags": ["cc-task", "garage-door"],
        "adoptability": {
            "install_line": INSTALL_LINE,
            "platforms": ["linux"],
            "api": "cli",
            "repo_open": "acme/tool",
            "receipt": "receipt.json",
        },
    }
    assert (
        gate.release_refusals(row, now=NOW.timestamp() + 60, roots=[tmp_path], secret=SECRET) == []
    )


def test_container_command_is_bare(tmp_path: Path) -> None:
    runner = FakeRunner()
    _produce(tmp_path, runner)
    run = next(cmd for cmd in runner.commands if cmd[0] == "podman")
    assert run[:3] == ["podman", "run", "--rm"]
    assert not any(flag in run for flag in ("-v", "--volume", "--mount", "--env-file"))
    assert run[run.index("--env") + 1] == "HOME=/root"
    assert not any("HAPAX_" in part for part in run)
    assert "/tmp/install.log" in run[-1] and INSTALL_LINE in run[-1]


def test_install_failure_fails_the_receipt_and_the_rest_is_not_reached(tmp_path: Path) -> None:
    rc, _, receipt = _produce(tmp_path, FakeRunner(install_rc=2))
    assert rc == 1 and receipt is not None
    assert receipt["outcome"] == "fail"
    assert receipt["checks"]["install"]["passed"] is False
    assert receipt["checks"]["zero_config"] == {"passed": False, "detail": "install failed"}
    assert receipt["checks"]["ttfv"]["passed"] is False


def test_runtime_failure_is_an_install_failure(tmp_path: Path) -> None:
    rc, _, receipt = _produce(tmp_path, FakeRunner(runtime_rc=125))
    assert rc == 1 and receipt is not None
    assert receipt["checks"]["install"]["passed"] is False
    assert "rc=125" in receipt["checks"]["install"]["detail"]


@pytest.mark.parametrize(
    ("runner_kwargs", "failed_check"),
    [
        ({"zc_out": "no harness found"}, "zero_config"),
        ({"zc_rc": 3}, "zero_config"),
        ({"fv_out": "nothing"}, "first_value"),
        ({"ttfv_ns": 93_000_000_000}, "ttfv"),
        (
            {
                "repo": {
                    "private": False,
                    "visibility": "public",
                    "has_issues": True,
                    "archived": False,
                    "license": {"spdx_id": "GPL-3.0"},
                }
            },
            "licence",
        ),
        (
            {
                "repo": {
                    "private": True,
                    "visibility": "private",
                    "has_issues": True,
                    "archived": False,
                    "license": {"spdx_id": "MIT"},
                }
            },
            "repo_open",
        ),
        (
            {
                "repo": {
                    "private": False,
                    "visibility": "public",
                    "has_issues": False,
                    "archived": False,
                    "license": {"spdx_id": "MIT"},
                }
            },
            "issues_open",
        ),
        (
            {
                "repo": {
                    "private": False,
                    "visibility": "public",
                    "has_issues": True,
                    "archived": True,
                    "license": {"spdx_id": "MIT"},
                }
            },
            "not_archived",
        ),
        ({"release": {}}, "release_notes"),
        ({"release": {"tag_name": "v1", "body": "  "}}, "release_notes"),
        ({"compare_rc": 22}, "compare_page"),
    ],
)
def test_each_failed_check_fails_the_receipt(
    tmp_path: Path, runner_kwargs: dict, failed_check: str
) -> None:
    rc, _, receipt = _produce(tmp_path, FakeRunner(**runner_kwargs))
    assert rc == 1 and receipt is not None
    assert receipt["checks"][failed_check]["passed"] is False, receipt["checks"]
    assert receipt["outcome"] == "fail"
    passing = {name for name, check in receipt["checks"].items() if check["passed"]}
    assert failed_check not in passing


def test_ttfv_over_budget_names_the_numbers(tmp_path: Path) -> None:
    _, _, receipt = _produce(tmp_path, FakeRunner(ttfv_ns=93_000_000_000))
    assert receipt is not None
    assert receipt["checks"]["ttfv"] == {
        "passed": False,
        "seconds": 93.0,
        "budget_seconds": 60,
        "detail": "93.0s against a 60s budget",
    }


def test_compare_page_url_is_checked_with_curl(tmp_path: Path) -> None:
    runner = FakeRunner()
    manifest = _manifest(tmp_path, compare=None, compare_page="https://example.org/tool/compare")
    rc, _, receipt = _produce(tmp_path, runner, manifest=manifest)
    assert rc == 0 and receipt is not None
    assert any(
        cmd[0] == "curl" and cmd[-1] == "https://example.org/tool/compare"
        for cmd in runner.commands
    )


def test_docker_stands_in_when_podman_is_absent(tmp_path: Path) -> None:
    rc, _, receipt = _produce(
        tmp_path, FakeRunner(), which=lambda name: "/usr/bin/docker" if name == "docker" else None
    )
    assert rc == 0 and receipt is not None and receipt["runtime"] == "docker"


def test_no_container_runtime_is_a_refusal_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(receipt_mod.Refused, match="receipt_refused:container_runtime_absent"):
        _produce(tmp_path, FakeRunner(), which=lambda name: None)
    assert not (tmp_path / "receipt.json").exists()


def test_missing_signing_credential_is_a_refusal(tmp_path: Path) -> None:
    with pytest.raises(receipt_mod.Refused, match="receipt_refused:signing_credential_absent"):
        _produce(tmp_path, FakeRunner(), secret="")
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"install_line": ""}, "install_line"),
        ({"repo": "not a repo"}, "repo"),
        ({"zero_config_pattern": None}, "zero_config_pattern"),
    ],
)
def test_invalid_manifest_is_a_refusal(tmp_path: Path, overrides: dict, field: str) -> None:
    manifest = _manifest(tmp_path, **overrides)
    with pytest.raises(receipt_mod.Refused, match=f"receipt_refused:manifest_invalid:{field}"):
        _produce(tmp_path, FakeRunner(), manifest=manifest)


def test_cli_refuses_without_a_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(pgr.PUBLIC_GATE_AUTHORITY_SECRET_ENV, SECRET)
    monkeypatch.setattr(receipt_mod.shutil, "which", lambda name: None)
    rc = receipt_mod.main(
        ["--manifest", str(_manifest(tmp_path)), "--out", str(tmp_path / "r.json")]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "receipt_refused:container_runtime_absent" in err
    assert "Next action" in err
