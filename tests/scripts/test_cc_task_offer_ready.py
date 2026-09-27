from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cc-task-offer-ready"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _preferred_platforms_yaml(preferred: str | None, *, nested: bool) -> str:
    if preferred is None:
        return ""
    if nested:
        return f"route_metadata:\n  route_constraints:\n    preferred_platforms: {preferred}\n"
    return f"route_constraints:\n  preferred_platforms: {preferred}\n"


def _task_frontmatter(
    *,
    status: str = "ready",
    assigned_to: str = "null",
    depends_on: str = "dep",
    authority_level: str = "delegated",
    mutation_surface: str = "planning",
    preferred_platforms: str | None = None,
    nested_preferred_platforms: bool = False,
) -> str:
    extra = _preferred_platforms_yaml(preferred_platforms, nested=nested_preferred_platforms)
    return f"""\
---
type: cc-task
task_id: ready-task
title: "Ready task"
status: {status}
assigned_to: {assigned_to}
priority: p1
wsjf: 5.0
depends_on:
  - {depends_on}
created_at: 2026-05-17T00:00:00Z
updated_at: 2026-05-17T00:00:00Z
parent_request: request.md
authority_case: CASE-TEST-001
parent_spec: spec.md
quality_floor: deterministic_ok
mutation_surface: {mutation_surface}
authority_level: {authority_level}
route_metadata_schema: 1
kind: planning
{extra}---

# Ready Task
"""


def _write_ready_task(vault: Path, **kwargs: Any) -> Path:
    return _write(vault / "active" / "ready-task.md", _task_frontmatter(**kwargs))


def _write_dep(vault: Path, *, status: str = "done") -> Path:
    return _write(
        vault / "closed" / "dep.md",
        f"""\
---
type: cc-task
task_id: dep
status: {status}
assigned_to: cx-test
pr: null
---

# Dep
""",
    )


def _run(vault: Path, task_id: str = "ready-task") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), task_id, "--vault-root", str(vault)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_promotes_dependency_satisfied_ready_task_to_offered(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault)
    _write_dep(vault)

    result = _run(vault)

    assert result.returncode == 0, result.stderr
    text = task.read_text(encoding="utf-8")
    assert "status: offered" in text
    assert "assigned_to: unassigned" in text
    assert "claimed_at: null" in text
    assert "authority_level: authoritative" in text
    assert "mutation_surface: vault_docs" in text
    assert "claimable: true" in text
    assert "promoted ready -> offered by cc-task-offer-ready" in text


# M77: rows minted straight to `offered` carried no `claimable: true`, which
# cc-claim requires, and no tool wrote the field. Frontmatter as minted 09-22:
_MINTED_OFFERED_ROW_0922 = """\
---
type: cc-task
task_id: minted-offered-row
title: 'Fix: connector classifier fails closed'
status: offered
blocked_reason: null
assigned_to: unassigned
priority: p2
wsjf: 1.5
effort_class: standard
quality_floor: verification_receipt
mutation_surface: source
authority_level: authoritative
route_metadata_schema: 1
kind: implementation
risk_tier: T1
depends_on: []
blocks: []
branch: null
pr: null
pr_repo: null
created_at: 2026-09-22T16:53:47Z
updated_at: 2026-09-22T16:53:47Z
claimed_at: null
completed_at: null
parent_request: null
parent_spec: spec.md
authority_case: CASE-CAPACITY-ROUTING-001
tags:
- cc-task
stage: S6_IMPLEMENTATION
implementation_authorized: true
---

# Objective

## Session log
"""


def _write_offered(vault: Path, *, replace: tuple[str, str] | None = None) -> Path:
    text = _MINTED_OFFERED_ROW_0922
    if replace is not None:
        assert text.count(replace[0]) == 1
        text = text.replace(*replace)
    return _write(vault / "active" / "minted-offered-row.md", text)


def test_offered_row_with_explicit_claimable_false_is_never_flipped(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_offered(
        vault, replace=("status: offered\n", "status: offered\nclaimable: false\n")
    )
    before = task.read_bytes()

    result = _run(vault, "minted-offered-row")

    assert result.returncode == 4
    assert "claimable is explicitly False" in result.stderr
    assert task.read_bytes() == before


@pytest.mark.parametrize(
    ("replace", "returncode", "message"),
    [
        (("assigned_to: unassigned", "assigned_to: cx-other"), 4, "assigned to 'cx-other'"),
        (("authority_case: CASE-CAPACITY-ROUTING-001", "authority_case: null"), 6, "authority"),
        (("depends_on: []", "depends_on:\n  - dep"), 5, "unmet dependencies"),
    ],
)
def test_offered_row_lacking_claimable_is_refused_on_the_promotion_checks(
    tmp_path: Path, replace: tuple[str, str], returncode: int, message: str
) -> None:
    vault = tmp_path / "tasks"
    task = _write_offered(vault, replace=replace)
    _write_dep(vault, status="in_progress")
    before = task.read_bytes()

    result = _run(vault, "minted-offered-row")

    assert result.returncode == returncode
    assert message in result.stderr
    assert task.read_bytes() == before


def test_already_claimable_offered_row_is_left_byte_identical(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_offered(
        vault, replace=("status: offered\n", "status: offered\nclaimable: true\n")
    )
    before = task.read_bytes()

    result = _run(vault, "minted-offered-row")

    assert result.returncode == 0, result.stderr
    assert task.read_bytes() == before


def test_minted_offered_row_shape_is_made_claimable_in_place(tmp_path: Path) -> None:
    from shared.frontmatter import parse_frontmatter_with_diagnostics

    vault = tmp_path / "tasks"
    task = _write_offered(vault)

    result = _run(vault, "minted-offered-row")

    assert result.returncode == 0, result.stderr
    text = task.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter_with_diagnostics(task).frontmatter
    assert frontmatter is not None
    assert frontmatter["claimable"] is True
    assert frontmatter["status"] == "offered"
    assert frontmatter["stage"] == "S6_IMPLEMENTATION"
    assert frontmatter["quality_floor"] == "verification_receipt"
    assert "marked claimable by cc-task-offer-ready" in text


# gemini-1 on #4741 @ 97d506740 (major): the shared write path inserted `claimable: true`
# unconditionally, so promoting a ready row overwrote an explicit `claimable: false` hold.


def test_ready_row_with_explicit_claimable_false_keeps_its_hold_on_promotion(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "tasks"
    text = _task_frontmatter().replace("status: ready\n", "status: ready\nclaimable: false\n")
    task = _write(vault / "active" / "ready-task.md", text)
    _write_dep(vault)

    result = _run(vault)

    assert result.returncode == 0, result.stderr
    after = task.read_text(encoding="utf-8")
    assert "status: offered" in after
    assert "claimable: false" in after
    assert "claimable: true" not in after


def _load_offer_ready() -> Any:
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader("cc_task_offer_ready_m77", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_a_hold_that_appears_before_the_lock_is_never_overwritten(tmp_path: Path) -> None:
    """claude-1 on #4741: the explicit-hold check ran only before the projection lock. A hold
    written in that window must stop the offered -> claimable write under the lock."""
    module = _load_offer_ready()
    vault = tmp_path / "tasks"
    # the note as it reads under the lock: a hold landed after the pre-lock check passed
    task = _write_offered(
        vault, replace=("status: offered\n", "status: offered\nclaimable: false\n")
    )
    before = task.read_bytes()

    rc = module._promote_under_lock(
        path=task,
        status="offered",
        route_changes={},
        timestamp="2026-09-25T09:40:00Z",
        task_id="minted-offered-row",
        dry_run=False,
        vault_root=vault,
        log_event="marked claimable by cc-task-offer-ready (test)",
        require_unset_claimable=True,
    )

    assert rc == 4
    assert task.read_bytes() == before


def test_offered_row_dry_run_marks_nothing(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_offered(vault)
    before = task.read_bytes()

    result = subprocess.run(
        [str(SCRIPT), "minted-offered-row", "--vault-root", str(vault), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "dry-run would mark" in result.stdout
    assert task.read_bytes() == before


def test_blocks_ready_task_with_nonterminal_dependency(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault)
    _write_dep(vault, status="in_progress")

    result = _run(vault)

    assert result.returncode == 5
    assert "unmet dependencies" in result.stderr
    assert "status: in_progress" in result.stderr
    assert "status: ready" in task.read_text(encoding="utf-8")


def test_blocks_ready_task_with_concrete_assignee(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault, assigned_to="cx-other")
    _write_dep(vault)

    result = _run(vault)

    assert result.returncode == 4
    assert "assigned to 'cx-other'" in result.stderr
    assert "status: ready" in task.read_text(encoding="utf-8")


def test_blocks_ready_task_with_unrepairable_route_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(
        vault,
        authority_level="not-a-real-authority-level",
        mutation_surface="not-a-real-surface",
    )
    _write_dep(vault)

    result = _run(vault)

    assert result.returncode == 7
    assert "route metadata is not dispatchable" in result.stderr
    assert "status: ready" in task.read_text(encoding="utf-8")


def _run_reconcile(vault: Path, *, dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [str(SCRIPT), "--reconcile", "--vault-root", str(vault)]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _write_task(vault: Path, task_id: str, *, status: str, depends_on: str) -> Path:
    return _write(
        vault / "active" / f"{task_id}.md",
        f"""\
---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: {status}
assigned_to: null
priority: p1
wsjf: 5.0
depends_on:
  - {depends_on}
created_at: 2026-05-17T00:00:00Z
updated_at: 2026-05-17T00:00:00Z
parent_request: request.md
authority_case: CASE-TEST-001
parent_spec: spec.md
quality_floor: deterministic_ok
mutation_surface: vault_docs
authority_level: authoritative
route_metadata_schema: 1
kind: planning
---

# {task_id}
""",
    )


def test_reconcile_promotes_satisfied_and_skips_unsatisfied(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    _write_dep(vault, status="done")
    t1 = _write_task(vault, "task-satisfied", status="ready", depends_on="dep")
    t2 = _write_task(vault, "task-blocked", status="ready", depends_on="missing-dep")
    t3 = _write_task(vault, "task-offered", status="offered", depends_on="dep")

    result = _run_reconcile(vault)

    assert result.returncode == 0
    assert "1 promoted, 1 skipped" in result.stdout
    assert "status: offered" in t1.read_text(encoding="utf-8")
    assert "status: ready" in t2.read_text(encoding="utf-8")
    assert "status: offered" in t3.read_text(encoding="utf-8")


def test_reconcile_dry_run_does_not_modify(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    _write_dep(vault, status="done")
    t1 = _write_task(vault, "task-ready", status="ready", depends_on="dep")

    result = _run_reconcile(vault, dry_run=True)

    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert "status: ready" in t1.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("preferred", "nested", "should_refuse"),
    [
        ("[claude]", False, True),
        ("[Claude]", False, True),
        ("[claude]", True, True),
        (None, False, False),
        ("[]", False, False),
        ("[kimi]", False, False),
        ("[claude, kimi]", False, False),
        ("[grok]", False, False),
        ("[gemini]", False, False),
        ("[qwen]", False, False),
    ],
)
def test_od2_preferred_platforms_gate(
    tmp_path: Path, preferred: str | None, nested: bool, should_refuse: bool
) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(
        vault,
        preferred_platforms=preferred,
        nested_preferred_platforms=nested,
    )
    _write_dep(vault)

    result = _run(vault)
    text = task.read_text(encoding="utf-8")

    if should_refuse:
        assert result.returncode == 7, result.stderr
        assert "route metadata is not dispatchable" in result.stderr
        assert "singleton walled carrier" in result.stderr
        assert "OD2" in result.stderr
        assert "status: ready" in text
        return

    assert result.returncode == 0, result.stderr
    assert "status: offered" in text


def _write_active_preferred(
    vault: Path,
    task_id: str,
    *,
    status: str = "offered",
    preferred_platforms: str = "[kimi]",
) -> Path:
    return _write(
        vault / "active" / f"{task_id}.md",
        f"""\
---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: {status}
assigned_to: unassigned
priority: p1
wsjf: 5.0
created_at: 2026-05-17T00:00:00Z
updated_at: 2026-05-17T00:00:00Z
parent_request: request.md
authority_case: CASE-TEST-001
parent_spec: spec.md
quality_floor: deterministic_ok
mutation_surface: vault_docs
authority_level: authoritative
route_metadata_schema: 1
kind: planning
route_constraints:
  preferred_platforms: {preferred_platforms}
---

# {task_id}
""",
    )


def test_concentration_cap_refuses_singleton_when_family_already_half(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault, preferred_platforms="[kimi]")
    _write_dep(vault)
    _write_active_preferred(vault, "already-kimi", preferred_platforms="[Kimi]")

    result = _run(vault)
    text = task.read_text(encoding="utf-8")

    assert result.returncode == 7, result.stderr
    assert "route metadata is not dispatchable" in result.stderr
    assert "CONCENTRATION_CAP_NUMERATOR" in result.stderr
    assert "CONCENTRATION_CAP_DENOMINATOR" in result.stderr
    assert "singleton [kimi]" in result.stderr
    assert "glm" in result.stderr
    assert "family-outage" in result.stderr
    assert "status: ready" in text


def test_concentration_cap_allows_two_element_set(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault, preferred_platforms="[kimi, glm]")
    _write_dep(vault)
    _write_active_preferred(vault, "already-kimi", preferred_platforms="[kimi]")

    result = _run(vault)

    assert result.returncode == 0, result.stderr
    assert "status: offered" in task.read_text(encoding="utf-8")


def test_concentration_cap_allows_omitted_preferred_platforms(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault)
    _write_dep(vault)
    _write_active_preferred(vault, "already-kimi", preferred_platforms="[kimi]")

    result = _run(vault)

    assert result.returncode == 0, result.stderr
    assert "status: offered" in task.read_text(encoding="utf-8")


def test_concentration_cap_allows_when_n_is_one(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault, preferred_platforms="[kimi]")
    _write_dep(vault)
    _write_task(vault, "no-pref", status="offered", depends_on="dep")

    result = _run(vault)

    assert result.returncode == 0, result.stderr
    assert "status: offered" in task.read_text(encoding="utf-8")
