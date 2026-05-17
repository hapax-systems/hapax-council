from __future__ import annotations

from typing import TYPE_CHECKING

from agents.hapax_daimonion import bridge_engine

if TYPE_CHECKING:
    import pytest


def test_deterministic_index_uses_strong_hash_without_md5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_md5(*args: object, **kwargs: object) -> None:
        raise AssertionError("MD5 must not be used for bridge phrase selection")

    monkeypatch.setattr(bridge_engine.hashlib, "md5", _fail_md5)

    first = bridge_engine._deterministic_index("thinking", 3, "session-id-sensitive")
    second = bridge_engine._deterministic_index("thinking", 3, "session-id-sensitive")
    different = bridge_engine._deterministic_index("thinking", 4, "session-id-sensitive")

    assert first == second
    assert first != different
    assert isinstance(first, int)
