"""Tests for the HACL Surface Registry (classifier organ).

Self-contained (no shared fixtures). Verifies the fail-closed invariants that
make a governance/consent/speech surface structurally impossible to compress.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from shared.compression.registry import (
    DENY_DEFAULT,
    Codec,
    RegistryError,
    Tier,
    get_surface_spec,
    load_registry,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "registry.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


# ── the shipped registry loads + validates ───────────────────────────────────


def test_real_registry_loads_and_validates() -> None:
    reg = load_registry()
    assert reg, "shipped registry should classify surfaces"
    # spot-check the tier assignments from the design
    assert reg["knowledge_search"].tier is Tier.LOSSLESS_OK
    assert reg["axioms_manifest"].tier is Tier.LOSSLESS_ONLY
    assert reg["spontaneous_speech_act"].tier is Tier.DENY
    assert reg["veto_chain_marker"].tier is Tier.HOT_PATH


def test_real_registry_no_lossy_on_protected_surfaces() -> None:
    reg = load_registry()
    for spec in reg.values():
        if spec.tier in (Tier.DENY, Tier.HOT_PATH):
            assert spec.codec is Codec.PASSTHROUGH
            assert spec.headroom_enabled is False
            assert spec.lossy_allowed is False
        if spec.tier is Tier.LOSSLESS_ONLY:
            assert spec.lossy_allowed is False
            assert spec.lossless_allowed is True


# ── fail-closed lookup ────────────────────────────────────────────────────────


def test_unknown_surface_is_deny() -> None:
    spec = get_surface_spec("some_surface_that_does_not_exist")
    assert spec is DENY_DEFAULT
    assert spec.tier is Tier.DENY
    assert spec.codec is Codec.PASSTHROUGH
    assert spec.lossy_allowed is False
    assert spec.lossless_allowed is False


def test_lookup_with_explicit_registry() -> None:
    reg = load_registry()
    assert get_surface_spec("knowledge_search", reg).tier is Tier.LOSSLESS_OK
    assert get_surface_spec("nope", reg) is DENY_DEFAULT


# ── structural invariants reject bad configs at load (fail-closed) ────────────


def test_default_tier_must_be_deny(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        version: 1
        default_tier: lossless_ok
        surfaces: {}
    """,
    )
    with pytest.raises(RegistryError, match="default_tier"):
        load_registry(p)


def test_deny_with_headroom_rejected(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        version: 1
        default_tier: deny
        surfaces:
          bad:
            tier: deny
            codec: passthrough
            headroom_enabled: true
    """,
    )
    with pytest.raises(RegistryError, match="cannot enable Headroom"):
        load_registry(p)


def test_deny_with_nonpassthrough_codec_rejected(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        version: 1
        default_tier: deny
        surfaces:
          bad:
            tier: hot_path
            codec: toon
    """,
    )
    with pytest.raises(RegistryError, match="must use passthrough"):
        load_registry(p)


def test_lossless_only_with_headroom_rejected(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        version: 1
        default_tier: deny
        surfaces:
          bad:
            tier: lossless_only
            codec: toon
            headroom_enabled: true
    """,
    )
    with pytest.raises(RegistryError, match="lossless_only cannot enable Headroom"):
        load_registry(p)


def test_lossless_ok_pilot_flag_allowed(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        version: 1
        default_tier: deny
        surfaces:
          ok:
            tier: lossless_ok
            codec: toon
            headroom_enabled: true
    """,
    )
    spec = load_registry(p)["ok"]
    assert spec.lossy_allowed is True
