"""World-to-record first caller on cc-task-closure-check (Edge C).

Pins: default off (zero behavior change), flag-on emit of witnessed accept,
incomplete_technical without learning event, append failure refuses close.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-task-closure-check.py"

_COMPLETE_VECTOR = {
    "quality_floor": 3,
    "information_scope": 2,
    "context_length": 2,
    "mutation_risk": 1,
    "verification_demand": 3,
    "ambiguity_novelty": 2,
    "composition_coupling": 1,
    "governance_sensitivity": 2,
}


def _load():
    loader = SourceFileLoader("cc_task_closure_check_outcome", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


mod = _load()


def _permitted_note(tmp_path: Path, frontmatter: dict[str, Any]) -> Path:
    import yaml

    body = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False)
        + "---\n\n## Acceptance criteria\n- [x] done\n"
    )
    note = tmp_path / "task.md"
    note.write_text(body, encoding="utf-8")
    return note


def test_default_off_no_emit(monkeypatch, tmp_path):
    monkeypatch.delenv("HAPAX_OUTCOME_GATE_ON_CLOSE", raising=False)
    calls: list[Any] = []

    def _boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("emit must not run when flag off")

    monkeypatch.setattr(
        "shared.gate_outcome_producer.emit_outcome_gate_event",
        _boom,
        raising=False,
    )
    # Patch where the function will be imported from inside maybe_emit
    import shared.gate_outcome_producer as gop

    monkeypatch.setattr(gop, "emit_outcome_gate_event", _boom)

    note = _permitted_note(
        tmp_path,
        {
            "type": "cc-task",
            "task_id": "t-off",
            "requirement_vector": _COMPLETE_VECTOR,
            "routing_class": "source_python",
        },
    )
    assert mod.main(["cc-task-closure-check.py", str(note)]) == 0
    assert calls == []


def test_flag_on_emits_witnessed_accept(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_OUTCOME_GATE_ON_CLOSE", "1")
    captured: list[dict[str, Any]] = []

    def _capture(task_fields, **kwargs):
        captured.append({"task_fields": dict(task_fields), **kwargs})
        return object()

    import shared.gate_outcome_producer as gop

    monkeypatch.setattr(gop, "emit_outcome_gate_event", _capture)

    ledger = tmp_path / "close-modal-outcomes.jsonl"
    monkeypatch.setattr(mod, "_CLOSE_MODAL_LEDGER", ledger)

    note = _permitted_note(
        tmp_path,
        {
            "type": "cc-task",
            "task_id": "t-emit",
            "requirement_vector": _COMPLETE_VECTOR,
            "routing_class": "source_python",
            "route_id": "codex.headless.full",
        },
    )
    assert mod.main(["cc-task-closure-check.py", str(note)]) == 0
    assert len(captured) == 1
    assert captured[0]["gate_result"] == "accept"
    assert captured[0]["gate_type"] == "deterministic"
    assert captured[0]["provenance"] == "witnessed"
    assert captured[0]["route"] == "codex.headless.full"
    assert captured[0]["task_fields"]["requirement_vector"] == _COMPLETE_VECTOR

    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert rows[-1]["modal_class"] == "permitted"
    assert rows[-1]["reason"] == "witnessed_accept_emitted"


def test_incomplete_vector_no_learning_emit(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_OUTCOME_GATE_ON_CLOSE", "1")
    calls: list[Any] = []

    import shared.gate_outcome_producer as gop

    monkeypatch.setattr(
        gop,
        "emit_outcome_gate_event",
        lambda *a, **k: calls.append(1),
    )

    ledger = tmp_path / "close-modal-outcomes.jsonl"
    monkeypatch.setattr(mod, "_CLOSE_MODAL_LEDGER", ledger)

    note = _permitted_note(
        tmp_path,
        {
            "type": "cc-task",
            "task_id": "t-incomplete",
            # missing dimensions — incomplete
            "requirement_vector": {"quality_floor": 1},
        },
    )
    assert mod.main(["cc-task-closure-check.py", str(note)]) == 0
    assert calls == []
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert rows[-1]["modal_class"] == "incomplete_technical"


def test_emit_failure_refuses_close(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_OUTCOME_GATE_ON_CLOSE", "1")

    import shared.gate_outcome_producer as gop

    def _fail(*_a, **_k):
        raise OSError("gate log not writable")

    monkeypatch.setattr(gop, "emit_outcome_gate_event", _fail)

    note = _permitted_note(
        tmp_path,
        {
            "type": "cc-task",
            "task_id": "t-fail",
            "requirement_vector": _COMPLETE_VECTOR,
            "routing_class": "source_python",
        },
    )
    assert mod.main(["cc-task-closure-check.py", str(note)]) == 3


def test_unchecked_ac_still_blocks_before_outcome_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_OUTCOME_GATE_ON_CLOSE", "1")
    calls: list[Any] = []

    import shared.gate_outcome_producer as gop

    monkeypatch.setattr(gop, "emit_outcome_gate_event", lambda *a, **k: calls.append(1))

    note = tmp_path / "blocked.md"
    note.write_text(
        "---\ntype: cc-task\ntask_id: t-block\n---\n\n## Acceptance criteria\n- [ ] not done\n",
        encoding="utf-8",
    )
    assert mod.main(["cc-task-closure-check.py", str(note)]) == 2
    assert calls == []
