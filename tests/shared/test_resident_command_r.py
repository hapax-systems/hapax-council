from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from prometheus_client import CollectorRegistry

from agents.telemetry import condition_metrics as cm
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


def _total(reg: CollectorRegistry, name: str) -> float:
    return sum(s.value for metric in reg.collect() for s in metric.samples if s.name == name)


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


def test_call_resident_command_r_records_local_capacity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capacity_path = tmp_path / "local-capacity.json"
    monkeypatch.setattr(cm, "LOCAL_CAPACITY_FILE", capacity_path)
    monkeypatch.setattr(cm, "LOCAL_CAPACITY_LEASE_DIR", tmp_path / "local-capacity-leases")
    monkeypatch.setattr(cm, "LOCAL_CAPACITY_CEILING", 2.0)
    cm.reset_for_testing()
    reg = CollectorRegistry()
    cm._ensure_metrics(reg)

    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        url = getattr(req, "full_url", "")
        if url.endswith("/v1/model"):
            return _FakeResponse({"id": resident_command_r.RESIDENT_COMMAND_R_MODEL})
        assert url.endswith("/v1/chat/completions")
        active = json.loads(capacity_path.read_text(encoding="utf-8"))
        assert active["inflight"] == 1
        return _FakeResponse(
            {
                "choices": [{"message": {"content": "<think>scratch</think>ready"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    content = resident_command_r.call_resident_command_r(
        "plan",
        chat_url="http://tabby.local/v1/chat/completions",
    )

    assert content == "ready"
    finished = json.loads(capacity_path.read_text(encoding="utf-8"))
    assert finished["inflight"] == 0
    assert finished["ttft_ratio"] == 1.0
    assert _total(reg, "hapax_llm_tokens_total") == 11.0
