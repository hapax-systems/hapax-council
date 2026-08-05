"""CLI tests for hapax-sdlc-gate-event-drain."""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from shared.gate_log import GateEvent, append_gate_event
from shared.route_metadata_schema import (
    FreshnessState,
    LearningEligibility,
    LearningEvidenceKind,
)
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-sdlc-gate-event-drain"


def _load():
    loader = SourceFileLoader("hapax_sdlc_gate_event_drain_cli", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


mod = _load()


def _event() -> GateEvent:
    return GateEvent(
        route="local_tool.local.worker",
        routing_class="source_python",
        requirement_vector={dim: 2 for dim in REQUIREMENT_VECTOR_DIMENSIONS},
        task_hash="sha256:cli-n1",
        gate_result="accept",
        gate_type="deterministic",
        provenance="witnessed",
        ts="2026-08-05T00:00:00+00:00",
        learning_eligibility=LearningEligibility(
            thompson_update_allowed=True,
            local_posterior_update_allowed=True,
            evidence_kind=LearningEvidenceKind.WITNESSED,
            evidence_freshness=FreshnessState.FRESH,
            confidence=1.0,
            envelope_valid=True,
            support_only=False,
            hkp_only=False,
            public_projection_forbidden=False,
            evidence_refs=["deterministic:cli"],
            reason_codes=["test"],
        ),
    )


def test_cli_report_json(tmp_path: Path, capsys) -> None:
    log = tmp_path / "g.jsonl"
    append_gate_event(_event(), path=log)
    rc = mod.main(
        [
            "--gate-log",
            str(log),
            "--router-state",
            str(tmp_path / "r.json"),
            "--json",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "report"
    assert out["would_apply"] == 1
    assert out["state_written"] is False
    assert not (tmp_path / "r.json").exists()


def test_cli_apply_writes(tmp_path: Path, capsys) -> None:
    log = tmp_path / "g.jsonl"
    state = tmp_path / "r.json"
    append_gate_event(_event(), path=log)
    rc = mod.main(["--gate-log", str(log), "--router-state", str(state), "--apply", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] == 1
    assert out["state_written"] is True
    assert state.exists()


def test_cli_status_json_includes_flag_and_next_actions(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.delenv("HAPAX_OUTCOME_GATE_ON_CLOSE", raising=False)
    log = tmp_path / "g.jsonl"
    log.write_text("", encoding="utf-8")
    rc = mod.main(
        [
            "--status",
            "--json",
            "--gate-log",
            str(log),
            "--router-state",
            str(tmp_path / "r.json"),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["outcome_gate_on_close_enabled_now"] is False
    assert out["mode"] == "report"
    assert isinstance(out.get("next_actions"), list)
    assert any("HAPAX_OUTCOME_GATE_ON_CLOSE" in a for a in out["next_actions"])


def test_cli_status_apply_includes_next_actions(tmp_path: Path, capsys) -> None:
    log = tmp_path / "g.jsonl"
    state = tmp_path / "r.json"
    append_gate_event(_event(), path=log)
    rc = mod.main(
        [
            "--status",
            "--apply",
            "--json",
            "--gate-log",
            str(log),
            "--router-state",
            str(state),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "apply"
    assert out["applied"] == 1
    assert isinstance(out.get("next_actions"), list)
    assert out["next_actions"]
