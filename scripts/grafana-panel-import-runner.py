#!/usr/bin/env python3
"""Grafana panel import runner — Playwright + HTTP API recipe.

Closes ``awareness-grafana-tv-panel-import-smoke`` cc-task without an
operator browser session: imports a dashboard panel JSON via the Grafana
HTTP API, captures the resulting dashboard UID, and (optionally) drives
the operator's existing Playwright session to take a screenshot of the
rendered panel for evidence.

Per cc-task `grafana-panel-import-runner` (Phase 1 of operator-blocking
automation 2026-05-01).

Usage::

    grafana-panel-import-runner.py --panel-json path/to/tv-panel.json [--screenshot]

Authentication is read from ``pass show grafana/api-key`` first, falling
back to the ``GRAFANA_API_KEY`` env var, falling back to ``--api-key``.
The runner aborts with a clear message if no key is present rather than
prompting the operator (the dissolution intent is to remove the
operator-blocking step entirely).

Anti-overclaim: imports a panel; does not author panel content. Live
behavior is bounded by ``mode_ceiling: public_archive`` (local
observability only; no public-facing dispatch).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_GRAFANA_URL = os.environ.get("HAPAX_GRAFANA_URL", "http://localhost:3001")
DEFAULT_PASS_PATH = "grafana/api-key"


def _resolve_api_key(cli_key: str | None) -> str | None:
    """Resolve the Grafana API key from pass / env / CLI in that order."""
    try:
        result = subprocess.run(
            ["pass", "show", DEFAULT_PASS_PATH],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            key = result.stdout.strip().splitlines()[0]
            if key:
                return key
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    env_key = os.environ.get("GRAFANA_API_KEY", "").strip()
    if env_key:
        return env_key
    if cli_key:
        return cli_key
    return None


def import_dashboard(
    panel_json_path: Path,
    *,
    grafana_url: str,
    api_key: str,
    folder_uid: str | None = None,
) -> dict[str, Any]:
    """POST the dashboard JSON to ``/api/dashboards/db``; return parsed response."""
    payload_text = panel_json_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    body = {
        "dashboard": payload.get("dashboard", payload),
        "overwrite": True,
        "message": f"hapax import via grafana-panel-import-runner ({panel_json_path.name})",
    }
    if folder_uid:
        body["folderUid"] = folder_uid
    request = urllib.request.Request(
        f"{grafana_url.rstrip('/')}/api/dashboards/db",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def capture_screenshot(
    dashboard_uid: str,
    *,
    grafana_url: str,
    output: Path,
    api_key: str | None = None,
) -> bool:
    """Use Playwright to capture a dashboard screenshot.

    Best-effort: returns ``True`` on success, ``False`` if Playwright is
    unavailable or the snippet fails. Does not raise — screenshot capture
    is evidence-grade, not blocking.
    """
    panel_url = f"{grafana_url.rstrip('/')}/d/{dashboard_uid}?kiosk=tv"
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"warning: Playwright unavailable for screenshot capture: {exc}", file=sys.stderr)
        return False

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                if api_key:
                    page.set_extra_http_headers({"Authorization": f"Bearer {api_key}"})
                page.goto(panel_url, wait_until="networkidle", timeout=15000)
                page.screenshot(path=str(output), full_page=True)
            finally:
                browser.close()
    except Exception as exc:
        print(f"warning: Grafana screenshot capture failed: {exc}", file=sys.stderr)
        return False
    return output.exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--panel-json",
        type=Path,
        required=True,
        help="path to dashboard JSON (Grafana export format)",
    )
    parser.add_argument(
        "--grafana-url",
        default=DEFAULT_GRAFANA_URL,
        help=f"Grafana base URL (default: {DEFAULT_GRAFANA_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Grafana API key (last-resort fallback; prefer pass show grafana/api-key)",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=None,
        help="capture a Playwright screenshot to this path",
    )
    parser.add_argument(
        "--folder-uid",
        default=None,
        help="optional Grafana folder UID for the imported dashboard",
    )
    args = parser.parse_args(argv)

    if not args.panel_json.is_file():
        print(f"error: panel JSON not found: {args.panel_json}", file=sys.stderr)
        return 2

    api_key = _resolve_api_key(args.api_key)
    if not api_key:
        print(
            f"error: Grafana API key not found. Tried: pass show {DEFAULT_PASS_PATH}, "
            f"GRAFANA_API_KEY env var, --api-key flag.",
            file=sys.stderr,
        )
        return 3

    try:
        result = import_dashboard(
            args.panel_json,
            grafana_url=args.grafana_url,
            api_key=api_key,
            folder_uid=args.folder_uid,
        )
    except urllib.error.HTTPError as exc:
        print(f"error: Grafana API HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 4
    except urllib.error.URLError as exc:
        print(
            f"error: Grafana API unreachable at {args.grafana_url}: {exc.reason}", file=sys.stderr
        )
        return 4

    uid = result.get("uid", "")
    print(json.dumps({"status": "imported", "uid": uid, "url": result.get("url", "")}))

    if args.screenshot:
        ok = capture_screenshot(
            uid,
            grafana_url=args.grafana_url,
            output=args.screenshot,
            api_key=api_key,
        )
        print(
            json.dumps(
                {
                    "status": "screenshot_captured" if ok else "screenshot_failed",
                    "path": str(args.screenshot),
                }
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
