"""TDD for the perception-conf generator — the lean SSOT spine.

The cortado contact-mic conf is currently hand-authored (L-12 edition) with a
hand-typed ``node.target`` that drifted to the retired Zoom L-12, so the live
``contact_mic`` node fell through to mk5 capture_AUX0 (the Rode) = an eavesdrop
class (REQ-20260616-perception-audio-ssot-program, Phase 1).

These tests pin the fix correct-by-construction: the registry declares a TYPED
hardware source (device + position) and the generator EMITS the conf from it, so
there is no hand-typed channel left to drift, and a perceptual/quarantine point
can never be emitted onto a broadcast-reachable target.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from shared.perception_conf_gen import (
    PerceptualBroadcastReachError,
    generated_contact_mic_conf_text,
)
from shared.perception_registry import (
    ExposureDomain,
    GeometryClass,
    HwSource,
    PerceptionPoint,
    PerceptionRegistry,
    load_default_registry,
)

MK5_PRO_INPUT = "alsa_input.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-input-0"

_GENERATOR_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "generate-pipewire-audio-confs.py"
)


def _load_generator_cli():
    """Import the hyphenated generator script as a module to exercise its CLI."""
    spec = importlib.util.spec_from_file_location("_gen_pw_audio_confs_cli", _GENERATOR_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cortado_registry(
    node_target: str = MK5_PRO_INPUT, position: str = "AUX1"
) -> PerceptionRegistry:
    return PerceptionRegistry(
        points={
            "cortado": PerceptionPoint(
                geometry=GeometryClass.CONTACT,
                exposure=ExposureDomain.QUARANTINE,
                pipewire_node="contact_mic",
                voice_source_tag="contact-mic",
                hw_source=HwSource(node_target=node_target, position=position),
            )
        }
    )


def test_contact_mic_conf_emitted_from_registry_targets_mk5_aux1() -> None:
    conf = generated_contact_mic_conf_text(_cortado_registry())
    # contact_mic module = everything before the preserved legacy mixer_master block.
    contact_mod = conf.split("LEGACY mixer_master")[0]
    assert f'node.target = "{MK5_PRO_INPUT}"' in contact_mod
    # UPPERCASE AUX1 matches the mk5 capture_AUX1 channel position (= input 2 = Cortado).
    # Lowercase 'aux1' falls back to capture_AUX0 (the Rode) = the eavesdrop.
    assert "audio.position = [ AUX1 ]" in contact_mod
    assert 'node.name = "contact_mic"' in contact_mod
    # the eavesdrop is gone correct-by-construction: no retired L-12 in the contact_mic binding.
    assert "ZOOM_Corporation_L-12" not in contact_mod
    # passive + dont-reconnect preserved (the room-mic-hijack guard).
    assert "node.passive = true" in contact_mod
    assert "node.dont-reconnect = true" in contact_mod
    # mixer_master preserved (live-consumed by ducker/reactivity — must not be deleted).
    assert 'node.name = "mixer_master"' in conf


def test_cross_check_refuses_broadcast_reachable_target_for_quarantine_point() -> None:
    # A perceptual/quarantine point whose source resolves to the broadcast tap
    # must be refused at generation time (exposure=quarantine ⇒ not broadcast).
    bad = _cortado_registry(node_target="hapax-livestream-tap")
    with pytest.raises(PerceptualBroadcastReachError):
        generated_contact_mic_conf_text(bad)


def test_lowercase_aux_position_is_normalized_uppercase() -> None:
    # Formal guard: lowercase 'aux1' (the original eavesdrop cause) is normalized
    # to 'AUX1' at the model boundary, so the generated conf always matches the
    # mk5 AUX1 channel position (= input 2 = Cortado), never falls back to AUX0.
    assert HwSource(node_target=MK5_PRO_INPUT, position="aux1").position == "AUX1"
    conf = generated_contact_mic_conf_text(_cortado_registry(position="aux1"))
    assert "audio.position = [ AUX1 ]" in conf
    assert "audio.position = [ aux1 ]" not in conf.split("LEGACY mixer_master")[0]


def test_missing_hw_source_raises() -> None:
    reg = PerceptionRegistry(
        points={
            "cortado": PerceptionPoint(
                geometry=GeometryClass.CONTACT,
                exposure=ExposureDomain.QUARANTINE,
                pipewire_node="contact_mic",
            )
        }
    )
    with pytest.raises(ValueError, match="hw_source"):
        generated_contact_mic_conf_text(reg)


def test_missing_point_raises() -> None:
    with pytest.raises(ValueError, match="no point"):
        generated_contact_mic_conf_text(PerceptionRegistry(points={}))


def test_cli_write_source_confs_then_check_roundtrip(tmp_path, monkeypatch) -> None:
    # The --write-source-confs CLI branch must emit exactly the library text,
    # and a subsequent --check-source-confs against that output must pass (0).
    gen = _load_generator_cli()
    conf = tmp_path / "hapax-contact-mic.conf"
    monkeypatch.setattr(gen, "CONTACT_MIC_CONF_PATH", conf)

    monkeypatch.setattr(sys, "argv", ["gen", "--write-source-confs"])
    assert gen.main() == 0
    assert conf.read_text(encoding="utf-8") == generated_contact_mic_conf_text(
        load_default_registry()
    )

    monkeypatch.setattr(sys, "argv", ["gen", "--check-source-confs"])
    assert gen.main() == 0


def test_cli_check_source_confs_detects_drift(tmp_path, monkeypatch) -> None:
    # The --check-source-confs gate must fail (SystemExit) when the deployed conf
    # drifts from the registry-generated text — this is the byte-diff guard that
    # makes a hand-edit (the original eavesdrop cause) impossible to land silently.
    gen = _load_generator_cli()
    conf = tmp_path / "hapax-contact-mic.conf"
    conf.write_text("# drifted hand-edit\n", encoding="utf-8")
    monkeypatch.setattr(gen, "CONTACT_MIC_CONF_PATH", conf)

    monkeypatch.setattr(sys, "argv", ["gen", "--check-source-confs"])
    with pytest.raises(SystemExit, match="differs from the registry-generated text"):
        gen.main()
