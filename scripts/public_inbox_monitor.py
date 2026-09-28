#!/usr/bin/env python3
"""Read-only route census and metadata-only alerting for public inboxes.

The Gmail watcher never requests a message body. State contains Gmail IDs and
history cursors only; notification text contains a route address and count.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import socket
import subprocess
import tempfile
from collections import deque
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

API = "https://api.cloudflare.com/client/v4"
DOMAINS = frozenset({"hapaxresearch.com", "hapaxromanum.com", "hapaxrad.com", "hapaxrnd.com"})
PUBLIC_ROOTS = (
    "https://raw.githubusercontent.com/hapax-systems/.github/main/profile/README.md",
    "https://raw.githubusercontent.com/hapax-systems/hapax-constitution/main/README.md",
    "https://raw.githubusercontent.com/hapax-systems/hapax-constitution/main/SUPPORT.md",
    "https://raw.githubusercontent.com/hapax-systems/hapax-constitution/main/SECURITY.md",
)
ADDRESS = re.compile(
    r"[A-Z0-9._%+-]+@(?:hapaxresearch|hapaxromanum|hapaxrad|hapaxrnd)\.com\b", re.I
)
STATE = Path.home() / "hapax-state/public-inbox-monitor/state.json"
WORKER_RECIPIENT = "hrl-han@hapaxresearch.com"
KNOWN_INBOXES = frozenset(
    {
        "contact@hapaxresearch.com",
        "rlk@hapaxresearch.com",
        "contact@hapaxromanum.com",
        WORKER_RECIPIENT,
    }
)


class MonitorError(Exception):
    """Failure safe to report without provider or foreign-message text."""


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.hrefs.update(value for key, value in attrs if key == "href" and value)


def _secret(name: str) -> str:
    result = subprocess.run(["hapax-secret", name], capture_output=True, text=True, check=False)
    if result.returncode or not result.stdout.strip():
        raise MonitorError("Cloudflare credential unavailable")
    return result.stdout.strip()


def _json_get(client: httpx.Client, path: str, *, params: dict | None = None) -> dict:
    try:
        response = client.get(path, params=params)
        response.raise_for_status()
        data = response.json()
        if not data.get("success") or not isinstance(data.get("result"), list):
            raise ValueError
        return data
    except (httpx.HTTPError, ValueError) as exc:
        raise MonitorError("Cloudflare route read failed") from exc


def _pages(client: httpx.Client, path: str) -> list[dict]:
    result: list[dict] = []
    page = 1
    while True:
        data = _json_get(client, path, params={"page": page, "per_page": 100})
        result.extend(data["result"])
        info = data.get("result_info") or {}
        if page >= info.get("total_pages", 1):
            return result
        page += 1
        if page > 100:
            raise MonitorError("Cloudflare route pagination exceeded limit")


def _routing_settings(client: httpx.Client, zone_id: str) -> dict:
    try:
        response = client.get(f"/zones/{zone_id}/email/routing")
        response.raise_for_status()
        data = response.json()
        if not data.get("success") or not isinstance(data.get("result"), dict):
            raise ValueError
        return data["result"]
    except (httpx.HTTPError, ValueError) as exc:
        raise MonitorError("Cloudflare routing-settings read failed") from exc


def cloudflare_routes() -> dict[str, str]:
    """Return every enabled literal address and its action; never destinations."""
    token = _secret("cloudflare-api-api_token")
    routes: dict[str, str] = {}
    zones_seen: set[str] = set()
    with httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for zone in _pages(client, "/zones"):
            if zone["name"] not in DOMAINS:
                continue
            zones_seen.add(zone["name"])
            settings = _routing_settings(client, zone["id"])
            rules = _pages(client, f"/zones/{zone['id']}/email/routing/rules")
            if any(rule.get("enabled") for rule in rules) and (
                settings.get("enabled") is not True or settings.get("status") != "ready"
            ):
                raise MonitorError("Enabled mail rule in an unready routing zone")
            for rule in rules:
                if not rule.get("enabled"):
                    continue
                actions = [a.get("type") for a in rule.get("actions", [])]
                matchers = rule.get("matchers", [])
                if len(actions) != 1 or actions[0] not in {"forward", "worker"}:
                    raise MonitorError("Unsupported enabled Cloudflare mail action")
                if actions[0] == "worker" and rule["actions"][0].get("value") != [
                    "han-mail-receive"
                ]:
                    raise MonitorError("HAN worker route points to unexpected worker")
                if (
                    len(matchers) != 1
                    or matchers[0].get("type") != "literal"
                    or matchers[0].get("field") != "to"
                ):
                    raise MonitorError("Unsupported enabled Cloudflare mail matcher")
                address = str(matchers[0].get("value", "")).lower()
                if (
                    address in routes
                    or not ADDRESS.fullmatch(address)
                    or not address.endswith("@" + zone["name"])
                ):
                    raise MonitorError("Duplicate or invalid enabled Cloudflare mail route")
                routes[address] = actions[0]
    if zones_seen != DOMAINS:
        raise MonitorError("Cloudflare zone inventory incomplete")
    return routes


def active_site_roots() -> tuple[str, ...]:
    """Include each zone with live DNS; fail on temporary resolver errors."""
    roots = []
    absent = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}
    for domain in sorted(DOMAINS):
        try:
            socket.getaddrinfo(domain, 443)
        except socket.gaierror as exc:
            if exc.errno in absent:
                continue
            raise MonitorError("Public-site DNS lookup failed") from exc
        roots.append(f"https://{domain}/")
    return tuple(roots)


def published_addresses(
    fetch: Callable[[str], str], roots: tuple[str, ...] = PUBLIC_ROOTS
) -> dict[str, list[str]]:
    """Crawl live owned sites and fixed public GitHub contact surfaces."""
    found: dict[str, list[str]] = {}
    queue = deque(roots)
    seen: set[str] = set()
    while queue:
        url = queue.popleft()
        if url in seen:
            continue
        if len(seen) >= 100:
            raise MonitorError("Public-site crawl exceeded limit")
        seen.add(url)
        try:
            body = fetch(url)
        except Exception as exc:
            raise MonitorError("Public surface unavailable for inbox census") from exc
        for address in sorted(set(x.lower() for x in ADDRESS.findall(body))):
            found.setdefault(address, []).append(url)
        if urlparse(url).hostname not in DOMAINS:
            continue
        parser = Links()
        parser.feed(body)
        for href in parser.hrefs:
            target = urljoin(url, href).split("#", 1)[0]
            if urlparse(target).hostname in DOMAINS and target not in seen:
                queue.append(target)
    return found


def check_routes(routes: dict[str, str], published: dict[str, list[str]]) -> list[str]:
    required = set(published) | KNOWN_INBOXES
    failures = [
        f"missing enabled route: {address}" for address in sorted(required) if address not in routes
    ]
    if routes.get(WORKER_RECIPIENT) not in {None, "worker"}:
        failures.append("HAN intake must use worker route")
    failures += [
        f"worker intake unsupported: {address}"
        for address, action in sorted(routes.items())
        if action == "worker" and address != WORKER_RECIPIENT
    ]
    return failures


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.parent.stat().st_mode & 0o077:
        raise MonitorError("Inbox monitor state directory is not private")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {"history_id": "", "pending_ids": []}
    if path.is_symlink():
        raise MonitorError("Inbox monitor state is a symlink")
    try:
        state = json.loads(path.read_text())
        if not isinstance(state["history_id"], str) or not isinstance(state["pending_ids"], list):
            raise ValueError
        if not all(isinstance(mid, str) for mid in state["pending_ids"]):
            raise ValueError
        return state
    except (OSError, ValueError, KeyError) as exc:
        raise MonitorError("Inbox monitor state invalid; no cursor reset") from exc


def _history(service: object, cursor: str) -> tuple[list[str], str]:
    ids: list[str] = []
    page_token = None
    end = cursor
    while True:
        page = (
            service.users()
            .history()
            .list(
                userId="me",
                startHistoryId=cursor,
                historyTypes=["messageAdded"],
                pageToken=page_token,
            )
            .execute()
        )
        for record in page.get("history", []):
            ids.extend(entry["message"]["id"] for entry in record.get("messagesAdded", []))
        end = str(page.get("historyId", end))
        page_token = page.get("nextPageToken")
        if not page_token:
            return list(dict.fromkeys(ids)), end


def _recipients(message: dict) -> set[str]:
    headers = (message.get("payload") or {}).get("headers") or []
    values = "\n".join(
        str(header.get("value", ""))
        for header in headers
        if str(header.get("name", "")).lower() in {"to", "cc", "x-original-to", "x-forwarded-to"}
    )
    return {item.lower() for item in ADDRESS.findall(values)}


def send_public_notification(title: str, message: str, **_options: object) -> bool:
    """Acknowledge only ntfy server acceptance on the HAN mail topic."""
    base = os.environ.get("NTFY_BASE_URL", "").rstrip("/")
    if not base:
        return False
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                base + "/",
                json={
                    "topic": "hapax-han-mail",
                    "title": title,
                    "message": message,
                    "priority": 4,
                    "tags": ["mail"],
                },
            )
        return 200 <= response.status_code < 300
    except (httpx.HTTPError, ValueError):
        return False


def watch_gmail(
    service: object, routes: dict[str, str], state_path: Path, notify: Callable[..., bool]
) -> int:
    """Persist IDs before cursor advancement; retry until alert acceptance."""
    forwarded = {address for address, action in routes.items() if action == "forward"}
    if not forwarded:
        raise MonitorError("No forwarding routes found")
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state_path.parent.is_symlink() or state_path.parent.stat().st_mode & 0o077:
        raise MonitorError("Inbox monitor state directory is not private")
    with (state_path.parent / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = _read_state(state_path)
        if not state["history_id"]:
            state["history_id"] = str(
                service.users().getProfile(userId="me", fields="historyId").execute()["historyId"]
            )
            _write_state(state_path, state)
            return 0
        new_ids, cursor = _history(service, state["history_id"])
        state["pending_ids"] = list(dict.fromkeys([*state["pending_ids"], *new_ids]))
        state["history_id"] = cursor
        _write_state(state_path, state)
        alerted = 0
        for mid in list(state["pending_ids"]):
            message = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["To", "Cc", "X-Original-To", "X-Forwarded-To"],
                    fields="id,payload/headers",
                )
                .execute()
            )
            recipients = _recipients(message) & forwarded
            if recipients:
                # A route address and count are enough; no sender, subject, snippet or body.
                title = "Public inbox mail"
                summary = "New mail to " + ", ".join(sorted(recipients))
                if not notify(title, summary, priority="high", tags=["mail"], technical=False):
                    raise MonitorError("Inbox alert was not accepted; pending ID retained")
                alerted += 1
            state["pending_ids"].remove(mid)
            _write_state(state_path, state)
        return alerted


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check", "watch"])
    args = parser.parse_args()
    try:
        routes = cloudflare_routes()
        if args.command == "check":
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:

                def fetch(url: str) -> str:
                    response = client.get(url)
                    response.raise_for_status()
                    return response.text

                published = published_addresses(fetch, (*active_site_roots(), *PUBLIC_ROOTS))
            failures = check_routes(routes, published)
            print(
                json.dumps(
                    {
                        "zones": len(DOMAINS),
                        "routes": routes,
                        "published": published,
                        "failures": failures,
                    },
                    sort_keys=True,
                )
            )
            return int(bool(failures))
        from shared.google_auth import build_service

        service = build_service(
            "gmail", "v1", ["https://www.googleapis.com/auth/gmail.readonly"], interactive=False
        )
        if service is None:
            raise MonitorError("Gmail credential unavailable")
        print(
            json.dumps({"alerted": watch_gmail(service, routes, STATE, send_public_notification)})
        )
        return 0
    except Exception as exc:
        print(
            f"Public inbox monitor stopped: {exc if isinstance(exc, MonitorError) else type(exc).__name__}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
