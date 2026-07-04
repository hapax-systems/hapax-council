from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from shared.governance.dispatch_redemption import (
    DispatchLaunchRedemptionAuthority,
    DispatchLaunchRedemptionServer,
    LaunchMintRequest,
    LaunchRedemptionContext,
    LaunchRedemptionEvent,
    LaunchRedemptionRequest,
    mint_launch_via_socket,
    redeem_launch_via_socket,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-dispatch-redemption-authority"


def _load_authority_script() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_dispatch_redemption_authority", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_runtime_receipt_refuses_socket_without_protocol_witness(tmp_path: Path) -> None:
    script = _load_authority_script()
    runtime_dir = tmp_path / "coord"
    runtime_dir.mkdir()
    runtime_dir.chmod(0o750)
    socket_path = runtime_dir / "dispatch-redemption.sock"

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as fake_server:
        fake_server.bind(str(socket_path))
        socket_path.chmod(0o660)
        fake_server.listen(1)

        receipt = script.runtime_receipt(runtime_dir, socket_path)

    assert receipt["healthy"] is False
    assert receipt["protocol_probe"]["ok"] is False


def test_runtime_receipt_requires_live_governor_protocol(tmp_path: Path) -> None:
    script = _load_authority_script()
    runtime_dir = tmp_path / "coord"
    # Pre-provision the namespace at its final mode: serve_once answers exactly
    # one connection, and a probe that lands in the server's mkdir->chmod window
    # would consume it against a not-yet-healthy dir snapshot, stranding every
    # retry on ConnectionRefused.
    runtime_dir.mkdir()
    runtime_dir.chmod(0o750)
    socket_path = runtime_dir / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(
        DispatchLaunchRedemptionAuthority(now=lambda: 1000.0),
        socket_path=socket_path,
    )
    thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    thread.start()

    receipt = _receipt_with_retry(script, runtime_dir, socket_path)
    thread.join(timeout=5)

    assert receipt["healthy"] is True
    assert receipt["runtime_dir"]["mode"] == "0750"
    assert receipt["socket"]["mode"] == "0660"
    assert receipt["protocol_probe"] == {"ok": True, "reason": "protocol_witnessed"}


def _receipt_with_retry(
    script: ModuleType, runtime_dir: Path, socket_path: Path
) -> dict[str, object]:
    last: dict[str, object] | None = None
    for _ in range(100):
        last = script.runtime_receipt(runtime_dir, socket_path)
        if last["healthy"] is True:
            return last
        time.sleep(0.01)
    assert last is not None
    return last


def _context(worktree: Path, *, route_ref: str = "route-decision:test") -> LaunchRedemptionContext:
    return LaunchRedemptionContext(
        task_id="task-x",
        lane="cx-amber",
        platform="codex",
        mode="headless",
        profile="full",
        worktree=str(worktree),
        purpose="external_launch",
        dispatch_message_id="019f-test",
        route_decision_ref=route_ref,
        authority_case="CASE-CAPACITY-ROUTING-001",
    )


# ── mint_policy ──────────────────────────────────────────────────────


def test_mint_policy_refuses_missing_worktree(tmp_path: Path) -> None:
    script = _load_authority_script()
    refusal = script.mint_policy(_context(tmp_path / "absent"))
    assert refusal is not None and refusal.startswith("worktree_missing:")


def test_mint_policy_refuses_missing_route_decision_receipt(tmp_path: Path) -> None:
    script = _load_authority_script()
    refusal = script.mint_policy(_context(tmp_path, route_ref=str(tmp_path / "absent.json")))
    assert refusal is not None and refusal.startswith("route_decision_receipt_missing:")


def test_mint_policy_accepts_governed_context(tmp_path: Path) -> None:
    script = _load_authority_script()
    assert script.mint_policy(_context(tmp_path)) is None
    receipt = tmp_path / "route-decision.json"
    receipt.write_text("{}\n", encoding="utf-8")
    assert script.mint_policy(_context(tmp_path, route_ref=str(receipt))) is None


# ── check_runtime_dir ────────────────────────────────────────────────


def test_check_runtime_dir_missing_namespace_names_next_action(tmp_path: Path) -> None:
    script = _load_authority_script()
    with pytest.raises(SystemExit) as excinfo:
        script.check_runtime_dir(tmp_path / "absent")
    message = str(excinfo.value)
    assert "runtime namespace missing" in message
    assert "hapax-dispatch-redemption.service" in message


def test_check_runtime_dir_refuses_foreign_owned_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _load_authority_script()
    runtime_dir = tmp_path / "coord"
    runtime_dir.mkdir()
    real_stat = os.stat

    def fake_stat(path: object, *args: object, **kwargs: object) -> object:
        if str(path) == str(runtime_dir):
            return SimpleNamespace(st_uid=os.getuid() + 1, st_gid=os.getgid())
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(script.os, "stat", fake_stat)
    with pytest.raises(SystemExit) as excinfo:
        script.check_runtime_dir(runtime_dir)
    message = str(excinfo.value)
    assert "not this daemon's user" in message
    assert "re-provisions" in message


# ── event writer sink ────────────────────────────────────────────────


def test_event_writer_appends_token_free_jsonl(tmp_path: Path) -> None:
    script = _load_authority_script()
    events_path = tmp_path / "ledger" / "events.jsonl"
    writer = script._event_writer(events_path)
    writer(
        LaunchRedemptionEvent(
            event_type="grant_minted",
            grant_id="grant-1",
            task_id="task-x",
            lane="cx-amber",
            platform="codex",
            mode="headless",
            profile="full",
            dispatch_message_id="019f-test",
            route_decision_ref="route-decision:test",
            reason="minted",
            observed_at=1000.0,
        )
    )
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event_type"] == "grant_minted"
    assert payload["grant_id"] == "grant-1"
    assert "token" not in payload


# ── --receipt exit codes + live serve end-to-end ─────────────────────


def test_receipt_mode_exits_1_when_namespace_absent(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "absent-coord"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--receipt",
            "--runtime-dir",
            str(runtime_dir),
            "--socket-path",
            str(runtime_dir / "dispatch-redemption.sock"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    receipt = json.loads(result.stdout)
    assert receipt["healthy"] is False
    assert receipt["runtime_dir"]["present"] is False
    assert receipt["protocol_probe"] == {"ok": False, "reason": "socket_absent"}


def test_serve_binds_mint_policy_event_sink_and_purge_into_live_governor(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "coord"
    runtime_dir.mkdir()
    runtime_dir.chmod(0o750)
    socket_path = runtime_dir / "dispatch-redemption.sock"
    events_path = tmp_path / "events.jsonl"
    worktree = tmp_path / "reins"
    worktree.mkdir()

    proc = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--serve",
            "--socket-path",
            str(socket_path),
            "--runtime-dir",
            str(runtime_dir),
            "--events-path",
            str(events_path),
            "--purge-interval",
            "0.05",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if socket_path.exists():
                break
            time.sleep(0.05)
        assert socket_path.exists(), "governor socket never appeared"

        # --receipt exits 0 against the live governor.
        receipt_run = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--receipt",
                "--runtime-dir",
                str(runtime_dir),
                "--socket-path",
                str(socket_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert receipt_run.returncode == 0, receipt_run.stdout
        assert json.loads(receipt_run.stdout)["healthy"] is True

        # serve() wired mint_policy into the live authority: ungoverned
        # context (missing worktree) is refused at mint.
        refused = mint_launch_via_socket(
            LaunchMintRequest(
                context=_context(tmp_path / "absent"),
                requester="pytest",
                requester_pid=os.getpid(),
                ttl_s=30.0,
                observed_at=time.time(),
            ),
            socket_path=socket_path,
        )
        assert refused.ok is False
        assert refused.reason.startswith("mint_policy_refused:worktree_missing:")

        # Governed mint → one-time redeem through the same socket.
        context = _context(worktree)
        minted = mint_launch_via_socket(
            LaunchMintRequest(
                context=context,
                requester="pytest",
                requester_pid=os.getpid(),
                ttl_s=30.0,
                observed_at=time.time(),
            ),
            socket_path=socket_path,
        )
        assert minted.ok is True, minted.reason
        assert minted.token

        redeemed = redeem_launch_via_socket(
            LaunchRedemptionRequest(
                token=minted.token,
                context=context,
                wrapper="pytest-wrapper",
                wrapper_pid=os.getpid(),
                observed_at=time.time(),
            ),
            socket_path=socket_path,
        )
        assert redeemed.ok is True, redeemed.reason
        assert redeemed.reason == "redeemed"

        # Purge wiring: after the (test-tuned) purge interval the consumed
        # grant leaves the table, so a replay maps to unknown_token instead
        # of already_consumed. Both fail closed; only purge yields the former.
        replay_reason = None
        for _ in range(50):
            replay = redeem_launch_via_socket(
                LaunchRedemptionRequest(
                    token=minted.token,
                    context=context,
                    wrapper="pytest-wrapper",
                    wrapper_pid=os.getpid(),
                    observed_at=time.time(),
                ),
                socket_path=socket_path,
            )
            assert replay.ok is False
            replay_reason = replay.reason
            if replay_reason == "unknown_token":
                break
            time.sleep(0.1)
        assert replay_reason == "unknown_token"

        # Event ledger is written and token-free.
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        event_types = {event["event_type"] for event in events}
        assert {"mint_refused", "grant_minted", "grant_redeemed", "grant_refused"} <= event_types
        assert minted.token not in events_path.read_text(encoding="utf-8")
    finally:
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=15)

    assert proc.returncode == 0, stderr
    assert not socket_path.exists()
    assert "purged" in stdout
