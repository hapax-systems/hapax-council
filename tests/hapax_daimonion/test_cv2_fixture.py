"""Regression tests for hapax_daimonion collection-time hardware stubs."""

from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock

import pytest


def test_hapax_daimonion_conftest_preserves_installed_cv2() -> None:
    if importlib.util.find_spec("cv2") is None:
        pytest.skip("cv2 is not installed on this host")

    import cv2

    assert not isinstance(cv2, MagicMock)
