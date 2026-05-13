"""omg.lol API client wrapper — ytb-OMG1.

Single wrapper around the omg.lol REST API used by every omg.lol-
writing daemon in the outreach / surface-publishing epic. Handles
credential loading (`pass show omg-lol/api-key`), exponential-backoff
retry on 5xx + 429, silent-skip on persistent 401/403, and per-call
Prometheus accounting so `ytb-OMG9` infrastructure-observability can
correlate traffic to upstream outcomes.

Stateless across requests; callers hold one instance per daemon.

Spec: API docs at https://api.omg.lol/. Endpoint paths mirror the
published REST surface. This module doesn't attempt to cover the full
15-collection Postman surface — it covers the minimum-useful subset
used by ytb-OMG2/3/4/6/7/8 and ytb-OMG-CREDITS. New endpoints can be
added by mirroring the pattern of existing methods.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

OMG_LOL_API_BASE = "https://api.omg.lol"
DEFAULT_PASS_KEY = "omg-lol/api-key"
DEFAULT_ADDRESS = "hapax"


@dataclass
class ApiCallOutcome:
    """Observability payload per HTTP call. Mirrors the shape used by
    `shared.youtube_api_client.ApiCallOutcome` so downstream metric
    consumers can treat the two surfaces uniformly."""

    endpoint: str
    result: str  # "ok" | "auth_failed" | "rate_limited" | "server_error" | "disabled" | "skipped"
    http_status: int | None
    retries: int = 0
    latency_s: float = 0.0


class OmgLolHttpError(Exception):
    """Raised by `_execute` when a non-retriable HTTP response indicates
    a real client-side mistake (4xx that isn't 401/403/429). Surfaces
    the status, endpoint, and response body so the caller can decide
    whether to abort the enclosing operation or continue silently."""

    def __init__(self, *, status: int, endpoint: str, message: str) -> None:
        super().__init__(f"omg.lol {endpoint} → HTTP {status}: {message}")
        self.status = status
        self.endpoint = endpoint
        self.message = message


try:
    from prometheus_client import Counter

    _API_CALLS_TOTAL = Counter(
        "hapax_broadcast_omg_api_calls_total",
        "omg.lol API call attempts and their outcomes.",
        ["endpoint", "result"],
    )

    def _record_metric(outcome: ApiCallOutcome) -> None:
        _API_CALLS_TOTAL.labels(endpoint=outcome.endpoint, result=outcome.result).inc()
except ImportError:

    def _record_metric(outcome: ApiCallOutcome) -> None:
        log.debug("prometheus_client unavailable; metric dropped")


def _load_api_key(pass_key: str) -> str | None:
    """Load the omg.lol API key from the operator's `pass` store.

    Returns None when `pass show` fails (no key, pass not initialized,
    gpg-agent unavailable) — caller handles the disabled path.
    """
    try:
        result = subprocess.run(
            ["pass", "show", pass_key],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.warning("pass show failed (%s): %s", pass_key, e)
        return None
    if result.returncode != 0:
        log.warning(
            "pass show returned %d for %s: %s", result.returncode, pass_key, result.stderr.strip()
        )
        return None
    return result.stdout.strip() or None


class OmgLolClient:
    """Resilient omg.lol REST client.

    Usage::

        client = OmgLolClient()
        resp = client.post_status("hapax", content="live now", emoji="📻")
        if resp:
            print(resp["response"]["id"])

    Endpoint methods return parsed JSON on success or None on
    disabled / persistent 4xx / exhausted retries. Callers should
    treat None as a no-op (silent-skip).
    """

    def __init__(
        self,
        address: str = DEFAULT_ADDRESS,
        pass_key: str = DEFAULT_PASS_KEY,
        max_retries: int = 3,
        backoff_base_s: float = 1.0,
        timeout_s: float = 15.0,
    ) -> None:
        self.address = address
        self._pass_key = pass_key
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._timeout_s = timeout_s
        self._api_key = _load_api_key(pass_key)
        self._session: Any = requests.Session() if self._api_key else None

    @property
    def enabled(self) -> bool:
        return self._api_key is not None and self._session is not None

    @property
    def api_key(self) -> str | None:
        """Bearer token loaded from pass, for publication-bus adapters."""
        return self._api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _execute(
        self,
        method: str,
        path: str,
        *,
        endpoint: str,
        json_body: dict | None = None,
        text_body: str | None = None,
    ) -> dict | None:
        if not self.enabled:
            log.warning("omg.lol client disabled; skipping %s", endpoint)
            _record_metric(ApiCallOutcome(endpoint=endpoint, result="disabled", http_status=None))
            return None

        url = f"{OMG_LOL_API_BASE}{path}"
        started = time.time()
        last_status: int | None = None

        for attempt in range(self._max_retries + 1):
            try:
                if text_body is not None:
                    request_headers = {
                        **self._headers(),
                        "Content-Type": "text/plain; charset=utf-8",
                    }
                    resp = self._session.request(
                        method=method,
                        url=url,
                        headers=request_headers,
                        data=text_body.encode("utf-8"),
                        timeout=self._timeout_s,
                    )
                else:
                    resp = self._session.request(
                        method=method,
                        url=url,
                        headers=self._headers(),
                        json=json_body,
                        timeout=self._timeout_s,
                    )
            except requests.RequestException as e:
                log.warning("omg.lol %s network error (attempt %d): %s", endpoint, attempt, e)
                if attempt < self._max_retries:
                    time.sleep(self._backoff_base_s * (2**attempt))
                    continue
                _record_metric(
                    ApiCallOutcome(
                        endpoint=endpoint,
                        result="network_error",
                        http_status=None,
                        retries=attempt,
                        latency_s=time.time() - started,
                    )
                )
                return None

            status = resp.status_code
            last_status = status

            if 200 <= status < 300:
                _record_metric(
                    ApiCallOutcome(
                        endpoint=endpoint,
                        result="ok",
                        http_status=status,
                        retries=attempt,
                        latency_s=time.time() - started,
                    )
                )
                try:
                    return resp.json()
                except ValueError:
                    log.warning("omg.lol %s returned 2xx but non-JSON body", endpoint)
                    return {"raw": resp.text}

            if status in (401, 403):
                log.warning(
                    "omg.lol %s auth failure (HTTP %d); silent-skip — operator must re-verify pass key",
                    endpoint,
                    status,
                )
                _record_metric(
                    ApiCallOutcome(
                        endpoint=endpoint,
                        result="auth_failed",
                        http_status=status,
                        retries=attempt,
                        latency_s=time.time() - started,
                    )
                )
                return None

            if status == 429:
                retry_after = float(resp.headers.get("Retry-After", "0") or 0)
                delay = max(retry_after, self._backoff_base_s * (2**attempt))
                log.info("omg.lol %s rate-limited (HTTP 429); sleeping %.1fs", endpoint, delay)
                if attempt < self._max_retries:
                    time.sleep(delay)
                    continue
                _record_metric(
                    ApiCallOutcome(
                        endpoint=endpoint,
                        result="rate_limited",
                        http_status=status,
                        retries=attempt,
                        latency_s=time.time() - started,
                    )
                )
                return None

            if status >= 500:
                log.warning(
                    "omg.lol %s server error (HTTP %d attempt %d)", endpoint, status, attempt
                )
                if attempt < self._max_retries:
                    time.sleep(self._backoff_base_s * (2**attempt))
                    continue
                _record_metric(
                    ApiCallOutcome(
                        endpoint=endpoint,
                        result="server_error",
                        http_status=status,
                        retries=attempt,
                        latency_s=time.time() - started,
                    )
                )
                return None

            # Non-retriable 4xx other than 401/403/429 — log + metric, return None.
            # (Could raise OmgLolHttpError if stricter callers need to abort,
            # but None fits the silent-skip pattern the rest of this module uses.)
            log.warning("omg.lol %s client error (HTTP %d): %s", endpoint, status, resp.text[:200])
            _record_metric(
                ApiCallOutcome(
                    endpoint=endpoint,
                    result="client_error",
                    http_status=status,
                    retries=attempt,
                    latency_s=time.time() - started,
                )
            )
            return None

        # Unreachable — the loop returns in every branch. Kept for type checker.
        _record_metric(
            ApiCallOutcome(
                endpoint=endpoint,
                result="exhausted",
                http_status=last_status,
                retries=self._max_retries + 1,
                latency_s=time.time() - started,
            )
        )
        return None

    # ── Address info ──────────────────────────────────────────────────

    def address_info_public(self, address: str) -> dict | None:
        return self._execute("GET", f"/address/{address}/info", endpoint="address.info.public")

    def address_info_private(self, address: str) -> dict | None:
        return self._execute("GET", f"/account/{address}/info", endpoint="address.info.private")

    # ── Now page ──────────────────────────────────────────────────────

    def get_now(self, address: str) -> dict | None:
        return self._execute("GET", f"/address/{address}/now", endpoint="address.now.get")

    def set_now(self, address: str, *, content: str, listed: bool = True) -> dict | None:
        return self._execute(
            "POST",
            f"/address/{address}/now",
            endpoint="address.now.set",
            json_body={"content": content, "listed": 1 if listed else 0},
        )

    # ── Web page ──────────────────────────────────────────────────────

    def get_web(self, address: str) -> dict | None:
        return self._execute("GET", f"/address/{address}/web", endpoint="address.web.get")

    def set_web(self, address: str, *, content: str, publish: bool = True) -> dict | None:
        return self._execute(
            "POST",
            f"/address/{address}/web",
            endpoint="address.web.set",
            json_body={"content": content, "publish": publish, "type": "HTML"},
        )

    # ── Statuslog ─────────────────────────────────────────────────────

    def get_statuses(self, address: str) -> dict | None:
        return self._execute(
            "GET", f"/address/{address}/statuses", endpoint="address.statuses.list"
        )

    def get_status(self, address: str, status_id: str) -> dict | None:
        return self._execute(
            "GET",
            f"/address/{address}/statuses/{status_id}",
            endpoint="address.statuses.get",
        )

    def post_status(
        self,
        address: str,
        *,
        content: str,
        emoji: str | None = None,
        external_url: str | None = None,
        skip_mastodon_post: bool = False,
    ) -> dict | None:
        body: dict[str, Any] = {"content": content}
        if emoji is not None:
            body["emoji"] = emoji
        if external_url is not None:
            body["external_url"] = external_url
        if skip_mastodon_post:
            body["skip_mastodon_post"] = True
        return self._execute(
            "POST",
            f"/address/{address}/statuses",
            endpoint="address.statuses.post",
            json_body=body,
        )

    def update_status(
        self,
        address: str,
        status_id: str,
        *,
        content: str | None = None,
        emoji: str | None = None,
    ) -> dict | None:
        body: dict[str, Any] = {"id": status_id}
        if content is not None:
            body["content"] = content
        if emoji is not None:
            body["emoji"] = emoji
        return self._execute(
            "PATCH",
            f"/address/{address}/statuses",
            endpoint="address.statuses.update",
            json_body=body,
        )

    def get_bio(self, address: str) -> dict | None:
        return self._execute(
            "GET", f"/address/{address}/statuses/bio", endpoint="address.statuses.bio.get"
        )

    def set_bio(self, address: str, *, content: str) -> dict | None:
        return self._execute(
            "POST",
            f"/address/{address}/statuses/bio",
            endpoint="address.statuses.bio.set",
            json_body={"content": content},
        )

    # ── Weblog ────────────────────────────────────────────────────────

    def list_entries(self, address: str) -> dict | None:
        return self._execute(
            "GET", f"/address/{address}/weblog/entries", endpoint="address.weblog.list"
        )

    def get_entry(self, address: str, entry_id: str) -> dict | None:
        return self._execute(
            "GET",
            f"/address/{address}/weblog/entry/{entry_id}",
            endpoint="address.weblog.get",
        )

    def set_entry(self, address: str, entry_id: str, *, content: str) -> dict | None:
        # omg.lol weblog API expects raw markdown body (Content-Type:
        # text/plain), NOT a JSON-wrapped {"entry": ...} payload. The
        # JSON envelope causes the server to save the entry but parse
        # nothing — title/body land empty, slug becomes "untitled".
        # Verified 2026-04-25 via direct curl comparison.
        return self._execute(
            "POST",
            f"/address/{address}/weblog/entry/{entry_id}",
            endpoint="address.weblog.set",
            text_body=content,
        )

    def delete_entry(self, address: str, entry_id: str) -> dict | None:
        return self._execute(
            "DELETE",
            f"/address/{address}/weblog/delete/{entry_id}",
            endpoint="address.weblog.delete",
        )

    def latest_post(self, address: str) -> dict | None:
        return self._execute(
            "GET",
            f"/address/{address}/weblog/post/latest",
            endpoint="address.weblog.latest",
        )

    def get_weblog_config(self, address: str) -> dict | None:
        return self._execute(
            "GET",
            f"/address/{address}/weblog/configuration",
            endpoint="address.weblog.config.get",
        )

    def set_weblog_config(self, address: str, *, configuration: str) -> dict | None:
        # The weblog configuration endpoint expects the raw configuration file
        # as the request body, not a JSON-wrapped {"content": ...} payload.
        # A JSON body can return 200 while leaving the config unchanged.
        return self._execute(
            "POST",
            f"/address/{address}/weblog/configuration",
            endpoint="address.weblog.config.set",
            text_body=configuration,
        )

    def get_template(self, address: str) -> dict | None:
        return self._execute(
            "GET",
            f"/address/{address}/weblog/template",
            endpoint="address.weblog.template.get",
        )

    def set_template(self, address: str, *, template: str) -> dict | None:
        # The template endpoint follows the same raw-body contract as weblog
        # configuration.
        return self._execute(
            "POST",
            f"/address/{address}/weblog/template",
            endpoint="address.weblog.template.set",
            text_body=template,
        )

    # ── Pastebin ──────────────────────────────────────────────────────

    def list_pastes(self, address: str) -> dict | None:
        return self._execute(
            "GET", f"/address/{address}/pastebin", endpoint="address.pastebin.list"
        )

    def get_paste(self, address: str, slug: str) -> dict | None:
        return self._execute(
            "GET",
            f"/address/{address}/pastebin/{slug}",
            endpoint="address.pastebin.get",
        )

    def set_paste(
        self,
        address: str,
        *,
        content: str,
        title: str | None = None,
        listed: bool = True,
    ) -> dict | None:
        body: dict[str, Any] = {"content": content, "listed": 1 if listed else 0}
        if title is not None:
            body["title"] = title
        return self._execute(
            "POST",
            f"/address/{address}/pastebin",
            endpoint="address.pastebin.set",
            json_body=body,
        )

    def delete_paste(self, address: str, slug: str) -> dict | None:
        return self._execute(
            "DELETE",
            f"/address/{address}/pastebin/{slug}",
            endpoint="address.pastebin.delete",
        )

    # ── PURLs ─────────────────────────────────────────────────────────

    def list_purls(self, address: str) -> dict | None:
        return self._execute("GET", f"/address/{address}/purls", endpoint="address.purls.list")

    def get_purl(self, address: str, purl: str) -> dict | None:
        return self._execute(
            "GET",
            f"/address/{address}/purl/{purl}",
            endpoint="address.purls.get",
        )

    def create_purl(self, address: str, *, name: str, url: str, counter: int = 0) -> dict | None:
        return self._execute(
            "POST",
            f"/address/{address}/purl",
            endpoint="address.purls.create",
            json_body={"name": name, "url": url, "counter": counter},
        )

    def delete_purl(self, address: str, purl: str) -> dict | None:
        return self._execute(
            "DELETE",
            f"/address/{address}/purl/{purl}",
            endpoint="address.purls.delete",
        )

    # ── Email forwarding ──────────────────────────────────────────────

    def get_email(self, address: str) -> dict | None:
        return self._execute("GET", f"/address/{address}/email", endpoint="address.email.get")

    def set_email(self, address: str, *, forwards_to: str | list[str]) -> dict | None:
        if isinstance(forwards_to, list):
            destination = ",".join(forwards_to)
        else:
            destination = forwards_to
        return self._execute(
            "POST",
            f"/address/{address}/email",
            endpoint="address.email.set",
            json_body={"destination": destination},
        )

    # ── DNS ───────────────────────────────────────────────────────────

    def list_dns(self, address: str) -> dict | None:
        return self._execute("GET", f"/address/{address}/dns", endpoint="address.dns.list")

    def create_dns(
        self,
        address: str,
        *,
        type: str,  # noqa: A002 — DNS uses "type" as the canonical field name
        name: str,
        value: str,
        ttl: int = 3600,
    ) -> dict | None:
        return self._execute(
            "POST",
            f"/address/{address}/dns",
            endpoint="address.dns.create",
            json_body={"type": type, "name": name, "data": value, "ttl": ttl},
        )

    def delete_dns(self, address: str, record_id: str) -> dict | None:
        return self._execute(
            "DELETE",
            f"/address/{address}/dns/{record_id}",
            endpoint="address.dns.delete",
        )

    # ── Discovery ─────────────────────────────────────────────────────

    def directory(self) -> dict | None:
        return self._execute("GET", "/directory", endpoint="directory.list")

    def service_info(self) -> dict | None:
        return self._execute("GET", "/service/info", endpoint="service.info")
