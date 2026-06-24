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
    blocked_reason: str = "waiting",
    blocked_witness: str | None = None,
    depends_on: list[str] | None = None,
    depends_style: str = "indented",
    pr: int | None = None,
    quality_floor: str = "frontier_required",
    authority_level: str = "authoritative",
    mutation_surface: str = "source",
    body: str = "",
) -> Path:
    deps = depends_on or []
    deps_text = "[]"
    if deps:
        if depends_style == "unindented":
            deps_text = "\n" + "\n".join(f"- {dep}" for dep in deps)
        elif depends_style == "inline":
            deps_text = "[" + ", ".join(deps) + "]"
        elif depends_style == "scalar":
            deps_text = deps[0]
        else:
            deps_text = "\n" + "\n".join(f"  - {dep}" for dep in deps)
    pr_text = f"pr: {pr}" if pr is not None else "pr: null"
    witness_text = f"blocked_witness: {blocked_witness}\n" if blocked_witness else ""
    path = vault / folder / f"{task_id}.md"
    path.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: {status}
blocked_reason: {blocked_reason}
{witness_text}assigned_to: cx-test
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


def test_parse_depends_reads_yaml_frontmatter_shapes() -> None:
    module = _load_module()

    cases = [
        ("depends_on:\n  - dep-a\n  - dep-b", ["dep-a", "dep-b"]),
        ("depends_on:\n- dep-a\n- dep-b", ["dep-a", "dep-b"]),
        ("depends_on: [dep-a, dep-b]", ["dep-a", "dep-b"]),
        ("depends_on: dep-a", ["dep-a"]),
        ("depends_on: []", []),
    ]

    for frontmatter, expected in cases:
        text = f"---\n{frontmatter}\n---\n\n# Task\n"
        assert module._parse_depends(text) == expected


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

    assert module.cascade_unblock("valid-dep") == 1
    text = target.read_text(encoding="utf-8")
    assert "status: offered" in text
    assert "blocked_reason: null" in text


def test_cascade_unblocks_valid_dependency_with_unindented_yaml_list(
    tmp_path: Path,
) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    module._check_pr_merged = lambda _pr: "merged"
    _write_task(
        vault,
        "closed",
        "valid-dep",
        status="done",
        body="## Acceptance criteria\n\n- [x] Evidence exists\n",
    )
    target = _write_task(
        vault,
        "active",
        "target",
        status="blocked",
        depends_on=["valid-dep"],
        depends_style="unindented",
    )

    assert module.cascade_unblock("valid-dep") == 1
    text = target.read_text(encoding="utf-8")
    assert "status: offered" in text
    assert "blocked_reason: null" in text


def test_cascade_preserves_blocked_with_current_evidence(tmp_path: Path) -> None:
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
        blocked_reason="minio_mirror_still_d_state",
        blocked_witness="~/.cache/hapax/witness/minio-d-state.json",
        depends_on=["valid-dep"],
    )

    assert module.cascade_unblock("valid-dep") == 0
    text = target.read_text(encoding="utf-8")
    assert "status: blocked" in text
    assert "blocked_reason: minio_mirror_still_d_state" in text
    assert "blocked_witness: ~/.cache/hapax/witness/minio-d-state.json" in text


def test_cascade_preserves_blocked_with_current_evidence_even_with_unmet_dependency(
    tmp_path: Path,
) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    module._check_pr_merged = lambda _pr: "merged"
    _write_task(
        vault,
        "closed",
        "invalid-dep",
        status="done",
        body="## Acceptance criteria\n\n- [ ] Evidence exists\n",
    )
    target = _write_task(
        vault,
        "active",
        "target",
        status="blocked",
        blocked_reason="minio_mirror_still_d_state",
        blocked_witness="~/.cache/hapax/witness/minio-d-state.json",
        depends_on=["invalid-dep"],
    )

    assert module.cascade_unblock() == 0
    text = target.read_text(encoding="utf-8")
    assert "status: blocked" in text
    assert "blocked_reason: minio_mirror_still_d_state" in text
    assert "blocked_witness: ~/.cache/hapax/witness/minio-d-state.json" in text
    assert "waiting_for_closure_valid_dependencies" not in text


def test_cascade_surfaces_precise_active_blocked_dependency(tmp_path: Path) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    module._check_pr_merged = lambda _pr: "merged"
    _write_task(
        vault,
        "active",
        "blocked-dep",
        status="blocked",
        blocked_reason="provider_budget_receipt_absent",
        blocked_witness="~/.cache/hapax/witness/provider-budget.json",
    )
    target = _write_task(
        vault,
        "active",
        "target",
        status="blocked",
        depends_on=["blocked-dep"],
    )

    assert module.cascade_unblock() == 0
    text = target.read_text(encoding="utf-8")
    assert "status: blocked" in text
    assert "blocked-dep (blocked_reason:provider_budget_receipt_absent" in text
    assert "blocked_witness:~/.cache/hapax/witness/provider-budget.json" in text


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

    assert module.cascade_unblock("false-dep") == 0
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

    assert module.cascade_unblock("open-pr-dep") == 0
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

    assert module.cascade_unblock("bad-route-dep") == 0
    text = target.read_text(encoding="utf-8")
    assert "status: blocked" in text
    assert "route_metadata:" in text


def test_close_triggered_cascade_does_not_validate_unrelated_closed_tasks(
    tmp_path: Path,
) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    checked_prs: list[str] = []

    def check_pr(pr_number: str) -> str:
        checked_prs.append(pr_number)
        if pr_number == "999":
            raise AssertionError("unrelated PR should not be checked")
        return "merged"

    module._check_pr_merged = check_pr
    _write_task(vault, "closed", "valid-dep", status="done", pr=123)
    _write_task(vault, "closed", "unrelated-dep", status="done", pr=999)
    target = _write_task(
        vault,
        "active",
        "target",
        status="blocked",
        depends_on=["valid-dep"],
    )

    assert module.cascade_unblock("valid-dep") == 1
    assert checked_prs == ["123"]
    assert "status: offered" in target.read_text(encoding="utf-8")


def test_cascade_withdraw_when_all_deps_nonfulfilling(tmp_path: Path) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    _write_task(vault, "active", "dep-a", status="withdrawn")
    _write_task(vault, "active", "dep-b", status="superseded")
    target = _write_task(
        vault,
        "active",
        "downstream",
        status="ready",
        depends_on=["dep-a", "dep-b"],
    )

    assert module.cascade_withdraw() == 1
    text = target.read_text(encoding="utf-8")
    assert "status: withdrawn" in text
    assert "all dependencies withdrawn/cancelled" in text


def test_cascade_withdraw_skips_mixed_deps(tmp_path: Path) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    _write_task(vault, "closed", "dep-done", status="done")
    _write_task(vault, "active", "dep-withdrawn", status="withdrawn")
    target = _write_task(
        vault,
        "active",
        "downstream",
        status="blocked",
        depends_on=["dep-done", "dep-withdrawn"],
    )

    assert module.cascade_withdraw() == 0
    assert "status: blocked" in target.read_text(encoding="utf-8")


def test_cascade_withdraw_skips_already_withdrawn(tmp_path: Path) -> None:
    module = _load_module()
    vault = _make_vault(tmp_path, module)
    _write_task(vault, "active", "dep-a", status="withdrawn")
    target = _write_task(
        vault,
        "active",
        "downstream",
        status="withdrawn",
        depends_on=["dep-a"],
    )

    assert module.cascade_withdraw() == 0
    assert "status: withdrawn" in target.read_text(encoding="utf-8")


def test_safe_read_text_tolerates_missing_file(tmp_path: Path) -> None:
    module = _load_module()
    missing = tmp_path / "gone.md"
    assert module._safe_read_text(missing) is None
    present = tmp_path / "here.md"
    present.write_text("hello", encoding="utf-8")
    assert module._safe_read_text(present) == "hello"


def test_blocked_candidates_survives_concurrent_close(tmp_path: Path, monkeypatch) -> None:
    """Regression: a note moved out of active/ mid-sweep must not crash.

    Reproduces the P0 failure where cc-close relocates active/*.md while the
    reconciler is iterating, yielding FileNotFoundError from read_text. The
    sweep must skip the vanished note and keep processing the rest.
    """
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
    vanishing = _write_task(
        vault, "active", "vanishing", status="blocked", depends_on=["valid-dep"]
    )
    survivor = _write_task(vault, "active", "survivor", status="blocked", depends_on=["valid-dep"])

    real_read_text = Path.read_text

    def racing_read_text(self: Path, *args, **kwargs):
        # Simulate cc-close moving the note to closed/ between glob and read.
        if self == vanishing and vanishing.exists():
            vanishing.unlink()
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", racing_read_text)

    # Must not raise FileNotFoundError; survivor still gets processed.
    assert module.cascade_unblock("valid-dep") == 1
    monkeypatch.undo()
    assert "status: offered" in survivor.read_text(encoding="utf-8")
    assert not vanishing.exists()
