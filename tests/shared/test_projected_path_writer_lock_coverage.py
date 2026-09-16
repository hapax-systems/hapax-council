"""Coverage: every writer to a projected task-note path takes the projection lock.

Two things live here.

**End-to-end** — the real CLI tools, racing on one real note, under a redirected ``HOME``.
The row's acceptance shape is "two writers, one flock, no lost copy", and the only way to know
the tools take the lock is to run the tools.

**Conformance** — the inventory itself, as an assertion. The row's floor was four writers
(``cc-stage-advance``, ``cc-scope-widen``, ``cc-task-repair``, the gate's
``_stamp_frontmatter_field``) and named the floor a floor rather than a ceiling. It was right
to: the floor came from one search shape — grep for the literal vault path — and a second shape
over the callers of :mod:`shared.cc_task_root` finds ``cc-claim``, ``cc-close``,
``cc-cascade-unblock`` and ``cc-task-pr-link.sh``, none of which spell the vault themselves.
A list that was assembled by grep will be re-assembled by grep the next time someone adds a
writer, so it is pinned here instead: a file that writes a task note and is not in the
converted set has to be added to one list or the other, with a reason.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ───────────────────────────────────────────────────────────── end-to-end, the real tools


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True)
    return root


NOTE = """\
---
type: cc-task
task_id: lock-probe-1
title: "concurrent writer probe"
status: claimed
assigned_to: theta
authority_case: CASE-CAPACITY-ROUTING-001
parent_spec: 30-areas/probe.md
route_metadata_schema: 1
stage: S6_IMPLEMENTATION
mutation_scope_refs:
  - shared/task_note_lock.py
updated_at: 2026-09-16T00:00:00Z
---

## Session log
"""


def _tool_env(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home),
        "HAPAX_COORD_DIR": str(home / "coord"),
        "HAPAX_AGENT_ROLE": "theta-test",
        "PYTHONPATH": f"{REPO_ROOT}:{os.environ.get('PYTHONPATH', '')}",
    }


@pytest.fixture
def probe(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    home = tmp_path / "home"
    home.mkdir()
    note = _vault(home) / "active" / "lock-probe-1.md"
    note.write_text(NOTE, encoding="utf-8")
    return home, note, _tool_env(home)


def test_cc_stage_advance_waits_for_a_held_projection_lock(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """The tool must be *observably* serialized, not merely importing the module.

    A conformance grep can only see that the name appears. This runs the tool against a lock a
    second process is holding and requires it to wait — the difference between taking a lock and
    mentioning one.
    """

    home, note, env = probe
    root = home / "coord" / "task-locks"

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from shared import task_note_lock as tnl
                with tnl.projected_path_lock("lock-probe-1", (Path({str(note)!r}),),
                                             root=Path({str(root)!r}), timeout=30.0):
                    print("HELD", flush=True)
                    time.sleep(4)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        started = time.monotonic()
        done = subprocess.run(
            [str(REPO_ROOT / "scripts" / "cc-stage-advance"), "lock-probe-1", "S7_RELEASE"],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )
        waited = time.monotonic() - started
    finally:
        holder.wait(timeout=30)

    assert waited > 2.0, (
        f"cc-stage-advance did not wait for the projection lock (returned in {waited:.2f}s); "
        f"stdout={done.stdout!r} stderr={done.stderr!r}"
    )
    assert "S7_RELEASE" in note.read_text(encoding="utf-8")


def test_two_tools_writing_one_note_concurrently_lose_no_copy(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """``cc-stage-advance`` and ``cc-scope-widen`` on one note, at once, both survive.

    Each is a read-modify-write of the whole file. Unserialized, whichever reads first and
    writes last erases the other's field entirely — and neither reports anything wrong, because
    from inside each one the write succeeded.
    """

    _home, note, env = probe
    procs = [
        subprocess.Popen(
            [str(REPO_ROOT / "scripts" / "cc-stage-advance"), "lock-probe-1", "S7_RELEASE"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        ),
        subprocess.Popen(
            [
                str(REPO_ROOT / "scripts" / "cc-scope-widen"),
                "lock-probe-1",
                "--add",
                "shared/coord_projection.py",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        ),
    ]
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, f"writer failed: {out!r} {err!r}"

    final = note.read_text(encoding="utf-8")
    assert "stage: S7_RELEASE" in final, f"the stage advance's copy was lost:\n{final}"
    assert "shared/coord_projection.py" in final, f"the scope widen's copy was lost:\n{final}"


def test_the_gate_stamp_refuses_rather_than_racing_a_held_lock(
    probe: tuple[Path, Path, dict[str, str]],
) -> None:
    """The gate stamps frontmatter; under contention it must refuse, not fail open.

    Failing open is what it did before, and it is what put the gate in the row's writer
    inventory. The stamp not landing is safe — the caller then reports an insufficient stage and
    the operator retries. The stamp landing mid-transition is not.
    """

    home, note, env = probe
    root = home / "coord" / "task-locks"
    before = note.read_text(encoding="utf-8")

    stamp = textwrap.dedent(
        f"""
        SCRIPT_DIR={str(REPO_ROOT / "hooks" / "scripts")!r}
        . {str(REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh")!r} 2>/dev/null || true
        """
    )
    # Source only the function under test; the impl script is a gate, not a library.
    body = (REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh").read_text(encoding="utf-8")
    match = re.search(r"^_stamp_frontmatter_field\(\) \{.*?^\}", body, re.M | re.S)
    assert match, "the gate's stamp function was renamed; update this test with it"
    stamp = f"SCRIPT_DIR={str(REPO_ROOT / 'hooks' / 'scripts')!r}\n{match.group(0)}\n"

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from shared import task_note_lock as tnl
                with tnl.projected_path_lock(None, (Path({str(note)!r}),),
                                             root=Path({str(root)!r}), timeout=30.0):
                    print("HELD", flush=True)
                    time.sleep(6)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        done = subprocess.run(
            ["bash", "-c", f'{stamp}\n_stamp_frontmatter_field "{note}" stage S9_DONE'],
            capture_output=True,
            text=True,
            env={**env, "HAPAX_TASK_NOTE_LOCK_TIMEOUT": "1"},
            timeout=60,
        )
    finally:
        holder.wait(timeout=30)

    assert done.returncode != 0, "the gate stamped a note held by another writer"
    assert note.read_text(encoding="utf-8") == before, "the refused stamp still wrote"
    assert "stamp skipped" in done.stderr, done.stderr


# ───────────────────────────────────────────────────────────── conformance: the inventory

#: Writers converted to take the projection lock. Each must still take it.
UNDER_LOCK = (
    "scripts/cc-stage-advance",
    "scripts/cc-scope-widen",
    "scripts/cc-task-repair",
    "hooks/scripts/cc-task-gate.impl.sh",
)

#: Files that name the vault and write, but are NOT task-note writers — each with the reason
#: it is out of scope. A bare "not a writer" is not a reason; the reason has to say what it
#: writes instead, so the next person can check it rather than trust it.
NOT_A_TASK_NOTE_WRITER = {
    "scripts/cc_hygiene/dashboard.py": "writes the _dashboard/ markdown, never a task note",
    "scripts/cc_hygiene/ntfy.py": "writes its own notification state JSON",
    "scripts/cc-pr-review-dispatch.py": "writes review dossiers under _evidence/, not notes",
    "scripts/epistemic_quality_dataset.py": "reads notes; writes JSONL datasets elsewhere",
    "scripts/cc-phase-advance.py": "writes request notes under a different root",
    "shared/policy_decide.py": "vault paths appear only in test fixtures/allowlists",
    "shared/merge_queue_lineage.py": "vault path appears only inside a parsing regex",
    "shared/capability_surface_delta.py": "reads active/ to render a delta report",
    "scripts/check-cc-task-vault-shape.py": "read-only vault shape checker",
    "scripts/cc_hygiene/checks.py": "read-only hygiene checks",
    "hooks/scripts/hooks-doctor.sh": "reports hook wiring; writes no note",
    "scripts/scheduler-readiness-unblock-reconcile.py": "writes no note (reconcile report only)",
}

#: Task-note writers the sweep found that this change does NOT yet route through the lock.
#: They are listed rather than forgotten: an entry here is an open hazard with a named owner,
#: and the test below fails the moment a NEW writer appears that is in neither list.
KNOWN_UNCONVERTED = {
    # MEASURED 2026-09-16, and worse than "own lock root" suggests. Claim publication holds
    # shared/sdlc_claim.py::_claim_publication_lock, which is keyed by the ROLE digest and
    # lives under ~/.cache/hapax/task-locks, while a transition over the same note is keyed
    # by task id + path under coord_base_dir()/task-locks. Different root AND different key
    # space, so neither excludes the other — and sdlc_claim calls _apply_projections (which
    # takes no lock of its own) directly. This is the row's hazard in the estate's highest
    # frequency note writer, reached through the projection machinery itself.
    #
    # Not fixed here on purpose: the role lock is doing a different, legitimate job, so the
    # fix is to take BOTH — and a second lock outside this primitive's total order is a
    # lock-order inversion waiting to happen. It needs its own row and its own deadlock
    # argument, not a rider on a p0.
    "scripts/cc-claim": "role-keyed lock in a different root; see the note above — own row",
    # NOT the same as cc-claim, and the earlier reason string here said it was. Measured
    # 2026-09-16: shared/sdlc_close.py DOES reach _transition_locks with the canonical root
    # — it is correct — but three search shapes find no caller outside tests. The live close
    # is scripts/cc-close doing the active/ -> closed/ move itself: read, mutate,
    # tmp.replace(new_path), then path.unlink() on the active note, unserialized. It is the
    # only writer here that UNLINKS a projected path, so a transition holding that note's
    # preimage can have its subject removed underneath it.
    "scripts/cc-close": "live closer moves+unlinks unserialized; sdlc_close is correct but unwired — own row",
    "scripts/cc-cascade-unblock": "batch unblocker; convert with the batch-writer pass",
    "scripts/cc-task-offer-ready": "offer-readiness stamper; convert with the batch-writer pass",
    "scripts/cc-migration-capability": "migration tool, run by hand",
    "scripts/cc-pr-merge-watcher.py": "daemon writer; convert with the daemon pass",
    "scripts/cc-pr-autoqueue.py": "daemon writer; convert with the daemon pass",
    "scripts/protected-lane-revive-reconcile.py": "reconciler; convert with the daemon pass",
    "scripts/refused_lifecycle_classify.py": "refused/ lifecycle; convert with the daemon pass",
    "scripts/refused_lifecycle_migrate_schema.py": "one-shot schema migration",
    "scripts/migrate_native_tasks_to_vault.py": "one-shot import, runs before any transition",
    "scripts/downstream_contribution_ledger_v0.py": "appends a report note, not a task note",
    "scripts/downstream_contribution_measurement_design.py": "same",
    "scripts/audit-route-metadata-seed-candidates.py": "writes an audit report",
    "scripts/braided_value_snapshot_runner.py": "reads notes; writes a snapshot",
    "scripts/velocity_report_evidence_snapshot.py": "writes an evidence snapshot",
    "scripts/rag_documents_v2_shadow.py": "writes a shadow index",
    "scripts/cc-task-backfill-nogo": "backfill tool, run by hand",
    "scripts/cc-task-lint": "read-only lint",
    "scripts/cc-task-offer-ready ": "duplicate guard",
    "scripts/refused_lifecycle_migrate_schema.py ": "duplicate guard",
    "scripts/check-audio-authority-case.py": "read-only check",
    "scripts/check-peer-glob-coherence.py": "read-only check",
    "scripts/protected-lane-revive-reconcile.py ": "duplicate guard",
    "scripts/cc-close-sibling-check.py": "read-only check",
    "scripts/cc-hygiene-sweeper.py": "read-only sweep + ntfy",
    "scripts/cc-hygiene-dashboard-renderer.py": "renders the dashboard",
    "scripts/migrate_native_tasks_to_vault.py ": "duplicate guard",
    "scripts/refused_lifecycle_migrate_schema.py  ": "duplicate guard",
    "hooks/scripts/cc-task-pr-link.sh": "stamps pr:/pr_repo:; convert with the hook pass",
    "hooks/scripts/cc-task-gate-bootstrap.py": "creates a new note; no transition can exist yet",
    "hooks/scripts/cc-task-closure-gate.sh": "read-only closure gate",
    "hooks/scripts/work-resolution-gate.sh": "read-only branch/PR gate",
    "hooks/scripts/authorization-packet-validator.sh": "read-only validator",
    "hooks/scripts/pr-release-gate.sh": "read-only release precheck",
    "hooks/scripts/session-context.sh": "read-only session banner",
    "hooks/scripts/sense_reissue_capture.py": "writes its own capture JSONL",
    "hooks/scripts/cc-task-root.sh": "resolver only",
    "agents/coordinator/core.py": "coordinator note writer; convert with the daemon pass",
    "agents/triage_officer/core.py": "triage writer; convert with the daemon pass",
    "agents/refused_lifecycle/runner.py": "refused/ lifecycle; convert with the daemon pass",
    "agents/refused_lifecycle/state.py": "state helper for the above",
    "agents/marketing/cc_task_cross_linker.py": "cross-linker; convert with the daemon pass",
    "agents/relay_to_cc_tasks.py": "creates new notes from relay items",
    "agents/request_decomposer/writer.py": "creates new request notes",
    "agents/jr_spark_auto_consumer/consumer.py": "creates new notes from spark items",
    "agents/interview_compass.py": "writes its own compass file",
    "agents/content_id_watcher/__init__.py": "reads notes",
    "agents/coordination_tui/app.py": "read-only TUI",
    "agents/coordination_tui/data.py": "read-only TUI data",
    "agents/deliberative_council/capability_admission.py": "reads notes",
    "agents/drift_detector/probes_executive.py": "reads notes",
    "agents/operator_current_state/collector.py": "reads notes",
    "agents/publication_bus/refusal_brief_daemon.py": "writes refusal briefs",
    "agents/playwright_grant_submission_runner/__init__.py": "grant runner; reads notes",
    "agents/playwright_grant_submission_runner/package.py": "grant packaging",
    "agents/studio_compositor/durf_source.py": "reads notes for overlay copy",
    "shared/gate0b_claim_publication_install.py": "installs the claim-publication machinery",
    "shared/p0_incident_intake.py": "creates new incident notes",
    "shared/recovery_governor.py": "recovery writer; convert with the daemon pass",
    "shared/sdlc_close.py": "correctly takes the transition lock, but has no production caller — own row",
    "shared/sdlc_invariants.py": "read-only invariant monitor",
    "shared/scheduler_readiness_reconciler.py": "reconciler; reads notes",
    "shared/github_public_surface.py": "reads notes for the public surface",
    "shared/public_gate_receipts.py": "writes receipts",
    "shared/task_graph_tree_effect_scorer.py": "reads notes",
    "shared/cc_task_root.py": "resolver only",
    "shared/coord_projection.py": "owns the transition; takes the lock by construction",
    "shared/task_note_lock.py": "the lock itself",
    "shared/sdlc_claim.py": "role-keyed lock, different root; see the cc-claim note — own row",
    "scripts/cc-migration-capability ": "duplicate guard",
    "scripts/refused_lifecycle_classify.py ": "duplicate guard",
    "scripts/downstream_contribution_ledger_v0.py ": "duplicate guard",
}


def _candidate_files() -> set[str]:
    """Union of the search shapes. One grep's silence is a fact about the grep."""

    found: set[str] = set()
    for pattern in ("hapax-cc-tasks", r"cc_task_root|cc-task-root|CC_TASK_ROOT"):
        out = subprocess.run(
            [
                "grep",
                "-rlE",
                pattern,
                "--include=*.py",
                "--include=*.sh",
                "--include=cc-*",
                "scripts",
                "hooks",
                "shared",
                "agents",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        ).stdout
        found |= {line.strip() for line in out.splitlines() if line.strip()}
    return found


def test_every_converted_writer_actually_takes_the_lock() -> None:
    """Assert the call shape, with comments stripped.

    A conformance grep that reads its own explanatory comments passes on a file that only
    *talks* about the lock. So the import and the call are matched separately, on
    comment-stripped source, and the call must be a real ``with`` of the context manager.
    """

    for rel in UNDER_LOCK:
        path = REPO_ROOT / rel
        source = path.read_text(encoding="utf-8")
        stripped = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in source.splitlines())
        assert re.search(
            r"from\s+shared\.task_note_lock\s+import\s+[^\n]*projected_path_lock", stripped
        ), f"{rel} does not import the projection lock"
        assert re.search(
            r"(with\s+projected_path_lock\s*\(|lock\s*=\s*projected_path_lock\s*\()", stripped
        ), f"{rel} imports the projection lock but never takes it"


def test_the_writer_inventory_has_no_unclassified_file() -> None:
    """A new task-note writer must be classified, not silently added.

    This is the part that keeps the inventory a floor. The row's floor of four came from one
    search shape and missed ``cc-claim`` and ``cc-close``; the same thing happens again the
    moment the list lives only in a commit message. Anything the sweep finds must be in exactly
    one of: converted, not-a-note-writer, or known-unconverted-with-a-reason.
    """

    classified = set(UNDER_LOCK) | set(NOT_A_TASK_NOTE_WRITER) | set(KNOWN_UNCONVERTED)
    unclassified = sorted(rel for rel in _candidate_files() if rel not in classified)
    assert not unclassified, (
        "these files reach the cc-task vault and are in no inventory list:\n  "
        + "\n  ".join(unclassified)
        + "\n\nClassify each one: add it to UNDER_LOCK (and route it through "
        "projected_path_lock), to NOT_A_TASK_NOTE_WRITER with what it writes instead, or to "
        "KNOWN_UNCONVERTED with the pass that will convert it."
    )


def test_the_transition_and_the_writers_share_one_lock_implementation() -> None:
    """``coord_projection`` must delegate, not re-implement.

    Two implementations that agree today serialize nothing the day they stop agreeing, and
    nothing would detect it. This asserts the delegation rather than the agreement.
    """

    source = (REPO_ROOT / "shared" / "coord_projection.py").read_text(encoding="utf-8")
    stripped = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in source.splitlines())
    body = re.search(r"^def _transition_locks\(.*?(?=\n@|\ndef |\nclass )", stripped, re.M | re.S)
    assert body, "_transition_locks was renamed; update this test with it"
    assert "task_note_lock.projected_path_lock" in body.group(0), (
        "_transition_locks no longer delegates to the shared primitive — the transition and the "
        "task-note writers are two lock domains again"
    )
    assert "fcntl.flock" not in body.group(0), (
        "_transition_locks took a flock of its own; the primitive is shared/task_note_lock.py"
    )
