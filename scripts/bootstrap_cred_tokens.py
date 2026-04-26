#!/usr/bin/env python3
"""Bootstrap pass-store credentials by browser automation.

Visits each service's token-creation page in a Playwright Chromium
session that uses a persistent profile (so 2FA / SSO state survives
across runs). Extracts the token via DOM scrape, pipes it directly into
``pass insert -m <key>`` via subprocess stdin — token bytes never touch
this script's stdout, never get printed, never reach Claude's tool
output.

Per-service status is reported with a redacted summary line; the actual
token values stay in pass-store.

Usage::

    uv run python scripts/bootstrap_cred_tokens.py
    uv run python scripts/bootstrap_cred_tokens.py --only zenodo,osf
    uv run python scripts/bootstrap_cred_tokens.py --dry-run
    uv run python scripts/bootstrap_cred_tokens.py --force  # overwrite existing pass entries

The persistent profile lives at ``~/.config/hapax/playwright-cred-bootstrap/``;
delete it to force fresh logins. Browser runs headed (non-headless) so
the operator can complete 2FA / scope-selection interactively when
needed.

Crossref is intentionally excluded — it is email-based registration
($275-500/year) and not browser-scrapable.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Pass-store keys per service
KEYS = {
    "zenodo": ["zenodo/api-token"],
    "osf": ["osf/api-token"],
    "ia": ["ia/access-key", "ia/secret-key"],
    "bluesky": ["bluesky/operator-app-password", "bluesky/operator-did"],
    "philarchive": ["philarchive/session-cookie"],
}

PROFILE_DIR = Path.home() / ".config/hapax/playwright-cred-bootstrap"
TIMEOUT_MS = 90_000  # 90s per page action — generous for 2FA

ServiceStatus = Literal["ok", "skipped_exists", "skipped_only_filter", "manual_fallback", "error"]


@dataclass
class ServiceResult:
    service: str
    status: ServiceStatus
    note: str = ""


log = logging.getLogger("bootstrap-cred-tokens")


def pass_has(key: str) -> bool:
    """Return True if pass-store already has this key."""
    rc = subprocess.run(
        ["pass", "show", key],
        capture_output=True,
        check=False,
    )
    return rc.returncode == 0


def pass_insert(key: str, token_bytes: bytes) -> None:
    """Pipe ``token_bytes`` directly into ``pass insert -m <key>``.

    ``-m`` is multi-line mode; reads stdin until EOF. No echo.
    capture_output=True so any pass-side output doesn't leak via our stdout.
    """
    proc = subprocess.run(
        ["pass", "insert", "-m", "-f", key],
        input=token_bytes,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        # Don't include stderr — it might echo token bytes
        raise RuntimeError(f"pass insert failed for {key} (rc={proc.returncode})")


# ── Per-service bootstrap functions ─────────────────────────────────


async def bootstrap_zenodo(page, *, dry_run: bool, force: bool) -> ServiceResult:
    key = "zenodo/api-token"
    if not force and pass_has(key):
        return ServiceResult("zenodo", "skipped_exists", f"{key} already in pass-store")

    if dry_run:
        await page.goto(
            "https://zenodo.org/account/settings/applications/tokens/new/",
            wait_until="networkidle",
            timeout=TIMEOUT_MS,
        )
        return ServiceResult("zenodo", "ok", "(dry-run; page reached)")

    try:
        await page.goto(
            "https://zenodo.org/account/settings/applications/tokens/new/",
            wait_until="networkidle",
            timeout=TIMEOUT_MS,
        )
        # Fill name
        await page.fill('input[name="name"]', "hapax-publication-bus")
        # Tick deposit:write + deposit:actions scopes
        for scope in ("deposit:write", "deposit:actions"):
            await page.check(f'input[type="checkbox"][value="{scope}"]')
        # Submit
        await page.click('button[type="submit"]:has-text("Create")')
        await page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
        # Token shown in <code> on confirmation page
        token = await page.eval_on_selector("code", "el => el.textContent.trim()")
        if not token or len(token) < 20:
            return ServiceResult("zenodo", "manual_fallback", "could not locate token in page")
        pass_insert(key, token.encode())
        del token
        return ServiceResult("zenodo", "ok", f"{key} provisioned")
    except Exception as exc:
        return ServiceResult("zenodo", "manual_fallback", f"{type(exc).__name__}")


async def bootstrap_osf(page, *, dry_run: bool, force: bool) -> ServiceResult:
    key = "osf/api-token"
    if not force and pass_has(key):
        return ServiceResult("osf", "skipped_exists", f"{key} already in pass-store")

    if dry_run:
        await page.goto(
            "https://osf.io/settings/tokens/", wait_until="networkidle", timeout=TIMEOUT_MS
        )
        return ServiceResult("osf", "ok", "(dry-run; page reached)")

    try:
        await page.goto(
            "https://osf.io/settings/tokens/", wait_until="networkidle", timeout=TIMEOUT_MS
        )
        await page.click('a:has-text("Create token"), button:has-text("Create token")')
        await page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
        await page.fill('input[name="name"]', "hapax-publication-bus")
        await page.check('input[value="osf.full_write"]')
        await page.click('button:has-text("Create token")')
        await page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
        # Token displayed once in a copyable field
        token = await page.eval_on_selector(
            "input[readonly], code, .token-value",
            "el => (el.value || el.textContent || '').trim()",
        )
        if not token or len(token) < 20:
            return ServiceResult("osf", "manual_fallback", "could not locate token")
        pass_insert(key, token.encode())
        del token
        return ServiceResult("osf", "ok", f"{key} provisioned")
    except Exception as exc:
        return ServiceResult("osf", "manual_fallback", f"{type(exc).__name__}")


async def bootstrap_ia(page, *, dry_run: bool, force: bool) -> ServiceResult:
    keys = ["ia/access-key", "ia/secret-key"]
    if not force and all(pass_has(k) for k in keys):
        return ServiceResult("ia", "skipped_exists", "both ia keys already in pass-store")

    if dry_run:
        await page.goto(
            "https://archive.org/account/s3.php", wait_until="networkidle", timeout=TIMEOUT_MS
        )
        return ServiceResult("ia", "ok", "(dry-run; page reached)")

    try:
        await page.goto(
            "https://archive.org/account/s3.php", wait_until="networkidle", timeout=TIMEOUT_MS
        )
        # IA's s3.php shows existing keys (or button to generate). Common
        # selectors: ``input[id="access"]`` or ``td`` inside the keys table.
        # Try to read whatever's labelled access/secret.
        access = await page.eval_on_selector(
            'input[id*="access"], code:nth-of-type(1)',
            "el => (el.value || el.textContent || '').trim()",
        )
        secret = await page.eval_on_selector(
            'input[id*="secret"], code:nth-of-type(2)',
            "el => (el.value || el.textContent || '').trim()",
        )
        if not access or not secret or len(access) < 8 or len(secret) < 8:
            return ServiceResult(
                "ia",
                "manual_fallback",
                "could not locate access/secret keys (page layout drift?)",
            )
        pass_insert("ia/access-key", access.encode())
        pass_insert("ia/secret-key", secret.encode())
        del access, secret
        return ServiceResult("ia", "ok", "ia/access-key + ia/secret-key provisioned")
    except Exception as exc:
        return ServiceResult("ia", "manual_fallback", f"{type(exc).__name__}")


async def bootstrap_bluesky(page, *, dry_run: bool, force: bool) -> ServiceResult:
    pwd_key = "bluesky/operator-app-password"
    did_key = "bluesky/operator-did"
    if not force and pass_has(pwd_key) and pass_has(did_key):
        return ServiceResult("bluesky", "skipped_exists", "both bluesky keys already in pass-store")

    if dry_run:
        await page.goto(
            "https://bsky.app/settings/app-passwords",
            wait_until="networkidle",
            timeout=TIMEOUT_MS,
        )
        return ServiceResult("bluesky", "ok", "(dry-run; page reached)")

    # Bluesky's SPA + DOM is volatile — flag for manual.
    return ServiceResult(
        "bluesky",
        "manual_fallback",
        "Bluesky SPA + dialog flow brittle for scraping — recommend manual",
    )


async def bootstrap_philarchive(page, *, dry_run: bool, force: bool) -> ServiceResult:
    key = "philarchive/session-cookie"
    if not force and pass_has(key):
        return ServiceResult("philarchive", "skipped_exists", f"{key} already in pass-store")

    if dry_run:
        await page.goto("https://philarchive.org/", wait_until="networkidle", timeout=TIMEOUT_MS)
        return ServiceResult("philarchive", "ok", "(dry-run; page reached)")

    try:
        await page.goto("https://philarchive.org/", wait_until="networkidle", timeout=TIMEOUT_MS)
        cookies = await page.context.cookies("https://philarchive.org")
        # Keep the session/login cookies; pack as Cookie: header value
        rendered = "; ".join(
            f"{c['name']}={c['value']}" for c in cookies if c["domain"].endswith("philarchive.org")
        )
        if not rendered or len(rendered) < 10:
            return ServiceResult(
                "philarchive",
                "manual_fallback",
                "no philarchive.org cookies (not logged in?)",
            )
        pass_insert(key, rendered.encode())
        del rendered
        return ServiceResult("philarchive", "ok", f"{key} provisioned")
    except Exception as exc:
        return ServiceResult("philarchive", "manual_fallback", f"{type(exc).__name__}")


SERVICE_BOOTSTRAPPERS = {
    "zenodo": bootstrap_zenodo,
    "osf": bootstrap_osf,
    "ia": bootstrap_ia,
    "bluesky": bootstrap_bluesky,
    "philarchive": bootstrap_philarchive,
}


# ── Orchestrator ───────────────────────────────────────────────────


async def run(only: list[str] | None, dry_run: bool, force: bool, cdp_url: str | None) -> int:
    from playwright.async_api import async_playwright

    services = only or list(SERVICE_BOOTSTRAPPERS)
    results: list[ServiceResult] = []

    async with async_playwright() as p:
        if cdp_url:
            # Attach to operator's already-running Chrome (with their real
            # logged-in profile). Chrome must be running with
            # --remote-debugging-port=<n> matching this URL's port.
            print(f"→ connecting to operator Chrome via CDP at {cdp_url}", file=sys.stderr)
            browser = await p.chromium.connect_over_cdp(cdp_url)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            close_ctx = False  # don't close operator's browser
        else:
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1280, "height": 900},
            )
            close_ctx = True
        page = await ctx.new_page()

        for service in services:
            if service not in SERVICE_BOOTSTRAPPERS:
                results.append(ServiceResult(service, "error", f"unknown service '{service}'"))
                continue
            print(f"→ {service}: navigating + provisioning...", file=sys.stderr)
            result = await SERVICE_BOOTSTRAPPERS[service](page, dry_run=dry_run, force=force)
            results.append(result)
            print(f"  {result.status}: {result.note}", file=sys.stderr)

        await page.close()
        if close_ctx:
            await ctx.close()

    # Summary
    print("\n=== Bootstrap summary ===", file=sys.stderr)
    print(f"{'service':<12} {'status':<22} note", file=sys.stderr)
    print("-" * 70, file=sys.stderr)
    for r in results:
        print(f"{r.service:<12} {r.status:<22} {r.note}", file=sys.stderr)

    needs_manual = [r for r in results if r.status == "manual_fallback"]
    if needs_manual:
        print("\nServices needing manual fallback:", file=sys.stderr)
        for r in needs_manual:
            print(f"  - {r.service}: {r.note}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        help="Comma-separated subset (e.g., zenodo,osf)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Visit pages but don't generate or store tokens",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing pass-store entries",
    )
    parser.add_argument(
        "--cdp-url",
        default=None,
        help=(
            "Attach to a running Chrome via CDP (e.g. http://localhost:9222) "
            "instead of launching a Playwright-managed Chromium. Use this to "
            "leverage operator's already-logged-in Chrome profile. Chrome "
            "must be started with --remote-debugging-port=<port>."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(levelname)s %(message)s",
    )

    return asyncio.run(
        run(
            only=args.only,
            dry_run=args.dry_run,
            force=args.force,
            cdp_url=args.cdp_url,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
