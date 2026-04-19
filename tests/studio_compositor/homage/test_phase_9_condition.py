"""HOMAGE Phase 9 (task #115) — research-condition gating tests.

The LRR discipline says every parameter change that could confound
the Bayesian posterior must open under a named condition. HOMAGE's
condition is ``cond-phase-a-homage-active-001``. These tests pin the
condition's open/close gate as a pure function of the two observable
signals:

1. ``HAPAX_HOMAGE_ACTIVE`` environment flag (default-ON per Phase 12).
2. The active package identity carried in
   ``/dev/shm/hapax-compositor/homage-substrate-package.json`` — the
   choreographer's single source of truth.

The condition is OPEN when HOMAGE is active AND BitchX (or its
consent-safe variant) is the live package. The condition is CLOSED
when either the feature flag is off OR the substrate payload reports
some non-BitchX package OR the substrate file is missing (package
retire / boot).

Reads are wired through the existing ``shared/perceptual_field.py``
module so the narrative director can mechanise a single source of
truth ("if field.homage.package_name in CONDITION_PACKAGES and the
env flag is set, cite the condition in grounding_provenance").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import shared.perceptual_field as pf
from shared.perceptual_field import build_perceptual_field

CONDITION_ID = "cond-phase-a-homage-active-001"

# Packages that open the condition. BitchX is the first (and currently
# only) concrete member; the consent-safe variant counts as well since
# it's the same package tree with identity accents stripped.
CONDITION_PACKAGES: frozenset[str] = frozenset({"bitchx", "bitchx_consent_safe"})


def _condition_open(field, flag_active: bool) -> bool:
    """Pure predicate: does the current state satisfy the condition?

    Keeps the gate logic under test so a regression in either
    signal makes the condition implicitly close rather than
    silently continuing under stale provenance.
    """
    if not flag_active:
        return False
    return field.homage.package_name in CONDITION_PACKAGES


# ── Gate opens ────────────────────────────────────────────────────────────


class TestConditionOpens:
    def test_opens_when_flag_on_and_bitchx_active(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        _write_substrate(tmp_path, package="bitchx")
        field = build_perceptual_field()
        assert _condition_open(field, flag_active=True) is True
        assert field.homage.package_name == "bitchx"

    def test_opens_under_consent_safe_variant(self, monkeypatch, tmp_path):
        """The consent-safe variant is a first-class member of the
        condition — we don't want live-egress data discarded from
        the posterior just because the consent gate engaged."""
        _redirect_paths(monkeypatch, tmp_path)
        _write_substrate(tmp_path, package="bitchx_consent_safe")
        _write_consent_flag(tmp_path)
        field = build_perceptual_field()
        assert _condition_open(field, flag_active=True) is True
        assert field.homage.consent_safe_active is True


# ── Gate closes ───────────────────────────────────────────────────────────


class TestConditionCloses:
    def test_closes_when_package_retired(self, monkeypatch, tmp_path):
        """Substrate file absent → choreographer has not published yet,
        or has retired the package. Condition closes."""
        _redirect_paths(monkeypatch, tmp_path)
        # No substrate-package file on disk.
        field = build_perceptual_field()
        assert _condition_open(field, flag_active=True) is False
        assert field.homage.package_name is None

    def test_closes_when_flag_flipped_off(self, monkeypatch, tmp_path):
        """Operator disabled HOMAGE via ``HAPAX_HOMAGE_ACTIVE=0`` — even
        if the substrate file still carries bitchx from before, the
        gate must close because the feature flag is the operator's
        kill switch."""
        _redirect_paths(monkeypatch, tmp_path)
        _write_substrate(tmp_path, package="bitchx")
        field = build_perceptual_field()
        assert _condition_open(field, flag_active=False) is False

    def test_closes_when_non_bitchx_package_active(self, monkeypatch, tmp_path):
        """Another package (future work) would open its own condition,
        not bitchx's. Gate closes under any foreign package name."""
        _redirect_paths(monkeypatch, tmp_path)
        _write_substrate(tmp_path, package="demoscene_1995")
        field = build_perceptual_field()
        assert _condition_open(field, flag_active=True) is False

    def test_closes_on_substrate_rewrite_to_empty(self, monkeypatch, tmp_path):
        """Choreographer retires a package by overwriting with an empty
        package identifier. Gate must close cleanly so the next
        director tick stops citing this condition."""
        _redirect_paths(monkeypatch, tmp_path)
        # Step 1: BitchX active, condition open.
        _write_substrate(tmp_path, package="bitchx")
        field_open = build_perceptual_field()
        assert _condition_open(field_open, flag_active=True) is True
        # Step 2: retirement — choreographer rewrites with empty package.
        _write_substrate(tmp_path, package="")
        field_closed = build_perceptual_field()
        assert _condition_open(field_closed, flag_active=True) is False
        assert field_closed.homage.package_name is None


# ── State-transition (open → closed → open) ───────────────────────────────


class TestStateTransitions:
    def test_flag_flip_toggles_gate(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        _write_substrate(tmp_path, package="bitchx")
        field = build_perceptual_field()
        # Open, then closed, then open — pure function of args.
        assert _condition_open(field, flag_active=True) is True
        assert _condition_open(field, flag_active=False) is False
        assert _condition_open(field, flag_active=True) is True

    def test_package_swap_toggles_gate(self, monkeypatch, tmp_path):
        _redirect_paths(monkeypatch, tmp_path)
        # Active with bitchx.
        _write_substrate(tmp_path, package="bitchx")
        assert _condition_open(build_perceptual_field(), flag_active=True) is True
        # Package swapped out.
        _write_substrate(tmp_path, package="demoscene_1995")
        assert _condition_open(build_perceptual_field(), flag_active=True) is False
        # Package swapped back.
        _write_substrate(tmp_path, package="bitchx")
        assert _condition_open(build_perceptual_field(), flag_active=True) is True


# ── Condition declaration file present in the repo ────────────────────────


class TestConditionDeclarationFile:
    """Pins the presence and shape of the condition declaration md file.

    The research protocol (``research/protocols/conditions/``) is the
    permanent record. Before activation the declaration must be
    committed to the repo so analysts can reproduce the experimental
    context from the git history alone.
    """

    def _declaration_path(self) -> Path:
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / "research" / "protocols" / "conditions" / f"{CONDITION_ID}.md"

    def test_declaration_exists(self):
        assert self._declaration_path().exists(), (
            f"Condition {CONDITION_ID} must have a declaration at "
            f"{self._declaration_path()} before activation."
        )

    def test_declaration_cites_parent_condition(self):
        text = self._declaration_path().read_text(encoding="utf-8")
        assert "cond-phase-a-volitional-director-001" in text, (
            "Condition must cite its parent for clean A/B comparability."
        )

    def test_declaration_cites_design_spec(self):
        text = self._declaration_path().read_text(encoding="utf-8")
        assert "2026-04-18-homage-framework-design" in text


# ── Fixtures helpers ──────────────────────────────────────────────────────


def _redirect_paths(monkeypatch, tmp_path):
    """Redirect every PerceptualField source path at ``tmp_path``."""
    monkeypatch.setattr(pf, "_PERCEPTION_STATE", tmp_path / "perception-state.json")
    monkeypatch.setattr(pf, "_STIMMUNG_STATE", tmp_path / "stimmung-state.json")
    monkeypatch.setattr(pf, "_ALBUM_STATE", tmp_path / "album-state.json")
    monkeypatch.setattr(pf, "_CHAT_STATE", tmp_path / "chat-state.json")
    monkeypatch.setattr(pf, "_CHAT_RECENT", tmp_path / "chat-recent.json")
    monkeypatch.setattr(pf, "_STREAM_LIVE", tmp_path / "stream-live")
    monkeypatch.setattr(pf, "_PRESENCE_STATE", tmp_path / "presence-state.json")
    monkeypatch.setattr(pf, "_WORKING_MODE", tmp_path / "working-mode")
    monkeypatch.setattr(pf, "_CONSENT_CONTRACTS_DIR", tmp_path / "contracts")
    monkeypatch.setattr(pf, "_OBJECTIVES_DIR", tmp_path / "objectives")
    monkeypatch.setattr(pf, "_read_stream_mode", lambda: None)
    monkeypatch.setattr(pf, "_HOMAGE_ACTIVE_ARTEFACT", tmp_path / "homage-active-artefact.json")
    monkeypatch.setattr(pf, "_HOMAGE_VOICE_REGISTER", tmp_path / "homage-voice-register.json")
    monkeypatch.setattr(pf, "_HOMAGE_SUBSTRATE_PACKAGE", tmp_path / "homage-substrate-package.json")
    monkeypatch.setattr(pf, "_HOMAGE_CONSENT_SAFE_FLAG", tmp_path / "consent-safe-active.json")


def _write_substrate(tmp_path: Path, *, package: str) -> None:
    """Write the choreographer's substrate-package broadcast shape.

    Matches the payload the choreographer actually writes in
    ``agents/studio_compositor/homage/choreographer.py::broadcast_package_to_substrates``
    so the test exercises the real on-disk contract.
    """
    substrate = tmp_path / "homage-substrate-package.json"
    substrate.write_text(
        json.dumps(
            {
                "package": package,
                "palette_accent_hue_deg": 180.0,
                "custom_slot_index": 4,
                "substrate_source_ids": ["reverie"],
            }
        ),
        encoding="utf-8",
    )


def _write_consent_flag(tmp_path: Path) -> None:
    flag = tmp_path / "consent-safe-active.json"
    flag.write_text(
        json.dumps(
            {
                "active": True,
                "since_ts": 0.0,
                "target_layout": "consent-safe.json",
            }
        ),
        encoding="utf-8",
    )


# Ensure pytest can collect this module when run from a CWD that
# omits the hapax-council root; the tests themselves don't rely on
# any pytest plugins, only monkeypatch and tmp_path (stdlib fixtures).
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
