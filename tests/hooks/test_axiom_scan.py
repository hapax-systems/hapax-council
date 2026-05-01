"""Tests for hooks/scripts/axiom-scan.sh.

The hook is a PreToolUse blocker for T0 axiom violations. The pattern
set lives in axiom-patterns.sh; the hook reads stdin JSON, extracts
file content from any of the four tool-input shapes
(Edit/Write/MultiEdit/NotebookEdit), strips comments to avoid prose
false-positives, and either exits 2 (block) with a recovery hint or
exits 0 (allow).

Source-byte hygiene: every fixture is constructed at runtime via the
``_t(...)`` helper so this file's bytes never literally contain a
banned pattern. The hook also exempts ``tests/hooks/test_axiom_scan.py``
via the file-path block, but constructing fixtures at runtime keeps
the source clean against the broader scans used by other tools too.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "axiom-scan.sh"


def _t(*parts: str) -> str:
    """Concatenate token fragments at runtime.

    Splitting tokens like ('cl', 'ass') and ('def ', 'authenticate_user')
    keeps banned regex matches out of this file's bytes while letting
    the resulting fixtures still trigger the hook on stdin.
    """
    return "".join(parts)


def _run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _edit(content: str, *, file_path: str = "src/foo.py") -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "new_string": content},
    }


def _write(content: str, *, file_path: str = "src/foo.py") -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def _multi_edit(strings: list[str], *, file_path: str = "src/foo.py") -> dict:
    return {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": file_path,
            "edits": [{"new_string": s} for s in strings],
        },
    }


def _notebook_edit(content: str, *, notebook_path: str = "x.ipynb") -> dict:
    return {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": notebook_path, "new_source": content},
    }


# Fixture builders, all runtime-constructed.

CLASS_KW = ("cl", "ass ")


def _cls_block(name: str) -> str:
    """Return a triggering source block: 'class <name>:\\n    pass\\n'."""
    return _t(*CLASS_KW, name, ":\n    pass\n")


def _cls_inline(name: str, suffix: str = " ...") -> str:
    """Return a triggering one-liner: 'class <name>...'."""
    return _t(*CLASS_KW, name, suffix)


def _authenticate_user_def() -> str:
    return _t("def ", "authenticate", "_user(creds): pass\n")


def _generate_feedback_def() -> str:
    return _t("def ", "generate", "_feedback(report): ...\n")


def _django_auth_import() -> str:
    return _t("from ", "django.contrib.auth import authenticate\n")


# Empty-input fast paths


class TestEmptyInput:
    def test_empty_json_object_exits_zero(self) -> None:
        result = _run({})
        assert result.returncode == 0

    def test_no_content_exits_zero(self) -> None:
        result = _run(_edit(""))
        assert result.returncode == 0

    def test_unrecognized_tool_input_shape_exits_zero(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {"command": "echo hi"}})
        assert result.returncode == 0


# Self-exemption: pattern files themselves


class TestPatternFileExemption:
    def test_axiom_patterns_sh_self_exempt(self) -> None:
        result = _run(_edit(_cls_block("UserManager"), file_path="hooks/scripts/axiom-patterns.sh"))
        assert result.returncode == 0

    def test_axiom_scan_sh_self_exempt(self) -> None:
        result = _run(_edit(_cls_block("UserService"), file_path="hooks/scripts/axiom-scan.sh"))
        assert result.returncode == 0

    def test_axiom_commit_scan_sh_self_exempt(self) -> None:
        result = _run(
            _edit(_cls_block("AuthManager"), file_path="hooks/scripts/axiom-commit-scan.sh")
        )
        assert result.returncode == 0

    def test_test_files_self_exempt(self) -> None:
        result = _run(_edit(_cls_block("AuthManager"), file_path="tests/hooks/test_axiom_scan.py"))
        assert result.returncode == 0


# Doc files skip class patterns


class TestDocFileExemption:
    def test_md_class_pattern_allowed(self) -> None:
        result = _run(_edit(_cls_inline("UserManager"), file_path="docs/foo.md"))
        assert result.returncode == 0, result.stderr

    def test_md_function_pattern_still_blocks(self) -> None:
        result = _run(_edit(_authenticate_user_def(), file_path="docs/foo.md"))
        assert result.returncode == 2
        assert "Axiom violation" in result.stderr

    def test_txt_rst_adoc_also_exempted(self) -> None:
        for ext in ("txt", "rst", "adoc"):
            result = _run(_edit(_cls_inline("UserService"), file_path=f"foo.{ext}"))
            assert result.returncode == 0


# Code files: class-pattern blocks


class TestSingleUserDomain:
    def test_user_manager_class_blocks(self) -> None:
        result = _run(_write(_cls_block("UserManager")))
        assert result.returncode == 2
        assert "single_user" in result.stderr

    def test_auth_manager_class_blocks(self) -> None:
        result = _run(_write(_cls_block("AuthManager")))
        assert result.returncode == 2
        assert "single_user" in result.stderr

    def test_role_manager_class_blocks(self) -> None:
        result = _run(_write(_cls_block("RoleManager")))
        assert result.returncode == 2
        assert "single_user" in result.stderr

    def test_authenticate_user_function_blocks(self) -> None:
        result = _run(_write(_authenticate_user_def()))
        assert result.returncode == 2
        assert "single_user" in result.stderr

    def test_django_auth_import_blocks(self) -> None:
        result = _run(_write(_django_auth_import()))
        assert result.returncode == 2
        assert "single_user" in result.stderr

    def test_multi_tenant_class_blocks(self) -> None:
        result = _run(_write(_cls_block("MultiTenant")))
        assert result.returncode == 2
        assert "single_user" in result.stderr


class TestManagementGovernanceDomain:
    def test_generate_feedback_blocks(self) -> None:
        result = _run(_write(_generate_feedback_def()))
        assert result.returncode == 2
        assert "management_governance" in result.stderr
        assert "mg-boundary" in result.stderr

    def test_feedback_generator_class_blocks(self) -> None:
        result = _run(_write(_cls_block("FeedbackGenerator")))
        assert result.returncode == 2
        assert "management_governance" in result.stderr

    def test_coaching_recommender_class_blocks(self) -> None:
        result = _run(_write(_cls_block("CoachingRecommender")))
        assert result.returncode == 2
        assert "management_governance" in result.stderr


# Comment stripping prevents false positives


class TestCommentStripping:
    def test_python_full_line_comment_stripped(self) -> None:
        body = _t("# ", _cls_inline("UserManager", " removed"), "\nx = 1\n")
        result = _run(_write(body))
        assert result.returncode == 0, result.stderr

    def test_python_inline_comment_stripped(self) -> None:
        body = _t("x = 1  # ", _cls_inline("UserManager", " removed"), "\n")
        result = _run(_write(body))
        assert result.returncode == 0, result.stderr

    def test_c_double_slash_comment_stripped(self) -> None:
        body = _t("// ", _cls_inline("UserManager", " removed"), "\nint x = 1;\n")
        result = _run(_write(body))
        assert result.returncode == 0, result.stderr

    def test_html_comment_stripped(self) -> None:
        body = _t("<!-- ", _cls_inline("UserManager"), " -->")
        result = _run(_edit(body, file_path="page.html"))
        assert result.returncode == 0, result.stderr


# Recovery hint sub-categorization


class TestRecoveryHints:
    def test_auth_pattern_yields_auth_recovery(self) -> None:
        result = _run(_write(_cls_block("AuthManager")))
        assert result.returncode == 2
        assert (
            "Remove auth/permission/role code" in result.stderr
            or "single user is always authorized" in result.stderr
        )

    def test_tenant_pattern_yields_tenant_recovery(self) -> None:
        result = _run(_write(_cls_block("TenantManager")))
        assert result.returncode == 2
        assert (
            "Remove user/tenant abstraction" in result.stderr
            or "There is exactly one user" in result.stderr
        )


# Tool-input shape coverage


class TestToolInputShapes:
    def test_edit_new_string_scanned(self) -> None:
        result = _run(_edit(_cls_inline("UserManager")))
        assert result.returncode == 2

    def test_write_content_scanned(self) -> None:
        result = _run(_write(_cls_inline("UserManager")))
        assert result.returncode == 2

    def test_multi_edit_edits_scanned(self) -> None:
        result = _run(_multi_edit(["x = 1", _cls_inline("UserManager")]))
        assert result.returncode == 2

    def test_notebook_edit_new_source_scanned(self) -> None:
        result = _run(_notebook_edit(_cls_inline("UserManager")))
        assert result.returncode == 2
