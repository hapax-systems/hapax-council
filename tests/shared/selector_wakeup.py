"""Opt-in sandbox test aid: bound selector waits when socketpair wakeups are denied.

Loaded explicitly with ``-p tests.shared.selector_wakeup`` on restricted hosts.
Threads, context propagation and blocking operations remain real. Only idle
selector waits are capped; synchronous custody reads still block the loop.
"""

import selectors

import pytest


@pytest.fixture(autouse=True)
def bounded_selector_wait(monkeypatch):
    original = selectors.EpollSelector.select

    def select(self, timeout=None):
        return original(self, 0.01 if timeout is None else min(timeout, 0.01))

    monkeypatch.setattr(selectors.EpollSelector, "select", select)
