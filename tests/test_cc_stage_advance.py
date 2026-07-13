"""Tests for scripts/cc-stage-advance — the council-side AVSDLC stage-setter.

Self-contained (no shared conftest): each test builds a synthetic vault under a
pinned HOME and invokes the script via subprocess. Coordination reform Phase 2.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter
from shared.relay_mq import (
    build_canon_echo_envelope,
    load_dispatch_echo_expectation,
    send_message,
)
from shared.relay_mq_envelope import Envelope

SCRIPT = Path(__file__).parent.parent / "scripts" / "cc-stage-advance"
CLOSE_SCRIPT = Path(__file__).parent.parent / "scripts" / "cc-close"


def test_close_refuses_when_project_runtime_is_unprovisioned(tmp_path: Path) -> None:
    isolated_script = tmp_path / "isolated" / "scripts" / "cc-close"
    isolated_script.parent.mkdir(parents=True)
    isolated_script.write_bytes(CLOSE_SCRIPT.read_bytes())
    isolated_script.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_AGENT_ROLE"] = "alpha"

    result = subprocess.run(
        ["bash", str(isolated_script), "missing-task"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    assert "project_runtime_unprovisioned" in result.stderr


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _dispatch_record(source_message_id: str, *, task_id: str, lane: str) -> dict:
    canon = {
        "canon_hash": "a" * 64,
        "canon_version": 1,
        "image_hash": "b" * 64,
        "level": "pi0",
        "payload_sha256": hashlib.sha256(b"canon s10").hexdigest(),
        "stage_token": "S10",
    }
    position_body = {
        "authority_case": "CASE-TEST-001",
        "declared_task_constraint_digest": "c" * 64,
        "effective_constraint_state": "unresolved_scope_chain",
        "lane": lane,
        "legal_successors": ["S11"],
        "stage_token": "S10",
        "task_id": task_id,
    }
    position_hash = _hash(position_body)
    position = {
        **position_body,
        "position_hash": position_hash,
        "position_ref": f"dispatch-position@sha256:{position_hash}",
    }
    binding_body = {
        "advisory_carriage": True,
        "canon": canon,
        "may_authorize": False,
        "position": position,
        "receipt_is_admission": False,
        "schema": "hapax.dispatch-canon-binding.v1",
    }
    binding_hash = _hash(binding_body)
    binding = {
        **binding_body,
        "binding_hash": binding_hash,
        "binding_ref": f"dispatch-canon-binding@sha256:{binding_hash}",
    }
    return {
        "event": "methodology_dispatch",
        "ok": True,
        "launched": True,
        "launch_returncode": 0,
        "launch_eligible": True,
        "durable_mq_dispatch_bound": True,
        "durable_mq_message_id": source_message_id,
        "may_authorize": False,
        "receipt_is_admission": False,
        "canon_binding": binding,
        "canon_binding_hash": binding_hash,
        "canon_binding_ref": binding["binding_ref"],
        "dispatch_position_hash": position_hash,
        "dispatch_position_ref": position["position_ref"],
    }


def _make_task(
    home: Path,
    task_id: str,
    *,
    stage: str | None = "S6_IMPLEMENTATION",
    authority_case: str | None = "CASE-TEST-001",
    status: str = "in_progress",
) -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    note = active / f"{task_id}-x.md"
    stage_line = f"stage: {stage}\n" if stage else ""
    ac_line = f"authority_case: {authority_case}\n" if authority_case else ""
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "T"
status: {status}
assigned_to: alpha
{ac_line}{stage_line}updated_at: 2026-01-01T00:00:00Z
---

# T

## Session log
""",
        encoding="utf-8",
    )
    return note


def _run(
    home: Path,
    *args: str,
    guard_refs: tuple[str, ...] = (),
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "alpha"
    # Redirect the coord SSOT log under the test HOME so emitting a stage event
    # never touches /var/lib/hapax/coord during the test.
    env["HAPAX_COORD_DIR"] = str(home / ".cache" / "hapax" / "coord")
    env.pop("HAPAX_CANON_ECHO_ENFORCEMENT", None)
    env.pop("HAPAX_STAGE_ADVANCE_FAIL_PHASE", None)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *args,
            *(item for ref in guard_refs for item in ("--guard-evidence", ref)),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def _note(home: Path, task_id: str) -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    return next(iter(active.glob(f"{task_id}-*.md")))


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _initialize_coord_log(home: Path) -> None:
    coord = home / ".cache" / "hapax" / "coord"
    log = CoordEventLog(
        db_path=coord / "ledger.db",
        jsonl_path=coord / "ledger.jsonl",
        spool_dir=coord / "spool",
    )
    log.append(
        CoordEvent(
            event_id="test-event-plane-initialized",
            timestamp="2026-07-11T15:00:00Z",
            event_type="test.event_plane_initialized",
            actor="test",
            subject="test",
            payload={"may_authorize": False},
        ),
        writer=CoordWriter.daemon("test"),
    )


class TestStageAdvance:
    def test_forward_advance_holds_until_effect_activation(self, tmp_path: Path) -> None:
        note = _make_task(tmp_path, "t1")
        before = note.read_bytes()
        tree_before = _tree_snapshot(tmp_path)
        r = _run(
            tmp_path,
            "t1",
            "S7_RELEASE",
            guard_refs=(
                "implementation_complete=receipt:test:implementation",
                "evidence_present=receipt:test:evidence",
            ),
        )
        assert r.returncode == 2
        assert "canon_transition_inspection_hold" in r.stderr
        assert note.read_bytes() == before
        assert _tree_snapshot(tmp_path) == tree_before
        ledger = tmp_path / ".cache" / "hapax" / "authority-case-ledger.jsonl"
        assert not ledger.exists()

    def test_raw_ingress_seam_precedes_all_successor_effects(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        seam = source.index('require_protected_action("lifecycle.transition")')
        assert "drain_successor_outboxes" not in source
        assert seam < source.index("ensure_successor_outbox_task_directory(")
        assert "_retired_close_transaction_unreachable" not in source

    def test_backward_refused_without_flag(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t2", stage="S7_RELEASE")
        r = _run(tmp_path, "t2", "S6_IMPLEMENTATION")
        assert r.returncode == 2
        assert "canon_transition_inspection_hold" in r.stderr

    def test_backward_override_removed(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t3", stage="S7_RELEASE")
        r = _run(tmp_path, "t3", "S6_IMPLEMENTATION", "--allow-backward")
        assert r.returncode == 2
        assert "removed" in r.stderr
        assert "stage: S7_RELEASE" in _note(tmp_path, "t3").read_text()

    def test_invalid_stage_refused(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t4")
        r = _run(tmp_path, "t4", "PHASE_SEVEN")
        assert r.returncode == 2

    def test_missing_authority_case_refused(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t5", authority_case=None)
        r = _run(tmp_path, "t5", "S7_RELEASE")
        assert r.returncode == 2
        assert "canon_transition_inspection_hold" in r.stderr

    def test_missing_stage_backfill_is_refused(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t6", stage=None)
        r = _run(tmp_path, "t6", "S6_IMPLEMENTATION")
        assert r.returncode == 2
        assert "canon_transition_inspection_hold" in r.stderr
        assert "stage:" not in _note(tmp_path, "t6").read_text()

    def test_not_found_is_error(self, tmp_path: Path) -> None:
        (tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active").mkdir(
            parents=True
        )
        r = _run(tmp_path, "nope", "S7_RELEASE")
        assert r.returncode == 2

    def test_non_edge_refused_without_partial_mutation(self, tmp_path: Path) -> None:
        note = _make_task(tmp_path, "t7", stage="S0_INTAKE")
        before = note.read_bytes()

        r = _run(tmp_path, "t7", "S11")

        assert r.returncode == 2
        assert "terminal_edge_requires_cc_close" in r.stderr
        assert note.read_bytes() == before
        assert not (tmp_path / ".cache" / "hapax" / "authority-case-ledger.jsonl").exists()

    def test_ambiguous_blocked_edge_requires_edge_class(self, tmp_path: Path) -> None:
        note = _make_task(tmp_path, "t8", stage="S6_IMPLEMENTATION")
        before = note.read_bytes()

        ambiguous = _run(tmp_path, "t8", "BLOCKED")
        assert ambiguous.returncode == 2
        assert "canon_transition_inspection_hold" in ambiguous.stderr
        assert note.read_bytes() == before

        selected = _run(
            tmp_path,
            "t8",
            "BLOCKED",
            "--edge-class",
            "fall",
            guard_refs=("gate_refused=receipt:test:gate-refusal",),
        )
        assert selected.returncode == 2
        assert "canon_transition_inspection_hold" in selected.stderr
        assert note.read_bytes() == before

    def test_failure_injection_cannot_bypass_effect_activation(self, tmp_path: Path) -> None:
        note = _make_task(tmp_path, "t9")
        before = note.read_bytes()
        env = os.environ.copy()
        env.update(
            HOME=str(tmp_path),
            HAPAX_AGENT_ROLE="alpha",
            HAPAX_COORD_DIR=str(tmp_path / ".cache" / "hapax" / "coord"),
            HAPAX_STAGE_ADVANCE_FAIL_PHASE="before_applied",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "t9",
                "S7",
                "--edge-class",
                "next",
                "--guard-evidence",
                "implementation_complete=receipt:test:implementation",
                "--guard-evidence",
                "evidence_present=receipt:test:evidence",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

        assert result.returncode == 2
        assert "canon_transition_inspection_hold" in result.stderr
        assert note.read_bytes() == before

    def test_echo_enforcement_requires_position_and_echo_refs(self, tmp_path: Path) -> None:
        note = _make_task(tmp_path, "t10")
        _initialize_coord_log(tmp_path)
        before = note.read_bytes()
        env = os.environ.copy()
        env.update(
            HOME=str(tmp_path),
            HAPAX_AGENT_ROLE="alpha",
            HAPAX_COORD_DIR=str(tmp_path / ".cache" / "hapax" / "coord"),
            HAPAX_CANON_ECHO_ENFORCEMENT="1",
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "t10", "S7", "--edge-class", "next"],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert result.returncode == 2
        assert "canon_echo_required" in result.stderr
        assert note.read_bytes() == before

    def test_echo_enforcement_rejects_raw_unpublished_claim_sidecars(self, tmp_path: Path) -> None:
        note = _make_task(tmp_path, "t-raw-claim")
        _initialize_coord_log(tmp_path)
        before = note.read_bytes()
        cache = tmp_path / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        for key in ("alpha", "alpha-session-test"):
            claim = cache / f"cc-active-task-{key}"
            epoch = cache / f"cc-claim-epoch-{key}"
            claim.write_text("t-raw-claim\n", encoding="utf-8")
            epoch.write_text("123 t-raw-claim\n", encoding="utf-8")
            claim.chmod(0o600)
            epoch.chmod(0o600)
        env = os.environ.copy()
        env.update(
            HOME=str(tmp_path),
            HAPAX_AGENT_ROLE="alpha",
            HAPAX_SESSION_ID="session-test",
            HAPAX_COORD_DIR=str(cache / "coord"),
            HAPAX_CANON_ECHO_ENFORCEMENT="1",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "t-raw-claim",
                "S7",
                "--edge-class",
                "next",
                "--position-ref",
                f"dispatch-position@sha256:{'a' * 64}",
                "--echo-receipt-ref",
                "mq:raw-sidecar-is-not-a-publication",
                "--guard-evidence",
                "implementation_complete=receipt:test:implementation",
                "--guard-evidence",
                "evidence_present=receipt:test:evidence",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

        assert result.returncode == 2
        assert "claim_dispatch_binding_missing" in result.stderr
        assert note.read_bytes() == before

    def test_canon_bound_close_projects_all_terminal_surfaces_atomically(
        self, tmp_path: Path
    ) -> None:
        task_id = "t-close"
        note = _make_task(tmp_path, task_id, stage="S10_CLOSURE")
        active = note.parent
        receipt_path = active / f"{task_id}.acceptance.yaml"
        db_path = tmp_path / ".cache" / "hapax" / "relay" / "messages.db"
        db_path.parent.mkdir(parents=True)
        source_message_id = "dispatch-close-source"
        send_message(
            db_path,
            Envelope(
                message_id=source_message_id,
                sender="hapax-coordinator",
                message_type="dispatch",
                priority=0,
                subject=task_id,
                authority_case="CASE-TEST-001",
                authority_item=task_id,
                recipients_spec="alpha",
                payload=json.dumps({"task_id": task_id}),
            ),
        )
        ledger_dir = tmp_path / "orchestration"
        ledger_dir.mkdir()
        ledger_path = ledger_dir / "methodology-dispatch.jsonl"
        ledger_path.write_text(
            json.dumps(
                _dispatch_record(source_message_id, task_id=task_id, lane="alpha"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        expected = load_dispatch_echo_expectation(
            ledger_path,
            source_message_id=source_message_id,
            task_id=task_id,
            lane="alpha",
        )
        observed = datetime.now(UTC)
        echo = build_canon_echo_envelope(
            expected,
            sender="alpha",
            session_id="session-test",
            observed_at=observed,
        )
        send_message(db_path, echo)
        receipt_body = {
            "acceptor": "operator",
            "verdict": "accepted",
            "timestamp": "2026-07-11T15:00:00Z",
            "artifact": "artifact:test",
            "task_id": task_id,
            "authority_case": "CASE-TEST-001",
            "canon_binding_ref": expected.binding_ref,
            "position_ref": expected.position_ref,
            "canon_echo_receipt_ref": f"mq:{echo.message_id}",
            "transition": "S10->S11",
            "artifact_sha256": "d" * 64,
            "may_authorize": "false",
        }
        receipt_path.write_text(
            yaml.safe_dump(
                {**receipt_body, "receipt_hash": _hash(receipt_body)},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        cache = tmp_path / ".cache" / "hapax"
        (cache / "cc-active-task-alpha").write_text(task_id + "\n", encoding="utf-8")
        (cache / "cc-active-task-alpha-session-test").write_text(task_id + "\n", encoding="utf-8")
        (cache / "cc-claim-epoch-alpha").write_text("123 t-close\n", encoding="utf-8")
        (cache / "cc-claim-epoch-alpha-session-test").write_text("123 t-close\n", encoding="utf-8")
        relay = cache / "relay" / "alpha.yaml"
        relay.write_text(
            "role: alpha\nstatus: active\ncurrent_claim: t-close\nstage_token: S10\n",
            encoding="utf-8",
        )
        coord_dir = cache / "coord"
        _initialize_coord_log(tmp_path)
        env = os.environ.copy()
        env.update(
            HOME=str(tmp_path),
            HAPAX_AGENT_ROLE="alpha",
            HAPAX_SESSION_ID="session-test",
            HAPAX_RELAY_MQ_DB=str(db_path),
            HAPAX_ORCHESTRATION_LEDGER_DIR=str(ledger_dir),
            HAPAX_COORD_DIR=str(coord_dir),
            HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT="1",
            HAPAX_RAPID_CLOSE_OFF="1",
            HAPAX_PR_MERGE_GATE_OFF="1",
            HAPAX_ARTIFACT_DISPOSITION_GATE_OFF="1",
            HAPAX_CC_HYGIENE_OFF="1",
        )

        result = subprocess.run(
            ["bash", str(CLOSE_SCRIPT), task_id, "--status", "done"],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )

        assert result.returncode == 2
        assert "claim_dispatch_binding_missing" in result.stderr
        assert note.is_file()
        assert receipt_path.is_file()
        assert not (active.parent / "closed" / note.name).exists()
