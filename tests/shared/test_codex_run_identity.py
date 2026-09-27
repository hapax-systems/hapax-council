"""Actual native rollout correlation for the fresh local headless consumer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.codex_execution_receipt import observe_codex_run_identity
from shared.platform_capability_registry import ExecutionDescriptor

SID = "01900000-1234-7000-8000-123456789abc"
START = "2026-09-21T07:00:00.000Z"
DESC = ExecutionDescriptor(model_id="gpt-6-astra", effort="xhigh")


def _native(tmp_path: Path, *, model="gpt-6-astra", effort="xhigh"):
    home = tmp_path / "native"
    project = tmp_path / "project"
    project.mkdir()
    path = home / "sessions/2026/09/21" / f"rollout-2026-09-21T07-00-01-{SID}.jsonl"
    path.parent.mkdir(parents=True)
    events = [
        {
            "type": "session_meta",
            "timestamp": "2026-09-21T07:00:01Z",
            "payload": {"id": SID, "cwd": str(project)},
        },
        {
            "type": "turn_context",
            "timestamp": "2026-09-21T07:00:02Z",
            "payload": {"turn_id": "turn-one", "model": model, "effort": effort},
        },
    ]

    def write():
        path.write_text("".join(json.dumps(e) + "\n" for e in events))

    write()
    return home, project, path, events, write


def _observe(home, project, **kwargs):
    return observe_codex_run_identity(
        DESC,
        route_id="codex.headless.full",
        session_id=SID,
        native_home=home,
        workdir=project,
        launch_started_at=START,
        **kwargs,
    )


def test_correlates_native_identity_with_frozen_declaration(tmp_path):
    home, project, path, _, _ = _native(tmp_path)
    result = _observe(home, project)
    assert result["status"] == "matched"
    assert result["declared"] == DESC.model_dump(mode="json")
    assert result["turns"][0]["observed"] == {"model": "gpt-6-astra", "effort": "xhigh"}
    assert result["rollout"]["path"] == str(path)
    assert result["rollout"]["bytes"] == path.stat().st_size
    assert len(result["rollout"]["sha256"]) == 64
    assert result["may_authorize"] is False


def test_relative_bindings_are_frozen_as_physical_absolute_paths(tmp_path, monkeypatch):
    home, project, _, _, _ = _native(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = _observe(home.relative_to(tmp_path), project.relative_to(tmp_path))
    assert result["status"] == "matched"
    assert result["native_home"] == str(home.resolve())
    assert result["workdir"] == str(project.resolve())


@pytest.mark.parametrize(
    "model,effort,status",
    [
        ("gpt-5.5", "xhigh", "misattributed"),
        ("gpt-6-astra", "low", "misattributed"),
        ("gpt-5.5", None, "misattributed"),
        (None, "low", "misattributed"),
        (None, "xhigh", "unverified"),
        ("gpt-6-astra", None, "unverified"),
    ],
)
def test_preserves_known_mismatch_and_missing_axes(tmp_path, model, effort, status):
    home, project, _, _, _ = _native(tmp_path, model=model, effort=effort)
    assert _observe(home, project)["status"] == status


@pytest.mark.parametrize(
    "change,reason",
    [
        ("session", "native_rollout_session_mismatch"),
        ("cwd", "native_rollout_workdir_mismatch"),
        ("old", "native_rollout_predates_launch"),
        ("duplicate_meta", "native_rollout_session_metadata_ambiguous"),
        ("missing_turns", "native_turn_context_absent"),
        ("malformed", "native_rollout_malformed"),
        ("duplicate_key", "native_rollout_malformed"),
        ("partial", "native_rollout_malformed"),
        ("missing", "native_rollout_unavailable"),
        ("multiple", "native_rollout_ambiguous"),
    ],
)
def test_wrong_or_unavailable_run_never_matches(tmp_path, change, reason):
    home, project, path, events, write = _native(tmp_path)
    if change == "session":
        events[0]["payload"]["id"] = "another-run"
    elif change == "cwd":
        events[0]["payload"]["cwd"] = str(tmp_path / "elsewhere")
    elif change == "old":
        events[0]["timestamp"] = "2026-09-20T07:00:00Z"
    elif change == "duplicate_meta":
        events.append(events[0])
    elif change == "missing_turns":
        events.pop()
    write()
    if change == "malformed":
        path.write_text(path.read_text() + "not JSON\n")
    elif change == "duplicate_key":
        path.write_text(
            path.read_text().replace('"effort": "xhigh"', '"effort": "low", "effort": "xhigh"')
        )
    elif change == "partial":
        path.write_bytes(path.read_bytes()[:-2])
    elif change == "missing":
        path.unlink()
    elif change == "multiple":
        (path.parent / f"rollout-other-{SID}.jsonl").write_bytes(path.read_bytes())
    result = _observe(home, project)
    assert result["status"] == "unverified"
    assert reason in result["reason_codes"]
    assert result["may_authorize"] is False


def test_later_native_turn_mismatch_is_visible(tmp_path):
    home, project, _, events, write = _native(tmp_path)
    events.append(
        {
            "type": "turn_context",
            "timestamp": "2026-09-21T07:00:03Z",
            "payload": {"turn_id": "turn-two", "model": "gpt-5.5", "effort": "xhigh"},
        }
    )
    write()
    result = _observe(home, project)
    assert result["status"] == "misattributed"
    assert [turn["status"] for turn in result["turns"]] == ["matched", "misattributed"]


@pytest.mark.parametrize("position", [1, 2])
@pytest.mark.parametrize(
    "model,status", [("gpt-5.5", "misattributed"), ("gpt-6-astra", "unverified")]
)
def test_prelaunch_turn_does_not_erase_correlated_evidence(tmp_path, position, model, status):
    home, project, _, events, write = _native(tmp_path, model=model)
    events.insert(
        position,
        {
            "type": "turn_context",
            "timestamp": "2026-09-21T06:59:59Z",
            "payload": {"model": "gpt-6-astra", "effort": "xhigh"},
        },
    )
    write()
    result = _observe(home, project)
    assert result["status"] == status
    assert "native_turn_predates_launch" in result["reason_codes"]
    assert len(result["turns"]) == 1
    assert result["turns"][0]["observed"]["model"] == model
    assert result["may_authorize"] is False


def test_replay_pins_observed_prefix_and_rejects_changed_bytes(tmp_path):
    home, project, path, events, write = _native(tmp_path)
    first = _observe(home, project)
    original = path.read_bytes()
    with path.open("a") as stream:
        stream.write(
            json.dumps({"type": "turn_context", "payload": {"model": "later", "effort": "low"}})
            + "\n"
        )
    replay = _observe(home, project, expected_rollout=first["rollout"])
    assert replay == first
    path.write_bytes(original.replace(b"gpt-6-astra", b"gpt-5.astrb"))
    assert _observe(home, project, expected_rollout=first["rollout"])["reason_codes"] == [
        "native_rollout_hash_mismatch"
    ]


def test_missing_or_malformed_stream_session_is_unverified(tmp_path):
    home, project, _, _, _ = _native(tmp_path)
    for session in [None, "", "../../not-a-session", True]:
        result = observe_codex_run_identity(
            DESC,
            route_id="codex.headless.full",
            session_id=session,
            native_home=home,
            workdir=project,
            launch_started_at=START,
        )
        assert result["status"] == "unverified"
        assert result["reason_codes"] == ["native_session_identity_unavailable"]
