from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-cascade-unblock"


def _load_module() -> ModuleType:
    module_name = "cc_cascade_unblock_test_module"
    if module_name in sys.modules:
        del sys.modules[module_name]
    loader = SourceFileLoader(module_name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_vault(tmp_path: Path, module: ModuleType) -> Path:
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "closed").mkdir(parents=True)
    module.VAULT = vault
    module.ACTIVE = vault / "active"
    module.CLOSED = vault / "closed"
    return vault


def _write_task(
    vault: Path,
    folder: str,
    task_id: str,
    *,
    status: str,
    depends_on: list[str] | None = None,
    pr: int | None = None,
    quality_floor: str = "frontier_required",
    authority_level: str = "authoritative",
    mutation_surface: str = "source",
    body: str = "",
) -> Path:
    deps = depends_on or []
    deps_text = "[]"
    if deps:
        deps_text = "\n" + "\n".join(f"  - {dep}" for dep in deps)
    pr_text = f"pr: {pr}" if pr is not None else "pr: null"
    path = vault / folder / f"{task_id}.md"
    path.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: {status}
blocked_reason: waiting
assigned_to: cx-test
kind: build
authority_case: CASE-TEST
parent_spec: docs/spec.md
route_metadata_schema: 1
quality_floor: {quality_floor}
authority_level: {authority_level}
mutation_surface: {mutation_surface}
depends_on: {deps_text}
{pr_text}
---

# {task_id}

{body}
""",
        encoding="utf-8",
    )
    return path


def test_cascade_unblocks_only_when_dependency_closure_is_valid(tmp_path: Path) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    module._check_pr_merged = lambda _pr: "merged"
    _write_task(
        vault,
        "closed",
        "valid-dep",
        status="done",
        pr=123,
        body="## Acceptance criteria\n\n- [x] Evidence exists\n",
    )
    target = _write_task(
        vault,
        "active",
        "target",
        status="blocked",
        depends_on=["valid-dep"],
    )

    assert module.cascade_unblock() == 1
    text = target.read_text(encoding="utf-8")
    assert "status: offered" in text
    assert "blocked_reason: null" in text


def test_cascade_keeps_unchecked_acceptance_dependency_blocked(tmp_path: Path) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    module._check_pr_merged = lambda _pr: "merged"
    _write_task(
        vault,
        "closed",
        "false-dep",
        status="done",
        body="## Acceptance criteria\n\n- [ ] Evidence exists\n",
    )
    target = _write_task(
        vault,
        "active",
        "target",
        status="blocked",
        depends_on=["false-dep"],
    )

    assert module.cascade_unblock() == 0
    text = target.read_text(encoding="utf-8")
    assert "status: blocked" in text
    assert "unchecked_acceptance_criteria:Evidence exists" in text


def test_cascade_keeps_open_pr_dependency_blocked(tmp_path: Path) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    module._check_pr_merged = lambda _pr: "open"
    _write_task(vault, "closed", "open-pr-dep", status="done", pr=456)
    target = _write_task(
        vault,
        "active",
        "target",
        status="blocked",
        depends_on=["open-pr-dep"],
    )

    assert module.cascade_unblock() == 0
    assert "pr_open:456" in target.read_text(encoding="utf-8")


def test_cascade_keeps_malformed_route_dependency_blocked(tmp_path: Path) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    module._check_pr_merged = lambda _pr: "merged"
    _write_task(
        vault,
        "closed",
        "bad-route-dep",
        status="done",
        quality_floor="frontier_review_required",
        authority_level="authoritative",
    )
    target = _write_task(
        vault,
        "active",
        "target",
        status="blocked",
        depends_on=["bad-route-dep"],
    )

    assert module.cascade_unblock() == 0
    text = target.read_text(encoding="utf-8")
    assert "status: blocked" in text
    assert "route_metadata:" in text
