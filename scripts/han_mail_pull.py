#!/usr/bin/env python3
"""Pull HAN mail into a private foreign-data quarantine. No body interpretation.

Run from the repository with ``uv run python -m scripts.han_mail_pull``.
Credentials are obtained in process from hapax-secret, never from CLI arguments.
"""

from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
import time
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from email import policy
from email.parser import BytesHeaderParser
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

MAX_BYTES = 256 * 1024
POLL_SECONDS = 300
LIMITS = {"lists": 288, "gets": 500, "deletes": 500}
HASH = re.compile(r"[0-9a-f]{64}\Z")
QUARANTINE = Path.home() / "hapax-state/han-mail/quarantine"
DEPLOYMENT = Path(__file__).resolve().parents[1] / "workers/han-mail-receive/deployment.toml"


class IntakeError(Exception):
    """Safe fixed-string diagnostic, without foreign text or credentials."""


class KV(Protocol):
    def list_keys(self, cursor: str) -> tuple[list[dict], str]: ...
    def get_value(self, key: str) -> bytes | None: ...
    def delete_value(self, key: str) -> None: ...


def fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_directory(directory: Path) -> None:
    if not directory.exists():
        private_directory(directory.parent)
        directory.mkdir(mode=0o700)
        fsync_directory(directory.parent)
    if directory.is_symlink() or not directory.is_dir():
        raise IntakeError("Quarantine path must be a real private directory")


def atomic_write(path: Path, value: bytes) -> None:
    """A completed call means both file bytes and rename are on durable storage."""
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n").encode())


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists() and default is not None:
        return default.copy()
    try:
        if path.is_symlink():
            raise ValueError
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, OSError) as exc:
        raise IntakeError("Invalid local intake state; preserve files and investigate") from exc


def safe_text(value: object, limit: int = 240) -> str:
    return " ".join(str(value).split())[:limit]


def subject_only(raw: bytes) -> str:
    # Pass ONLY the bounded header block to the parser, never the body or MIME parts.
    boundaries = [i for marker in (b"\r\n\r\n", b"\n\n") if (i := raw.find(marker)) >= 0]
    if not boundaries or min(boundaries) > 32768:
        return "(subject unavailable)"
    headers = BytesHeaderParser(policy=policy.default).parsebytes(
        raw[: min(boundaries)] + b"\r\n\r\n"
    )
    try:
        return safe_text(headers.get("Subject", "(no subject)"))
    except (ValueError, LookupError):
        return "(subject unavailable)"


def verify_local(path: Path, key: str, size: int) -> None:
    if path.is_symlink():
        raise IntakeError("Refusing symlink in quarantine")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if os.fstat(stream.fileno()).st_size != size or digest != key:
            raise IntakeError("Local quarantine hash mismatch; remote copy retained")
        os.fsync(stream.fileno())
    fsync_directory(path.parent)


def store_item(root: Path, key: str, raw: bytes, metadata: dict) -> dict:
    if not HASH.fullmatch(key) or len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != key:
        raise IntakeError("Remote message hash or size mismatch; remote copy retained")
    if metadata.get("schema") != 1 or metadata.get("size") != len(raw):
        raise IntakeError("Remote metadata schema or size mismatch; remote copy retained")
    raw_path = root / f"{key}.eml"
    item_path = root / f"{key}.json"
    if not raw_path.exists():
        atomic_write(raw_path, raw)
    verify_local(raw_path, key, len(raw))
    if item_path.exists():
        item = read_json(item_path)
        if (
            item.get("sha256") != key
            or item.get("size") != len(raw)
            or item.get("type") != "han.mail.foreign-data"
        ):
            raise IntakeError("Local metadata mismatch; remote copy retained")
        # Re-fsync a prior publication too, including recovery after interrupted rename.
        with item_path.open("rb") as stream:
            os.fsync(stream.fileno())
        fsync_directory(root)
        return item
    auth = metadata.get("auth", {})
    if not isinstance(auth, dict):
        raise IntakeError("Invalid authentication metadata; remote copy retained")
    allowed = {"pass", "fail", "softfail", "neutral", "none", "temperror", "permerror", "unknown"}
    item = {
        "type": "han.mail.foreign-data",
        "schema": 1,
        "trust": "foreign-untrusted",
        "body_access": "operator-only",
        "sender": safe_text(metadata.get("sender", "(unknown)"), 254),
        "recipient": safe_text(metadata.get("recipient", "(unknown)"), 254),
        "subject": subject_only(raw),
        "received_at": safe_text(metadata.get("received_at", "(unknown)"), 40),
        "auth": {
            name: auth.get(name) if auth.get(name) in allowed else "unknown"
            for name in ("spf", "dkim", "dmarc")
        },
        "auth_verdict": "unverified (header observations only)",
        "size": len(raw),
        "sha256": key,
        "kv_key": key,
        "raw_file": f"{key}.eml",
        "notified": False,
        "notification_attempts": 0,
    }
    write_json(item_path, item)
    return item


class Budget:
    """Persistent reservations before requests; crashes consume rather than reset quota."""

    def __init__(self, root: Path, clock: Callable[[], float] = time.time):
        self.path = root / "poll-state.json"
        self.clock = clock
        self.state = read_json(self.path, {})

    def reserve(self, operation: str) -> bool:
        now = self.clock()
        day = datetime.fromtimestamp(now, UTC).date().isoformat()
        old_day = self.state.get("day", "")
        if day < old_day:
            return False  # Clock rollback must not reset a spent budget.
        if day > old_day:
            self.state = {
                "day": day,
                "last_list": self.state.get("last_list", 0),
                "cursor": self.state.get("cursor", ""),
            }
        if self.state.get(operation, 0) >= LIMITS[operation]:
            return False
        if operation == "lists":
            if now - self.state.get("last_list", 0) < POLL_SECONDS:
                return False
            self.state["last_list"] = now
        self.state[operation] = self.state.get(operation, 0) + 1
        write_json(self.path, self.state)
        return True

    def cursor(self, value: str) -> None:
        self.state["cursor"] = value
        write_json(self.path, self.state)


def pull_item(kv: KV, root: Path, key: str, metadata: dict, budget: Budget) -> bool:
    if not budget.reserve("gets"):
        return False
    raw = kv.get_value(key)
    if raw is None:  # Eventually consistent list after an earlier successful delete.
        return True
    store_item(root, key, raw, metadata)
    # This order is mutation-tested: verified raw + durable typed metadata BEFORE delete.
    if budget.reserve("deletes"):
        kv.delete_value(key)
    return True


def send_mail_notification(title: str, message: str, **desktop_options) -> bool:
    """One ntfy attempt, then desktop fallback; only acceptance settles pending mail."""
    # Follow the council's NTFY_BASE_URL convention; appendix binds only on tailnet.
    base_url = os.environ.get("NTFY_BASE_URL", "http://100.85.131.41:8090").rstrip("/")
    try:
        # JSON preserves Unicode without putting foreign text in HTTP headers.
        # No redirects, proxies or immediate retries for this private notice.
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                base_url + "/",
                json={
                    "topic": "hapax-han-mail",
                    "title": title,
                    "message": message,
                    "priority": 4,
                    "tags": ["mail"],
                },
            )
        if 200 <= response.status_code < 300:
            return True
    except (httpx.HTTPError, ValueError):
        pass

    try:
        from shared.notify import send_notification

        return send_notification(title, message, **desktop_options)
    except Exception:
        # A broken desktop channel must leave the durable batch available for retry.
        return False


def notify_pending(root: Path, notify: Callable[..., bool]) -> int:
    """Surface one summary for the complete pending batch, at most once per poll."""
    pending = []
    for path in sorted(root.glob("*.json")):
        if not HASH.fullmatch(path.stem):
            continue
        item = read_json(path)
        if item.get("notified"):
            continue
        verify_local(root / f"{path.stem}.eml", path.stem, item["size"])
        item["notification_attempts"] += 1
        write_json(path, item)
        pending.append((path, item))
    if not pending:
        return 0

    # Keep the existing deterministic hash order; display only the first item's metadata.
    first_path, first = pending[0]
    count = len(pending)
    attempt = max(item["notification_attempts"] for _, item in pending)
    title = f"HAN mail — {count} pending foreign item(s) [{first_path.stem[:12]}]"
    if attempt > 1:
        title += f" (delivery retry {attempt})"
    # Explicit allowlist: no raw bytes, path dereference, body or MIME excerpt.
    message = "\n".join(
        [
            f"Sender: {html.escape(first['sender'])}",
            f"Subject: {html.escape(first['subject'])}",
            f"Auth: {first['auth_verdict']}; "
            + ", ".join(
                f"{name.upper()}={first['auth'][name]}" for name in ("spf", "dkim", "dmarc")
            ),
            f"Received: {html.escape(first['received_at'])}",
        ]
    )
    if notify(title, message, priority="high", tags=["mail"], technical=False):
        for path, item in pending:
            item["notified"] = True
            write_json(path, item)
        return count
    return 0


def run_once(
    kv: KV, root: Path, notify: Callable[..., bool], clock: Callable[[], float] = time.time
) -> dict:
    private_directory(root)
    if root.stat().st_mode & 0o077:
        raise IntakeError("Quarantine must have mode 0700")
    with (root / ".pull.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget = Budget(root, clock)
        pulled = 0
        failure = None
        try:
            if budget.reserve("lists"):
                keys, cursor = kv.list_keys(budget.state.get("cursor", ""))
                complete = True
                for entry in keys:
                    key = entry.get("name", "")
                    if not HASH.fullmatch(key):  # Never fetch rate state as foreign mail.
                        continue
                    if not pull_item(kv, root, key, entry.get("metadata", {}), budget):
                        complete = False
                        break
                    pulled += 1
                if complete:
                    budget.cursor(cursor)
        except (IntakeError, OSError) as exc:
            failure = exc
        # Durable pending notifications survive deletes, outages and process crashes.
        sent = notify_pending(root, notify)
        if failure is not None:
            raise failure
        return {"pulled": pulled, "notified": sent}


class CloudflareKV:
    def __init__(self, namespace: str):
        def secret(name: str) -> str:
            result = subprocess.run(
                ["hapax-secret", name], capture_output=True, text=True, check=False
            )
            if result.returncode or not result.stdout.strip():
                raise IntakeError("Credential unavailable from hapax-secret")
            return result.stdout.strip()

        account = secret("cloudflare-api-account_id")
        self.client = httpx.Client(
            base_url="https://api.cloudflare.com/client/v4",
            headers={"Authorization": "Bearer " + secret("cloudflare-api-api_token")},
            timeout=30,
            follow_redirects=False,
        )
        self.base = f"/accounts/{account}/storage/kv/namespaces/{namespace}"
        subscriptions = self._json("GET", f"/accounts/{account}/subscriptions")["result"]
        if any("worker" in json.dumps(x.get("rate_plan", {})).lower() for x in subscriptions):
            raise IntakeError(
                "STOP: Workers subscription present; re-establish zero-spend authorization"
            )

    def _json(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not data.get("success"):
                raise ValueError
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise IntakeError(
                "Cloudflare request refused; no automatic retry or plan upgrade"
            ) from exc

    def list_keys(self, cursor: str) -> tuple[list[dict], str]:
        params = {"limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        data = self._json("GET", self.base + "/keys", params=params)
        return data["result"], data.get("result_info", {}).get("cursor", "")

    def get_value(self, key: str) -> bytes | None:
        try:
            with self.client.stream(
                "GET", self.base + "/values/" + quote(key, safe="")
            ) as response:
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise IntakeError("Remote value exceeds message size cap")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise IntakeError("Cloudflare value request refused; remote copy retained") from exc

    def delete_value(self, key: str) -> None:
        self._json("DELETE", self.base + "/values/" + quote(key, safe=""))


def main() -> int:
    os.umask(0o077)
    try:
        # Fixed production path: no CLI switch can redirect mail into an agent-read repo/vault.
        if QUARANTINE.resolve() != QUARANTINE:
            raise IntakeError("Quarantine path must not resolve through symlinks")
        config = tomllib.loads(DEPLOYMENT.read_text())
        kv = CloudflareKV(config["namespace_id"])
        result = run_once(kv, QUARANTINE, send_mail_notification)
        print(json.dumps(result))  # Counts only; no foreign metadata in journal output.
        return 0
    except IntakeError as exc:
        print(f"HAN mail pull stopped: {exc}")
        return 1
    except (OSError, ValueError, KeyError):
        print(
            "HAN mail pull stopped; preserve quarantine and inspect service/API configuration. No automatic retry or upgrade."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
