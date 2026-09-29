from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check-unused-functions.py"


def load_gate_module():
    spec = importlib.util.spec_from_file_location("check_unused_functions", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_vulture_output_keeps_callable_findings_only() -> None:
    gate = load_gate_module()

    output = "\n".join(
        [
            "agents/example.py:10: unused function 'helper' (60% confidence)",
            "agents/example.py:20: unused method 'build' (60% confidence)",
            "agents/example.py:30: unused class 'Plugin' (60% confidence)",
            "agents/example.py:40: unused property 'ready' (60% confidence)",
            "agents/example.py:50: unused variable 'count' (100% confidence)",
            "agents/example.py:60: unreachable code after 'return' (100% confidence)",
        ]
    )

    findings = gate.parse_vulture_output(output)

    assert [finding.kind for finding in findings] == ["function", "method", "class", "property"]
    assert [finding.name for finding in findings] == ["helper", "build", "Plugin", "ready"]


def test_parse_changed_lines_reads_zero_context_git_diff() -> None:
    gate = load_gate_module()

    diff_text = "\n".join(
        [
            "diff --git a/agents/example.py b/agents/example.py",
            "--- a/agents/example.py",
            "+++ b/agents/example.py",
            "@@ -4,0 +5,3 @@",
            "+def helper():",
            "+    return 1",
            "+",
            "@@ -20 +23,2 @@",
            "-old = 1",
            "+new = 2",
            "+other = 3",
        ]
    )

    changed = gate.parse_changed_lines(diff_text)

    assert changed[Path("agents/example.py")] == {5, 6, 7, 23, 24}


def test_findings_on_changed_lines_selects_definition_line_only() -> None:
    gate = load_gate_module()
    findings = [
        gate.Finding(
            path=Path("agents/example.py"),
            line=10,
            kind="function",
            name="new_helper",
            confidence=60,
            raw="agents/example.py:10: unused function 'new_helper' (60% confidence)",
        ),
        gate.Finding(
            path=Path("agents/example.py"),
            line=30,
            kind="function",
            name="legacy_helper",
            confidence=60,
            raw="agents/example.py:30: unused function 'legacy_helper' (60% confidence)",
        ),
    ]

    active = gate.findings_on_changed_lines(findings, {Path("agents/example.py"): {10, 11}})

    assert active == [findings[0]]


def test_vulture_unions_central_and_sorted_module_fragments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = load_gate_module()
    central = tmp_path / "vulture_whitelist.py"
    central.write_text("# legacy\n")
    fragment_dir = tmp_path / "vulture_whitelist.d"
    fragment_dir.mkdir()
    (fragment_dir / "z.py").write_text("# z\n")
    (fragment_dir / "a.py").write_text("# a\n")
    (fragment_dir / "ignore.txt").write_text("# ignored\n")
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "")

    monkeypatch.setattr(gate, "run_command", fake_run)
    assert gate.run_vulture(["shared"], gate.whitelist_paths(central), 60) == []
    assert commands == [
        [
            sys.executable,
            "-m",
            "vulture",
            "shared",
            str(central),
            str(fragment_dir / "a.py"),
            str(fragment_dir / "z.py"),
            "--min-confidence",
            "60",
        ]
    ]


def test_fragment_migration_preserves_the_vulture_finding_set(tmp_path: Path) -> None:
    gate = load_gate_module()
    source = tmp_path / "module.py"
    source.write_text("def dynamic_entry():\n    return 1\n")
    central = tmp_path / "vulture_whitelist.py"
    central.write_text("from module import dynamic_entry\ndynamic_entry\n")
    before = gate.run_vulture([str(source)], [central], 60)
    assert before == []

    central.write_text("# existing central entries stay here\n")
    fragment = tmp_path / "vulture_whitelist.d" / "module.py"
    fragment.parent.mkdir()
    fragment.write_text(
        "# dynamic caller: module registry\nfrom module import dynamic_entry\ndynamic_entry\n"
    )
    after = gate.run_vulture([str(source)], gate.whitelist_paths(central), 60)
    assert after == before


def test_migrated_whitelist_entries_match_pre_migration_text() -> None:
    """Pin the full entry set; Vulture findings can hide a dropped or broadened reference."""
    gate = load_gate_module()
    central = SCRIPT_PATH.parent / "vulture_whitelist.py"
    entries = {
        stripped
        for path in gate.whitelist_paths(central)
        for line in path.read_text().splitlines()
        if (stripped := line.strip())
        and not stripped.startswith("#")
        and not (stripped.startswith('"""') and stripped.endswith('"""'))
    }
    # SHA-256 of sorted, nonblank, noncomment text lines in the pre-migration
    # d081137ae:scripts/vulture_whitelist.py. The fragment's module docstring
    # is ignored; all import and reference lines remain in the comparison.
    digest = hashlib.sha256("\n".join(sorted(entries)).encode()).hexdigest()
    expected = "0f9705c35a3481d9c0768174683dd4345ebe0de8edc2238e858364b86dbfaeb2"  # pragma: allowlist secret
    assert digest == expected

    migrated = {
        "_EmaTrend.unobserved,",
        "_ema_parse_catalogue,",
        "_ema_parse_ledger,",
        "_ema_render_flag_drop,",
        "_ema_render_pile_status,",
        "_ema_render_reduction_row,",
        "_ema_split_frontmatter,",
    }
    assert migrated <= entries
