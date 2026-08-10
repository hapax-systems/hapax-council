from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


def test_extensionless_python_entrypoints_are_scanned(tmp_path: Path) -> None:
    """The estate keeps 146 Python entrypoints in scripts/ with no extension.

    Vulture's directory walk collects *.py only, so a helper called exclusively from one of
    them used to read as unused — and the documented remedy (a vulture_whitelist.py entry)
    would suppress that symbol name everywhere, permanently, rather than let the scanner read
    the caller. This pins that such files are handed to vulture explicitly.
    """
    gate = load_gate_module()

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    entrypoint = scripts / "cc-example-tool"
    entrypoint.write_text("#!/usr/bin/env python3\nfrom shared.x import helper\nhelper()\n")
    (scripts / "already-scanned.py").write_text("helper()\n")
    (scripts / "run-example.sh").write_text("#!/usr/bin/env bash\necho hi\n")
    (scripts / "README").write_text("not a program\n")

    found = gate.extensionless_python_files([str(scripts)])

    assert found == [str(entrypoint)], "only the extensionless Python entrypoint is added"


def test_helper_called_only_from_extensionless_script_is_not_reported(tmp_path: Path) -> None:
    """The end-to-end invariant, not just the file-list helper.

    This is the exact shape that failed CI on 2026-08-09: `latest_rollout_observation` in
    shared/ was called only from scripts/hapax-platform-capability-receipts, and the gate
    reported it unused.
    """
    gate = load_gate_module()

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "helper_module.py").write_text(
        "def only_called_from_an_entrypoint() -> int:\n    return 1\n"
    )

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "cc-example-tool").write_text(
        "#!/usr/bin/env python3\n"
        "from shared.helper_module import only_called_from_an_entrypoint\n"
        "only_called_from_an_entrypoint()\n"
    )
    whitelist = scripts / "vulture_whitelist.py"
    whitelist.write_text("")

    findings = gate.run_vulture([str(shared), str(scripts)], whitelist, 60)

    assert not [f for f in findings if f.name == "only_called_from_an_entrypoint"], (
        "a helper whose only caller is an extensionless entrypoint must not read as unused"
    )
