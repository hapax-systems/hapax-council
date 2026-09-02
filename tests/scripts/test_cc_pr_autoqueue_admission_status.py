"""The admission-status cap must be reported as a named, terminal condition.

GitHub caps commit statuses per (SHA, context) and will not delete them, so a head SHA
that reaches the cap can never carry a fresh admission proof again. That is categorically
different from a transient write failure: it does not self-heal, and the only recovery is
a new head SHA, which invalidates the review dossier. It was folded into a generic write
error between 2026-06-04 and 2026-08-22 and nobody saw it recur.
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cc-pr-autoqueue.py"
_loader = SourceFileLoader("cc_pr_autoqueue", str(_SCRIPT))
_spec = importlib.util.spec_from_loader("cc_pr_autoqueue", _loader)
assert _spec is not None
autoqueue = importlib.util.module_from_spec(_spec)
# @dataclass resolves its own module via sys.modules during class creation, so the module
# must be registered before exec_module or every dataclass in the script raises.
sys.modules["cc_pr_autoqueue"] = autoqueue
_loader.exec_module(autoqueue)


CAP_422 = (
    '{"message":"Validation Failed","errors":"Validation failed: This SHA and context '
    'has reached the maximum number of statuses.","status":"422"}'
)


def test_cap_exhaustion_is_recognised():
    assert autoqueue._is_status_cap_exhausted(CAP_422) is True


def test_cap_detection_is_case_insensitive():
    assert autoqueue._is_status_cap_exhausted(CAP_422.upper()) is True


def test_ordinary_write_failures_are_not_cap_exhaustion():
    """The negative direction: unrelated failures must not be labelled terminal."""
    for other in (
        '{"message":"Not Found","status":"404"}',
        '{"message":"Bad credentials","status":"401"}',
        '{"message":"Validation Failed","errors":"state is not included in the list"}',
        "",
        "status write failed rc=1",
    ):
        assert autoqueue._is_status_cap_exhausted(other) is False, other


def test_reason_constant_is_stable():
    """The reason is a contract with downstream consumers; changing it is a breaking change."""
    assert autoqueue.ADMISSION_STATUS_CAP_REASON == "admission_status_cap_exhausted"


def test_next_action_names_the_recovery_and_its_cost():
    """executive_function: an error names its next action, and this recovery is not free."""
    action = autoqueue.ADMISSION_STATUS_CAP_NEXT_ACTION
    assert "new head SHA" in action
    assert "review dossier" in action, "the recovery invalidates the review; that cost must be said"


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _writer_result(monkeypatch, tmp_path, github_output: str, returncode: int = 1):
    """Drive the real status writer with a stubbed gh call and no prior status."""
    monkeypatch.setattr(autoqueue, "_latest_admission_status", lambda *a, **k: None)
    monkeypatch.setattr(
        autoqueue, "_admission_status_for", lambda decision: ("failure", "cc-pr-autoqueue: blocked")
    )

    class _PR:
        head_sha = "a" * 40
        number = 4556

    class _Decision:
        pr = _PR()

    return autoqueue.set_autoqueue_admission_status(
        _Decision(),
        repo="o/r",
        repo_root=tmp_path,
        runner=lambda *a, **k: _Proc(returncode, stdout=github_output),
    )


def test_writer_surfaces_reason_and_next_action_on_cap(monkeypatch, tmp_path):
    """The changed workflow, not just the predicate: a capped write must carry both."""
    ok, message = _writer_result(monkeypatch, tmp_path, CAP_422)
    assert ok is False
    assert autoqueue.ADMISSION_STATUS_CAP_REASON in message
    assert "new head SHA" in message
    assert "maximum number of statuses" in message, (
        "GitHub's own evidence must survive in the message"
    )


def test_writer_leaves_ordinary_failures_unlabelled(monkeypatch, tmp_path):
    """The negative direction on the workflow, not merely on the predicate."""
    ok, message = _writer_result(monkeypatch, tmp_path, '{"message":"Not Found","status":"404"}')
    assert ok is False
    assert autoqueue.ADMISSION_STATUS_CAP_REASON not in message
    assert "new head SHA" not in message


def test_caller_classifies_from_github_evidence_not_from_the_injected_prefix(monkeypatch, tmp_path):
    """A message carrying only GitHub's text, with no injected prefix, is still classified.

    Pins the fix for the review finding that terminal classification was re-derived by
    substring-sniffing a prefix this code had itself added.
    """
    assert autoqueue._is_status_cap_exhausted(CAP_422) is True
    ok, message = _writer_result(monkeypatch, tmp_path, CAP_422)
    stripped = message.split("::", 1)[-1].strip()
    assert autoqueue.ADMISSION_STATUS_CAP_REASON not in stripped
    assert autoqueue._is_status_cap_exhausted(stripped) is True
