from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from shared import resident_command_r

if TYPE_CHECKING:
    import pytest


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_resident_command_r_cli_check_passes_for_loaded_command_r(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        assert getattr(req, "full_url", "").endswith("/v1/model")
        return _FakeResponse({"id": resident_command_r.RESIDENT_COMMAND_R_MODEL})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert resident_command_r.main(["--check"]) == 0

    captured = capsys.readouterr()
    assert resident_command_r.RESIDENT_COMMAND_R_MODEL in captured.out


def test_resident_command_r_cli_check_fails_for_wrong_model(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        assert getattr(req, "full_url", "").endswith("/v1/model")
        return _FakeResponse({"id": "wrong-model"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert resident_command_r.main(["--check"]) == 1

    captured = capsys.readouterr()
    assert "resident Command-R check failed" in captured.err
    assert "wrong-model" in captured.err
