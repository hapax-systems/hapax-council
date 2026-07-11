"""Regression tests for hapax_daimonion collection-time hardware stubs."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from unittest.mock import MagicMock

import pytest


def test_hapax_daimonion_conftest_preserves_installed_cv2() -> None:
    if importlib.util.find_spec("cv2") is None:
        pytest.skip("cv2 is not installed on this host")

    import cv2

    assert not isinstance(cv2, MagicMock)


def test_hapax_daimonion_conftest_stubs_cv2_when_uninstalled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daimonion_conftest = importlib.import_module("tests.hapax_daimonion.conftest")
    sentinel = object()
    original_cv2 = sys.modules.get("cv2", sentinel)
    real_import_module = importlib.import_module

    def fake_import_module(name: str, *args: object, **kwargs: object) -> object:
        if name == "cv2":
            raise ImportError("simulated missing OpenCV")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "cv2", raising=False)
    monkeypatch.setattr(daimonion_conftest.importlib, "import_module", fake_import_module)
    try:
        daimonion_conftest._stub_hardware_modules()
        assert isinstance(sys.modules.get("cv2"), MagicMock)
    finally:
        if original_cv2 is sentinel:
            sys.modules.pop("cv2", None)
        else:
            sys.modules["cv2"] = original_cv2
