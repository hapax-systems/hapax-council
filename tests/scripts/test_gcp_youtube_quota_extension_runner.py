"""Contract tests for scripts/gcp-youtube-quota-extension-runner.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gcp-youtube-quota-extension-runner.py"


@pytest.fixture(scope="module")
def runner_mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gcp_youtube_quota_extension_runner", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, value: float) -> None:
        self._value = value

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "status": "success",
                "data": {
                    "result": [
                        {
                            "metric": {},
                            "value": [1_714_000_000.0, str(self._value)],
                        }
                    ]
                },
            }
        ).encode()


def _opener(values: dict[str, float], seen: list[str] | None = None):
    def opener(url: str, **_kwargs: Any) -> _Response:
        query = parse_qs(urlparse(url).query)["query"][0]
        if seen is not None:
            seen.append(query)
        return _Response(values[query])

    return opener


_PROM_VALUES = {
    "last_over_time(hapax_broadcast_yt_quota_units_used[7d])": 2_500.0,
    "last_over_time(hapax_broadcast_yt_quota_remaining[7d])": 7_500.0,
    (
        "last_over_time(hapax_broadcast_yt_quota_units_used[7d]) + "
        "last_over_time(hapax_broadcast_yt_quota_remaining[7d])"
    ): 10_000.0,
    "last_over_time(hapax_broadcast_yt_quota_rate_per_min[7d])": 42.0,
    "max_over_time(hapax_broadcast_yt_quota_units_used[7d])": 8_750.0,
    "max_over_time(hapax_broadcast_yt_quota_rate_per_min[7d])": 125.0,
}


def test_collect_evidence_queries_current_and_seven_day_snapshot(runner_mod: ModuleType):
    seen: list[str] = []
    evidence = runner_mod.collect_evidence(
        "http://prometheus.invalid", opener=_opener(_PROM_VALUES, seen)
    )

    assert evidence["used_units_current"] == 2_500.0
    assert evidence["remaining_units_current"] == 7_500.0
    assert evidence["daily_cap_units_current"] == 10_000.0
    assert evidence["used_units_peak_7d"] == 8_750.0
    assert "max_over_time(hapax_broadcast_yt_quota_units_used[7d])" in seen


def test_main_dry_run_writes_request_and_never_opens_browser(
    runner_mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    template = tmp_path / "template.md"
    template.write_text("Project {{project_name}} peak {{used_units_peak_7d}}", encoding="utf-8")

    def fail_submitter(*_args: Any, **_kwargs: Any) -> dict[str, str | None]:
        raise AssertionError("dry run should not open Playwright")

    rc = runner_mod.main(
        [
            "--prometheus-url",
            "http://prometheus.invalid",
            "--project-id",
            "hapax-youtube",
            "--project-name",
            "Hapax YouTube",
            "--contact-email",
            "ops@example.invalid",
            "--template",
            str(template),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        opener=_opener(_PROM_VALUES),
        form_submitter=fail_submitter,
        env={},
    )

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    out_dir = Path(summary["output_dir"])
    request = json.loads((out_dir / "quota-request.json").read_text(encoding="utf-8"))
    assert request["project_id"] == "hapax-youtube"
    assert request["evidence"]["used_units_peak_7d"] == 8_750.0
    assert (out_dir / "justification.md").read_text(encoding="utf-8").strip() == (
        "Project Hapax YouTube peak 8750.0"
    )
    assert json.loads((out_dir / "outcome.json").read_text(encoding="utf-8"))["receipt_url"] is None


def test_submit_requires_flag_and_live_env(runner_mod: ModuleType, tmp_path: Path):
    called = False

    def submitter(*_args: Any, **_kwargs: Any) -> dict[str, str | None]:
        nonlocal called
        called = True
        return {"receipt_url": "https://support.google.com/receipt", "screenshot_path": None}

    rc = runner_mod.main(
        [
            "--prometheus-url",
            "http://prometheus.invalid",
            "--submit",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        opener=_opener(_PROM_VALUES),
        form_submitter=submitter,
        env={},
    )

    assert rc == 2
    assert called is False


def test_submit_with_live_env_captures_receipt(
    runner_mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    observed_submit: list[bool] = []

    def submitter(*_args: Any, **kwargs: Any) -> dict[str, str | None]:
        observed_submit.append(kwargs["submit"])
        return {
            "receipt_url": "https://support.google.com/youtube/contact/receipt",
            "screenshot_path": str(tmp_path / "preview.png"),
        }

    rc = runner_mod.main(
        [
            "--prometheus-url",
            "http://prometheus.invalid",
            "--submit",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        opener=_opener(_PROM_VALUES),
        form_submitter=submitter,
        env={runner_mod.LIVE_ENV: "1"},
    )

    assert rc == 0
    assert observed_submit == [True]
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt_url"].endswith("/receipt")
