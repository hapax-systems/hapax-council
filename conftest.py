"""Root conftest — prevent real notifications from leaking during tests.

This patches the I/O layer (urlopen, subprocess.run) inside shared.notify
so that tests which exercise the engine/delivery path without explicit mocks
cannot send real ntfy or desktop notifications.

Tests that explicitly mock these functions (e.g. test_notify.py) will see
their own mocks take precedence over this session-scoped patch.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="function")
def _block_real_notifications():
    """Prevent shared.notify from making real HTTP or subprocess calls.

    Individual tests can override by patching the same targets themselves —
    the innermost mock wins.

    We replace the ``subprocess`` attribute on ``shared.notify`` with a thin
    wrapper module whose ``.run`` is a no-op mock, while keeping the real
    exception classes (``TimeoutExpired``, etc.) so ``except`` clauses still
    work. This avoids patching the *global* ``subprocess.run`` which would
    break any other code that calls ``subprocess.run`` during the same test.
    """
    import subprocess as _real_subprocess

    mock_urlopen = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    # Build a lightweight stand-in module that keeps exception classes real
    fake_subprocess = types.ModuleType("subprocess")
    fake_subprocess.run = MagicMock(return_value=MagicMock(returncode=0))
    fake_subprocess.TimeoutExpired = _real_subprocess.TimeoutExpired
    fake_subprocess.CalledProcessError = _real_subprocess.CalledProcessError

    with (
        patch("shared.notify.urlopen", mock_urlopen),
        patch("shared.notify.subprocess", fake_subprocess),
    ):
        yield
