"""ORCID iD lookup for Hapax-published artifacts.

Per the 2026-04-25 operator action: the operator's ORCID iD is stored
at ``pass show orcid/orcid`` (one-time-human bootstrap acceptable per
the full-automation-or-no-engagement directive's CONDITIONAL_ENGAGE
tier — academic-publication-infrastructure cluster). Publishers
that support ORCID (Zenodo creators array, OSF contributors API,
Crossref deposit, future arXiv submission) read from here.

The iD is a stable persistent identifier that publicly resolves to
the operator's legal name + affiliations. Per the operator-referent
policy, ORCID iD use is reserved for formal-context attribution
(citation metadata, DOI records). Non-formal surfaces (omg.lol
weblog, social cross-surface posts) keep using non-formal referents
via ``shared.governance.omg_referent``.
"""

from __future__ import annotations

import logging
import os
import subprocess
from functools import lru_cache

log = logging.getLogger(__name__)

ORCID_PASS_KEY = "orcid/orcid"
ORCID_ENV_VAR = "HAPAX_OPERATOR_ORCID"


@lru_cache(maxsize=1)
def operator_orcid() -> str | None:
    """Return the operator's ORCID iD or ``None`` if unavailable.

    Resolution order:

    1. ``$HAPAX_OPERATOR_ORCID`` env var — wins if non-empty. Set by
       ``hapax-secrets.service`` (which sources from ``pass show
       orcid/orcid``) and consumed by services that load
       ``/run/user/1000/hapax-secrets.env`` via ``EnvironmentFile=``,
       or by ``scripts/configure-orcid.sh`` for one-time bootstrap.
    2. ``pass show orcid/orcid`` — direct pass-store fallback for
       processes that don't have the env var loaded (interactive CLI,
       tests, ad-hoc scripts).

    Cached for the process lifetime — the operator doesn't rotate the
    iD across a session. Returns ``None`` when both paths fail (no
    env var + ``pass show`` errors out for any reason — missing key,
    gpg-agent unavailable, pass not installed) so callers can degrade
    gracefully.

    The iD has the form ``NNNN-NNNN-NNNN-NNNN`` (16 hex digits in 4
    hyphen-separated quads). No format validation is enforced here —
    pass-store / env-var content is operator-controlled.
    """
    env_value = (os.environ.get(ORCID_ENV_VAR) or "").strip()
    if env_value:
        return env_value
    try:
        result = subprocess.run(
            ["pass", "show", ORCID_PASS_KEY],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.warning("pass show %s failed: %s", ORCID_PASS_KEY, e)
        return None
    if result.returncode != 0:
        log.debug(
            "pass show %s returned %d: %s",
            ORCID_PASS_KEY,
            result.returncode,
            result.stderr.strip(),
        )
        return None
    iD = result.stdout.strip().split("\n", 1)[0].strip()
    return iD or None


__all__ = ["operator_orcid", "ORCID_PASS_KEY", "ORCID_ENV_VAR"]
