from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci_select_pytest_shard import (
    RuntimeWeightConfig,
    build_shard_plan,
    build_shard_plan_from_collect,
    load_runtime_weight_config,
    load_runtime_weights,
    main,
    parse_collect_output,
    selected_paths,
)


def test_parse_collect_output_counts_tests_by_file() -> None:
    collected = "\n".join(
        [
            "noise from pytest",
            "tests/a/test_alpha.py::test_one",
            "tests/a/test_alpha.py::TestAlpha::test_two",
            "tests/b/test_beta.py::test_three[param]",
            "3 tests collected",
        ]
    )

    assert parse_collect_output(collected) == {
        "tests/a/test_alpha.py": 2,
        "tests/b/test_beta.py": 1,
    }


def test_runtime_weight_overrides_collected_count_and_isolates_slow_file() -> None:
    plan = build_shard_plan(
        {
            "tests/slow.py": 1,
            "tests/a.py": 6,
            "tests/b.py": 6,
            "tests/c.py": 6,
        },
        {"tests/slow.py": 20},
        shard_count=2,
    )

    assert selected_paths(plan, 1) == ["tests/slow.py"]
    assert selected_paths(plan, 2) == ["tests/a.py", "tests/b.py", "tests/c.py"]
    assert [summary.load for summary in plan] == [20, 18]


def test_unknown_files_fall_back_to_collected_test_count() -> None:
    plan = build_shard_plan(
        {
            "tests/a.py": 3,
            "tests/b.py": 2,
            "tests/c.py": 1,
        },
        {},
        shard_count=2,
    )

    assert [summary.load for summary in plan] == [3, 3]
    assert selected_paths(plan, 1) == ["tests/a.py"]
    assert selected_paths(plan, 2) == ["tests/b.py", "tests/c.py"]


def test_equal_weights_are_ordered_lexically_for_determinism() -> None:
    plan = build_shard_plan(
        {
            "tests/b.py": 2,
            "tests/a.py": 2,
        },
        {},
        shard_count=2,
    )

    assert selected_paths(plan, 1) == ["tests/a.py"]
    assert selected_paths(plan, 2) == ["tests/b.py"]


def test_configured_split_groups_are_selected_as_node_prefix_units() -> None:
    collected = "\n".join(
        [
            "tests/slow.py::TestSlowA::test_one",
            "tests/slow.py::TestSlowA::test_two",
            "tests/slow.py::TestSlowB::test_one",
            "tests/other.py::test_one",
            "tests/other.py::test_two",
        ]
    )
    runtime_config = RuntimeWeightConfig(
        file_weights={"tests/slow.py": 99},
        split_weights={
            "tests/slow.py::TestSlowA": 9,
            "tests/slow.py::TestSlowB": 8,
        },
    )

    plan = build_shard_plan_from_collect(collected, runtime_config, shard_count=2)
    all_selected = selected_paths(plan, 1) + selected_paths(plan, 2)

    assert selected_paths(plan, 1) == ["tests/slow.py::TestSlowA"]
    assert selected_paths(plan, 2) == ["tests/slow.py::TestSlowB", "tests/other.py"]
    assert "tests/slow.py" not in all_selected
    assert [summary.load for summary in plan] == [9, 10]


def test_unsplit_nodes_from_partially_split_file_use_exact_nodeid_not_whole_file() -> None:
    collected = "\n".join(
        [
            "tests/slow.py::TestSlowA::test_one",
            "tests/slow.py::TestNewClass::test_new_path",
        ]
    )
    runtime_config = RuntimeWeightConfig(
        file_weights={"tests/slow.py": 99},
        split_weights={"tests/slow.py::TestSlowA": 9},
    )

    plan = build_shard_plan_from_collect(collected, runtime_config, shard_count=2)
    all_selected = selected_paths(plan, 1) + selected_paths(plan, 2)

    assert "tests/slow.py::TestSlowA" in all_selected
    assert "tests/slow.py::TestNewClass::test_new_path" in all_selected
    assert "tests/slow.py" not in all_selected


def test_load_runtime_weights_accepts_explicit_weight_alias(tmp_path: Path) -> None:
    weights_path = tmp_path / "weights.yaml"
    weights_path.write_text(
        "\n".join(
            [
                "files:",
                "  tests/a.py:",
                "    collected_test_equivalent_weight: 42",
                "  tests/b.py:",
                "    weight: 3.5",
                "split_groups:",
                "  tests/a.py::TestA:",
                "    collected_test_equivalent_weight: 11",
            ]
        ),
        encoding="utf-8",
    )

    runtime_config = load_runtime_weight_config(weights_path)
    assert load_runtime_weights(weights_path) == {"tests/a.py": 42.0, "tests/b.py": 3.5}
    assert runtime_config.file_weights == {"tests/a.py": 42.0, "tests/b.py": 3.5}
    assert runtime_config.split_weights == {"tests/a.py::TestA": 11.0}


def test_load_runtime_weights_rejects_missing_numeric_weight(tmp_path: Path) -> None:
    weights_path = tmp_path / "weights.yaml"
    weights_path.write_text("files:\n  tests/a.py:\n    note: missing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="collected_test_equivalent_weight"):
        load_runtime_weights(weights_path)


def test_cli_prints_selected_files_and_runtime_weight_plan(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collect_output = tmp_path / "collect.txt"
    weights = tmp_path / "weights.yaml"
    collect_output.write_text(
        "\n".join(
            [
                "tests/slow.py::test_one",
                "tests/a.py::test_one",
                "tests/a.py::test_two",
                "tests/b.py::test_one",
                "tests/b.py::test_two",
            ]
        ),
        encoding="utf-8",
    )
    weights.write_text(
        "files:\n  tests/slow.py:\n    collected_test_equivalent_weight: 10\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--collect-output",
            str(collect_output),
            "--weights",
            str(weights),
            "--shard",
            "1",
            "--shards",
            "2",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "tests/slow.py\n"
    assert "Shard plan by runtime weight: 1=10-weight/1-units 2=4-weight/2-units" in (captured.err)
