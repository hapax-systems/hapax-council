"""Test temporal slot FBO management logic (mocked GL)."""

from agents.effect_graph.temporal_slot import TemporalSlotState


def test_initial_state():
    state = TemporalSlotState(num_buffers=1)
    assert state.accum_texture_id is None
    assert state.initialized is False


def test_marks_initialized_after_setup():
    state = TemporalSlotState(num_buffers=1)
    state.initialize(width=1280, height=720, texture_id=42)
    assert state.initialized is True
    assert state.accum_texture_id == 42
    assert state.width == 1280
    assert state.height == 720


def test_swap_updates_texture():
    state = TemporalSlotState(num_buffers=2)
    state.initialize(width=1280, height=720, texture_id=42)
    state.initialize_secondary(texture_id=43)
    assert state.accum_texture_id == 42
    state.swap()
    assert state.accum_texture_id == 43
    state.swap()
    assert state.accum_texture_id == 42


def test_swap_noop_with_single_buffer():
    state = TemporalSlotState(num_buffers=1)
    state.initialize(width=640, height=360, texture_id=99)
    assert state.accum_texture_id == 99
    state.swap()  # should not crash
    assert state.accum_texture_id == 99


def test_num_buffers_clamped_to_minimum_1():
    state = TemporalSlotState(num_buffers=0)
    assert state._num_buffers == 1
