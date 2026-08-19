"""mail_monitor must be DEFAULT-OFF, and must stay that way.

Regression pin for the 2026-08-18 kimi/auditor finding: ``logos/api/app.py``
mounted ``mail_monitor_router`` unconditionally, so any ``logos-api`` restart
silently activated a subsystem whose five cc-task rows were closed ``done`` with
acceptance criteria unchecked — accepted without ever being verified.

The reachable surface is ``POST /webhook/gmail``, which drives
``agents.mail_monitor.runner.process_history`` against live Gmail data. These
tests assert the route is ABSENT unless the operator opts in explicitly, and
present when they do — the second half matters as much as the first, because a
flag that never enables anything is just a deletion wearing a disguise.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator

import pytest

GMAIL_WEBHOOK_PATH = "/webhook/gmail"
FLAG = "HAPAX_MAIL_MONITOR_ENABLED"


def _load_app_with(flag_value: str | None):
    """Import a FRESH logos.api.app with the flag set as given.

    The mount decision is made at import time, so the module must be evicted
    from sys.modules first; re-importing a cached module would silently test
    nothing.
    """
    if flag_value is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = flag_value

    for name in [m for m in sys.modules if m.startswith("logos.api.app")]:
        del sys.modules[name]

    module = importlib.import_module("logos.api.app")
    return importlib.reload(module)


_MISSING = object()


@pytest.fixture(autouse=True)
def _restore_env_and_import_state() -> Iterator[None]:
    """Undo BOTH mutations this module makes: the env flag and the import cache.

    ``_load_app_with`` evicts and re-imports ``logos.api.app``, which replaces the
    cached module object AND rebinds the ``app`` attribute on the ``logos.api``
    package. Restoring only the env var leaves every later test in the session
    importing a module built under whichever flag value ran last — verified: after
    one call, module identity and the package attribute are both replaced.

    ``tests/test_query_api.py:15`` does ``from logos.api.app import app`` and is a
    live consumer of exactly that binding.
    """
    original_flag = os.environ.get(FLAG)
    saved_modules = {
        name: mod for name, mod in sys.modules.items() if name.startswith("logos.api.app")
    }
    api_pkg = sys.modules.get("logos.api")
    saved_pkg_attr = getattr(api_pkg, "app", _MISSING) if api_pkg is not None else _MISSING

    yield

    if original_flag is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = original_flag

    for name in [m for m in sys.modules if m.startswith("logos.api.app")]:
        del sys.modules[name]
    sys.modules.update(saved_modules)

    if api_pkg is not None:
        if saved_pkg_attr is _MISSING:
            # Nothing was bound before; a leftover binding is itself the pollution.
            if hasattr(api_pkg, "app"):
                delattr(api_pkg, "app")
        else:
            api_pkg.app = saved_pkg_attr


def _routes(app) -> set[str]:
    """Collect every reachable path, resolving FastAPI's deferred inclusion.

    This FastAPI version does not expand ``include_router`` eagerly: it appends
    a ``fastapi.routing._IncludedRouter`` wrapper and resolves routes later. A
    naive scan of ``app.routes`` therefore finds NO application paths at all, so
    an "endpoint is absent" assertion would pass whether or not the gate works —
    a vacuous test. Resolve through ``original_router`` so the assertion has
    teeth.
    """
    paths: set[str] = set()
    for route in app.routes:
        direct = getattr(route, "path", None)
        if direct:
            paths.add(direct)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            for sub in getattr(inner, "routes", []):
                sub_path = getattr(sub, "path", None)
                if sub_path:
                    paths.add(sub_path)
    return paths


def test_gmail_webhook_absent_when_flag_unset() -> None:
    """The default. No flag, no mail surface."""
    module = _load_app_with(None)
    assert GMAIL_WEBHOOK_PATH not in _routes(module.app)
    assert module._MAIL_MONITOR_ENABLED is False


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "  ", "maybe"])
def test_gmail_webhook_absent_for_falsey_values(value: str) -> None:
    """Anything that is not an explicit opt-in leaves the surface off.

    'maybe' is included deliberately: an unrecognised value must fail CLOSED,
    not be treated as truthy.
    """
    module = _load_app_with(value)
    assert GMAIL_WEBHOOK_PATH not in _routes(module.app)
    assert module._MAIL_MONITOR_ENABLED is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_gmail_webhook_present_when_explicitly_enabled(value: str) -> None:
    """Opting in must actually work — otherwise this is a deletion, not a gate."""
    module = _load_app_with(value)
    assert GMAIL_WEBHOOK_PATH in _routes(module.app)
    assert module._MAIL_MONITOR_ENABLED is True


def test_teardown_restores_the_import_cache() -> None:
    """The fixture must undo the sys.modules mutation, not only the env var.

    Driven directly, because a test cannot observe its own teardown. Without this
    the leak is invisible here and only shows up as a confusing failure in whatever
    test happens to import ``logos.api.app`` later in the session.
    """
    importlib.import_module("logos.api.app")
    baseline_module = sys.modules["logos.api.app"]
    api_pkg = sys.modules["logos.api"]
    baseline_attr = api_pkg.app

    fixture = _restore_env_and_import_state.__wrapped__()
    next(fixture)  # setup: snapshot
    _load_app_with("1")
    assert sys.modules["logos.api.app"] is not baseline_module, "mutation did not occur"

    with pytest.raises(StopIteration):
        next(fixture)  # teardown: restore

    assert sys.modules["logos.api.app"] is baseline_module
    assert api_pkg.app is baseline_attr
