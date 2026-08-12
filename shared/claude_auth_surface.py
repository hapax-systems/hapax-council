"""Whether this host's Claude turns are served by the subscription — measured, not asserted.

A transcript record carries no auth or billing field, so a turn served through an API key looks
identical there to one served on the subscription. The first repair labelled the receipt's
``auth_surface`` as ``caller_asserted`` and stopped: honest about the gap, but the route gate
still accepted the receipt, so an API-key-backed turn could still unblock a subscription-only
route. Labelling a hole is not closing one.

The claim IS observable, from two independent facts on this host:

* ``~/.claude.json`` ``oauthAccount`` records ``billingType`` and ``organizationType`` — measured
  2026-08-12: ``google_play_subscription`` / ``claude_max``. That establishes the ACCOUNT is a
  subscription. Membership only: this module reads the CATEGORY of the billing relationship and
  never a token, key, or credential value.
* Whether an API key is reachable at all. ``customApiKeyResponses.approved`` on this host is
  **non-empty**, so the API-key path is live here — the hazard is not hypothetical. If a key
  could have served the turn, the account-level marker no longer settles which credential did.

Both must hold. A subscription account with an API key in play cannot support the claim, because
nothing distinguishes the two at the transcript. That is a refusal, not a downgrade: there is no
weaker true statement to fall back to.

What this still does not prove is per-turn billing — no file records which credential served a
given request. The claim made here is the strongest one the host can support: *this account is a
subscription, and no API-key path was available to serve it.* The receipt names that as its
provenance instead of shrugging with ``caller_asserted``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

#: Where Claude Code records the signed-in account. Overridable for tests only.
CLAUDE_CONFIG_ENV = "HAPAX_CLAUDE_CONFIG_PATH"

#: ``billingType`` values that mean a subscription rather than metered API usage. An unfamiliar
#: value is NOT assumed to be a subscription — an unknown billing relationship is unknown.
SUBSCRIPTION_BILLING_TYPES = frozenset(
    {
        "google_play_subscription",
        "apple_iap_subscription",
        "stripe_subscription",
        "subscription",
    }
)

#: ``organizationType`` values consistent with a Claude subscription seat.
SUBSCRIPTION_ORGANIZATION_TYPES = frozenset({"claude_max", "claude_pro", "claude_team"})

#: Environment variables that would route a turn through a metered API key. Any one being set
#: means the transcript cannot tell us which credential served the turn.
API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY")

#: Settings key that makes Claude Code fetch a key at request time. Same consequence.
API_KEY_HELPER_KEY = "apiKeyHelper"

AUTH_SURFACE_PROVENANCE = "measured:oauth-account-subscription-marker"


class ClaudeAuthSurfaceUnavailable(RuntimeError):
    """The subscription claim cannot be supported. The message names the next action."""


@dataclass(frozen=True)
class SubscriptionMarker:
    """The two categorical facts the receipt may rest on. No credential values."""

    billing_type: str
    organization_type: str

    @property
    def provenance(self) -> str:
        return AUTH_SURFACE_PROVENANCE


def _config_path() -> Path:
    override = os.environ.get(CLAUDE_CONFIG_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude.json"


def _api_key_paths_active(config: dict) -> list[str]:
    """Every way a metered key could serve a turn on this host, right now."""

    active = [name for name in API_KEY_ENV_VARS if os.environ.get(name, "").strip()]
    if str(config.get(API_KEY_HELPER_KEY, "") or "").strip():
        active.append(API_KEY_HELPER_KEY)
    return active


def observe_subscription_marker() -> SubscriptionMarker:
    """Return the marker, or raise. Never returns a partial or assumed answer."""

    path = _config_path()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClaudeAuthSurfaceUnavailable(
            f"no Claude Code account record at {path}; the subscription claim has nothing behind "
            "it. Next: sign in with Claude Code on this host, then re-observe"
        ) from exc
    except (OSError, ValueError) as exc:
        raise ClaudeAuthSurfaceUnavailable(
            f"Claude Code account record at {path} is unreadable ({type(exc).__name__}); refusing "
            "rather than assuming a subscription. Next: repair it by signing in again"
        ) from exc
    if not isinstance(config, dict):
        raise ClaudeAuthSurfaceUnavailable(f"Claude Code account record at {path} is not an object")

    account = config.get("oauthAccount")
    if not isinstance(account, dict):
        raise ClaudeAuthSurfaceUnavailable(
            f"{path} records no oauthAccount, so nothing says this host is on a subscription. "
            "Next: sign in with Claude Code, or mint an operator-attested receipt instead"
        )

    billing = str(account.get("billingType") or "").strip().lower()
    organization = str(account.get("organizationType") or "").strip().lower()
    if billing not in SUBSCRIPTION_BILLING_TYPES:
        raise ClaudeAuthSurfaceUnavailable(
            f"oauthAccount.billingType is {billing or 'absent'}, which is not a known "
            "subscription billing relationship. An unrecognised value is unknown, not a "
            f"subscription. Next: if {billing or 'that value'} IS a subscription type, add it to "
            "SUBSCRIPTION_BILLING_TYPES along with the measurement that established it"
        )
    if organization not in SUBSCRIPTION_ORGANIZATION_TYPES:
        raise ClaudeAuthSurfaceUnavailable(
            f"oauthAccount.organizationType is {organization or 'absent'}, which is not a known "
            "Claude subscription seat"
        )

    # THE SECOND CONDITION, AND THE ONE THAT MAKES THIS A MEASUREMENT RATHER THAN A GUESS.
    #
    # A subscription account with a metered key in reach cannot support the claim: the transcript
    # records no auth field, so nothing distinguishes which credential served the turn. There is
    # no weaker true statement available, so this refuses rather than degrading — a receipt
    # reading "probably the subscription" would be the caller assertion this module replaces.
    active = _api_key_paths_active(config)
    if active:
        raise ClaudeAuthSurfaceUnavailable(
            f"an API-key path is active on this host ({', '.join(active)}), so a turn in the "
            "transcript may have been served by a metered key rather than the subscription, and "
            "the transcript records no auth field to tell them apart. Next: unset "
            f"{', '.join(active)} for the observing process, or mint an operator-attested receipt "
            "that does not claim measured auth"
        )

    return SubscriptionMarker(billing_type=billing, organization_type=organization)
