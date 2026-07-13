from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"


def _module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_methodology_dispatch_inert_test",
        str(SCRIPT),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def test_import_has_no_runtime_bootstrap_or_legacy_actuator_call() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "_bootstrap_project_runtime" not in source
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (
            (isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess")
            or (isinstance(node.func.value, ast.Name) and node.func.value.id == "os" and node.func.attr == "execvpe")
            or node.func.attr
            in {"unlink", "launch", "consume", "mkdir", "open", "write_text", "write_bytes"}
        )
        for node in ast.walk(tree)
    )
    for forbidden in (
        "wait_until_admitted",
        "append_failure_receipt_record",
        "update_worker_family_availability",
        "CapabilityConsumptionLedger",
        "write_route_decision_receipt",
        "append_gate_event",
    ):
        assert forbidden not in source


def test_every_legacy_actuator_holds_before_callback_or_io(tmp_path: Path) -> None:
    module = _module()
    callback_called = False

    def callback() -> int:
        nonlocal callback_called
        callback_called = True
        return 0

    calls = (
        lambda: module.sweep_stale_claims(tmp_path, tmp_path),
        lambda: module.run_claim_sweep(tmp_path),
        lambda: module._write_system_drain_audit(
            task_id="task",
            drained_from_lane="lane",
            capability_id="capability",
            liveness="dead",
            prior_status="claimed",
            operation_outcome="held",
            capability_consumed=False,
            edge_class="next",
            guard_evidence={},
        ),
        lambda: module._sliced_call(["/bin/false"]),
        lambda: module._await_sdlc_admission(SimpleNamespace()),
        lambda: module._classify_and_witness_terminal_failure(
            1,
            task_id="task",
            lane="lane",
            platform="codex",
            mode="headless",
            profile="full",
        ),
        lambda: module.classify_and_witness_launch(
            callback,
            task_id="task",
            lane="lane",
            platform="codex",
            mode="headless",
            profile="full",
        ),
        lambda: module.advance_task_stage(
            "task",
            "S2",
            edge_class="next",
            guard_evidence={},
        ),
        lambda: module.run_system_drain(SimpleNamespace(), tmp_path),
        lambda: module.write_receipt(),
        lambda: module._write_delayed_receipt(
            SimpleNamespace(),
            SimpleNamespace(),
        ),
        lambda: module.coord_event_log_from_env(),
    )
    for call in calls:
        with pytest.raises(module.Gate0AEffectHold):
            call()
    assert callback_called is False


@pytest.mark.parametrize("option", ("--list-platform-paths", "--capabilities"))
def test_pure_cli_inspection_survives_actuation_quarantine(option: str) -> None:
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), option],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
