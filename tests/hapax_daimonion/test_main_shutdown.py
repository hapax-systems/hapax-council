from __future__ import annotations

import asyncio
import glob
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _FastExit(RuntimeError):
    def __init__(self, code: int):
        super().__init__(f"os._exit({code})")
        self.code = code


class _FakeLoop:
    def __init__(self) -> None:
        self.handlers: list[tuple[object, ...]] = []
        self.closed = False

    def add_signal_handler(self, *args: object) -> None:
        self.handlers.append(args)

    def run_until_complete(self, coro: object) -> object:
        loop = asyncio.SelectorEventLoop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def close(self) -> None:
        self.closed = True


def _install_main_stubs(monkeypatch: pytest.MonkeyPatch, run_error: Exception | None = None):
    from agents.hapax_daimonion import __main__ as main_mod

    fake_loop = _FakeLoop()
    cleanup_pid_file = MagicMock()
    shutdown = MagicMock()
    uvloop_mod = SimpleNamespace(install=MagicMock())
    metrics_mod = SimpleNamespace(start_http_server=MagicMock())
    log_setup_mod = SimpleNamespace(configure_logging=MagicMock())
    tmp_wav_mod = SimpleNamespace(cleanup_all_wavs=MagicMock())
    daemon_instances = []

    class _FakeDaemon:
        def __init__(self, cfg: object) -> None:
            self.cfg = cfg
            self.stop = MagicMock()
            self.workspace_monitor = SimpleNamespace(reload_context=MagicMock())
            daemon_instances.append(self)

        async def run(self) -> None:
            if run_error is not None:
                raise run_error

    monkeypatch.setattr(sys, "argv", ["hapax-daimonion"])
    monkeypatch.setattr(main_mod, "load_config", MagicMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(main_mod, "_enforce_single_instance", MagicMock())
    monkeypatch.setattr(main_mod, "_cleanup_pid_file", cleanup_pid_file)
    monkeypatch.setattr(main_mod, "VoiceDaemon", _FakeDaemon)
    monkeypatch.setattr(main_mod.asyncio, "new_event_loop", MagicMock(return_value=fake_loop))
    monkeypatch.setattr(main_mod.logging, "shutdown", shutdown)
    monkeypatch.setattr(glob, "glob", MagicMock(return_value=[]))
    monkeypatch.setitem(sys.modules, "uvloop", uvloop_mod)
    monkeypatch.setitem(sys.modules, "prometheus_client", metrics_mod)
    monkeypatch.setitem(sys.modules, "agents._log_setup", log_setup_mod)
    monkeypatch.setitem(sys.modules, "agents._tmp_wav", tmp_wav_mod)

    return SimpleNamespace(
        main_mod=main_mod,
        fake_loop=fake_loop,
        cleanup_pid_file=cleanup_pid_file,
        shutdown=shutdown,
        daemon_instances=daemon_instances,
    )


def test_main_fast_exits_after_clean_daemon_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _install_main_stubs(monkeypatch)

    def fake_exit(code: int) -> None:
        raise _FastExit(code)

    monkeypatch.setattr(ctx.main_mod.os, "_exit", fake_exit)

    with pytest.raises(_FastExit) as exc_info:
        ctx.main_mod.main()

    assert exc_info.value.code == 0
    ctx.cleanup_pid_file.assert_called_once_with()
    assert ctx.fake_loop.closed is True
    ctx.shutdown.assert_called_once_with()
    assert len(ctx.daemon_instances) == 1


def test_main_fast_exit_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _install_main_stubs(monkeypatch)
    exit_mock = MagicMock()
    monkeypatch.setenv("HAPAX_DAIMONION_FAST_EXIT_AFTER_SHUTDOWN", "0")
    monkeypatch.setattr(ctx.main_mod.os, "_exit", exit_mock)

    ctx.main_mod.main()

    exit_mock.assert_not_called()
    ctx.shutdown.assert_not_called()
    ctx.cleanup_pid_file.assert_called_once_with()
    assert ctx.fake_loop.closed is True


def test_main_preserves_daemon_run_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    run_error = RuntimeError("startup failed")
    ctx = _install_main_stubs(monkeypatch, run_error=run_error)
    exit_mock = MagicMock()
    monkeypatch.setattr(ctx.main_mod.os, "_exit", exit_mock)

    with pytest.raises(RuntimeError, match="startup failed"):
        ctx.main_mod.main()

    exit_mock.assert_not_called()
    ctx.shutdown.assert_not_called()
    ctx.cleanup_pid_file.assert_called_once_with()
    assert ctx.fake_loop.closed is True
