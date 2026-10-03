"""Shared parts of the HTTP-API substitute reviewer seats (kimi, featherless, verboo).

Follows scripts/hapax-muse-reviewer and scripts/hapax-local-reviewer: a blind prompt on
stdin, tools off, the bare-fence output contract (``SEAT_PREAMBLE``), a prompt-size ceiling
that refuses above the measured fit, and the served model recorded on stderr. The API key is
read from the FileStore through ``shared.secrets.get_secret`` (operator ruling 2026-09-16) —
never a PAYG key.

Outage mapping (so the family-outage latch in cc-pr-review-dispatch fires). On a reviewer
process failure the dispatcher classifies the wrapper's STDERR with stdout as ``model_stdout``
(cc-pr-review-dispatch.py §reviewer run), so every failure here writes ONE terse line to
stderr, nothing to stdout, and exits nonzero:

* HTTP 429 / rate / balance wall -> :func:`quota_wall` -> review_team.is_quota_wall (QUOTA)
* HTTP 5xx / overload            -> :func:`provider_outage` -> review_team.is_provider_outage
* auth / config / over-ceiling / truncation / unreachable -> :func:`refuse`
  (``UNSUPPORTED_CLIENT``) -> review_team.is_reviewer_route_unavailable (ROUTE)

Clean-exit stdout is model-controlled, so a wall literal on stdout never classifies — the
signal must be a process failure with empty stdout. These wrappers honor that.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.review_seat_wrapper import SEAT_PREAMBLE, refuse  # noqa: E402  (re-exported)

__all__ = [
    "SEAT_PREAMBLE",
    "USER_AGENT",
    "refuse",
    "read_prompt",
    "seat_text",
    "over_ceiling",
    "read_api_key",
    "redact",
    "quota_wall",
    "provider_outage",
    "http_failure",
    "record_served_model",
]

# Some provider gateways (e.g. Featherless behind Cloudflare) block the default
# ``Python-urllib`` User-Agent (HTTP 403 code 1010); send an explicit one.
USER_AGENT = "hapax-review-seat/1.0"

# review_team._QUOTA_WALL_MAX_CHARS is 600; a real wall is a terse one-liner, so keep the
# whole stderr signal under that or is_quota_wall will (correctly) refuse to read it as a wall.
_MAX_WALL_CHARS = 560
_MAX_OUTAGE_CHARS = 3_800  # under review_team._PROVIDER_OUTAGE_MAX_CHARS (4000)


def redact(text: str, secret: str | None) -> str:
    """Remove the API key from any text that may reach a log or the dossier."""
    if secret and secret in text:
        text = text.replace(secret, "***")
    return text


def _one_line(detail: str, secret: str | None, budget: int) -> str:
    collapsed = " ".join(redact(detail, secret).split())
    return collapsed[: max(budget, 0)]


def read_prompt() -> str:
    """The dispatcher pipes the blind reviewer prompt on stdin."""
    return sys.stdin.read()


def seat_text(prompt: str) -> str:
    """Prefix the blind-seat preamble (tools off, bare-fence contract) to the prompt."""
    return f"{SEAT_PREAMBLE}\n\n{prompt.strip()}\n"


def over_ceiling(wrapper: str, text: str, max_bytes: int) -> int | None:
    """Refuse (route-unavailable) a prompt above the measured fit; the constitution
    substitutes another family rather than risk a partial review. Returns the refusal exit
    code when over the ceiling, else None."""
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        return refuse(
            wrapper,
            f"prompt of {size} bytes exceeds the measured {wrapper} ceiling of {max_bytes}; "
            "the constitution substitutes another family",
        )
    return None


def read_api_key(
    wrapper: str, secret_entry: str, *, env: str | None = None
) -> tuple[str | None, int | None]:
    """Read the seat's subscription/prepaid API key. Returns (key, None) or (None, refusal_code).

    Resolves through ``shared.secrets.get_secret``: the ``env`` override first (for CI/tests),
    then the FileStore. Never falls back to a PAYG key — a missing or empty secret is a
    route-unavailable refusal, not a silent switch to another billing surface.
    """
    try:
        from shared.secrets import SecretUnavailable, get_secret
    except ImportError:
        return None, refuse(
            wrapper, "estate secret resolver unimportable; run from the council checkout"
        )
    try:
        key = get_secret(secret_entry, env=env)
    except SecretUnavailable as exc:
        return None, refuse(wrapper, f"no FileStore secret {secret_entry!r}: {exc.legal_next}")
    if not key:
        return None, refuse(
            wrapper, f"FileStore secret {secret_entry!r} is empty; set it with `hapax-secret`"
        )
    return key, None


def quota_wall(wrapper: str, status: int, detail: str = "", secret: str | None = None) -> int:
    """Signal a provider usage/rate/balance wall (HTTP 429). review_team.is_quota_wall reads
    this stderr line and latches the family-outage witness; it is never read as a review."""
    line = f"{wrapper}: api error: HTTP {status} Too Many Requests"
    extra = _one_line(detail, secret, _MAX_WALL_CHARS - len(line) - 2)
    if extra:
        line = f"{line}; {extra}"
    print(line[:_MAX_WALL_CHARS], file=sys.stderr)
    return 1


def provider_outage(wrapper: str, status: int, detail: str = "", secret: str | None = None) -> int:
    """Signal a provider-side outage (HTTP 5xx / overload). review_team.is_provider_outage
    reads this stderr line and latches rather than reading it as a review."""
    line = f"{wrapper}: api error: HTTP {status} service unavailable"
    extra = _one_line(detail, secret, _MAX_OUTAGE_CHARS - len(line) - 2)
    if extra:
        line = f"{line}; {extra}"
    print(line[:_MAX_OUTAGE_CHARS], file=sys.stderr)
    return 1


def http_failure(wrapper: str, status: int, detail: str = "", secret: str | None = None) -> int:
    """Map an HTTP error status to the existing outage verdicts."""
    if status == 429:
        return quota_wall(wrapper, status, detail, secret)
    if 500 <= status < 600:
        return provider_outage(wrapper, status, detail, secret)
    if status in (401, 403):
        return refuse(
            wrapper,
            f"auth failed (HTTP {status}); check the FileStore subscription key, not a PAYG key",
        )
    return refuse(wrapper, f"HTTP {status}: {_one_line(detail, secret, 200)}")


def record_served_model(wrapper: str, served: str | None, pinned: str) -> None:
    """Record the served model on stderr for the dossier's served-model identity. A reviewer
    SUCCESS keeps stdout for the review alone, so this goes to stderr."""
    print(f"{wrapper}: served_model={served or 'unknown'} pinned_model={pinned}", file=sys.stderr)
