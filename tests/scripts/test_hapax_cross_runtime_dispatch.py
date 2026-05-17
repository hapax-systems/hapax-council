from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from shared.relay_mq import send_message
from shared.relay_mq_envelope import Envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-cross-runtime-dispatch"


def _write_registry(tmp_path: Path, lane: str = "cx-green", platform: str = "codex") -> Path:
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / f"{lane}.json").write_text(
        (f'{{"platform": "{platform}", "last_probe_utc": {time.time()}, "freshness_ttl_s": 3600}}'),
        encoding="utf-8",
    )
    return registry


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["HAPAX_TEAM_REGISTRY_DIR"] = str(_write_registry(tmp_path))
    env["HAPAX_ORCHESTRATION_LEDGER_DIR"] = str(tmp_path / "ledger")
    env["HAPAX_RELAY_MQ_DB"] = str(tmp_path / "relay" / "messages.db")
    env["HAPAX_SESSION_PROTECTION"] = str(tmp_path / "no-protection.md")
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        text=True,
        capture_output=True,
        timeout=5,
        env=env,
    )


def _dispatch_message(db_path: Path, *, lane: str = "cx-green", task: str = "task-1") -> str:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    env = Envelope(
        sender="operator",
        message_type="dispatch",
        priority=0,
        subject=task,
        authority_case="CASE-1",
        authority_item=task,
        recipients_spec=lane,
        payload="go",
    )
    return send_message(db_path, env)


def test_authority_bearing_dispatch_blocks_without_durable_mq(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--task",
        "task-1",
        "--case",
        "CASE-1",
        "--dry-run",
    )

    assert result.returncode == 1
    assert "lacks durable MQ binding" in result.stderr


def test_terminal_dispatch_can_be_labeled_advisory_only_without_mq(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--task",
        "task-1",
        "--case",
        "CASE-1",
        "--advisory-only",
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "ADVISORY_ONLY" in result.stdout
    assert "advisory:    true" in result.stdout


def test_fresh_durable_mq_dispatch_allows_authority_bearing_dry_run(tmp_path: Path) -> None:
    db_path = tmp_path / "relay" / "messages.db"
    message_id = _dispatch_message(db_path)

    result = _run(
        tmp_path,
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--task",
        "task-1",
        "--case",
        "CASE-1",
        "--mq-message-id",
        message_id,
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "durable_mq_dispatch_bound" in result.stdout
    assert "advisory:    false" in result.stdout
