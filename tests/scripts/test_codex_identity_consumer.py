"""The actual result reader recomputes identity from pinned native evidence."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shared.platform_capability_registry import ExecutionDescriptor

ROOT = Path(__file__).resolve().parents[2]
SID = "01900000-1234-7000-8000-123456789abc"
DESC = ExecutionDescriptor(model_id="gpt-5.5", effort="low")


def _consumer():
    loader = importlib.machinery.SourceFileLoader(
        "identity_consumer_dispatch", str(ROOT / "scripts/hapax-methodology-dispatch")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def _receipt(tmp_path, *, model="gpt-5.5", local=True, with_descriptor=True):
    native = tmp_path / "native"
    work = tmp_path / "work"
    work.mkdir()
    rollout = native / "sessions/2026/09/21" / f"rollout-current-{SID}.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(
        "".join(
            json.dumps(event) + "\n"
            for event in [
                {
                    "type": "session_meta",
                    "timestamp": "2026-09-21T07:00:01Z",
                    "payload": {"id": SID, "cwd": str(work)},
                },
                {
                    "type": "turn_context",
                    "timestamp": "2026-09-21T07:00:02Z",
                    "payload": {"model": model, "effort": "low"},
                },
            ]
        )
    )
    stream = tmp_path / "native.jsonl"
    stream.write_text(
        "".join(
            json.dumps(event) + "\n"
            for event in [
                {"type": "thread.started", "thread_id": SID},
                {"type": "turn.started"},
                {"type": "turn.completed"},
            ]
        )
    )
    receipt = tmp_path / "receipt.json"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "shared/execution_observer.py"),
            "--stream",
            str(stream),
            "--diagnostics",
            str(tmp_path / "stderr"),
            "--receipt",
            str(receipt),
            "--returncode",
            "0",
            *(["--local-child"] if local else []),
            "--execution-descriptor",
            DESC.model_dump_json() if with_descriptor else "",
            "--execution-route",
            "codex.headless.full",
            "--native-home",
            str(native),
            "--workdir",
            str(work),
            "--launch-started-at",
            "2026-09-21T07:00:00Z",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return receipt, rollout


def test_consumer_recomputes_frozen_identity_and_prefix_replay(tmp_path, monkeypatch):
    module = _consumer()
    receipt, rollout = _receipt(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("historical identity must not reload the current registry")

    monkeypatch.setattr(module, "resolve_execution_descriptor", forbidden)
    observed, reference = module.read_native_lifecycle_receipt(receipt, platform="codex")
    assert observed["execution_identity"]["status"] == "matched"
    assert observed["execution_identity"]["declared"] == DESC.model_dump(mode="json")
    assert reference.sha256 == hashlib.sha256(receipt.read_bytes()).hexdigest()
    with rollout.open("a") as out:
        out.write(json.dumps({"type": "turn_context", "payload": {"model": "changed"}}) + "\n")
    replay, replay_reference = module.read_native_lifecycle_receipt(
        receipt, platform="codex", result_ref=reference
    )
    assert replay == observed
    assert replay_reference == reference


def test_consumer_retains_native_mismatch_against_forged_match(tmp_path):
    receipt, _ = _receipt(tmp_path, model="gpt-6-astra")
    claimed = json.loads(receipt.read_text())
    assert claimed["execution_identity"]["status"] == "misattributed"
    claimed["execution_identity"]["status"] = "matched"
    claimed["execution_identity"]["turns"][0]["status"] = "matched"
    receipt.write_text(json.dumps(claimed))
    observed, reference = _consumer().read_native_lifecycle_receipt(receipt, platform="codex")
    assert observed["complete"] is True  # Process completion is a different fact.
    assert observed["execution_identity"]["status"] == "misattributed"
    assert "native_identity_receipt_mismatch" in observed["execution_identity"]["reason_codes"]
    assert observed["execution_identity"]["may_authorize"] is False
    assert reference is not None


@pytest.mark.parametrize("change", ["authority", "status", "turn_type"])
def test_consumer_classifies_inconsistent_matching_receipt_as_unverified(tmp_path, change):
    receipt, _ = _receipt(tmp_path)
    claimed = json.loads(receipt.read_text())
    identity = claimed["execution_identity"]
    if change == "authority":
        identity["may_authorize"] = True
    elif change == "status":
        identity["status"] = "misattributed"
    else:
        identity["turns"][0]["observed"]["effort"] = 1
    receipt.write_text(json.dumps(claimed))
    observed, reference = _consumer().read_native_lifecycle_receipt(receipt, platform="codex")
    assert observed["complete"] is True
    assert observed["execution_identity"]["status"] == "unverified"
    assert observed["execution_identity"]["turns"][0]["status"] == "matched"
    assert "native_identity_receipt_mismatch" in observed["execution_identity"]["reason_codes"]
    assert observed["execution_identity"]["may_authorize"] is False
    assert reference is not None


@pytest.mark.parametrize(
    "change",
    [
        "legacy",
        "missing_rollout",
        "changed_prefix",
        "wrong_session",
        "invalid_descriptor",
        "unsupported_claim",
        "native_home_symlink_loop",
    ],
)
def test_consumer_never_promotes_unavailable_identity(tmp_path, change):
    receipt, rollout = _receipt(tmp_path)
    claimed = json.loads(receipt.read_text())
    if change == "legacy":
        claimed.pop("execution_identity")
    elif change == "missing_rollout":
        rollout.unlink()
    elif change == "changed_prefix":
        rollout.write_bytes(rollout.read_bytes().replace(b"gpt-5.5", b"gpt-6.6"))
    elif change == "wrong_session":
        claimed["execution_identity"]["session_id"] = "other-run"
    elif change == "invalid_descriptor":
        claimed["execution_identity"]["declared"] = []
    elif change == "native_home_symlink_loop":
        loop = tmp_path / "loop"
        loop.symlink_to(loop)
        claimed["execution_identity"]["native_home"] = str(loop)
    else:
        claimed["execution_identity"] = {"status": "matched", "may_authorize": True}
    receipt.write_text(json.dumps(claimed))
    observed, _ = _consumer().read_native_lifecycle_receipt(receipt, platform="codex")
    assert observed["complete"] is True
    assert observed["execution_identity"]["status"] == "unverified"
    assert observed["execution_identity"]["may_authorize"] is False


def test_remote_identity_remains_unverified_even_with_claimed_match(tmp_path):
    receipt, _ = _receipt(tmp_path, local=False)
    claimed = json.loads(receipt.read_text())
    claimed["execution_identity"] = {"status": "matched", "may_authorize": True}
    receipt.write_text(json.dumps(claimed))
    observed, _ = _consumer().read_native_lifecycle_receipt(receipt, platform="codex")
    assert observed["complete"] is False
    assert observed["execution_identity"]["status"] == "unverified"
    assert observed["execution_identity"]["may_authorize"] is False


@pytest.mark.parametrize("returncode", [0, 7])
def test_producer_identity_exception_preserves_native_exit(tmp_path, monkeypatch, returncode):
    from shared import codex_execution_receipt, execution_observer

    stream = tmp_path / "native.jsonl"
    stream.write_text(
        json.dumps({"type": "thread.started", "thread_id": SID})
        + "\n"
        + json.dumps({"type": "turn.completed"})
        + "\n"
    )
    receipt = tmp_path / "receipt.json"

    def unavailable(*args, **kwargs):
        raise RuntimeError("private exception detail must not enter receipt")

    monkeypatch.setattr(codex_execution_receipt, "observe_codex_run_identity", unavailable)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "observer",
            "--stream",
            str(stream),
            "--diagnostics",
            str(tmp_path / "stderr"),
            "--receipt",
            str(receipt),
            "--returncode",
            str(returncode),
            "--local-child",
            "--execution-descriptor",
            DESC.model_dump_json(),
            "--execution-route",
            "codex.headless.full",
            "--native-home",
            str(tmp_path),
            "--workdir",
            str(tmp_path),
            "--launch-started-at",
            "2026-09-21T07:00:00Z",
        ],
    )
    assert execution_observer._native_receipt_main() == 0
    observed = json.loads(receipt.read_text())
    assert observed["process_returncode"] == returncode
    assert observed["complete"] is (returncode == 0)
    assert observed["execution_identity"] == {
        "status": "unverified",
        "may_authorize": False,
        "reason_codes": ["native_identity_observer_failed:RuntimeError"],
    }
    assert "private exception detail" not in receipt.read_text()


@pytest.mark.parametrize("platform", ["claude", "codex-app-server", "vibe"])
def test_consumer_keeps_lifecycle_separate_from_unimplemented_identity(
    tmp_path, monkeypatch, platform
):
    from shared.execution_observer import observe_native_lifecycle

    stream = tmp_path / "native.jsonl"
    stream.write_text(
        json.dumps({"type": "system", "subtype": "init", "session_id": "owned"})
        + "\n"
        + json.dumps({"type": "result", "subtype": "success"})
        + "\n"
    )
    receipt = tmp_path / "receipt.json"
    claimed = observe_native_lifecycle(stream, platform=platform, process_returncode=0)
    claimed.update(
        receipt_path=str(receipt),
        stream_path=str(stream),
        stream_sha256=hashlib.sha256(stream.read_bytes()).hexdigest(),
        owned_native_process=True,
        execution_identity={"status": "matched", "may_authorize": True},
    )
    receipt.write_text(json.dumps(claimed))
    module = _consumer()
    observed, reference = module.read_native_lifecycle_receipt(receipt, platform=platform)
    assert observed["may_authorize"] is False
    if platform == "claude":
        assert reference is not None
        assert observed["phase"] == "complete" and observed["complete"] is True
        assert observed["execution_identity"] == {
            "status": "unverified",
            "may_authorize": False,
            "reason_codes": ["native_identity_mapping_unimplemented"],
        }
    else:
        assert reference is None
        assert observed["phase"] == "unobserved"
        assert observed["reason"] == "native_receipt_platform_unsupported"
        assert "execution_identity" not in observed
    monkeypatch.setattr(module, "orchestration_ledger_dir", lambda: tmp_path / "ledger")
    ledger = module.write_receipt(
        task_id="fixture",
        lane="fixture",
        platform=platform,
        mode="headless",
        profile="full",
        route=None,
        validation=module.Validation(True, "fixture", None),
        prompt=None,
        launched=True,
        launch_returncode=0,
        native_lifecycle=observed,
        result_ref=reference,
    )
    recorded = json.loads(ledger.read_text())
    assert recorded["native_lifecycle"] == observed
    assert recorded["result_ref"] == (reference.model_dump(mode="json") if reference else None)
    assert recorded["launch_returncode"] == 0


def test_standalone_producer_without_descriptor_keeps_completion(tmp_path):
    receipt, _ = _receipt(tmp_path, with_descriptor=False)
    observed = json.loads(receipt.read_text())
    assert observed["complete"] is True and observed["process_returncode"] == 0
    assert observed["execution_identity"] == {
        "status": "unverified",
        "may_authorize": False,
        "reason_codes": ["native_launch_descriptor_unavailable"],
    }
