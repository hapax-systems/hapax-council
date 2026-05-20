from __future__ import annotations

import logging

from agents.studio_compositor import state


def test_legacy_studio_fx_mutations_enabled_outside_3d(monkeypatch):
    monkeypatch.delenv("HAPAX_3D_COMPOSITOR", raising=False)
    monkeypatch.delenv("HAPAX_3D_ENABLE_LEGACY_STUDIO_FX_MUTATIONS", raising=False)

    assert state.legacy_studio_fx_mutations_enabled_in_3d() is True


def test_legacy_studio_fx_mutations_disabled_by_default_in_3d(monkeypatch):
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    monkeypatch.delenv("HAPAX_3D_ENABLE_LEGACY_STUDIO_FX_MUTATIONS", raising=False)

    assert state.legacy_studio_fx_mutations_enabled_in_3d() is False


def test_legacy_studio_fx_mutations_can_be_explicitly_enabled_in_3d(monkeypatch):
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    monkeypatch.setenv("HAPAX_3D_ENABLE_LEGACY_STUDIO_FX_MUTATIONS", "true")

    assert state.legacy_studio_fx_mutations_enabled_in_3d() is True


def test_legacy_studio_fx_3d_skip_logs_once(caplog):
    state._LEGACY_STUDIO_FX_3D_SKIP_LOGGED = False
    caplog.set_level(logging.INFO, logger="agents.studio_compositor.state")

    state._log_legacy_studio_fx_3d_skip_once()
    state._log_legacy_studio_fx_3d_skip_once()

    messages = [
        record.getMessage()
        for record in caplog.records
        if "skipping legacy studio graph recruitment consumers" in record.getMessage()
    ]
    assert len(messages) == 1
    state._LEGACY_STUDIO_FX_3D_SKIP_LOGGED = False
