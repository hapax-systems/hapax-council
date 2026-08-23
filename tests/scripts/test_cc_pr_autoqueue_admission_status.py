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
