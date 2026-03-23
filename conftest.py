"""Root conftest — prevent real notifications and GPU model loading during tests.

This patches:
  1. I/O layer (urlopen, subprocess.run) inside shared.notify — prevents real
     ntfy or desktop notifications.
  2. GPU/ML modules (torch, model2vec, etc.) — prevents VRAM allocation during
     test collection. Without this, tests that transitively import voice/ML
     modules can load models and consume 18+ GiB of VRAM.

Tests that explicitly mock these functions will see their own mocks take
precedence over these session-scoped patches.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def _stub_gpu_modules():
    """Stub GPU/ML modules at import time to prevent VRAM allocation.

    This runs at collection time (before any test), so transitive imports
    from agents.hapax_voice.* can't accidentally load real torch/model2vec.
    The stubs in tests/hapax_voice/conftest.py are more detailed but only
    apply when that directory is collected — this catches everything else.
    """
    for mod_name in [
        "torch",
        "torch.cuda",
        "torch.nn",
        "torch.nn.functional",
        "torchaudio",
        "model2vec",
        "pyaudio",
        "openwakeword",
        "openwakeword.model",
    ]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()


_stub_gpu_modules()


@pytest.fixture(autouse=True, scope="function")
def _block_real_notifications():
    """Prevent shared.notify from making real HTTP or subprocess calls.

    Individual tests can override by patching the same targets themselves —
    the innermost mock wins.
    """
    mock_urlopen = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    mock_run = MagicMock()
    mock_run.return_value = MagicMock(returncode=0)

    with (
        patch("shared.notify.urlopen", mock_urlopen),
        patch("shared.notify._run_subprocess", mock_run),
    ):
        yield
