"""Pins for the seat owed set, v3 oracle plus the unsafe cases."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hapax-seat-owed-set"
VAULT = Path.home() / "Documents" / "Personal"

AT_1952 = "2026-09-24T19:52:20+00:00"
COMMIT_1952 = "1f3ae2fbd"
AT_2217 = "2026-09-24T22:17:37+00:00"
BUS_2217 = "2026-09-24T22:17:37"
COMMIT_2217 = "a847f9f3e"

O_ROWS = [
    "api-frontier-dead-credentials-retire-or-rotate-20260924",
    "appendix-litellm-4000-intent-restore-or-correct-20260924",
    "fleet-inventory-serving-roles-refresh-20260924",
    "openrouter-key-containment-console-act-20260924",
    "quota-ledger-reason-truth-kimi-glm-codex-local-20260924",
    "registry-declare-entitled-providers-and-reclassify-fugu-20260924",
    "routing-table-entitlement-rows-refresh-20260924",
    "sonar-alias-retirement-before-20260927",
    "workspace-agents-md-local-serving-lines-20260924",
]
E1 = "entitlement-census-producer-20260924"
CONDUCTOR = "session-conductor-false-parent-spawn-repair-20260924"
REVIEW_SUB = "review-substitute-seats-route-backed-receipts-20260924"
VERBOO = "verboo-failure-root-cause-20260924"
CLAUDE_ADMIT = "claude-interactive-admission-repair-20260924"
ESCALATION = ["recovery-escalation-lane-beta", "recovery-escalation-lane-gamma"]
TARGETS = [E1, *O_ROWS, CONDUCTOR, REVIEW_SUB, VERBOO, CLAUDE_ADMIT, *ESCALATION]


def _run(vault: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), "--vault", str(vault), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _snap(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_row(vault: Path, task_id: str, front: str, body: str) -> None:
    path = vault / "20-projects" / "hapax-cc-tasks" / "active" / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8")


def _offered(task_id: str, *, blocked: str = "null", impl: str = "false", created: str) -> str:
    return "\n".join(
        [
            f"task_id: {task_id}",
            "status: offered",
            f"blocked_reason: {blocked}",
            "assigned_to: unassigned",
            f"implementation_authorized: {impl}",
            f"created_at: {created}",
        ]
    )


def _members(proc: subprocess.CompletedProcess[str]) -> dict[str, list[str]]:
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return {row["task_id"]: row["classes"] for row in payload["rows"]}


def _payload(proc: subprocess.CompletedProcess[str]) -> dict:
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_section5_line_is_not_a_disposition(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "owed-row",
        _offered("owed-row", created="2026-09-24T20:17:27Z"),
        "## Session log\n- 2026-09-24T20:17:27Z dev3: drafted for the coordinator\n",
    )
    seat = tmp_path / "30-areas" / "hapax" / "frame" / "COORDINATOR-SEAT.md"
    seat.parent.mkdir(parents=True, exist_ok=True)
    seat.write_text("## 5\nfolded_into: owed-row\n", encoding="utf-8")
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert "owed-row" in found


def test_lane_author_mentioning_the_seat_is_not_seat_authored(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "lane-row",
        _offered("lane-row", created="2026-09-24T20:17:27Z"),
        "## Session log\n- 2026-09-24T20:17:27Z dev3: drafted at the seat's request\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert found["lane-row"] == ["S5"]


def test_yaml_null_is_not_a_blocked_reason(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "null-row",
        _offered("null-row", created="2026-09-24T20:17:27Z"),
        "## Session log\n- 2026-09-24T20:17:27Z dev3: drafted. coordinator copy.\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert "S1" not in found["null-row"]
    assert "S5" in found["null-row"]


def test_prose_await_the_coordinator_is_s1(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "await-row",
        _offered(
            "await-row",
            blocked="authority fields await the coordinator",
            created="2026-09-24T19:28:38Z",
        ),
        "## Session log\n- 2026-09-24T19:28:38Z filed by dev3 for the record\n",
    )
    found = _members(
        _run(
            tmp_path,
            "--commit",
            "WORKTREE",
            "--at",
            AT_1952,
            "--json",
            "--disable",
            "S1.marker,S5",
        )
    )
    assert found["await-row"] == ["S1"]


def test_s2_authorized_unassigned_is_owed_without_a_vault(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "s2-row",
        _offered("s2-row", impl="true", created="2026-09-24T20:17:27Z"),
        "## Session log\n- 2026-09-24T20:17:27Z dev3: drafted for a lane\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert found["s2-row"] == ["S2"]
    _write_row(
        tmp_path,
        "s2-row",
        _offered("s2-row", impl="false", created="2026-09-24T20:17:27Z"),
        "## Session log\n- 2026-09-24T20:17:27Z dev3: drafted for a lane\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert "S2" not in found["s2-row"]
    assert "S5" in found["s2-row"]


def test_s3_closure_marker_on_a_claimed_row_without_a_vault(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "s3-row",
        "\n".join(
            [
                "task_id: s3-row",
                "status: claimed",
                "blocked_reason: null",
                "assigned_to: dev3",
                "implementation_authorized: false",
                "created_at: 2026-09-24T19:00:00Z",
            ]
        ),
        "closure requested\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert found["s3-row"] == ["S3"]
    _write_row(
        tmp_path,
        "s3-row",
        "\n".join(
            [
                "task_id: s3-row",
                "status: claimed",
                "blocked_reason: null",
                "assigned_to: dev3",
                "implementation_authorized: false",
                "created_at: 2026-09-24T19:00:00Z",
            ]
        ),
        "work continues\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert "s3-row" not in found


def test_dev1_seat_log_author_is_a_seat_action(tmp_path: Path) -> None:
    _seat(tmp_path, "| incumbent | claude/dev1 — The process role is `dev1-seat`. |")
    _write_row(
        tmp_path,
        "seat-authored",
        _offered("seat-authored", created="2026-09-24T20:17:27Z"),
        "## Session log\n- 2026-09-24T20:17:27Z dev1-seat: drafted the row\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert "seat-authored" not in found


def test_logless_offered_row_is_in_the_set(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "logless-row",
        _offered("logless-row", created="2026-09-24T20:17:27Z"),
        "coordinator note without a session log\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert found["logless-row"] == ["S5"]


def test_aged_row_stays_in_the_set(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "old-row",
        _offered("old-row", created="2026-01-01T00:00:00Z"),
        "## Session log\n- 2026-01-01T00:00:00Z dev3: drafted. coordinator copy.\n",
    )
    found = _members(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert "S5" in found["old-row"]


def test_unknown_age_is_reported(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "undated-row",
        _offered("undated-row", created="not-a-timestamp"),
        "## Session log\n- 2026-09-24T20:17:27Z dev3: drafted. coordinator copy.\n",
    )
    payload = _payload(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    row = next(item for item in payload["rows"] if item["task_id"] == "undated-row")
    assert row["age_h"] is None
    assert row["cohort"] == "backlog"
    assert payload["totals"]["unknown_age"] == 1


def test_disable_s1_clears_both_parts(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "await-row",
        _offered(
            "await-row",
            blocked="awaiting_coordinator_grant",
            created="2026-09-24T19:28:38Z",
        ),
        "authority fields are left for the coordinator\n",
    )
    found = _members(
        _run(tmp_path, "--commit", "WORKTREE", "--at", AT_1952, "--json", "--disable", "S1")
    )
    assert "await-row" not in found


def test_s6_stub_adds_nothing(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "lane-row",
        _offered("lane-row", created="2026-09-24T20:17:27Z"),
        "coordinator copy\n",
    )
    payload = _payload(_run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--json"))
    assert payload["s6"] == "stub"
    assert payload["totals"]["S6"] == 0
    assert all("S6" not in row["classes"] for row in payload["rows"])


def test_session_start_injects_owed_block_for_incumbent(tmp_path: Path) -> None:
    created = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_row(
        tmp_path,
        "lane-row",
        _offered("lane-row", created=created),
        "## Session log\n- 2026-09-24T20:17:27Z dev3: drafted at the seat's request\n",
    )
    seat = tmp_path / "30-areas" / "hapax" / "frame" / "COORDINATOR-SEAT.md"
    seat.parent.mkdir(parents=True, exist_ok=True)
    seat.write_text("| incumbent | claude/dev1 — session `test` |\n", encoding="utf-8")
    refreshed = _run(tmp_path, "--refresh-cache")
    assert refreshed.returncode == 0, refreshed.stderr
    env = os.environ.copy()
    env["HAPAX_AGENT_ROLE"] = "dev1"
    proc = subprocess.run(
        ["python3", str(SCRIPT), "--vault", str(tmp_path), "--session-start"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    text = payload["hookSpecificOutput"]["additionalContext"]
    assert "The owed set is the control point; §5 is narrative." in text
    assert "SEAT section 5 is the control point" not in text
    assert "OWED BY THE SEAT (" in text
    assert "lane-row" in text


def test_missing_cache_emits_unavailable_inside_two_seconds(tmp_path: Path) -> None:
    import time

    _seat(tmp_path, "| incumbent | claude/dev1 — The process role is `dev1-seat`. |")
    env = os.environ.copy()
    env["HAPAX_AGENT_ROLE"] = "dev1-seat"
    started = time.perf_counter()
    proc = subprocess.run(
        ["python3", str(SCRIPT), "--vault", str(tmp_path), "--session-start"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    elapsed = time.perf_counter() - started
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 2
    text = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert text.startswith("OWED BY THE SEAT (unavailable:")
    assert "hapax-seat-owed-set --text-block" in text
    assert "seat-owed-set.txt" in text
    assert "\n" not in text


def test_session_start_silent_for_other_roles(tmp_path: Path) -> None:
    seat = tmp_path / "30-areas" / "hapax" / "frame" / "COORDINATOR-SEAT.md"
    seat.parent.mkdir(parents=True, exist_ok=True)
    seat.write_text("| incumbent | claude/dev1 — session `test` |\n", encoding="utf-8")
    env = os.environ.copy()
    env["HAPAX_AGENT_ROLE"] = "grok-owedset"
    proc = subprocess.run(
        ["python3", str(SCRIPT), "--vault", str(tmp_path), "--session-start"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def _have(commit: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(VAULT), "rev-parse", "--verify", f"{commit}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def test_v3_oracle_at_2217() -> None:
    if not _have(COMMIT_2217):
        pytest.skip("vault snapshot a847f9f3e is not present")
    payload = _payload(
        _snap(
            "--commit",
            COMMIT_2217,
            "--at",
            AT_2217,
            "--bus-until",
            BUS_2217,
            "--json",
            "--targets",
            ",".join(TARGETS),
        )
    )
    totals = payload["totals"]
    assert totals["rows"] == 534
    assert totals["S1"] == 11
    assert totals["S2"] == 321
    assert totals["S3"] == 2
    assert totals["S5"] == 209
    assert totals["new"] == 35
    assert totals["backlog"] == 499
    assert totals["unknown_age"] == 152
    assert totals["S4"] == 15
    assert totals["ack_true"] == 3
    missing = [task_id for task_id in TARGETS if payload["targets"][task_id] == "ABSENT"]
    assert missing == []


def test_e1_and_conductor_at_1952() -> None:
    if not _have(COMMIT_1952):
        pytest.skip("vault snapshot 1f3ae2fbd is not present")
    payload = _payload(
        _snap(
            "--commit",
            COMMIT_1952,
            "--at",
            AT_1952,
            "--bus-until",
            "2026-09-24T19:52:20",
            "--json",
            "--targets",
            f"{E1},{CONDUCTOR}",
        )
    )
    assert payload["targets"][E1].startswith("IN")
    assert "S1" in payload["targets"][E1]
    assert payload["targets"][E1].endswith(" new")
    assert "S2" in payload["targets"][CONDUCTOR]
    assert payload["targets"][CONDUCTOR].endswith(" new")


def test_disable_s2_drops_only_the_conductor() -> None:
    if not _have(COMMIT_2217):
        pytest.skip("vault snapshot a847f9f3e is not present")
    payload = _payload(
        _snap(
            "--commit",
            COMMIT_2217,
            "--at",
            AT_2217,
            "--bus-until",
            BUS_2217,
            "--disable",
            "S2",
            "--json",
            "--targets",
            ",".join(TARGETS),
        )
    )
    absent = [task_id for task_id, verdict in payload["targets"].items() if verdict == "ABSENT"]
    assert absent == [CONDUCTOR]


def test_disable_s3_drops_only_verboo() -> None:
    if not _have(COMMIT_2217):
        pytest.skip("vault snapshot a847f9f3e is not present")
    payload = _payload(
        _snap(
            "--commit",
            COMMIT_2217,
            "--at",
            AT_2217,
            "--bus-until",
            BUS_2217,
            "--disable",
            "S3",
            "--json",
            "--targets",
            ",".join(TARGETS),
        )
    )
    absent = [task_id for task_id, verdict in payload["targets"].items() if verdict == "ABSENT"]
    assert absent == [VERBOO]


def test_disable_s1_s2_s5_leaves_both_s3_rows() -> None:
    """Pins both counts. |O| is 2 rows. Among the 16 targets, 15 are absent.

    E0 (entitlement-census-and-single-view) is the second S3 row and is not a target.
    """
    if not _have(COMMIT_2217):
        pytest.skip("vault snapshot a847f9f3e is not present")
    other = "entitlement-census-and-single-view-20260924"
    payload = _payload(
        _snap(
            "--commit",
            COMMIT_2217,
            "--at",
            AT_2217,
            "--bus-until",
            BUS_2217,
            "--disable",
            "S1,S2,S5",
            "--json",
            "--targets",
            ",".join([*TARGETS, other]),
        )
    )
    assert payload["totals"]["rows"] == 2
    assert payload["totals"]["S3"] == 2
    present_targets = [
        task_id for task_id in TARGETS if payload["targets"][task_id].startswith("IN")
    ]
    assert present_targets == [VERBOO]
    assert payload["targets"][other].startswith("IN")


def test_fields_only_misses_only_verboo() -> None:
    if not _have(COMMIT_2217):
        pytest.skip("vault snapshot a847f9f3e is not present")
    payload = _payload(
        _snap(
            "--commit",
            COMMIT_2217,
            "--at",
            AT_2217,
            "--bus-until",
            BUS_2217,
            "--disable",
            "S1.marker,S3,S4",
            "--json",
            "--targets",
            ",".join(TARGETS),
        )
    )
    absent = [task_id for task_id, verdict in payload["targets"].items() if verdict == "ABSENT"]
    assert absent == [VERBOO]
    assert len(TARGETS) - len(absent) == 15


def _seat(vault: Path, line: str) -> None:
    path = vault / "30-areas" / "hapax" / "frame" / "COORDINATOR-SEAT.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(line + "\n", encoding="utf-8")


def _bus(vault: Path, seat: str, name: str, text: str) -> None:
    path = vault / "30-areas" / "hapax" / "lanebus" / seat / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_process_role_dev1_seat_injects_and_keeps_dev1_inbox(tmp_path: Path) -> None:
    created = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_row(
        tmp_path,
        "lane-row",
        _offered("lane-row", created=created),
        "## Session log\n- 2026-09-25T01:00:00Z dev3: drafted at the seat's request\n",
    )
    _bus(
        tmp_path,
        "dev1",
        "20260925T023937Z-dev17-dossier-4744-quorum-accept.md",
        "\n".join(
            [
                "---",
                "from: dev17",
                "to: dev1",
                "ack: true",
                "created_at: 2026-09-25T02:39:37Z",
                "---",
                "# Dossier #4744",
                "",
            ]
        ),
    )
    _seat(
        tmp_path,
        "| incumbent | claude/dev1 — session `test`. The process role is `dev1-seat`. |",
    )
    refreshed = _run(tmp_path, "--refresh-cache")
    assert refreshed.returncode == 0, refreshed.stderr
    env = os.environ.copy()
    env["HAPAX_AGENT_ROLE"] = "dev1-seat"
    proc = subprocess.run(
        ["python3", str(SCRIPT), "--vault", str(tmp_path), "--session-start"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    text = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "role dev1-seat" in text
    assert "lane-row" in text
    assert "4744" in text
    env["HAPAX_AGENT_ROLE"] = "dev1"
    silent = subprocess.run(
        ["python3", str(SCRIPT), "--vault", str(tmp_path), "--session-start"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert silent.stdout.strip() == ""


def test_re_token_disposes_the_answered_ask(tmp_path: Path) -> None:
    _bus(
        tmp_path,
        "dev1",
        "20260925T023937Z-dev17-dossier-4744-quorum-accept.md",
        "\n".join(
            [
                "---",
                "from: dev17",
                "ack: true",
                "created_at: 2026-09-25T02:39:37Z",
                "thread: mechanics-bundle-20260924",
                "---",
                "# Dossier #4744",
                "",
            ]
        ),
    )
    _bus(
        tmp_path,
        "dev1",
        "20260925T010000Z-dev18-open-question.md",
        "\n".join(
            [
                "---",
                "from: dev18",
                "ack: true",
                "created_at: 2026-09-25T01:00:00Z",
                "thread: other-thread",
                "---",
                "# Still open",
                "",
            ]
        ),
    )
    _bus(
        tmp_path,
        "dev17",
        "20260925T024057Z-dev1-follow-ups-after-merge.md",
        "\n".join(
            [
                "---",
                "from: claude/dev1 (seat, role dev1-seat)",
                "to: dev17",
                "created_at: 2026-09-25T02:40:57Z",
                "re: dossiers #4739, #4744, #4745",
                "---",
                "done",
                "",
            ]
        ),
    )
    payload = _payload(
        _run(
            tmp_path,
            "--commit",
            "WORKTREE",
            "--at",
            "2026-09-25T03:00:00+00:00",
            "--json",
        )
    )
    names = [item["name"] for item in payload["bus"]]
    assert "20260925T023937Z-dev17-dossier-4744-quorum-accept.md" not in names
    assert "20260925T010000Z-dev18-open-question.md" in names


def test_later_message_on_the_same_thread_disposes(tmp_path: Path) -> None:
    _bus(
        tmp_path,
        "dev1",
        "20260925T010000Z-dev18-ask.md",
        "\n".join(
            [
                "---",
                "from: dev18",
                "ack: true",
                "created_at: 2026-09-25T01:00:00Z",
                "thread: same-thread",
                "---",
                "",
            ]
        ),
    )
    _bus(
        tmp_path,
        "dev18",
        "20260925T020000Z-dev1-reply.md",
        "\n".join(
            [
                "---",
                "from: claude/dev1",
                "created_at: 2026-09-25T02:00:00Z",
                "thread: same-thread",
                "---",
                "done",
                "",
            ]
        ),
    )
    payload = _payload(
        _run(tmp_path, "--commit", "WORKTREE", "--at", "2026-09-25T03:00:00+00:00", "--json")
    )
    assert payload["bus"] == []


def _decision(vault: Path, in_force: bool) -> None:
    path = vault / "30-areas" / "hapax" / "frame" / "seat-stop-decisions.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "m103_in_force: " + ("true" if in_force else "false") + "\n"
        "cite: session-conductor-false-parent-spawn-repair-20260924\n",
        encoding="utf-8",
    )


def _start(vault: Path, role: str, source: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HAPAX_AGENT_ROLE"] = role
    return subprocess.run(
        ["python3", str(SCRIPT), "--vault", str(vault), "--session-start"],
        input=json.dumps({"source": source}),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_resume_non_seat_receives_conductor_directive_while_m103_holds(tmp_path: Path) -> None:
    _seat(tmp_path, "| incumbent | claude/dev1 — The process role is `dev1-seat`. |")
    _decision(tmp_path, True)
    proc = _start(tmp_path, "grok-owedset", "resume")
    assert proc.returncode == 0, proc.stderr
    text = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "CONDUCTOR: stop yours now:" in text
    assert "--role grok-owedset stop" in text
    assert "OWED BY THE SEAT" not in text


def test_resume_non_seat_gets_no_directive_when_m103_is_absent(tmp_path: Path) -> None:
    _seat(tmp_path, "| incumbent | claude/dev1 — The process role is `dev1-seat`. |")
    _decision(tmp_path, False)
    proc = _start(tmp_path, "grok-owedset", "resume")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_seat_resume_receives_owed_set_and_conductor_directive(tmp_path: Path) -> None:
    created = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_row(
        tmp_path,
        "lane-row",
        _offered("lane-row", created=created),
        "## Session log\n- 2026-09-25T01:00:00Z dev3: drafted\n",
    )
    _seat(tmp_path, "| incumbent | claude/dev1 — The process role is `dev1-seat`. |")
    _decision(tmp_path, True)
    refreshed = _run(tmp_path, "--refresh-cache")
    assert refreshed.returncode == 0, refreshed.stderr
    proc = _start(tmp_path, "dev1-seat", "resume")
    assert proc.returncode == 0, proc.stderr
    text = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "OWED BY THE SEAT" in text
    assert "lane-row" in text
    assert "CONDUCTOR: stop yours now:" in text
    assert "--role dev1-seat stop" in text


def test_reply_that_names_an_ask_without_a_disposition_does_not_dispose(tmp_path: Path) -> None:
    _bus(
        tmp_path,
        "dev1",
        "20260925T023937Z-dev17-dossier-4744-quorum-accept.md",
        "\n".join(
            [
                "---",
                "from: dev17",
                "ack: true",
                "created_at: 2026-09-25T02:39:37Z",
                "---",
                "# Dossier #4744",
                "",
            ]
        ),
    )
    _bus(
        tmp_path,
        "dev17",
        "20260925T024057Z-dev1-follow-ups-after-merge.md",
        "\n".join(
            [
                "---",
                "from: claude/dev1",
                "created_at: 2026-09-25T02:40:57Z",
                "re: dossiers #4739, #4744, #4745",
                "---",
                "follow-ups only",
                "",
            ]
        ),
    )
    payload = _payload(
        _run(tmp_path, "--commit", "WORKTREE", "--at", "2026-09-25T03:00:00+00:00", "--json")
    )
    names = [item["name"] for item in payload["bus"]]
    assert "20260925T023937Z-dev17-dossier-4744-quorum-accept.md" in names


def test_ticket_number_does_not_match_inside_the_timestamp(tmp_path: Path) -> None:
    _bus(
        tmp_path,
        "dev1",
        "20260925T014745Z-dev17-other-ask.md",
        "\n".join(
            [
                "---",
                "from: dev17",
                "ack: true",
                "created_at: 2026-09-25T01:47:45Z",
                "---",
                "# Other ask",
                "",
            ]
        ),
    )
    _bus(
        tmp_path,
        "dev17",
        "20260925T020000Z-dev1-reply.md",
        "\n".join(
            [
                "---",
                "from: claude/dev1",
                "created_at: 2026-09-25T02:00:00Z",
                "re: #4745",
                "---",
                "done",
                "",
            ]
        ),
    )
    payload = _payload(
        _run(tmp_path, "--commit", "WORKTREE", "--at", "2026-09-25T03:00:00+00:00", "--json")
    )
    names = [item["name"] for item in payload["bus"]]
    assert "20260925T014745Z-dev17-other-ask.md" in names


def test_process_role_phrase_outside_the_incumbent_row_is_ignored(tmp_path: Path) -> None:
    _seat(
        tmp_path,
        "\n".join(
            [
                "| incumbent | claude/dev1 — The process role is `dev1-seat`. |",
                "",
                "## 5",
                "process role is `other-role`",
            ]
        ),
    )
    created = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_row(
        tmp_path,
        "lane-row",
        _offered("lane-row", created=created),
        "coordinator copy\n",
    )
    refreshed = _run(tmp_path, "--refresh-cache")
    assert refreshed.returncode == 0, refreshed.stderr
    seated = _start(tmp_path, "dev1-seat", "clear")
    other = _start(tmp_path, "other-role", "clear")
    assert "lane-row" in json.loads(seated.stdout)["hookSpecificOutput"]["additionalContext"]
    assert other.stdout.strip() == ""


def test_absent_binary_still_emits_the_orientation_line(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts" / "hapax-seat-session-start")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    text = proc.stdout
    assert "COORDINATOR-SEAT.md" in text
    assert "OWED BY THE SEAT (unavailable: binary not installed" in text
    assert text.strip()


def test_quiet_prints_only_the_total_line(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "lane-row",
        _offered("lane-row", created="2026-09-24T20:17:27Z"),
        "coordinator copy\n",
    )
    proc = _run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--quiet")
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line]
    assert len(lines) == 1
    assert lines[0].startswith("TOTAL rows=")
    assert "lane-row" not in proc.stdout


def test_drop_in_uses_oneshot_base_and_activation_worktree() -> None:
    base = Path.home() / ".config/systemd/user/lanebus-staleness-sweep.service"
    if not base.is_file():
        pytest.skip("base user unit is not installed on this host")
    text = base.read_text(encoding="utf-8")
    assert "Type=oneshot" in text
    drop = ROOT / "systemd/units/lanebus-staleness-sweep.service.d/seat-owed-set.conf"
    body = drop.read_text(encoding="utf-8")
    assert "ExecStart=-" not in body
    assert ".cache/hapax/source-activation/worktree/scripts/hapax-seat-owed-set" in body
    assert "hapax-council--grok-owedset" not in body


def test_bad_commit_is_not_an_empty_owed_set(tmp_path: Path) -> None:
    proc = _run(tmp_path, "--commit", "deadbeef", "--at", AT_2217, "--json")
    assert proc.returncode != 0
    assert "OWED BY THE SEAT (0)" not in proc.stdout


def test_reply_older_than_the_ask_does_not_dispose_it(tmp_path: Path) -> None:
    _bus(
        tmp_path,
        "dev1",
        "20260925T023937Z-dev17-dossier-4744-quorum-accept.md",
        "\n".join(
            [
                "---",
                "from: dev17",
                "ack: true",
                "created_at: 2026-09-25T02:39:37Z",
                "---",
                "# Dossier #4744",
                "",
            ]
        ),
    )
    _bus(
        tmp_path,
        "dev17",
        "20260925T010000Z-dev1-earlier.md",
        "\n".join(
            [
                "---",
                "from: claude/dev1",
                "created_at: 2026-09-25T01:00:00Z",
                "re: #4744",
                "---",
                "done",
                "",
            ]
        ),
    )
    payload = _payload(
        _run(tmp_path, "--commit", "WORKTREE", "--at", "2026-09-25T03:00:00+00:00", "--json")
    )
    names = [item["name"] for item in payload["bus"]]
    assert "20260925T023937Z-dev17-dossier-4744-quorum-accept.md" in names


def test_reply_without_re_or_thread_stays_owed(tmp_path: Path) -> None:
    _bus(
        tmp_path,
        "dev1",
        "20260925T010000Z-dev18-ask.md",
        "\n".join(
            [
                "---",
                "from: dev18",
                "ack: true",
                "created_at: 2026-09-25T01:00:00Z",
                "thread: ask-thread",
                "---",
                "",
            ]
        ),
    )
    _bus(
        tmp_path,
        "dev18",
        "20260925T020000Z-dev1-unrelated.md",
        "\n".join(
            [
                "---",
                "from: claude/dev1",
                "created_at: 2026-09-25T02:00:00Z",
                "re: something else",
                "thread: other-thread",
                "---",
                "",
            ]
        ),
    )
    payload = _payload(
        _run(tmp_path, "--commit", "WORKTREE", "--at", "2026-09-25T03:00:00+00:00", "--json")
    )
    assert [item["name"] for item in payload["bus"]] == ["20260925T010000Z-dev18-ask.md"]


def test_summary_lists_new_and_bus_and_oldest_backlog(tmp_path: Path) -> None:
    _write_row(
        tmp_path,
        "fresh-row",
        _offered("fresh-row", created="2026-09-24T21:00:00Z"),
        "coordinator copy\n",
    )
    for index in range(20):
        _write_row(
            tmp_path,
            f"old-{index:02d}",
            _offered(f"old-{index:02d}", created="2026-01-01T00:00:00Z"),
            "coordinator copy\n",
        )
    proc = _run(tmp_path, "--commit", "WORKTREE", "--at", AT_2217, "--text-block")
    assert proc.returncode == 0, proc.stderr
    text = proc.stdout
    assert "fresh-row" in text
    assert "BACKLOG counts" in text
    assert "OLDEST backlog (15 of 20)" in text
    assert "old-19" not in text
    assert "Reply residual:" in text
    full = tmp_path / ".cache" / "seat-owed-set.txt"
    assert full.is_file()
    saved = full.read_text(encoding="utf-8")
    assert "old-19" in saved
    assert "full list:" in text


def test_everything_disabled_is_empty() -> None:
    if not _have(COMMIT_2217):
        pytest.skip("vault snapshot a847f9f3e is not present")
    payload = _payload(
        _snap(
            "--commit",
            COMMIT_2217,
            "--at",
            AT_2217,
            "--bus-until",
            BUS_2217,
            "--disable",
            "S1,S2,S3,S4,S5",
            "--json",
        )
    )
    assert payload["totals"]["rows"] == 0
    assert payload["totals"]["S4"] == 0
