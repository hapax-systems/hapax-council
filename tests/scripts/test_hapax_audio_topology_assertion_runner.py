"""Contracts for the hard-failing audio topology assertion runner."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "hapax-audio-topology-assertion-runner"
ASSERTION_SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-audio-topology-assertion.service"
VERIFY_SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-audio-topology-verify.service"


def _runner_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("HAPAX_AUDIO_TOPOLOGY_", "HAPAX_STUB_")):
            env.pop(key)
    return env


def _stub_cli(tmp_path: Path, rc: int) -> Path:
    cli = tmp_path / "stub-hapax-audio-topology"
    cli.write_text(
        """#!/usr/bin/env bash
set -u
count_file="${HAPAX_STUB_COUNT_FILE:-}"
count=1
if [ -n "$count_file" ]; then
  if [ -f "$count_file" ]; then
    count="$(cat "$count_file")"
    count=$((count + 1))
  fi
  printf '%s\\n' "$count" > "$count_file"
fi
printf '%s\\n' "$@" > "$HAPAX_STUB_ARGS"
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--output" ]; then
    out="$arg"
    break
  fi
  prev="$arg"
done
if [ -n "$out" ]; then
  mkdir -p "$(dirname "$out")"
  printf '{"stub_report": true}\\n' > "$out"
fi
if [ "${HAPAX_STUB_RETRY_ONCE:-0}" = "1" ] && [ "$count" -eq 1 ]; then
  printf -- '- nodes only in left (expected but missing):\\n'
  printf -- '  - hapax-livestream-tap\\n'
  exit 2
fi
printf 'stub verify output'
exit "$HAPAX_STUB_RC"
""",
        encoding="utf-8",
    )
    cli.chmod(0o755)
    return cli


def _run_runner(tmp_path: Path, rc: int = 0) -> subprocess.CompletedProcess[str]:
    out_dir = tmp_path / "audio"
    descriptor = tmp_path / "audio-topology.yaml"
    descriptor.write_text("nodes: []\nedges: []\n", encoding="utf-8")
    env = _runner_env()
    env.update(
        {
            "HAPAX_AUDIO_TOPOLOGY_CLI": str(_stub_cli(tmp_path, rc)),
            "HAPAX_AUDIO_TOPOLOGY_DESCRIPTOR": str(descriptor),
            "HAPAX_AUDIO_TOPOLOGY_OUT_DIR": str(out_dir),
            "HAPAX_AUDIO_TOPOLOGY_READY_POLL_S": "0",
            "HAPAX_STUB_ARGS": str(tmp_path / "argv.txt"),
            "HAPAX_STUB_RC": str(rc),
        }
    )
    return subprocess.run(
        [str(RUNNER)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_runner_keeps_assertion_status_separate_from_periodic_verify_report(
    tmp_path: Path,
) -> None:
    result = _run_runner(tmp_path)

    assert result.returncode == 0, result.stderr
    out_dir = tmp_path / "audio"
    status_path = out_dir / "topology-assertion-status.json"
    assertion_report = out_dir / "topology-assertion-verify.json"
    periodic_report = out_dir / "topology-verify.json"

    assert status_path.exists()
    assert assertion_report.exists()
    assert not periodic_report.exists()

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["exit_code"] == 0
    assert status["attempts"] == 1
    assert isinstance(status["waited_s"], int)
    assert status["waited_s"] >= 0
    assert status["ready_timeout_s"] == 30
    assert status["status_path"] == str(status_path)
    assert status["structured_report_path"] == str(assertion_report)


def test_runner_invokes_verify_with_strict_and_structured_output(tmp_path: Path) -> None:
    result = _run_runner(tmp_path)

    assert result.returncode == 0
    argv = (tmp_path / "argv.txt").read_text(encoding="utf-8").splitlines()
    assert argv[0:2] == ["verify", "--strict"]
    assert "--output" in argv
    output_index = argv.index("--output")
    assert argv[output_index + 1] == str(tmp_path / "audio" / "topology-assertion-verify.json")
    prometheus_index = argv.index("--prometheus-textfile")
    assert argv[prometheus_index + 1] == ""
    assert argv[2] == str(tmp_path / "audio-topology.yaml")


def test_runner_propagates_verify_failure_without_suppressing_hard_gate(
    tmp_path: Path,
) -> None:
    result = _run_runner(tmp_path, rc=2)

    assert result.returncode == 2
    status = json.loads(
        (tmp_path / "audio" / "topology-assertion-status.json").read_text(encoding="utf-8")
    )
    assert status["ok"] is False
    assert status["exit_code"] == 2
    assert status["attempts"] == 1
    assert "stub verify output" in status["output"]


def test_runner_retries_boot_readiness_missing_node_once(tmp_path: Path) -> None:
    out_dir = tmp_path / "audio"
    descriptor = tmp_path / "audio-topology.yaml"
    descriptor.write_text("nodes: []\nedges: []\n", encoding="utf-8")
    env = _runner_env()
    count_file = tmp_path / "count.txt"
    env.update(
        {
            "HAPAX_AUDIO_TOPOLOGY_CLI": str(_stub_cli(tmp_path, 0)),
            "HAPAX_AUDIO_TOPOLOGY_DESCRIPTOR": str(descriptor),
            "HAPAX_AUDIO_TOPOLOGY_OUT_DIR": str(out_dir),
            "HAPAX_AUDIO_TOPOLOGY_READY_POLL_S": "0",
            "HAPAX_STUB_ARGS": str(tmp_path / "argv.txt"),
            "HAPAX_STUB_COUNT_FILE": str(count_file),
            "HAPAX_STUB_RC": "0",
            "HAPAX_STUB_RETRY_ONCE": "1",
        }
    )

    result = subprocess.run(
        [str(RUNNER)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    status = json.loads((out_dir / "topology-assertion-status.json").read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["exit_code"] == 0
    assert status["attempts"] == 2
    assert count_file.read_text(encoding="utf-8").strip() == "2"


def test_assertion_and_periodic_verify_services_have_distinct_output_contracts() -> None:
    assertion_runner = RUNNER.read_text(encoding="utf-8")
    assertion_unit = ASSERTION_SERVICE.read_text(encoding="utf-8")
    verify_unit = VERIFY_SERVICE.read_text(encoding="utf-8")

    assert "topology-assertion-status.json" in assertion_runner
    assert "topology-assertion-verify.json" in assertion_runner
    assert "topology-verify.json" in verify_unit
    assert "hapax-audio-topology-assertion-runner" in assertion_unit
    assert 'OUT_FILE="${OUT_DIR}/topology-verify.json"' not in assertion_runner


def test_assertion_service_requires_and_orders_after_pipewire() -> None:
    assertion_unit = ASSERTION_SERVICE.read_text(encoding="utf-8")

    assert "Requires=pipewire.service" in assertion_unit
    assert (
        "After=pipewire.service wireplumber.service pipewire-pulse.service "
        "hapax-l12-mainmix-tap-loopback.service"
    ) in assertion_unit
    assert (
        "Wants=pipewire.service wireplumber.service pipewire-pulse.service "
        "hapax-l12-mainmix-tap-loopback.service"
    ) in assertion_unit
