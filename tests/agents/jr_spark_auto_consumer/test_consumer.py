"""Regression tests for ``agents.jr_spark_auto_consumer``."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from agents.jr_spark_auto_consumer import (
    Artefact,
    AutoConsumerConfig,
    Packet,
    RecordingStateMachineClient,
    classify_packet,
    run_once,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "scripts" / "hapax-jr-spark-auto-consumer"


def _write_packet(
    packet_root: Path,
    *,
    role: str,
    task_id: str,
    title: str | None = None,
    timestamp: str = "20260503T120000Z",
) -> Path:
    packet_root.mkdir(parents=True, exist_ok=True)
    path = packet_root / f"{timestamp}-{role}-{task_id}.md"
    packet_title = title or task_id.replace("-", " ")
    path.write_text(
        "\n".join(
            [
                "---",
                "type: gemini-jr-packet",
                "created_at: 2026-05-03T12:00:00Z",
                f"jr_role: {role}",
                f"task_id: {task_id}",
                f"title: {json.dumps(packet_title)}",
                "status: ready_for_senior_review",
                "senior_review_required: true",
                "---",
                "",
                f"# {packet_title}",
                "",
                "Synthetic packet body with bounded senior intake notes.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _packet(path: Path) -> Packet:
    text = path.read_text(encoding="utf-8")
    frontmatter_text = text.split("\n---\n", 1)[0].removeprefix("---\n")
    body = text.split("\n---\n", 1)[1]
    frontmatter: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        key, _, value = line.partition(":")
        frontmatter[key] = value.strip()
    return Packet(path=path, frontmatter=frontmatter, body=body)


def _write_cc_task(
    vault_root: Path,
    *,
    task_id: str,
    status: str = "offered",
    assigned_to: str = "unassigned",
    body: str = "Task body.",
) -> Path:
    active = vault_root / "active"
    active.mkdir(parents=True, exist_ok=True)
    path = active / f"{task_id}.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "type: cc-task",
                f"task_id: {task_id}",
                f"title: {json.dumps(task_id.replace('-', ' '))}",
                f"status: {status}",
                f"assigned_to: {assigned_to}",
                "priority: p3",
                "wsjf: 3",
                "---",
                "",
                f"# {task_id}",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _config(tmp_path: Path) -> AutoConsumerConfig:
    return AutoConsumerConfig(
        packet_root=tmp_path / "jr" / "packets",
        vault_root=tmp_path / "vault",
        repo_root=REPO_ROOT,
        jr_team_bin=REPO_ROOT / "scripts" / "hapax-gemini-jr-team",
        state_root=tmp_path / "state",
        enable_gh=False,
        git_log_limit=0,
    )


def test_classifier_consumes_stripped_slug_cc_task_match(tmp_path: Path) -> None:
    packet = _packet(
        _write_packet(
            tmp_path,
            role="jr-test-scout",
            task_id="test-gaps-cc-task-closure-hook",
        )
    )

    decision = classify_packet(
        packet,
        [
            Artefact(
                kind="cc-task",
                ref="cc-task/cc-task-closure-hook",
                text="cc-task-closure-hook closure discipline acceptance tests",
            )
        ],
    )

    assert decision.action == "consume"
    assert decision.artefact == "cc-task/cc-task-closure-hook"
    assert decision.reason == "stripped-prefix-match"


def test_unmatched_pattern_packet_supersedes_via_state_machine(tmp_path: Path) -> None:
    config = _config(tmp_path)
    packet = _write_packet(
        config.packet_root,
        role="jr-currentness-scout",
        task_id="pyright-180-incremental-perf",
    )
    client = RecordingStateMachineClient()

    actions = run_once(config, client=client, artefacts=[])

    assert [action.action for action in actions] == ["supersede"]
    assert actions[0].reason == "auto-classified pattern: currentness scout"
    assert client.calls == [
        ("supersede", str(packet), "auto-classified pattern: currentness scout")
    ]


def test_unmatched_actionable_packet_creates_offered_task_and_consumes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    packet = _write_packet(
        config.packet_root,
        role="jr-test-scout",
        task_id="test-gaps-iota-lane-final",
        title="Iota lane final test gaps",
    )
    client = RecordingStateMachineClient()

    actions = run_once(config, client=client, artefacts=[])

    assert [action.action for action in actions] == ["create_task"]
    created = config.vault_root / "active" / "test-gaps-iota-lane-final.md"
    text = created.read_text(encoding="utf-8")
    assert "status: offered" in text
    assert "assigned_to: unassigned" in text
    assert "audit_origin: jr-spark-auto-consumer" in text
    assert f"source_packet: {packet.name}" in text
    assert client.calls[0][0] == "consume"
    assert client.calls[0][2].startswith("cc-task/test-gaps-iota-lane-final")


def test_matching_claimed_cc_task_does_not_modify_task_note(tmp_path: Path) -> None:
    config = _config(tmp_path)
    claimed = _write_cc_task(
        config.vault_root,
        task_id="camera-salience",
        status="claimed",
        assigned_to="cx-alpha",
        body="Claim owner keeps this note stable.",
    )
    before = claimed.read_text(encoding="utf-8")
    packet = _write_packet(
        config.packet_root,
        role="jr-reviewer",
        task_id="review-camera-salience-design",
    )
    client = RecordingStateMachineClient()

    actions = run_once(
        config,
        client=client,
        artefacts=[
            Artefact(
                kind="cc-task",
                ref="cc-task/camera-salience",
                text=before,
                status="claimed",
                assigned_to="cx-alpha",
                source_path=claimed,
            )
        ],
    )

    assert [action.action for action in actions] == ["consume"]
    assert actions[0].artefact == "cc-task/camera-salience"
    assert claimed.read_text(encoding="utf-8") == before
    assert client.calls == [("consume", str(packet), "cc-task/camera-salience")]


def test_may_3_audit_fixture_set_classifications(tmp_path: Path) -> None:
    consumed = _packet(
        _write_packet(
            tmp_path / "packets",
            role="jr-currentness-scout",
            task_id="alpha-codex-tmux-multiplex-current",
            title="Alpha Codex tmux multiplex currentness",
        )
    )
    noop = _packet(
        _write_packet(
            tmp_path / "packets",
            role="jr-currentness-scout",
            task_id="pyright-180-incremental-perf",
        )
    )
    lost = _packet(
        _write_packet(
            tmp_path / "packets",
            role="jr-test-scout",
            task_id="test-gaps-iota-lane-final",
        )
    )
    artefacts = [
        Artefact(
            kind="pr",
            ref="pr/2324",
            text="feat(compositor): alpha codex tmux multiplex gauge and layout current signal",
        )
    ]

    assert classify_packet(consumed, artefacts).action == "consume"
    assert classify_packet(noop, []).action == "supersede"
    lost_decision = classify_packet(lost, [])
    assert lost_decision.action == "create_task"
    assert lost_decision.task_id == "test-gaps-iota-lane-final"


def test_cli_dry_run_uses_jr_root_packet_env(tmp_path: Path) -> None:
    jr_root = tmp_path / "jr"
    _write_packet(
        jr_root / "packets",
        role="jr-currentness-scout",
        task_id="obsidian-130-api-changes",
    )
    env = os.environ.copy()
    env["HAPAX_GEMINI_JR_ROOT"] = str(jr_root)
    result = subprocess.run(
        [
            "python",
            str(RUNNER),
            "run",
            "--vault-root",
            str(tmp_path / "vault"),
            "--state-root",
            str(tmp_path / "state"),
            "--no-gh",
            "--git-log-limit",
            "0",
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload[0]["action"] == "supersede"
