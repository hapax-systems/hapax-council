"""Integration tests for axiom hook scripts.

Tests axiom-scan.sh (PreToolUse) and axiom-commit-scan.sh (PreToolUse/Bash)
with Claude Code's JSON input format.
"""
import json
import subprocess
from pathlib import Path

import pytest

from shared.config import HAPAX_SYSTEM_DIR
HOOKS_DIR = HAPAX_SYSTEM_DIR / "hooks" / "scripts"
AXIOM_SCAN = HOOKS_DIR / "axiom-scan.sh"
AXIOM_COMMIT_SCAN = HOOKS_DIR / "axiom-commit-scan.sh"

pytestmark = pytest.mark.skipif(
    not AXIOM_SCAN.exists(),
    reason="hapax-system hooks not installed",
)


def _run_hook(script: Path, tool_input: dict, tool_name: str = "Write") -> subprocess.CompletedProcess:
    """Run a hook script with simulated Claude Code JSON input."""
    payload = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": "test-session",
    }
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=10,
    )


class TestAxiomScan:
    """Tests for axiom-scan.sh — PreToolUse blocker."""

    def test_blocks_user_manager_class(self):
        """Write with class UserManager should be blocked (exit 2)."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
            "content": "class UserManager:\n    pass\n",
        })
        assert result.returncode == 2
        assert b"Axiom violation" in result.stderr

    def test_blocks_auth_import(self):
        """Write with django auth import should be blocked."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
            "content": "from django.contrib.auth import authenticate\n",
        })
        assert result.returncode == 2

    def test_blocks_multi_tenant_class(self):
        """Write with MultiTenant class should be blocked."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
            "content": "class MultiTenantConfig:\n    pass\n",
        })
        assert result.returncode == 2

    def test_allows_safe_content(self):
        """Write with normal code should pass (exit 0)."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
            "content": "def process_data():\n    return 42\n",
        })
        assert result.returncode == 0

    def test_allows_empty_content(self):
        """Write with no content should pass."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
        })
        assert result.returncode == 0

    def test_edit_new_string_format(self):
        """Edit tool uses new_string field, not content."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
            "new_string": "class AuthManager:\n    pass\n",
            "old_string": "pass\n",
        }, tool_name="Edit")
        assert result.returncode == 2

    def test_edit_safe_content(self):
        """Edit with safe new_string should pass."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
            "new_string": "def run():\n    pass\n",
            "old_string": "pass\n",
        }, tool_name="Edit")
        assert result.returncode == 0

    def test_recovery_hint_for_auth_violation(self):
        """Blocked auth pattern should include recovery guidance."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
            "content": "class AuthManager:\n    pass\n",
        })
        assert result.returncode == 2
        assert b"Recovery:" in result.stderr

    def test_recovery_hint_for_mgmt_violation(self):
        """Blocked management governance pattern should include recovery guidance."""
        result = _run_hook(AXIOM_SCAN, {
            "file_path": "/tmp/test.py",
            "content": "class FeedbackGenerator:\n    pass\n",
        })
        assert result.returncode == 2
        assert b"Recovery:" in result.stderr
        assert b"management_governance" in result.stderr


class TestAxiomCommitScan:
    """Tests for axiom-commit-scan.sh — Bash tool hook."""

    def test_ignores_non_git_commands(self):
        """Non-git commands should pass through (exit 0)."""
        result = _run_hook(AXIOM_COMMIT_SCAN, {
            "command": "echo hello",
        }, tool_name="Bash")
        assert result.returncode == 0

    def test_ignores_git_status(self):
        """git status is not a commit/push, should pass."""
        result = _run_hook(AXIOM_COMMIT_SCAN, {
            "command": "git status",
        }, tool_name="Bash")
        assert result.returncode == 0

    def test_ignores_empty_command(self):
        """Empty command should pass."""
        result = _run_hook(AXIOM_COMMIT_SCAN, {}, tool_name="Bash")
        assert result.returncode == 0

    def test_recovery_hint_in_commit_scan(self):
        """Commit scan script should contain recovery hint output."""
        script = HOOKS_DIR / "axiom-commit-scan.sh"
        content = script.read_text()
        assert 'echo "Recovery: $RECOVERY"' in content

    def test_detects_sed_i_with_violation(self):
        """sed -i writing auth patterns should be caught."""
        result = _run_hook(AXIOM_COMMIT_SCAN, {
            "command": "sed -i 's/pass/class User" + "Manager:\n    pass/' /tmp/test.py",
        }, tool_name="Bash")
        assert result.returncode == 2
        assert b"Axiom violation" in result.stderr

    def test_detects_python_c_with_violation(self):
        """python -c writing auth patterns should be caught."""
        result = _run_hook(AXIOM_COMMIT_SCAN, {
            "command": "python -c \"open('/tmp/test.py','w').write('class Auth" + "Service:\n    pass')\"",
        }, tool_name="Bash")
        assert result.returncode == 2

    def test_allows_safe_sed(self):
        """sed -i with safe content should pass."""
        result = _run_hook(AXIOM_COMMIT_SCAN, {
            "command": "sed -i 's/old/new/' /tmp/test.py",
        }, tool_name="Bash")
        assert result.returncode == 0

    def test_allows_safe_redirect(self):
        """echo redirect with safe content should pass."""
        result = _run_hook(AXIOM_COMMIT_SCAN, {
            "command": "echo 'hello world' > /tmp/test.txt",
        }, tool_name="Bash")
        assert result.returncode == 0

    def test_curl_localhost_passes(self):
        """curl to localhost should pass without warning."""
        result = _run_hook(AXIOM_COMMIT_SCAN, {
            "command": "curl http://localhost:4000/v1/models",
        }, tool_name="Bash")
        assert result.returncode == 0
        assert b"corporate_boundary" not in result.stderr

    def test_curl_external_warns_in_corporate_context(self):
        """curl to external URL with .corporate-boundary marker should produce advisory."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = Path(tmpdir) / ".corporate-boundary"
            marker.touch()
            result = subprocess.run(
                ["bash", str(AXIOM_COMMIT_SCAN)],
                input=json.dumps({
                    "tool_name": "Bash",
                    "tool_input": {"command": "curl https://api.example.com/data"},
                    "session_id": "test",
                }).encode(),
                capture_output=True,
                timeout=10,
                cwd=tmpdir,
            )
        # Advisory only — still exit 0
        assert result.returncode == 0
        # Should have advisory in stderr when corporate-boundary marker exists
        assert b"corporate_boundary" in result.stderr

