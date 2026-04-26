"""Type-A structural-refusal watcher (HTTP conditional-GET).

Async daemon that polls external API documentation / TOS pages / release-
notes for the type-A REFUSED tasks. Uses ``If-None-Match`` +
``If-Modified-Since`` per the spec to respect external infrastructure;
SHA-256 fingerprint fallback when ETag absent. 15s timeout per probe.

Conservative-by-default: any HTTP error, any timeout, or any unchanged
fingerprint returns ``ProbeResult(changed=False)`` so the substrate
re-affirms instead of falsely accepting.

Cadence-degrade per Refusal Brief §6: weekly default; monthly after 12
consecutive re-affirmations. Any non-re-affirm transition resets to weekly.

Spec: ``docs/research/2026-04-25-refused-lifecycle-pipeline.md`` §2.A.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from agents.refused_lifecycle import runner
from agents.refused_lifecycle.evaluator import decide_transition
from agents.refused_lifecycle.metrics import probe_failures_total, probes_total
from agents.refused_lifecycle.state import ProbeResult, RefusalTask

log = logging.getLogger(__name__)


CADENCE_WEEKLY = timedelta(days=7)
CADENCE_MONTHLY = timedelta(days=30)
STABLE_THRESHOLD = 12  # re-affirmations before cadence-degrade

PROBE_TIMEOUT_SECONDS = 15.0
SNIPPET_MAX_CHARS = 500
SNIPPET_HALF_WINDOW = 200  # chars on each side of the keyword match

# Identifying User-Agent so external infrastructure (Bandcamp / Discogs /
# RYM / Crossref / alphaXiv) can attribute probes to a specific bot, rate-
# limit if needed, and reach the operator out-of-band. Mailto is the
# operator's published contact per the cold-contact substrate.
PROBE_USER_AGENT = (
    "hapax-refused-lifecycle-watcher/1.0 (+https://github.com/ryanklee/hapax-council)"
)


def extract_snippet_around_keyword(text: str, keywords: list[str]) -> str:
    """Return ≤500 chars of context around the first matching keyword.

    Falls back to the leading 500 chars of the text when no keyword matches.
    Case-insensitive matching; the original casing of ``text`` is preserved
    in the returned snippet.
    """
    lower = text.lower()
    for kw in keywords:
        idx = lower.find(kw.lower())
        if idx == -1:
            continue
        start = max(0, idx - SNIPPET_HALF_WINDOW)
        end = min(len(text), idx + len(kw) + SNIPPET_HALF_WINDOW)
        return text[start:end][:SNIPPET_MAX_CHARS]
    return text[:SNIPPET_MAX_CHARS]


def count_trailing_reaffirms(history: list) -> int:
    """Count consecutive re-affirmations at the tail of refusal_history."""
    count = 0
    for entry in reversed(history):
        if getattr(entry, "transition", None) == "re-affirmed":
            count += 1
        else:
            break
    return count


def cadence_for_task(task: RefusalTask) -> timedelta:
    """Return the next-evaluation cadence per Refusal Brief §6."""
    if count_trailing_reaffirms(task.refusal_history) >= STABLE_THRESHOLD:
        return CADENCE_MONTHLY
    return CADENCE_WEEKLY


async def probe_url(task: RefusalTask) -> ProbeResult:
    """Execute one HTTP-conditional-GET probe for a type-A task.

    Conservative semantics:
    - HTTP error / timeout / 5xx → ``changed=False, error=<reason>``
    - 304 Not Modified → ``changed=False`` (silent re-affirm)
    - 200 with same SHA256 → ``changed=False``
    - 200 with new SHA256 BUT no lift-keyword present → ``changed=False``
      (content shifted but not in lift direction)
    - 200 with new SHA256 AND lift-keyword present → ``changed=True``
      with the surrounding ≤500-char snippet as ``evidence_url``/``snippet``
    """
    probe = task.evaluation_probe or {}
    url = probe.get("url")
    if not url:
        return ProbeResult(changed=False, error="no probe url configured")

    headers: dict[str, str] = {"User-Agent": PROBE_USER_AGENT}
    if probe.get("last_etag"):
        headers["If-None-Match"] = probe["last_etag"]
    if probe.get("last_lm"):
        headers["If-Modified-Since"] = probe["last_lm"]

    probes_total.labels(trigger="structural", slug=task.slug).inc()
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        probe_failures_total.labels(trigger="structural", slug=task.slug, reason="timeout").inc()
        return ProbeResult(changed=False, error=f"timeout: {exc!r}")
    except (TimeoutError, httpx.HTTPError) as exc:
        probe_failures_total.labels(trigger="structural", slug=task.slug, reason="http-error").inc()
        return ProbeResult(changed=False, error=f"http: {exc!r}")

    resp_etag = resp.headers.get("ETag")
    resp_lm = resp.headers.get("Last-Modified")

    if resp.status_code == 304:
        # 304 carries no body; preserve previous ETag/LM if server omitted them
        return ProbeResult(
            changed=False,
            etag=resp_etag or probe.get("last_etag"),
            last_modified=resp_lm or probe.get("last_lm"),
            fingerprint=probe.get("last_fingerprint"),
        )
    if resp.status_code >= 400:
        probe_failures_total.labels(
            trigger="structural", slug=task.slug, reason=f"http-{resp.status_code}"
        ).inc()
        return ProbeResult(changed=False, error=f"http-{resp.status_code}")

    body = resp.text
    fingerprint = hashlib.sha256(body.encode()).hexdigest()
    if fingerprint == probe.get("last_fingerprint"):
        return ProbeResult(
            changed=False,
            etag=resp_etag,
            last_modified=resp_lm,
            fingerprint=fingerprint,
        )

    keywords = probe.get("lift_keywords") or []
    body_lower = body.lower()
    matched_keyword = next((kw for kw in keywords if kw.lower() in body_lower), None)
    if matched_keyword is None:
        # Content changed but not in lift direction — re-affirm; still persist
        # the new fingerprint/etag so the next probe gets a fast 304 path
        return ProbeResult(
            changed=False,
            etag=resp_etag,
            last_modified=resp_lm,
            fingerprint=fingerprint,
        )

    snippet = extract_snippet_around_keyword(body, keywords)
    return ProbeResult(
        changed=True,
        evidence_url=str(resp.url),
        snippet=snippet[:SNIPPET_MAX_CHARS],
        etag=resp_etag,
        last_modified=resp_lm,
        fingerprint=fingerprint,
    )


def _persist_probe_state(
    task: RefusalTask, resp_etag: str | None, resp_lm: str | None, fingerprint: str | None
) -> None:
    """Update task.evaluation_probe with the latest etag / LM / fingerprint."""
    probe = dict(task.evaluation_probe or {})
    if resp_etag is not None:
        probe["last_etag"] = resp_etag
    if resp_lm is not None:
        probe["last_lm"] = resp_lm
    if fingerprint is not None:
        probe["last_fingerprint"] = fingerprint
    task.evaluation_probe = probe


async def _tick_async(now: datetime, active_dir: Path) -> int:
    """Run one structural-watcher pass: probe all due type-A tasks, dispatch."""
    count = 0
    for task in runner.iter_refused_tasks(active_dir):
        if "structural" not in task.evaluation_trigger:
            continue
        if task.next_evaluation_at and task.next_evaluation_at > now:
            continue
        result = await probe_url(task)
        # Persist conditional-GET state BEFORE apply_transition so the
        # frontmatter rewrite captures the latest ETag / LM / fingerprint
        _persist_probe_state(task, result.etag, result.last_modified, result.fingerprint)
        event = decide_transition(task, [result])
        # Cadence-decision feeds the next_evaluation_at reset
        cadence = cadence_for_task(task)
        task.next_evaluation_at = now + cadence
        runner.apply_transition(Path(task.path), task, event, now)
        count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-dir", type=Path, default=runner.DEFAULT_ACTIVE_DIR)
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    count = asyncio.run(_tick_async(now, args.active_dir))
    print(f"structural-watcher: probed {count} type-A tasks")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "CADENCE_MONTHLY",
    "CADENCE_WEEKLY",
    "PROBE_TIMEOUT_SECONDS",
    "SNIPPET_MAX_CHARS",
    "STABLE_THRESHOLD",
    "cadence_for_task",
    "count_trailing_reaffirms",
    "extract_snippet_around_keyword",
    "main",
    "probe_failures_total",
    "probe_url",
    "probes_total",
]
