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
DEFAULT_GRAFANA_URL = os.environ.get(
    "HAPAX_YOUTUBE_QUOTA_GRAFANA_URL",
    "http://localhost:3000/d/yt-quota/youtube-data-api-quota-ytb-001?orgId=1",
)
DEFAULT_PROFILE = Path(
    os.environ.get(
        "HAPAX_GCP_YOUTUBE_QUOTA_PROFILE",
        str(Path.home() / ".cache/hapax/playwright/gcp-youtube-quota"),
    )
)
MIN_PEAK_UNITS_DEFAULT = 1.0
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
QUOTA_FORM_ANSWER_KEYS = (
    "Which API Client are you requesting a quota increase for?",
    "What API project number are you requesting increased quota for?",
    "Which YouTube API Service(s) are you requesting a quota increase for?",
    'How much "Additional Quota" are you requesting?',
    "Justification for requesting additional quota?",
    "Explain in detail how you use YouTube API Services today",
    "What functionality would your API client be lacking without more quota?",
    "What potential workarounds would you use to compensate for less quota?",
)
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


def evidence_blockers(evidence: dict[str, str | float], *, min_peak_units: float) -> list[str]:
    """Return fail-closed reasons that make a live quota filing premature."""
    used_peak = float(evidence.get("used_units_peak_7d", 0.0))
    rate_peak = float(evidence.get("rate_per_min_peak_7d", 0.0))
    if used_peak >= min_peak_units or rate_peak > 0.0:
        return []
    return [
        (
            f"insufficient observed YouTube API quota burn: 7-day peak={used_peak:g} "
            f"units, peak_rate={rate_peak:g} units/min, required_peak>={min_peak_units:g}"
        )
    ]


def build_quota_form_answers(request: dict[str, Any]) -> dict[str, str]:
    """Build the quota-section answer packet for operator review and filing."""
    additional_quota = int(request["additional_quota_units"])
    requested = int(request["requested_quota_units"])
    current = int(request["current_quota_units"])
    evidence = request["evidence"]
    current_use = (
        "Hapax uses the YouTube Data API for a single-operator, operator-owned 24/7 "
        "AI livestream stack: broadcast lifecycle checks, metadata/description updates, "
        "retention and viewer telemetry ingestion, Content ID monitoring, captions, "
        "and a Shorts extraction/upload pipeline. The API client does not redistribute "
        "third-party data, does not operate as a multi-user SaaS product, and remains "
        "scoped to the operator's own channel and broadcast artifacts."
    )
    missing_functionality = (
        "Without higher daily quota, Hapax must sharply reduce autonomous metadata "
        "refresh cadence, Shorts upload throughput, captions publication, analytics "
        "ingestion, and Content ID monitoring. Those reductions degrade the public "
        "research archive and force manual batching around the 10,000-unit default "
        "allocation instead of allowing reliable always-on livestream operations."
    )
    workarounds = (
        "Fallback would be lower-frequency polling, smaller samples, deferred Shorts "
        "uploads, skipped caption updates, and local estimation from already-cached "
        "state. Hapax will not shard traffic across extra projects to evade quota; "
        "the preferred mitigation is one compliant quota extension on the existing "
        "YouTube Data API project."
    )
    justification = (
        f"Requesting {additional_quota} additional units/day so the project can move "
        f"from {current} to {requested} units/day. Current Prometheus evidence sampled "
        f"{evidence['sampled_at']} shows current usage {evidence['used_units_current']} "
        f"units, seven-day peak usage {evidence['used_units_peak_7d']} units, current "
        f"burn rate {evidence['rate_per_min_current']} units/min, and seven-day peak "
        f"rate {evidence['rate_per_min_peak_7d']} units/min. The request supports "
        "bounded single-operator livestream orchestration and gives the compliance "
        "reviewer arithmetic evidence for the requested headroom."
    )
    return {
        QUOTA_FORM_ANSWER_KEYS[0]: str(request["project_name"]),
        QUOTA_FORM_ANSWER_KEYS[1]: str(request["project_id"]),
        QUOTA_FORM_ANSWER_KEYS[2]: "YouTube Data API v3",
        QUOTA_FORM_ANSWER_KEYS[3]: str(additional_quota),
        QUOTA_FORM_ANSWER_KEYS[4]: justification,
        QUOTA_FORM_ANSWER_KEYS[5]: current_use,
        QUOTA_FORM_ANSWER_KEYS[6]: missing_functionality,
        QUOTA_FORM_ANSWER_KEYS[7]: workarounds,
    }


def write_response_tracking(output_dir: Path, summary: dict[str, Any]) -> None:
    receipt = summary.get("receipt_url") or "not submitted"
    status = summary.get("status") or "packet_created"
    blockers = summary.get("evidence_blockers") or []
    blocker_lines = "\n".join(f"- {reason}" for reason in blockers) if blockers else "- none"
    output_dir.joinpath("response-tracking.md").write_text(
        "\n".join(
            [
                "# YouTube API quota extension response tracking",
                "",
                f"- status: {status}",
                f"- receipt_url: {receipt}",
                f"- form_url: {FORM_URL}",
                f"- grafana_dashboard_url: {summary.get('grafana_dashboard_url')}",
                f"- grafana_screenshot_path: {summary.get('grafana_screenshot_path') or 'not captured'}",
                "",
                "## Evidence blockers",
                "",
                blocker_lines,
                "",
                "## Follow-up",
                "",
                "- Replace `status` with approval / request-for-more-info / denial when Google responds.",
                "- Attach the Grafana quota-consumption screenshot before live filing.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def capture_grafana_dashboard(url: str, *, output_dir: Path) -> str:
    """Capture the quota dashboard as evidence for the Google form."""
    from playwright.sync_api import sync_playwright

    screenshot = output_dir / "grafana-quota-dashboard.png"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        page.set_default_timeout(20_000)
        page.goto(url, wait_until="networkidle")
        page.screenshot(path=str(screenshot), full_page=True)
        browser.close()
    return str(screenshot)


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
    parser.add_argument("--min-peak-units", type=float, default=MIN_PEAK_UNITS_DEFAULT)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--grafana-url", default=DEFAULT_GRAFANA_URL)
    parser.add_argument("--capture-grafana", action="store_true")
    parser.add_argument("--allow-insufficient-evidence", action="store_true")
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--submit", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    opener: Any = urlopen,
    form_submitter: Any = fill_quota_form,
    grafana_capturer: Any = capture_grafana_dashboard,
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
        "additional_quota_units": max(0, args.requested_quota - args.current_quota),
        "form_url": FORM_URL,
        "grafana_dashboard_url": args.grafana_url,
        "evidence": evidence,
    }
    request["justification"] = _render(args.template, {**request, **evidence})
    request["quota_form_answers"] = build_quota_form_answers(request)
    blockers = evidence_blockers(evidence, min_peak_units=args.min_peak_units)
    request["evidence_blockers"] = blockers
    request["evidence_status"] = "ready" if not blockers else "insufficient_evidence"
    output_dir = args.output_dir / datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quota-request.json").write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "justification.md").write_text(request["justification"] + "\n")
    (output_dir / "quota-form-answers.json").write_text(
        json.dumps(request["quota_form_answers"], indent=2, sort_keys=True) + "\n"
    )
    grafana_screenshot_path: str | None = None
    if args.capture_grafana:
        grafana_screenshot_path = grafana_capturer(args.grafana_url, output_dir=output_dir)
    outcome: dict[str, Any] = {
        "receipt_url": None,
        "screenshot_path": None,
        "grafana_screenshot_path": grafana_screenshot_path,
        "grafana_dashboard_url": args.grafana_url,
        "evidence_status": request["evidence_status"],
        "evidence_blockers": blockers,
    }
    if args.submit and env.get(LIVE_ENV) != "1":
        print(f"refusing live submit: set {LIVE_ENV}=1 and pass --submit", file=sys.stderr)
        return 2
    if (args.open_browser or args.submit) and blockers and not args.allow_insufficient_evidence:
        outcome["status"] = "blocked_insufficient_evidence"
        summary = {"output_dir": str(output_dir), **outcome}
        (output_dir / "outcome.json").write_text(json.dumps(summary, indent=2) + "\n")
        write_response_tracking(output_dir, summary)
        print(json.dumps(summary, sort_keys=True))
        return 3
    if args.open_browser or args.submit:
        outcome = form_submitter(request, output_dir=output_dir, submit=args.submit)
        outcome.setdefault("grafana_screenshot_path", grafana_screenshot_path)
        outcome.setdefault("grafana_dashboard_url", args.grafana_url)
        outcome.setdefault("evidence_status", request["evidence_status"])
        outcome.setdefault("evidence_blockers", blockers)
    outcome.setdefault("status", "submitted" if outcome.get("receipt_url") else "packet_created")
    summary = {"output_dir": str(output_dir), **outcome}
    (output_dir / "outcome.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_response_tracking(output_dir, summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
