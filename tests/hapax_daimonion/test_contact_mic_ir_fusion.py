"""Test contact mic + IR hand zone cross-modal fusion."""

from agents.hapax_daimonion.backends.contact_mic_ir import _classify_activity_with_ir


def test_tapping_plus_mpc_pads():
    result = _classify_activity_with_ir(
        energy=0.3,
        onset_rate=2.0,
        centroid=200.0,
        autocorr_peak=0.0,
        ir_hand_zone="mpc-pads",
        ir_hand_activity="tapping",
    )
    assert result == "pad-work"


def test_energy_plus_turntable():
    result = _classify_activity_with_ir(
        energy=0.2,
        onset_rate=0.5,
        centroid=100.0,
        autocorr_peak=0.5,
        ir_hand_zone="turntable",
        ir_hand_activity="sliding",
    )
    assert result == "scratching"


def test_typing_plus_desk_center():
    result = _classify_activity_with_ir(
        energy=0.2,
        onset_rate=1.2,
        centroid=300.0,
        autocorr_peak=0.0,
        ir_hand_zone="desk-center",
        ir_hand_activity="tapping",
    )
    assert result == "typing"


def test_no_ir_falls_back_to_base():
    result = _classify_activity_with_ir(
        energy=0.2,
        onset_rate=1.2,
        centroid=300.0,
        autocorr_peak=0.0,
        ir_hand_zone="none",
        ir_hand_activity="none",
    )
    assert result == "typing"


def test_idle_stays_idle():
    result = _classify_activity_with_ir(
        energy=0.05,
        onset_rate=0.0,
        centroid=0.0,
        autocorr_peak=0.0,
        ir_hand_zone="mpc-pads",
        ir_hand_activity="resting",
    )
    assert result == "idle"


def test_drumming_plus_mpc_pads():
    result = _classify_activity_with_ir(
        energy=0.5,
        onset_rate=2.5,
        centroid=140.0,
        autocorr_peak=0.0,
        ir_hand_zone="mpc-pads",
        ir_hand_activity="tapping",
    )
    assert result == "drumming"
