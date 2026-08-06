from __future__ import annotations

import ast
from pathlib import Path

import hapax_agentic_trust

PACKAGE_ROOT = Path(__file__).parents[1]
SOURCE_ROOT = PACKAGE_ROOT / "src" / "hapax_agentic_trust"
REPO_ROOT = PACKAGE_ROOT.parents[1]


def test_root_api_is_exactly_read_only_evidence_surface() -> None:
    assert hapax_agentic_trust.__all__ == [
        "AgenticRunGraph",
        "AgenticRunSummary",
        "AgenticTrustEvidenceReceiptV1",
        "AgenticTrustIntegerFactsV1",
        "AgenticTrustVerificationError",
        "DEFAULT_VERIFICATION_LIMITS",
        "TechnicalTelemetryV1",
        "VerificationLimits",
        "VerifiedTerminalProjection",
        "verify_terminal_projection",
    ]


def test_production_package_uses_exact_read_only_import_and_io_allowlist() -> None:
    allowed_import_roots = {
        "__future__",
        "_receipt_chain",
        "base64",
        "binascii",
        "collections",
        "contract",
        "custody",
        "dataclasses",
        "datetime",
        "enum",
        "evidence_receipt",
        "errors",
        "hashlib",
        "json",
        "limits",
        "math",
        "os",
        "pathlib",
        "re",
        "run_graph",
        "stat",
        "terminal",
        "types",
        "typing",
    }
    allowed_os_calls = {"close", "dup", "fstat", "open", "read", "stat"}
    forbidden_defs = {
        "append",
        "build_terminal_bundle",
        "capture_evidence",
        "launch",
        "prepare_receipt_chain",
        "publish_terminal_bundle",
        "send",
    }
    forbidden_builtin_calls = {"__import__", "compile", "eval", "exec", "open"}
    forbidden_path_calls = {
        "chmod",
        "hardlink_to",
        "mkdir",
        "rename",
        "replace",
        "symlink_to",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
    violations: list[str] = []
    open_call_count = 0

    def contains_os_flag(node: ast.AST, flag: str) -> bool:
        return any(
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "os"
            and child.attr == flag
            for child in ast.walk(node)
        )

    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        read_only_flag_names = {
            target.id
            for assignment in ast.walk(tree)
            if isinstance(assignment, ast.Assign) and contains_os_flag(assignment.value, "O_RDONLY")
            for target in assignment.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in forbidden_defs:
                    violations.append(f"{path.name}: def {node.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] not in allowed_import_roots:
                        violations.append(f"{path.name}: unlisted import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".", 1)[0] not in allowed_import_roots:
                    violations.append(f"{path.name}: unlisted import from {node.module}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                if node.func.attr not in allowed_os_calls:
                    violations.append(f"{path.name}: unlisted os.{node.func.attr}")
                if node.func.attr == "open":
                    open_call_count += 1
                    flags = node.args[1] if len(node.args) > 1 else None
                    is_read_only = flags is not None and (
                        contains_os_flag(flags, "O_RDONLY")
                        or isinstance(flags, ast.Name)
                        and flags.id in read_only_flag_names
                    )
                    if not is_read_only:
                        violations.append(f"{path.name}: os.open without proven O_RDONLY flags")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in forbidden_builtin_calls:
                    violations.append(f"{path.name}: builtin {node.func.id}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_path_calls
            ):
                violations.append(f"{path.name}: mutation method {node.func.attr}")
    source = "\n".join(path.read_text(encoding="utf-8") for path in SOURCE_ROOT.rglob("*.py"))
    for forbidden_flag in ("O_APPEND", "O_CREAT", "O_EXCL", "O_RDWR", "O_TRUNC", "O_WRONLY"):
        if f"os.{forbidden_flag}" in source:
            violations.append(f"forbidden os.open flag {forbidden_flag}")
    assert open_call_count == 6
    assert violations == []


def test_package_has_no_implicit_observer_or_dispatch_delta_channel() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in SOURCE_ROOT.rglob("*.py"))
    assert "HAPAX_CAPABILITY_SURFACE_DELTA_FILE" not in source
    assert "CapabilityAdapter" not in source
    assert "WorkerAdapter" not in source
    assert "dispatcher" not in source.lower()
    assert "watcher" not in source.lower()


def test_no_var_tmp_runtime_dependency() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in SOURCE_ROOT.rglob("*.py"))
    assert "/var/tmp" not in source


def test_no_console_script_or_root_runtime_dependency() -> None:
    pyproject = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" not in pyproject
    root_pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "hapax-agentic-trust" not in root_pyproject
