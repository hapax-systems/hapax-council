"""Conformance fixtures for platform session contract v1."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.platform_session_contract import (
    CONTRACT_EVENT_KINDS,
    AdapterContract,
    ControlMessage,
    ControlVerb,
    PlatformSessionContractError,
    adapter_artifacts,
    adapter_contract,
    adapter_contracts,
    artifact_projection_rows,
    coordination_plane_projection,
    normalize_native_events,
    parse_control_message,
    parse_jsonl_events,
    render_control_message,
    resolve_identity,
    run_conformance_fixture,
    validate_contract_event,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "platform_session_contract"
TASK_ID = "platform-contract-v1-spec-20260612"


def _fixture_rows(adapter: str, tmp_path: Path) -> tuple[dict[str, object], ...]:
    artifacts = _materialized_artifacts(adapter, tmp_path)
    if adapter == "adapter-claude":
        output_rows = parse_jsonl_events(FIXTURES / "claude-headless-output.jsonl")
    elif adapter == "adapter-codex":
        output_rows = parse_jsonl_events(FIXTURES / "codex-interactive-output.jsonl")
    else:
        raise AssertionError(adapter)
    observed_control_endpoints = (
        {artifacts.control_endpoint} if artifacts.control_endpoint.startswith("tmux:") else set()
    )
    return (
        *artifact_projection_rows(
            adapter,
            artifacts,
            task_id=TASK_ID,
            observed_control_endpoints=observed_control_endpoints,
        ),
        *output_rows,
    )


def _materialized_artifacts(adapter: str, tmp_path: Path):
    home = tmp_path / "home"
    runtime_dir = tmp_path / "run"
    if adapter == "adapter-claude":
        artifacts = adapter_artifacts(
            "adapter-claude",
            "alpha",
            home=home,
            runtime_dir=runtime_dir,
        )
        assert artifacts.output_stream is not None
        output_path = Path(artifacts.output_stream)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            (FIXTURES / "claude-headless-output.jsonl").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        endpoint = Path(artifacts.control_endpoint)
        endpoint.parent.mkdir(parents=True, exist_ok=True)
        endpoint.touch()
    elif adapter == "adapter-codex":
        artifacts = adapter_artifacts(
            "adapter-codex",
            "cx-red",
            home=home,
            runtime_dir=runtime_dir,
            mode="interactive",
        )
    else:
        raise AssertionError(adapter)
    claim_path = Path(artifacts.claim_file)
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim_path.write_text(f"{TASK_ID}\n", encoding="utf-8")
    return artifacts


def test_contract_event_kind_enum_is_closed() -> None:
    assert set(CONTRACT_EVENT_KINDS) == {
        "tool_call",
        "file_write",
        "claim",
        "push",
        "dossier_write",
        "task_mention",
        "status",
        "error",
        "heartbeat",
    }


def test_off_vocabulary_contract_event_is_rejected() -> None:
    with pytest.raises(PlatformSessionContractError) as exc:
        validate_contract_event(
            {
                "ts": "2026-06-12T06:00:00Z",
                "session_id": "cx-red",
                "kind": "thought_blob",
                "payload": {},
            }
        )

    assert exc.value.code == "off_vocabulary_event"
    assert "valid kinds:" in str(exc.value)


def test_off_vocabulary_lifecycle_state_is_rejected() -> None:
    with pytest.raises(PlatformSessionContractError) as exc:
        validate_contract_event(
            {
                "ts": "2026-06-12T06:00:00Z",
                "session_id": "cx-red",
                "kind": "status",
                "payload": {"lifecycle_state": "zombie"},
            }
        )

    assert exc.value.code == "off_vocabulary_lifecycle"
    assert "valid lifecycle states:" in str(exc.value)


def test_invalid_contract_event_has_next_action() -> None:
    with pytest.raises(PlatformSessionContractError) as exc:
        validate_contract_event(
            {
                "ts": "not-a-timestamp",
                "session_id": "cx-red",
                "kind": "status",
                "payload": {},
            }
        )

    assert exc.value.code == "invalid_contract_event"
    assert "Next action:" in str(exc.value)


def test_platform_event_serializes_to_contract_jsonl() -> None:
    event = validate_contract_event(
        {
            "ts": "2026-06-12T06:00:00Z",
            "session_id": "cx-red",
            "kind": "status",
            "payload": {"lifecycle_state": "announce"},
        }
    )

    line = event.to_json_line()

    assert line.endswith("\n")
    assert json.loads(line)["kind"] == "status"


def test_claude_headless_fixture_passes_contract_conformance(tmp_path: Path) -> None:
    result = run_conformance_fixture(
        "adapter-claude",
        _fixture_rows("adapter-claude", tmp_path),
        session_id="claude-fixture-session",
        task_id=TASK_ID,
        ts=datetime(2026, 6, 12, 6, tzinfo=UTC),
    )

    assert result.ok
    assert result.checks == {
        "spawn_announce": True,
        "identity_visible": True,
        "event_vocabulary": True,
        "control_roundtrip": True,
        "claim_visible": True,
    }
    assert "file_write" in result.projection["event_kinds"]
    assert result.projection["file_paths"] == [
        "docs/specs/platform-session-contract-v1-20260612.md"
    ]
    assert result.projection["mentioned_tasks"] == [TASK_ID]


def test_codex_fixture_passes_contract_conformance(tmp_path: Path) -> None:
    result = run_conformance_fixture(
        "adapter-codex",
        _fixture_rows("adapter-codex", tmp_path),
        session_id="codex-fixture-session",
        task_id=TASK_ID,
        ts=datetime(2026, 6, 12, 6, tzinfo=UTC),
    )

    assert result.ok
    assert result.checks == {
        "spawn_announce": True,
        "identity_visible": True,
        "event_vocabulary": True,
        "control_roundtrip": True,
        "claim_visible": True,
    }
    assert result.projection["file_paths"] == [
        "docs/specs/platform-session-contract-v1-20260612.md"
    ]


def test_conformance_fixture_rejects_empty_native_evidence() -> None:
    with pytest.raises(PlatformSessionContractError) as exc:
        run_conformance_fixture(
            "adapter-claude",
            [],
            session_id="claude-fixture-session",
            task_id=TASK_ID,
            ts=datetime(2026, 6, 12, 6, tzinfo=UTC),
        )

    assert exc.value.code == "conformance_failed"
    assert "spawn_announce" in str(exc.value)
    assert "identity_visible" in str(exc.value)
    assert "claim_visible" in str(exc.value)


def test_claude_output_fixture_keeps_native_stream_json_shape() -> None:
    rows = parse_jsonl_events(FIXTURES / "claude-headless-output.jsonl")

    assert all("type" in row for row in rows)
    assert all("kind" not in row for row in rows)
    assert all("ts" not in row for row in rows)
    assert any(row.get("type") == "system" and row.get("subtype") == "init" for row in rows)
    assert all(row.get("type") not in {"hapax_lifecycle", "hapax_claim"} for row in rows)


def test_artifact_projection_rows_pin_launcher_birth_and_claim_evidence(tmp_path: Path) -> None:
    artifacts = _materialized_artifacts("adapter-claude", tmp_path)
    rows = artifact_projection_rows("adapter-claude", artifacts, task_id=TASK_ID)

    assert [row["type"] for row in rows] == ["hapax_lifecycle", "hapax_lifecycle", "hapax_claim"]
    assert [row.get("state") for row in rows[:2]] == ["spawn", "announce"]
    assert str(rows[0]["output_stream"]).endswith(
        "/.cache/hapax/claude-headless/alpha/output.jsonl"
    )
    assert rows[2]["source"] == "claim_file"
    assert str(rows[2]["claim_file"]).endswith("/.cache/hapax/cc-active-task-alpha")


def test_artifact_projection_requires_observed_claim_file(tmp_path: Path) -> None:
    artifacts = adapter_artifacts(
        "adapter-claude",
        "alpha",
        home=tmp_path / "home",
        runtime_dir=tmp_path / "run",
    )

    with pytest.raises(PlatformSessionContractError) as exc:
        artifact_projection_rows("adapter-claude", artifacts, task_id=TASK_ID)

    assert exc.value.code == "artifact_not_observed"


def test_artifact_projection_rejects_mismatched_claim_and_missing_files(tmp_path: Path) -> None:
    artifacts = _materialized_artifacts("adapter-claude", tmp_path)

    Path(artifacts.claim_file).write_text("other-task-20260612\n", encoding="utf-8")
    with pytest.raises(PlatformSessionContractError) as claim_exc:
        artifact_projection_rows("adapter-claude", artifacts, task_id=TASK_ID)
    assert claim_exc.value.code == "artifact_not_observed"
    assert "expected" in str(claim_exc.value)

    Path(artifacts.claim_file).write_text(f"{TASK_ID}\n", encoding="utf-8")
    assert artifacts.output_stream is not None
    Path(artifacts.output_stream).unlink()
    with pytest.raises(PlatformSessionContractError) as output_exc:
        artifact_projection_rows("adapter-claude", artifacts, task_id=TASK_ID)
    assert output_exc.value.code == "artifact_not_observed"
    assert "output stream not observed" in str(output_exc.value)

    Path(artifacts.output_stream).write_text("{}", encoding="utf-8")
    Path(artifacts.control_endpoint).unlink()
    with pytest.raises(PlatformSessionContractError) as control_exc:
        artifact_projection_rows("adapter-claude", artifacts, task_id=TASK_ID)
    assert control_exc.value.code == "artifact_not_observed"
    assert "control endpoint not observed" in str(control_exc.value)


def test_artifact_projection_requires_observed_tmux_endpoint(tmp_path: Path) -> None:
    artifacts = _materialized_artifacts("adapter-codex", tmp_path)

    with pytest.raises(PlatformSessionContractError) as exc:
        artifact_projection_rows("adapter-codex", artifacts, task_id=TASK_ID)

    assert exc.value.code == "artifact_not_observed"
    assert "tmux control endpoint not observed" in str(exc.value)

    rows = artifact_projection_rows(
        "adapter-codex",
        artifacts,
        task_id=TASK_ID,
        observed_control_endpoints={artifacts.control_endpoint},
    )
    assert [row["type"] for row in rows] == ["hapax_lifecycle", "hapax_lifecycle", "hapax_claim"]


def test_claude_adapter_matches_real_headless_artifact_layout() -> None:
    script = (REPO_ROOT / "scripts" / "hapax-claude-headless").read_text(encoding="utf-8")
    artifacts = adapter_artifacts(
        "adapter-claude",
        "alpha",
        home=Path("/home/operator"),
        runtime_dir=Path("/run/user/1000"),
    )

    assert 'LOG_DIR="$HOME/.cache/hapax/claude-headless/$ROLE"' in script
    assert 'LOG_FILE="$LOG_DIR/output.jsonl"' in script
    assert 'PIPE_DIR="${HAPAX_CLAUDE_HEADLESS_PIPE_DIR:-/run/user/$(id -u)/hapax-claude}"' in script
    assert 'STDIN_PIPE="$PIPE_DIR/$ROLE.stdin"' in script
    assert 'CLAIM_FILE="$HOME/.cache/hapax/cc-active-task-$ROLE"' in script
    assert '(cd "$WORKDIR" && "$WORKDIR/scripts/cc-claim" "$CLAUDE_TASK")' in script
    assert (
        artifacts.output_stream == "/home/operator/.cache/hapax/claude-headless/alpha/output.jsonl"
    )
    assert artifacts.control_endpoint == "/run/user/1000/hapax-claude/alpha.stdin"
    assert artifacts.native_input_format == "Claude stdin-json over FIFO"
    assert artifacts.native_output_format == "Claude stream-json"


def test_codex_adapter_matches_headless_and_interactive_launcher_artifacts() -> None:
    interactive_script = (REPO_ROOT / "scripts" / "hapax-codex").read_text(encoding="utf-8")
    headless_script = (REPO_ROOT / "scripts" / "hapax-codex-headless").read_text(encoding="utf-8")

    assert 'TMUX_NAME="hapax-codex-$SESSION"' in interactive_script
    assert 'LOG_DIR="$HOME/.cache/hapax/codex-headless/$SESSION"' in headless_script
    assert 'LOG_FILE="$LOG_DIR/output.jsonl"' in headless_script
    assert (
        'PID_DIR="${HAPAX_CODEX_HEADLESS_PID_DIR:-/run/user/$(id -u)/hapax-codex}"'
        in headless_script
    )
    assert '[[ -d "$PID_DIR" ]] || PID_DIR="$LOG_DIR"' in headless_script
    assert 'PID_FILE="$PID_DIR/$SESSION.pid"' in headless_script
    assert 'CLAIM_FILE="$HOME/.cache/hapax/cc-active-task-$SESSION"' in headless_script
    assert '(cd "$WORKDIR" && "$WORKDIR/scripts/cc-claim" "$CODEX_TASK")' in headless_script
    assert '"$CLAIM_SCRIPT" "$TASK_ID"' in interactive_script
    assert "  --json\n" in headless_script
    assert '  --cd "$WORKDIR"\n' in headless_script


def test_codex_fixture_projects_onto_same_plane_as_claude(tmp_path: Path) -> None:
    claude_events = (
        *normalize_native_events(
            "adapter-claude",
            _fixture_rows("adapter-claude", tmp_path),
            session_id="session-fixture",
        ),
    )
    codex_events = (
        *normalize_native_events(
            "adapter-codex",
            _fixture_rows("adapter-codex", tmp_path),
            session_id="session-fixture",
        ),
    )

    claude_projection = coordination_plane_projection(claude_events)
    codex_projection = coordination_plane_projection(codex_events)
    assert claude_projection["announced"] is True
    assert codex_projection["announced"] is True
    assert claude_projection["identified"] is True
    assert codex_projection["identified"] is True
    assert claude_projection["claimed_tasks"] == codex_projection["claimed_tasks"] == [TASK_ID]
    assert claude_projection["mentioned_tasks"] == [TASK_ID]
    assert codex_projection["mentioned_tasks"] == []
    assert claude_projection["file_paths"] == codex_projection["file_paths"]


def test_task_mentions_do_not_project_as_claims() -> None:
    event = validate_contract_event(
        {
            "ts": "2026-06-12T06:00:00Z",
            "session_id": "cx-red",
            "kind": "task_mention",
            "payload": {"task_id": TASK_ID},
        }
    )

    projection = coordination_plane_projection([event])

    assert projection["claimed_tasks"] == []
    assert projection["mentioned_tasks"] == [TASK_ID]


def test_codex_adapter_declares_every_known_divergence_shim() -> None:
    contract = adapter_contract("adapter-codex")
    shims = {shim.divergence: shim for shim in contract.shims}

    assert set(shims) >= {
        "control_transport",
        "role_resolution",
        "dispatch_flags",
        "output_format",
        "relay_exclusion_visibility",
    }
    assert "tmux-buffer text" in shims["control_transport"].native_surface
    assert "--json" in contract.dispatch_flags
    assert "--cd" in contract.dispatch_flags


def test_declared_adapter_shims_map_to_existing_tests() -> None:
    test_names = {name for name, value in globals().items() if name.startswith("test_") and value}
    missing = sorted(
        shim.test_id
        for contract in adapter_contracts()
        for shim in contract.shims
        if shim.test_id not in test_names
    )

    assert missing == []


def test_control_roundtrip_for_claude_fifo_stdin_json() -> None:
    message = ControlMessage(
        ts=datetime(2026, 6, 12, 6, tzinfo=UTC),
        session_id="claude-fixture-session",
        verb=ControlVerb.CONTEXT_INJECT,
        payload={"focused_card": "platform-contract-v1-spec-20260612"},
    )

    native = render_control_message("adapter-claude", message)
    assert isinstance(native, dict)
    assert native["type"] == "user"
    assert native["message"]["content"][0]["type"] == "text"

    parsed = parse_control_message("adapter-claude", native)
    assert parsed == message


def test_control_roundtrip_for_codex_text_transport() -> None:
    message = ControlMessage(
        ts=datetime(2026, 6, 12, 6, tzinfo=UTC),
        session_id="cx-red-session",
        verb=ControlVerb.TAKE_CONTROLS,
        payload={"task_id": "platform-contract-v1-spec-20260612"},
    )

    native = render_control_message("adapter-codex", message)
    assert isinstance(native, str)
    assert native.startswith("HAPAX_PLATFORM_SESSION_CONTROL_V1 ")

    parsed = parse_control_message("adapter-codex", native)
    assert parsed == message


def test_role_resolution_shims_cover_claude_and_codex() -> None:
    claude = resolve_identity(
        "adapter-claude",
        {"HAPAX_AGENT_NAME": "alpha", "HAPAX_SESSION_ID": "uuid-claude"},
    )
    codex = resolve_identity(
        "adapter-codex",
        {
            "HAPAX_AGENT_NAME": "cx-red",
            "HAPAX_AGENT_SLOT": "alpha",
            "HAPAX_SESSION_ID": "uuid-codex",
        },
    )

    assert claude.session_name == "alpha"
    assert claude.slot == "alpha"
    assert claude.claim_key == "cc-active-task-alpha"
    assert codex.session_name == "cx-red"
    assert codex.slot == "alpha"
    assert codex.claim_key == "cc-active-task-cx-red"


def test_role_resolution_fallbacks_cover_launcher_aliases() -> None:
    claude = resolve_identity(
        "adapter-claude",
        {"CLAUDE_ROLE": "beta", "HAPAX_SESSION_ID": "uuid-claude"},
    )
    codex = resolve_identity(
        "adapter-codex",
        {"CODEX_THREAD_NAME": "cx-blue", "HAPAX_SESSION_ID": "uuid-codex"},
    )

    assert claude.session_name == "beta"
    assert codex.session_name == "cx-blue"


def test_identity_resolution_failures_name_launcher_variables() -> None:
    with pytest.raises(PlatformSessionContractError) as exc:
        resolve_identity("adapter-codex", {})

    assert exc.value.code == "missing_session_id"
    assert "HAPAX_SESSION_ID" in str(exc.value)

    with pytest.raises(PlatformSessionContractError) as name_exc:
        resolve_identity("adapter-codex", {"HAPAX_SESSION_ID": "uuid-codex"})

    assert name_exc.value.code == "missing_session_name"
    assert "CODEX_THREAD_NAME" in str(name_exc.value)

    with pytest.raises(PlatformSessionContractError) as claude_name_exc:
        resolve_identity("adapter-claude", {"HAPAX_SESSION_ID": "uuid-claude"})

    assert claude_name_exc.value.code == "missing_session_name"
    assert "CLAUDE_ROLE" in str(claude_name_exc.value)


def test_codex_interactive_and_headless_artifacts_are_adapter_native_only() -> None:
    interactive = adapter_artifacts(
        "adapter-codex",
        "cx-red",
        home=Path("/home/operator"),
        mode="interactive",
    )
    headless = adapter_artifacts(
        "adapter-codex",
        "cx-red",
        home=Path("/home/operator"),
        runtime_dir=Path("/run/user/1000"),
        mode="headless",
    )

    assert interactive.control_endpoint == "tmux:hapax-codex-cx-red"
    assert interactive.output_stream is None
    assert (
        headless.output_stream == "/home/operator/.cache/hapax/codex-headless/cx-red/output.jsonl"
    )
    assert headless.pid_file == "/run/user/1000/hapax-codex/cx-red.pid"


def test_adapter_contracts_are_closed_to_claude_and_codex_first() -> None:
    contracts = adapter_contracts()

    assert {contract.adapter for contract in contracts} == {"adapter-claude", "adapter-codex"}
    assert all(isinstance(contract, AdapterContract) for contract in contracts)


def test_jsonl_parser_rejects_invalid_lines(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(PlatformSessionContractError) as exc:
        parse_jsonl_events(bad)

    assert exc.value.code == "invalid_jsonl"
    assert "one JSON object per line" in str(exc.value)

    primitive = tmp_path / "primitive.jsonl"
    primitive.write_text("42\n", encoding="utf-8")

    with pytest.raises(PlatformSessionContractError) as primitive_exc:
        parse_jsonl_events(primitive)

    assert primitive_exc.value.code == "invalid_jsonl"
    assert "expected JSON object" in str(primitive_exc.value)


def test_control_parser_rejects_wrong_native_transport_shape() -> None:
    with pytest.raises(PlatformSessionContractError) as exc:
        parse_control_message("adapter-codex", "plain operator text")

    assert exc.value.code == "invalid_control_message"
    assert "HAPAX_PLATFORM_SESSION_CONTROL_V1" in str(exc.value)

    with pytest.raises(PlatformSessionContractError) as claude_exc:
        parse_control_message("adapter-claude", {"message": {"content": ["plain text"]}})

    assert claude_exc.value.code == "invalid_control_message"
    assert "message.content" in str(claude_exc.value)

    with pytest.raises(PlatformSessionContractError) as mapping_exc:
        parse_control_message("adapter-claude", "plain operator text")

    assert mapping_exc.value.code == "invalid_control_message"
    assert "expected Claude stdin-json mapping" in str(mapping_exc.value)

    with pytest.raises(PlatformSessionContractError) as json_exc:
        parse_control_message("adapter-codex", "HAPAX_PLATFORM_SESSION_CONTROL_V1 {not-json}")

    assert json_exc.value.code == "invalid_control_message"
    assert "expected control envelope key" in str(json_exc.value)

    invalid_payload = "HAPAX_PLATFORM_SESSION_CONTROL_V1 " + json.dumps(
        {"hapax_platform_session_control_v1": {"session_id": "cx-red"}}
    )
    with pytest.raises(PlatformSessionContractError) as payload_exc:
        parse_control_message("adapter-codex", invalid_payload)

    assert payload_exc.value.code == "invalid_control_message"
    assert "expected fields ts, session_id, verb, payload" in str(payload_exc.value)


def test_unknown_adapter_is_actionable() -> None:
    with pytest.raises(PlatformSessionContractError) as exc:
        adapter_contract("adapter-vibe")

    assert exc.value.code == "unknown_adapter"
    assert "supported adapters: adapter-claude, adapter-codex" in str(exc.value)
    assert "Next action:" in str(exc.value)


def test_unknown_native_event_maps_to_contract_error() -> None:
    (event,) = normalize_native_events(
        "adapter-claude",
        [{"type": "mystery_frame", "detail": "native drift"}],
        session_id="claude-fixture-session",
    )

    assert event.kind.value == "error"
    assert event.payload == {"code": "native_event_unmapped", "native_type": "mystery_frame"}


def test_contract_shaped_native_event_passthrough_is_validated() -> None:
    (event,) = normalize_native_events(
        "adapter-codex",
        [
            {
                "ts": "2026-06-12T06:00:00Z",
                "session_id": "codex-fixture-session",
                "kind": "heartbeat",
                "payload": {"source": "adapter"},
            }
        ],
        session_id="ignored-session",
    )

    assert event.session_id == "codex-fixture-session"
    assert event.kind.value == "heartbeat"


def test_lifecycle_artifact_invalid_state_maps_to_error_event() -> None:
    (event,) = normalize_native_events(
        "adapter-claude",
        [{"type": "hapax_lifecycle", "state": "zombie", "source": "fixture"}],
        session_id="claude-fixture-session",
    )

    assert event.kind.value == "error"
    assert event.payload == {
        "code": "invalid_lifecycle_state",
        "lifecycle_state": "zombie",
        "adapter": "adapter-claude",
    }


def test_claude_native_error_maps_to_contract_error() -> None:
    (event,) = normalize_native_events(
        "adapter-claude",
        [{"type": "error", "message": "boom"}],
        session_id="claude-fixture-session",
    )

    assert event.kind.value == "error"
    assert event.payload == {"message": "boom"}


def test_codex_native_branch_mappings_cover_status_push_error_and_unmapped() -> None:
    events = normalize_native_events(
        "adapter-codex",
        [
            {"type": "thread.started"},
            {"type": "turn.started"},
            {"type": "file_write", "path": "docs/example.md"},
            {"type": "push", "remote": "origin"},
            {"type": "status", "payload": {"status": "parked"}},
            {"type": "error", "message": "boom"},
            {"type": "mystery_frame"},
        ],
        session_id="codex-fixture-session",
    )

    assert [event.kind.value for event in events] == [
        "status",
        "status",
        "file_write",
        "push",
        "status",
        "error",
        "error",
    ]
    assert events[-1].payload == {"code": "native_event_unmapped", "native_type": "mystery_frame"}


def test_codex_native_status_cannot_bypass_lifecycle_vocabulary() -> None:
    with pytest.raises(PlatformSessionContractError) as exc:
        normalize_native_events(
            "adapter-codex",
            [{"type": "status", "payload": {"lifecycle_state": "zombie"}}],
            session_id="codex-fixture-session",
        )

    assert exc.value.code == "off_vocabulary_lifecycle"
