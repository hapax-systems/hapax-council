"""PR-head selection of tests from the merge-group full-suite surface."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.ci_select_pytest_shard import (
    changed_paths_from_pr_base,
    main,
    select_affected_test_files,
)

if TYPE_CHECKING:
    import pytest

FULL = (
    "tests/scripts/test_hapax_methodology_dispatch.py",
    "tests/test_no_pass_invocations.py",
    "tests/ci/test_ci_affected_pytest.py",
    "tests/shared/test_unrelated.py",
)
ROOT = Path(__file__).resolve().parents[2]


def test_dispatch_default_selects_outside_diff_contract() -> None:
    selected = select_affected_test_files(("scripts/hapax-methodology-dispatch",), FULL)
    assert selected == {test: ("scripts/hapax-methodology-dispatch",) for test in FULL[:2]}


def test_moved_restore_script_selects_runtime_inventory_control() -> None:
    selected = select_affected_test_files(("scripts/hapax-cachyos-restore.sh",), FULL)
    assert selected == {"tests/test_no_pass_invocations.py": ("scripts/hapax-cachyos-restore.sh",)}


def test_direct_test_edit_and_rename_or_delete() -> None:
    assert select_affected_test_files((FULL[2],), FULL) == {FULL[2]: (FULL[2],)}
    assert select_affected_test_files(("tests/deleted.py",), FULL) == {
        test: ("tests/deleted.py",) for test in FULL
    }


def test_unknown_base_and_unmapped_source_fail_to_full_suite() -> None:
    assert select_affected_test_files(None, FULL) == {test: ("<unknown-base>",) for test in FULL}
    assert select_affected_test_files(("shared/unmapped.py",), FULL) == {
        test: ("shared/unmapped.py",) for test in FULL
    }


def test_docs_only_selects_none() -> None:
    assert select_affected_test_files(("docs/runbooks/example.md",), FULL) == {}
    assert select_affected_test_files(("docs/architecture/system-dynamics-map.svg",), FULL) == {
        test: ("docs/architecture/system-dynamics-map.svg",) for test in FULL
    }


def test_named_path_consumer_outside_fixed_contract_is_selected(tmp_path: Path) -> None:
    extra = "tests/test_extra_consumer.py"
    test = tmp_path / extra
    test.parent.mkdir()
    test.write_text("# exercises scripts/hapax-cachyos-restore.sh\n", encoding="utf-8")
    inventory = tmp_path / "tests/test_no_pass_invocations.py"
    inventory.write_text("# runtime inventory\n", encoding="utf-8")
    selected = select_affected_test_files(
        ("scripts/hapax-cachyos-restore.sh",),
        (extra, "tests/test_no_pass_invocations.py"),
        tmp_path,
    )
    assert set(selected) == {extra, "tests/test_no_pass_invocations.py"}


def test_pinned_diff_reports_both_sides_of_a_rename(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=tmp_path, check=True)
    old = tmp_path / "scripts/old.sh"
    old.parent.mkdir()
    old.write_text("#!/bin/sh\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    old.rename(tmp_path / "scripts/new.sh")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "rename"], cwd=tmp_path, check=True)

    assert changed_paths_from_pr_base(tmp_path, base) == (
        "scripts/new.sh",
        "scripts/old.sh",
    )
    assert changed_paths_from_pr_base(tmp_path, "missing") is None


def test_cli_logs_selected_test_and_changed_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=tmp_path, check=True)
    source = tmp_path / "scripts/hapax-methodology-dispatch"
    source.parent.mkdir()
    source.write_text("model=old\n", encoding="utf-8")
    for test in FULL:
        path = tmp_path / test
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    source.write_text("model=glm-5.2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "default changed"], cwd=tmp_path, check=True)
    collected = tmp_path / "collect.txt"
    collected.write_text("\n".join(f"{test}::test_fixture" for test in FULL), encoding="utf-8")
    weights = tmp_path / "weights.yaml"
    weights.write_text("files: {}\n", encoding="utf-8")
    assert (
        main(
            [
                "--collect-output",
                str(collected),
                "--weights",
                str(weights),
                "--shard",
                "1",
                "--shards",
                "1",
                "--affected-base-sha",
                base,
                "--repo-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert set(output.out.splitlines()) == set(FULL[:2])
    assert (
        "Affected full-suite test: tests/scripts/test_hapax_methodology_dispatch.py "
        "<= scripts/hapax-methodology-dispatch"
    ) in output.err
    assert (
        main(
            [
                "--collect-output",
                str(collected),
                "--weights",
                str(weights),
                "--shard",
                "1",
                "--shards",
                "2",
                "--affected-base-sha",
                base,
                "--repo-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    shard_output = capsys.readouterr()
    logged_tests = {
        line.split(" <= ", 1)[0].removeprefix("Affected full-suite test: ")
        for line in shard_output.err.splitlines()
        if line.startswith("Affected full-suite test: ")
    }
    assert logged_tests == set(shard_output.out.splitlines())


def test_workflow_aggregates_pr_shards_without_changing_merge_group_gate() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    shard = workflow.split("  test-full-shard:", 1)[1].split("\n  test-title-cards:", 1)[0]
    aggregate = workflow.split("  test:\n", 1)[1].split("\n  web-build:", 1)[0]
    assert "github.event_name == 'merge_group' || github.event_name == 'pull_request'" in shard
    assert "shard: [1, 2, 3, 4]" in shard
    assert '--affected-base-sha "$PR_BASE_SHA"' in shard
    assert "Verify PR-head affected full-suite shards" in aggregate
    assert "TEST_FULL_SHARD_RESULT: ${{ needs.test-full-shard.result }}" in aggregate


def test_preflight_names_hosted_equivalent_lint_commands() -> None:
    runbook = (ROOT / "docs/runbooks/pr-head-affected-full-suite.md").read_text(encoding="utf-8")
    assert (
        'uv run python scripts/check-unused-functions.py --diff-range "$PR_BASE_SHA..HEAD"'
        in runbook
    )
    assert "uv run python scripts/system_dynamics_map_materialize.py" in runbook
    assert (
        "git diff --quiet -- 'docs/architecture/system-dynamics-map*' 'schemas/system-dynamics-map'"
        in runbook
    )


def test_dispatch_default_ejection_specimen_red_then_green(tmp_path: Path) -> None:
    source = tmp_path / "scripts/hapax-methodology-dispatch"
    source.parent.mkdir()
    source.write_text("model=glm-5.2\n", encoding="utf-8")
    test = tmp_path / "tests/scripts/test_hapax_methodology_dispatch.py"
    test.parent.mkdir(parents=True)
    stale = (
        "from pathlib import Path\n"
        "def test_default_model():\n"
        "    assert 'model=glm-5.3' in Path('scripts/hapax-methodology-dispatch').read_text()\n"
    )
    test.write_text(stale, encoding="utf-8")
    selected = select_affected_test_files(
        ("scripts/hapax-methodology-dispatch",),
        ("tests/scripts/test_hapax_methodology_dispatch.py",),
        tmp_path,
    )
    assert tuple(selected) == ("tests/scripts/test_hapax_methodology_dispatch.py",)
    red = subprocess.run(["pytest", *selected, "-q"], cwd=tmp_path, capture_output=True)
    assert red.returncode == 1
    test.write_text(
        stale.replace("glm-5.3", "glm-5.2") + "# assertion repaired\n", encoding="utf-8"
    )
    green = subprocess.run(["pytest", *selected, "-q"], cwd=tmp_path, capture_output=True)
    assert green.returncode == 0


def test_restore_move_ejection_specimen_red_then_green(tmp_path: Path) -> None:
    source = tmp_path / "scripts/hapax-cachyos-restore.sh"
    source.parent.mkdir()
    source.write_text("pass show backup\n", encoding="utf-8")
    test = tmp_path / "tests/test_no_pass_invocations.py"
    test.parent.mkdir()
    test.write_text(
        "from pathlib import Path\n"
        "def test_no_pass_invocations():\n"
        "    assert 'pass show' not in Path('scripts/hapax-cachyos-restore.sh').read_text()\n",
        encoding="utf-8",
    )
    selected = select_affected_test_files(
        ("scripts/hapax-cachyos-restore.sh",), ("tests/test_no_pass_invocations.py",), tmp_path
    )
    assert tuple(selected) == ("tests/test_no_pass_invocations.py",)
    red = subprocess.run(["pytest", *selected, "-q"], cwd=tmp_path, capture_output=True)
    assert red.returncode == 1
    source.write_text("hapax-secret show backup\n", encoding="utf-8")
    green = subprocess.run(["pytest", *selected, "-q"], cwd=tmp_path, capture_output=True)
    assert green.returncode == 0
