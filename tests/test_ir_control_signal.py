"""Test IR perception backend reports control signal."""


def test_ir_control_signal_fresh():
    from shared.control_signal import ControlSignal

    sig = ControlSignal(component="ir_perception", reference=1.0, perception=1.0)
    assert sig.error == 0.0


def test_ir_control_signal_stale():
    from shared.control_signal import ControlSignal

    sig = ControlSignal(component="ir_perception", reference=1.0, perception=0.0)
    assert sig.error == 1.0
