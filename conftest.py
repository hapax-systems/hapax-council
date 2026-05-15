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

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Tests should not create live OpenTelemetry exporter threads. GitHub Actions
# sets this explicitly; keep the same default locally so full-suite runs do not
# hang on Langfuse/OTLP background workers after pytest reaches 100%.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")


def _stub_gpu_modules():
    """Stub GPU/ML modules at import time to prevent VRAM allocation.

    This runs at collection time (before any test), so transitive imports
    from agents.hapax_daimonion.* can't accidentally load real torch/model2vec.
    The stubs in tests/hapax_daimonion/conftest.py are more detailed but only
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


def _qdrant_available() -> bool:
    """Check if Qdrant is reachable on localhost:6333."""
    import socket

    try:
        s = socket.create_connection(("localhost", 6333), timeout=1)
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


_QDRANT_UP = _qdrant_available()


@pytest.fixture(autouse=True, scope="function")
def _mock_qdrant_if_unavailable():
    """Prevent Qdrant connection errors in CI (no Qdrant server).

    Patches the raw factory (``_get_qdrant_raw`` / ``_get_qdrant_grpc_raw``)
    to return a MagicMock so the consent gate wrapping in ``get_qdrant()``
    stays intact — the LRR Phase 6 FINDING-R closure invariant (tests in
    ``tests/shared/test_qdrant_gate_wiring.py``) asserts ``get_qdrant()``
    returns a ``ConsentGatedQdrant``, so we must not replace it wholesale.
    """
    if _QDRANT_UP:
        yield
        return

    mock_client = MagicMock()
    mock_client.get_collections.return_value = MagicMock(collections=[])
    mock_client.scroll.return_value = ([], None)
    mock_client.search.return_value = []
    mock_client.count.return_value = MagicMock(count=0)

    # Clear any cached real client so the patched raw factories take effect.
    try:
        import shared.config as _shared_config

        _shared_config.get_qdrant.cache_clear()
        _shared_config.get_qdrant_grpc.cache_clear()
        _shared_config._get_qdrant_raw.cache_clear()
        _shared_config._get_qdrant_grpc_raw.cache_clear()
    except (ImportError, AttributeError):
        _shared_config = None  # noqa: F841 — silenced for try/finally below

    targets = [
        "shared.config._get_qdrant_raw",
        "shared.config._get_qdrant_grpc_raw",
    ]
    try:
        import agents._config  # noqa: F401

        targets.append("agents._config.get_qdrant")
    except ImportError:
        pass

    patches = [patch(t, return_value=mock_client) for t in targets]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()
    if _shared_config is not None:
        _shared_config.get_qdrant.cache_clear()
        _shared_config.get_qdrant_grpc.cache_clear()
        _shared_config._get_qdrant_raw.cache_clear()
        _shared_config._get_qdrant_grpc_raw.cache_clear()


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


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Force-close module-level network clients so pytest can exit cleanly.

    LiteLLM, Qdrant, and httpx keep TCP pools alive in module-level or
    ``functools.lru_cache``-backed singletons. After tests finish, these
    sockets never close and the pytest process hangs until the CI
    ``timeout -s KILL 1500`` wrapper shoots it. Real tests finish in
    ~11-15 min; the remaining ~10-14 min until KILL is pure tax per
    PR. This finalizer turns that tax into a clean ~0.1s teardown.

    Idempotent + swallows everything: teardown must never fail.
    """
    import contextlib
    import gc

    # Audio: some tests instantiate persistent PipeWire playback helpers. If a
    # test forgets to close them, their reaper/subprocess state can keep xdist
    # workers alive after all tests pass.
    with contextlib.suppress(Exception):
        from agents.hapax_daimonion.pw_audio_output import PwAudioOutput

        for obj in list(gc.get_objects()):
            if isinstance(obj, PwAudioOutput):
                with contextlib.suppress(Exception):
                    obj.close()

    # OpenTelemetry/Langfuse: shut down any provider a side-effect import may
    # have installed despite test disables. Provider shutdown joins batch
    # exporter workers instead of letting xdist wait for stuck subprocesses.
    with contextlib.suppress(Exception):
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()

    with contextlib.suppress(Exception):
        for module_name in ("shared.telemetry", "agents._telemetry"):
            module = sys.modules.get(module_name)
            if module is None:
                continue
            client = getattr(module, "_langfuse", None)
            if client is not None:
                for method_name in ("flush", "shutdown", "close"):
                    method = getattr(client, method_name, None)
                    if callable(method):
                        with contextlib.suppress(Exception):
                            method()
                with contextlib.suppress(Exception):
                    module._langfuse = None

    # Qdrant: clear ``shared.config`` lru_caches + close raw clients.
    with contextlib.suppress(Exception):
        import shared.config as _cfg

        for factory in ("_get_qdrant_raw", "_get_qdrant_grpc_raw"):
            cache = getattr(_cfg, factory, None)
            if cache is None:
                continue
            try:
                client = cache()
            except Exception:  # noqa: BLE001
                client = None
            with contextlib.suppress(Exception):
                cache.cache_clear()
            if client is not None:
                # QdrantClient has a .close() that tears down httpx + grpc.
                with contextlib.suppress(Exception):
                    client.close()

    # LiteLLM: close the module's shared httpx + async client sessions.
    # LiteLLM registers ``aclient_session`` / ``client_session`` at module level
    # with connection pools; these leak sockets post-session.
    with contextlib.suppress(Exception):
        import litellm

        for attr in ("client_session", "aclient_session", "in_memory_llm_clients_cache"):
            obj = getattr(litellm, attr, None)
            if obj is None:
                continue
            with contextlib.suppress(Exception):
                close = getattr(obj, "close", None)
                if callable(close):
                    close()
            with contextlib.suppress(Exception):
                setattr(litellm, attr, None)

    # httpx: close any module-level AsyncClient/Client survivors.
    # ``httpx._client`` keeps no global registry, but pydantic-ai's
    # LiteLLMProvider holds a ``httpx.AsyncClient`` that pins sockets.
    # Walk live objects for any Client with an open transport + close.
    with contextlib.suppress(Exception):
        import httpx

        for obj in list(gc.get_objects()):
            if isinstance(obj, httpx.AsyncClient | httpx.Client):
                with contextlib.suppress(Exception):
                    close = getattr(obj, "close", None)
                    if callable(close):
                        # AsyncClient.close is a coroutine; schedule + ignore.
                        import asyncio
                        import inspect

                        if inspect.iscoroutinefunction(close):
                            with contextlib.suppress(Exception):
                                loop = asyncio.new_event_loop()
                                try:
                                    loop.run_until_complete(close())
                                finally:
                                    loop.close()
                        else:
                            close()

    # Give the gc a nudge so sockets get finalized before interpreter exit.
    with contextlib.suppress(Exception):
        gc.collect()
