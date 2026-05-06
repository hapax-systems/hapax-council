"""Tests for ``scripts/hapax-gemini-jr-team``."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RUNNER = REPO_ROOT / "scripts" / "hapax-gemini-jr-team"


def _env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HAPAX_GEMINI_JR_ROOT"] = str(tmp_path / "jr")
    env["HAPAX_GEMINI_JR_RELAY"] = str(tmp_path / "relay" / "gemini-jr.yaml")
    env["HAPAX_GEMINI_JR_DASHBOARD"] = str(tmp_path / "dashboard" / "gemini-jr-team.md")
    env["HAPAX_GEMINI_JR_LEVERAGE_DASHBOARD"] = str(tmp_path / "dashboard" / "jr-spark-leverage.md")
    return env


def _write_fake_packet(
    packets_dir: Path,
    *,
    role: str = "jr-reviewer",
    task_id: str = "fake-task",
    status: str = "ready_for_senior_review",
    senior_required: str = "true",
    timestamp: str = "20260503T120000Z",
) -> Path:
    """Synthesize a packet with a stable filename for state-machine tests."""
    packets_dir.mkdir(parents=True, exist_ok=True)
    path = packets_dir / f"{timestamp}-{role}-{task_id}.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "type: gemini-jr-packet",
                "created_at: 2026-05-03T12:00:00Z",
                f"jr_role: {role}",
                f"task_id: {task_id}",
                'title: "Fake task"',
                f"status: {status}",
                "model: gemini-3.1-pro-preview",
                "strict_latest_model: true",
                "prompt_sha256: deadbeef",
                "sidecar_exit_code: 0",
                f"senior_review_required: {senior_required}",
                "---",
                "",
                "# Fake task",
                "",
                "## Gemini Output",
                "",
                "Synthetic body for state-machine tests.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_jr_team_script_compiles() -> None:
    result = subprocess.run(
        ["python", "-m", "py_compile", str(RUNNER)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr


def test_dry_run_uses_strict_latest_model_and_redacts_prompt(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(RUNNER),
            "dispatch",
            "--role",
            "jr-reviewer",
            "--task-id",
            "secret-review",
            "--title",
            "Secret review",
            "--prompt",
            "SECRET_PROMPT_VALUE",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["model"] == "gemini-3.1-pro-preview"
    assert payload["strict_latest_model"] is True
    command = payload["command"]
    assert "--strict-model" in command
    assert "gemini-3.1-pro-preview" in command
    assert "gemini-3-flash-preview" not in json.dumps(payload)
    assert "SECRET_PROMPT_VALUE" not in json.dumps(payload)
    assert "<redacted-prompt>" in command


def test_dispatch_writes_packet_relay_dashboard_and_no_prompt_metadata(tmp_path: Path) -> None:
    fake_sidecar = tmp_path / "fake-sidecar"
    calls = tmp_path / "calls.jsonl"
    fake_sidecar.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\0' "$*" >> {calls}
case "$*" in
  *"gemini-3.1-pro-preview"*"--strict-model"*) ;;
  *) echo "missing strict latest model" >&2; exit 9 ;;
esac
printf '%s\\n' 'Finding: supplied packet has one test gap.'
printf '%s\\n' 'Created execution plan for SessionEnd: 2 hook(s)'
printf '%s\\n' 'Expanding hook command: noisy-hook'
printf '%s\\n' 'Hook execution for SessionEnd: 2 hooks executed successfully'
"""
    )
    fake_sidecar.chmod(0o755)
    secret_prompt = "PRIVATE_PROMPT_SHOULD_NOT_ENTER_METADATA"

    result = subprocess.run(
        [
            str(RUNNER),
            "--sidecar-bin",
            str(fake_sidecar),
            "dispatch",
            "--role",
            "jr-test-scout",
            "--task-id",
            "packet-test-gap",
            "--title",
            "Packet test gap",
            "--prompt",
            secret_prompt,
            "--timeout",
            "5",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    packet = Path(result.stdout.strip())
    assert packet.exists()
    assert "Finding: supplied packet has one test gap." in packet.read_text()
    assert "strict_latest_model: true" in packet.read_text()
    assert "Created execution plan for SessionEnd" not in packet.read_text()
    assert "Expanding hook command:" not in packet.read_text()
    assert "Hook execution for SessionEnd" not in packet.read_text()
    metadata = (tmp_path / "jr" / "metadata.jsonl").read_text()
    assert "PRIVATE_PROMPT_SHOULD_NOT_ENTER_METADATA" not in metadata
    record = json.loads(metadata.splitlines()[0])
    assert record["model"] == "gemini-3.1-pro-preview"
    assert record["strict_latest_model"] is True
    assert record["status"] == "ready_for_senior_review"
    relay = tmp_path / "relay" / "gemini-jr.yaml"
    dashboard = tmp_path / "dashboard" / "gemini-jr-team.md"
    assert relay.exists()
    assert dashboard.exists()
    assert "authority: no_repo_edits_no_claims_no_prs_no_merge_no_deploy" in relay.read_text()
    assert "Gemini CLI is a packet-only junior support team" in dashboard.read_text()
    call_line = calls.read_text()
    assert "--strict-model" in call_line
    assert "gemini-3.1-pro-preview" in call_line
    assert "gemini-3-flash-preview" not in call_line


# --- consume / supersede / triage state-machine tests --------------------


def test_consume_rewrites_frontmatter_and_clears_review_required(tmp_path: Path) -> None:
    env = _env(tmp_path)
    packets = tmp_path / "jr" / "packets"
    packet = _write_fake_packet(packets, task_id="consume-target")

    result = subprocess.run(
        [
            str(RUNNER),
            "consume",
            packet.name,
            "--by",
            "alpha",
            "--artefact",
            "pr/9999",
            "--note",
            "hand-graduated to PR #9999",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr

    text = packet.read_text()
    assert "status: consumed" in text
    assert "consumed_by: alpha" in text
    assert "consumption_artefact: pr/9999" in text
    assert "senior_review_required: false" in text
    assert "consumption_note:" in text
    # Body preserved
    assert "Synthetic body for state-machine tests." in text


def test_supersede_records_reason_and_clears_review_required(tmp_path: Path) -> None:
    env = _env(tmp_path)
    packets = tmp_path / "jr" / "packets"
    packet = _write_fake_packet(packets, task_id="supersede-target")

    result = subprocess.run(
        [
            str(RUNNER),
            "supersede",
            packet.name,
            "--by",
            "beta",
            "--reason",
            "covered by cc-task X already",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr

    text = packet.read_text()
    assert "status: superseded" in text
    assert "consumed_by: beta" in text
    assert "superseded_reason:" in text
    assert "covered by cc-task X already" in text
    assert "senior_review_required: false" in text


def test_triage_lists_pending_and_excludes_consumed(tmp_path: Path) -> None:
    env = _env(tmp_path)
    packets = tmp_path / "jr" / "packets"
    pending = _write_fake_packet(packets, task_id="still-pending", timestamp="20260503T100000Z")
    _write_fake_packet(
        packets,
        task_id="already-consumed",
        timestamp="20260503T100100Z",
        senior_required="false",
    )

    result = subprocess.run(
        [str(RUNNER), "triage", "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    fnames = [p["filename"] for p in parsed]
    assert pending.name in fnames
    # The senior_review_required=false packet must be excluded
    assert all("already-consumed" not in n for n in fnames)


def test_triage_role_filter_narrows_results(tmp_path: Path) -> None:
    env = _env(tmp_path)
    packets = tmp_path / "jr" / "packets"
    _write_fake_packet(
        packets, role="jr-reviewer", task_id="reviewer-only", timestamp="20260503T100000Z"
    )
    _write_fake_packet(
        packets, role="jr-test-scout", task_id="test-scout-only", timestamp="20260503T100100Z"
    )

    result = subprocess.run(
        [str(RUNNER), "triage", "--role", "jr-test-scout", "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert len(parsed) == 1
    assert parsed[0]["role"] == "jr-test-scout"
    assert parsed[0]["task_id"] == "test-scout-only"


def test_consume_updates_leverage_dashboard(tmp_path: Path) -> None:
    env = _env(tmp_path)
    packets = tmp_path / "jr" / "packets"
    packet = _write_fake_packet(packets, task_id="dashboard-target")
    leverage = tmp_path / "dashboard" / "jr-spark-leverage.md"

    subprocess.run(
        [
            str(RUNNER),
            "consume",
            packet.name,
            "--by",
            "alpha",
            "--artefact",
            "cc-task/some-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
        check=True,
    )

    assert leverage.exists()
    body = leverage.read_text()
    assert "Pending senior review: **0**" in body
    assert "Consumed (lifetime): **1**" in body
    assert "cc-task/some-task" in body


def test_status_subcommand_emits_both_dashboards(tmp_path: Path) -> None:
    env = _env(tmp_path)
    # Force at least one packet on disk so dashboards have content
    _write_fake_packet(tmp_path / "jr" / "packets", task_id="status-test")
    result = subprocess.run(
        [str(RUNNER), "status"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    # Activity dashboard + leverage dashboard
    assert "gemini-jr-team.md" in result.stdout
    assert "jr-spark-leverage.md" in result.stdout
    activity = tmp_path / "dashboard" / "gemini-jr-team.md"
    leverage = tmp_path / "dashboard" / "jr-spark-leverage.md"
    assert activity.exists()
    assert leverage.exists()


def test_consume_rejects_missing_packet(tmp_path: Path) -> None:
    env = _env(tmp_path)
    (tmp_path / "jr" / "packets").mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            str(RUNNER),
            "consume",
            "does-not-exist.md",
            "--by",
            "alpha",
            "--artefact",
            "pr/0",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode != 0
    assert "packet not found" in result.stderr


# --- jr-test-scout coverage gaps (audit 20260503T041448Z) ----------------


def test_dispatch_prompt_and_prompt_file_mutex_exits_with_error(tmp_path: Path) -> None:
    """Gap 1: ``--prompt`` and ``--prompt-file`` together must not silently pick one.

    The runner ``raise SystemExit("--prompt and --prompt-file are mutually
    exclusive")`` from ``_prompt_from_args``. Verify the user gets a
    non-zero exit + the error message on stderr.
    """

    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("from file", encoding="utf-8")
    result = subprocess.run(
        [
            str(RUNNER),
            "dispatch",
            "--role",
            "jr-reviewer",
            "--task-id",
            "x",
            "--title",
            "x",
            "--prompt",
            "from arg",
            "--prompt-file",
            str(prompt_file),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=5,
    )
    assert result.returncode != 0
    assert "--prompt and --prompt-file are mutually exclusive" in result.stderr


def test_dispatch_reads_stdin_when_no_prompt_args(tmp_path: Path) -> None:
    """Gap 2: stdin fallback when ``sys.stdin.isatty()`` is false.

    Pipe input into the dispatcher with neither ``--prompt`` nor
    ``--prompt-file``; ``--dry-run`` lets us inspect the planned packet
    contract without invoking sidecar.
    """

    result = subprocess.run(
        [
            str(RUNNER),
            "dispatch",
            "--role",
            "jr-reviewer",
            "--task-id",
            "stdin-task",
            "--title",
            "Stdin Task",
            "--dry-run",
        ],
        input="STDIN_PROMPT_BODY",
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    # Dry-run must redact the prompt — but the digest changes only when
    # the sidecar prompt body changes, so we assert the contract: stdin
    # was consumed and a non-empty prompt_sha256 was produced.
    assert payload["task_id"] == "stdin-task"
    assert isinstance(payload["prompt_sha256"], str) and len(payload["prompt_sha256"]) == 64


def test_dispatch_writes_blocked_status_on_sidecar_nonzero_exit(tmp_path: Path) -> None:
    """Gap 3: sidecar non-zero exit → packet status = blocked_strict_model_or_sidecar_error."""

    fake_sidecar = tmp_path / "fake-sidecar"
    fake_sidecar.write_text(
        """#!/usr/bin/env bash
printf 'sidecar barfed\\n' >&2
exit 5
"""
    )
    fake_sidecar.chmod(0o755)

    result = subprocess.run(
        [
            str(RUNNER),
            "--sidecar-bin",
            str(fake_sidecar),
            "dispatch",
            "--role",
            "jr-reviewer",
            "--task-id",
            "blocked-task",
            "--title",
            "Blocked",
            "--prompt",
            "anything",
            "--timeout",
            "5",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=10,
    )
    assert result.returncode == 5  # propagates sidecar's exit code
    packet = Path(result.stdout.strip())
    assert packet.exists()
    text = packet.read_text()
    assert "status: blocked_strict_model_or_sidecar_error" in text
    record = json.loads((tmp_path / "jr" / "metadata.jsonl").read_text().splitlines()[0])
    assert record["status"] == "blocked_strict_model_or_sidecar_error"
    assert record["exit_code"] == 5


def test_plan_subcommand_lists_roles_and_authority(tmp_path: Path) -> None:
    """Gap 4: ``plan`` subcommand prints model policy + role authority lines."""

    result = subprocess.run(
        [str(RUNNER), "plan"],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "model: gemini-3.1-pro-preview" in out
    assert "strict_latest_model: true" in out
    assert "authority: packet-only" in out
    # At least the two canonical roles seen across the fleet
    assert "jr-reviewer:" in out
    assert "jr-test-scout:" in out


def test_recent_records_skips_malformed_metadata_lines(tmp_path: Path) -> None:
    """Gap 5: ``_recent_records`` must survive malformed ``metadata.jsonl`` lines.

    Pre-seed the metadata log with a mix of valid + corrupt rows; invoke
    ``status`` (which calls ``_recent_records`` indirectly via the
    dashboard); assert no crash and the dashboard reflects the valid
    rows only.
    """

    metadata = tmp_path / "jr" / "metadata.jsonl"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    valid_record = {
        "created_at": "2026-05-04T12:00:00Z",
        "role": "jr-reviewer",
        "task_id": "valid-task",
        "status": "ready_for_senior_review",
        "exit_code": 0,
        "packet_path": str(tmp_path / "jr" / "packets" / "valid.md"),
    }
    metadata.write_text(
        "\n".join(
            [
                json.dumps(valid_record, sort_keys=True),
                "this-is-not-json",
                "{'unbalanced': true",  # invalid JSON
                "",  # blank line
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(RUNNER), "status"],
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    dashboard = tmp_path / "dashboard" / "gemini-jr-team.md"
    assert dashboard.exists()
    body = dashboard.read_text()
    assert "valid-task" in body
