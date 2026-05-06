# M8 Sampler Capture Template

This is the one-time M8 project setup expected by
`agents.m8_control.sample_capture.M8SampleCapture`.

## Project Setup

1. Create or open the project that should receive Hapax-recorded samples.
2. Pick one track and set its instrument type to `SAMPLER`.
3. In the sampler instrument view, put the cursor on `REC.` and press `EDIT`
   to enter the sample editor.
4. Set `SRC` to `USB` or `ALL`, depending on whether line input should also
   be included.
5. Put the cursor on `START`.
6. Leave the M8 in this view before enabling automated capture.

The default automation assumes the cursor is already on `START`: `EDIT`
starts recording and `EDIT` stops recording. If a project template needs
navigation steps before reaching `START`, construct `M8SampleCapture` with a
custom `start_sequence` and `stop_sequence`.

## Host Route

Install the staging sink if it is not already deployed:

```fish
cp config/pipewire/hapax-m8-sample-input.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
pactl list short sinks | grep hapax-m8-sample-input
```

The Python capture path loads a short-lived `pactl module-loopback` from the
selected source to the M8 USB audio sink, then unloads it after capture. This
keeps the M8 input silent outside bounded capture windows.

## Dry Run

```fish
uv run python - <<'PY'
from agents.m8_control.sample_capture import M8SampleCapture

result = M8SampleCapture().capture(
    audio_source="livestream_tap",
    duration_s=4.0,
    sample_slot_name="reverie_glow",
)
print(result)
PY
```

Expected behavior: the M8 enters recording for the requested duration, stops,
and leaves a sample in the active sampler slot. The returned `sample_slot_name`
is a Hapax-side label; the M8 still owns its slot index and filename workflow.

## References

- Dirtywave M8 Model:02 manual, Sample Editor section: recording uses `EDIT`
  on `START`, and `SRC` can be set to USB.
- `config/pipewire/hapax-m8-sample-input.conf`
- `agents/m8_control/sample_capture.py`
