import os
import sys
from types import SimpleNamespace

from agents.studio_compositor import __main__ as compositor_main


def test_native_thread_limits_default_before_opencv(monkeypatch) -> None:
    for key in compositor_main._NATIVE_THREAD_LIMIT_ENV_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    calls: list[int] = []
    fake_cv2 = SimpleNamespace(setNumThreads=lambda value: calls.append(value))
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

    compositor_main._configure_native_thread_limits()

    for key in compositor_main._NATIVE_THREAD_LIMIT_ENV_DEFAULTS:
        assert os.environ[key] == "1"
    assert calls == [1]


def test_native_thread_limits_preserve_operator_overrides(monkeypatch) -> None:
    monkeypatch.setenv("OPENCV_FOR_THREADS_NUM", "2")
    monkeypatch.setenv("OMP_NUM_THREADS", "3")
    calls: list[int] = []
    fake_cv2 = SimpleNamespace(setNumThreads=lambda value: calls.append(value))
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

    compositor_main._configure_native_thread_limits()

    assert os.environ["OPENCV_FOR_THREADS_NUM"] == "2"
    assert os.environ["OMP_NUM_THREADS"] == "3"
    assert calls == [2]
