"""Pin the de-vendored notify shims: agents/_notify.py and logos/_notify.py must
re-export the single source-of-truth symbols from shared.notify (identity), so every
importer inherits the governed P0 intake routing + drain. Guards against a future edit
that silently drops a re-export and re-introduces a bypass / ImportError."""

from __future__ import annotations

import agents._notify as agents_notify
import logos._notify as logos_notify
import shared.notify as canonical

_PUBLIC = (
    "send_notification",
    "send_enriched_notification",
    "send_webhook",
    "obsidian_uri",
    "briefing_uri",
    "nudges_uri",
)


def test_agents_notify_shim_reexports_shared_notify() -> None:
    for name in _PUBLIC:
        assert hasattr(agents_notify, name), f"agents._notify missing {name}"
        assert getattr(agents_notify, name) is getattr(canonical, name), (
            f"agents._notify.{name} must be shared.notify.{name} (re-export, not a fork copy)"
        )


def test_logos_notify_shim_reexports_shared_notify() -> None:
    for name in _PUBLIC:
        assert hasattr(logos_notify, name), f"logos._notify missing {name}"
        assert getattr(logos_notify, name) is getattr(canonical, name), (
            f"logos._notify.{name} must be shared.notify.{name} (re-export, not a fork copy)"
        )


def test_shim_send_notification_is_the_intake_routing_one() -> None:
    # shared.notify.send_notification routes through the governed intake; the shim must
    # expose that exact callable so importers stop bypassing it.
    import inspect

    sig = inspect.signature(agents_notify.send_notification)
    assert "technical" in sig.parameters, (
        "the re-exported send_notification must carry the intake `technical` kwarg"
    )
