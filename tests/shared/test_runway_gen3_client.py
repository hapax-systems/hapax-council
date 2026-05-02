"""Tests for the Runway Gen-3 REST API client.

Uses ``httpx.MockTransport`` so the suite never touches the real
Runway API. Covers: request body shape (watermark default, contest
duration limits), polling lifecycle, terminal states, timeout, and
the env-var bootstrap error path.
"""

from __future__ import annotations

import json

import httpx
import pytest

from shared.runway_gen3_client import (
    CONTEST_WATERMARK_REQUIRED,
    DEFAULT_API_VERSION,
    DEFAULT_MODEL,
    MIN_POLL_INTERVAL_S,
    TERMINAL_STATUSES,
    GenerateRequest,
    RunwayClientError,
    RunwayGen3Client,
    RunwayTaskStatus,
)

# ── Request shape ────────────────────────────────────────────────────


class TestRequestShape:
    def test_default_model_is_gen3a_turbo(self) -> None:
        req = GenerateRequest(promptText="x")
        assert req.model == DEFAULT_MODEL == "gen3a_turbo"

    def test_default_watermark_is_true(self) -> None:
        """Big Pitch contest requires visible watermark — must be the default."""
        req = GenerateRequest(promptText="x")
        assert req.watermark is True
        assert CONTEST_WATERMARK_REQUIRED is True

    def test_duration_must_be_in_contest_range(self) -> None:
        """Contest accepts 60-180s clips. The model accepts 1-180s
        broadly (Gen-3 has its own min for short loops)."""
        # within range
        GenerateRequest(promptText="x", duration=10)
        GenerateRequest(promptText="x", duration=60)
        GenerateRequest(promptText="x", duration=180)
        # out of range
        with pytest.raises(ValueError):
            GenerateRequest(promptText="x", duration=0)
        with pytest.raises(ValueError):
            GenerateRequest(promptText="x", duration=181)

    def test_extra_fields_rejected(self) -> None:
        """Pydantic extra=forbid catches typos before they reach the API."""
        with pytest.raises(ValueError):
            GenerateRequest(promptText="x", waterMark=True)  # type: ignore[call-arg]


# ── Bootstrap / env-var ─────────────────────────────────────────────


class TestBootstrap:
    def test_missing_api_key_raises_with_actionable_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("RUNWAY_API_KEY", raising=False)
        with pytest.raises(RunwayClientError) as exc:
            RunwayGen3Client()
        msg = str(exc.value)
        assert "RUNWAY_API_KEY" in msg
        assert "subscription" in msg.lower(), (
            "error must mention subscription requirement (API credits "
            "alone don't qualify for Big Pitch contest)"
        )

    def test_explicit_api_key_overrides_env(self) -> None:
        client = RunwayGen3Client(
            api_key="explicit",
            http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        )
        assert client._headers()["Authorization"] == "Bearer explicit"

    def test_default_api_version_in_headers(self) -> None:
        client = RunwayGen3Client(
            api_key="x",
            http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        )
        assert client._headers()["X-Runway-Version"] == DEFAULT_API_VERSION


# ── Generate path ───────────────────────────────────────────────────


def _ok_handler(*, body: dict[str, object]) -> httpx.MockTransport:
    """Return a transport that always returns 200 with the given JSON body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


class TestGenerate:
    def test_generate_posts_to_image_to_video_endpoint(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"id": "task-1", "status": "PENDING"})

        client = RunwayGen3Client(
            api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        result = client.generate(GenerateRequest(promptText="cinematic"))
        assert captured["url"] == "https://api.runwayml.com/v1/image_to_video"
        assert captured["auth"] == "Bearer k"
        body = captured["body"]
        assert body["promptText"] == "cinematic"
        assert body["model"] == "gen3a_turbo"
        assert body["watermark"] is True
        assert result.id == "task-1"
        assert result.status == RunwayTaskStatus.PENDING

    def test_generate_4xx_raises_runway_client_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="Unauthorized")

        client = RunwayGen3Client(
            api_key="bad", http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(RunwayClientError) as exc:
            client.generate(GenerateRequest(promptText="x"))
        assert "401" in str(exc.value)


# ── Poll lifecycle ──────────────────────────────────────────────────


class TestPollLifecycle:
    def test_poll_returns_terminal_succeeded(self) -> None:
        client = RunwayGen3Client(
            api_key="k",
            http_client=httpx.Client(
                transport=_ok_handler(
                    body={"id": "task-1", "status": "SUCCEEDED", "output": ["https://signed/url"]}
                )
            ),
        )
        result = client.poll("task-1")
        assert result.status == RunwayTaskStatus.SUCCEEDED
        assert result.output == ["https://signed/url"]

    def test_terminal_statuses_set_is_correct(self) -> None:
        assert RunwayTaskStatus.SUCCEEDED in TERMINAL_STATUSES
        assert RunwayTaskStatus.FAILED in TERMINAL_STATUSES
        assert RunwayTaskStatus.CANCELED in TERMINAL_STATUSES
        assert RunwayTaskStatus.PENDING not in TERMINAL_STATUSES
        assert RunwayTaskStatus.IN_PROGRESS not in TERMINAL_STATUSES


# ── generate_and_wait orchestration ──────────────────────────────────


class TestGenerateAndWait:
    def test_immediate_terminal_skips_polling(self) -> None:
        sleeps: list[float] = []
        client = RunwayGen3Client(
            api_key="k",
            http_client=httpx.Client(
                transport=_ok_handler(
                    body={"id": "task-1", "status": "SUCCEEDED", "output": ["url"]}
                )
            ),
        )
        result = client.generate_and_wait(
            GenerateRequest(promptText="x"),
            sleeper=sleeps.append,
        )
        assert result.status == RunwayTaskStatus.SUCCEEDED
        assert sleeps == [], "no sleep when generate returns terminal directly"

    def test_polls_until_terminal(self) -> None:
        # Generate → PENDING; first poll → IN_PROGRESS; second → SUCCEEDED
        responses = iter(
            [
                {"id": "t1", "status": "PENDING"},
                {"id": "t1", "status": "IN_PROGRESS", "progress": 0.5},
                {"id": "t1", "status": "SUCCEEDED", "output": ["url"]},
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(responses))

        sleeps: list[float] = []
        clock_t = [0.0]

        def fake_clock() -> float:
            return clock_t[0]

        def fake_sleeper(s: float) -> None:
            sleeps.append(s)
            clock_t[0] += s

        client = RunwayGen3Client(
            api_key="k",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        result = client.generate_and_wait(
            GenerateRequest(promptText="x"),
            sleeper=fake_sleeper,
            clock=fake_clock,
        )
        assert result.status == RunwayTaskStatus.SUCCEEDED
        assert len(sleeps) == 2
        # First sleep at MIN, second backed off (1.5x)
        assert sleeps[0] == MIN_POLL_INTERVAL_S
        assert sleeps[1] > MIN_POLL_INTERVAL_S

    def test_timeout_raises_runway_client_error(self) -> None:
        # generate returns PENDING; every poll returns PENDING → timeout
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": "t1", "status": "PENDING"})

        clock_t = [0.0]

        def fake_clock() -> float:
            return clock_t[0]

        def fake_sleeper(s: float) -> None:
            clock_t[0] += s

        client = RunwayGen3Client(
            api_key="k",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(RunwayClientError, match="did not reach terminal"):
            client.generate_and_wait(
                GenerateRequest(promptText="x"),
                poll_timeout_s=20.0,
                sleeper=fake_sleeper,
                clock=fake_clock,
            )
