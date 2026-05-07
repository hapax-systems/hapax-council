"""Pin the re-export shims at ``agents.audio_signal_assertion.{classifier,probes,transitions}``.

The implementation moved to ``agents.audio_health.*`` but legacy import
paths must keep working. The three shim modules each re-export a fixed
``__all__`` set; consumers (daemon, tests, callers in other modules)
import from either path.

These tests pin two invariants:

  1. Every name in the shim's ``__all__`` actually resolves on the
     shim and is the same object as the canonical export from the
     ``agents.audio_health`` source — no shadowing, no rebinding.
  2. The shim's ``__all__`` exactly matches the corresponding source
     module's ``__all__`` (or is a documented strict subset). A
     future rename in ``agents.audio_health`` that drops a name
     would otherwise silently break every legacy importer.
"""

from __future__ import annotations

from importlib import import_module

import pytest


@pytest.mark.parametrize(
    ("shim_path", "source_path"),
    [
        ("agents.audio_signal_assertion.classifier", "agents.audio_health.classifier"),
        ("agents.audio_signal_assertion.probes", "agents.audio_health.probes"),
        ("agents.audio_signal_assertion.transitions", "agents.audio_health.transitions"),
    ],
)
def test_shim_reexports_resolve_and_match_source(shim_path: str, source_path: str) -> None:
    """Each name listed in the shim's ``__all__`` is the same object
    as the canonical export from the source module.

    "Same object" (``is``) — not just equal — because re-export shims
    must not introduce a parallel binding that callers can drift away
    from. If the shim ever wrapped or replaced a symbol, downstream
    ``isinstance``/identity checks against the canonical export would
    silently start failing.
    """
    shim = import_module(shim_path)
    source = import_module(source_path)

    assert hasattr(shim, "__all__"), f"{shim_path} must declare __all__"

    for name in shim.__all__:
        assert hasattr(shim, name), (
            f"{shim_path} promises {name!r} in __all__ but doesn't expose it"
        )
        assert hasattr(source, name), (
            f"shim {shim_path} re-exports {name!r} but source {source_path} no longer "
            "provides it — the shim is stale and would import-error legacy callers"
        )
        assert getattr(shim, name) is getattr(source, name), (
            f"shim {shim_path}.{name} is not the same object as {source_path}.{name} — "
            "the shim has shadowed the canonical export"
        )


@pytest.mark.parametrize(
    "shim_path",
    [
        "agents.audio_signal_assertion.classifier",
        "agents.audio_signal_assertion.probes",
        "agents.audio_signal_assertion.transitions",
    ],
)
def test_shim_all_is_a_subset_of_source_all(shim_path: str) -> None:
    """The shim's ``__all__`` must be a subset of the source module's
    ``__all__``. The shim may legitimately expose only a portion of
    the source surface (e.g. a deprecation that progressively drops
    names), but it must never expose a name the source doesn't.
    """
    shim = import_module(shim_path)
    source_path = shim_path.replace("agents.audio_signal_assertion", "agents.audio_health")
    source = import_module(source_path)

    if not hasattr(source, "__all__"):
        pytest.skip(f"{source_path} does not declare __all__; subset check N/A")

    extra = set(shim.__all__) - set(source.__all__)
    assert not extra, (
        f"shim {shim_path} promises names not in source {source_path}.__all__: "
        f"{sorted(extra)} — source surface drifted under the shim"
    )
