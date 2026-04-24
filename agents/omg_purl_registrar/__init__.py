"""PURL registrar — ytb-OMG7.

Idempotent one-shot that registers the initial set of hapax PURLs
(persistent short URLs at ``hapax.omg.lol/u/<slug>``) and exposes a
CLI for future additions. Uses :class:`OmgLolClient` for every call.

Seed PURLs (on operator `--seed` run):

    stream      → YouTube channel
    geal        → GEAL spec
    vocab       → vocabulary anchor on hapax.omg.lol
    axioms      → governance anchor
    research    → research anchor
    claim5      → current research claim (TBD — placeholder target)
    now         → hapax.omg.lol/now
    mail        → mailto:hapax@omg.lol

Idempotent: if a PURL already exists with the same target, re-running
is a no-op; if the target differs, the registrar logs the drift and
skips (operator can edit manually via omg.lol UI or re-run with
``--force`` to overwrite).
"""

from agents.omg_purl_registrar.registrar import (
    INITIAL_PURLS,
    PurlRegistrar,
    PurlSpec,
    build_initial_purls,
)

__all__ = [
    "INITIAL_PURLS",
    "PurlRegistrar",
    "PurlSpec",
    "build_initial_purls",
]
