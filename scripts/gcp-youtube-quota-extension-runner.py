#!/usr/bin/env python3
"""Build and optionally submit the YouTube Data API quota request."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

FORM_URL = "https://support.google.com/youtube/contact/yt_api_form"
LIVE_ENV = "HAPAX_GCP_YOUTUBE_QUOTA_LIVE_SUBMIT"
DEFAULT_OUTPUT = Path.home() / ".local/state/hapax/gcp-youtube-quota-extension-runner"
DEFAULT_TEMPLATE = (
    Path.home() / "Documents/Personal/30-areas/hapax/youtube-quota-justification-template.md"
)
DEFAULT_PROFILE = Path(
    os.environ.get(
        "HAPAX_GCP_YOUTUBE_QUOTA_PROFILE",
        str(Path.home() / ".cache/hapax/playwright/gcp-youtube-quota"),
    )
)
PROMQL = {
    "used_units_current": "last_over_time(hapax_broadcast_yt_quota_units_used[7d])",
    "remaining_units_current": "last_over_time(hapax_broadcast_yt_quota_remaining[7d])",
    "daily_cap_units_current": (
        "last_over_time(hapax_broadcast_yt_quota_units_used[7d]) + "
        "last_over_time(hapax_broadcast_yt_quota_remaining[7d])"
    ),
    "rate_per_min_current": "last_over_time(hapax_broadcast_yt_quota_rate_per_min[7d])",
    "used_units_peak_7d": "max_over_time(hapax_broadcast_yt_quota_units_used[7d])",
    "rate_per_min_peak_7d": "max_over_time(hapax_broadcast_yt_quota_rate_per_min[7d])",
}
FIELDS = (
    (("Project name", "API project", "Google Cloud project"), "project_name"),
    (("Project ID", "Project number", "API key project"), "project_id"),
    (("Current quota", "Current allocation"), "current_quota_units"),
    (("Requested quota", "Quota requested", "New quota"), "requested_quota_units"),
    (("Use case", "Justification", "Description"), "justification"),
)
FALLBACK_TEMPLATE = (
    "Requesting {{requested_quota_units}} YouTube Data API units/day for {{project_name}} "
    "({{project_id}}). Current quota is {{current_quota_units}} units/day. Seven-day "
    "peak burn was {{used_units_peak_7d}} units and {{rate_per_min_peak_7d}} units/min. "
    "Use case: 24/7 operator-owned livestream orchestration, metadata rotation, "
    "retention analytics, Content ID monitoring, Shorts pipeline, and broadcast lifecycle."
)


def _prom(url: str, query: str, opener: Any) -> float:
    endpoint = f"{url.rstrip('/')}/api/v1/query?{urlencode({'query': query})}"
    with opener(endpoint, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("data", {}).get("result", [])
    if payload.get("status") != "success" or not result:
        raise RuntimeError(f"prometheus query returned no sample: {query}")
    return float(result[0]["value"][1])


def collect_evidence(
    prometheus_url: str,
    *,
    opener: Any = urlopen,
    now: datetime | None = None,
) -> dict[str, str | float]:
    evidence: dict[str, str | float] = {
        "sampled_at": (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    }
    evidence.update({name: _prom(prometheus_url, query, opener) for name, query in PROMQL.items()})
    return evidence


def _render(template: Path, values: dict[str, Any]) -> str:
    text = template.read_text(encoding="utf-8") if template.exists() else FALLBACK_TEMPLATE
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _fill(page: Any, labels: tuple[str, ...], value: str) -> None:
    for label in labels:
        try:
            page.get_by_label(label, exact=False).first.fill(value)
            return
        except Exception:
            pass
    raise RuntimeError(f"none of the expected labels were fillable: {labels!r}")


def fill_quota_form(
    request: dict[str, Any], *, output_dir: Path, submit: bool
) -> dict[str, str | None]:  # pragma: no cover - needs live Google session
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(DEFAULT_PROFILE), headless=False
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(20_000)
        page.goto(FORM_URL, wait_until="domcontentloaded")
        for labels, key in FIELDS:
            _fill(page, labels, str(request[key]))
        screenshot = output_dir / "form-preview.png"
        page.screenshot(path=str(screenshot), full_page=True)
        receipt_url = page.url
        if submit:
            page.get_by_role("button", name=re.compile("submit|send", re.I)).click()
            page.wait_for_load_state("networkidle")
            receipt_url = page.url
        context.close()
    return {"receipt_url": receipt_url, "screenshot_path": str(screenshot)}


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prometheus-url", default=os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    )
    parser.add_argument("--project-id", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument(
        "--project-name", default=os.environ.get("HAPAX_YOUTUBE_QUOTA_PROJECT_NAME", "")
    )
    parser.add_argument("--contact-email", default=os.environ.get("HAPAX_OPERATOR_EMAIL", ""))
    parser.add_argument("--current-quota", type=int, default=10_000)
    parser.add_argument("--requested-quota", type=int, default=100_000)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--submit", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    opener: Any = urlopen,
    form_submitter: Any = fill_quota_form,
    env: dict[str, str] | os._Environ[str] = os.environ,
) -> int:
    args = _args(argv)
    evidence = collect_evidence(args.prometheus_url, opener=opener)
    request: dict[str, Any] = {
        "project_id": args.project_id or "unknown-project",
        "project_name": args.project_name or args.project_id or "Hapax YouTube API project",
        "contact_email": args.contact_email,
        "current_quota_units": args.current_quota,
        "requested_quota_units": args.requested_quota,
        "form_url": FORM_URL,
        "evidence": evidence,
    }
    request["justification"] = _render(args.template, {**request, **evidence})
    output_dir = args.output_dir / datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quota-request.json").write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "justification.md").write_text(request["justification"] + "\n")
    outcome: dict[str, str | None] = {"receipt_url": None, "screenshot_path": None}
    if args.submit and env.get(LIVE_ENV) != "1":
        print(f"refusing live submit: set {LIVE_ENV}=1 and pass --submit", file=sys.stderr)
        return 2
    if args.open_browser or args.submit:
        outcome = form_submitter(request, output_dir=output_dir, submit=args.submit)
    summary = {"output_dir": str(output_dir), **outcome}
    (output_dir / "outcome.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
