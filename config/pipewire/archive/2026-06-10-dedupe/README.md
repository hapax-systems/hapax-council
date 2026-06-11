# PipeWire Conf Dedupe Archive - 2026-06-10

Task: `voice-p0-pipewire-conf-dedupe-20260610`
AuthorityCase: `CASE-VOICE-FOUNDATION-20260610`

This archive preserves conf fossils moved out of repository deployable paths.
They are not deleted because they carry useful provenance, but they must not be
copied into `~/.config/pipewire/pipewire.conf.d/`.

## Canonical Rule

Top-level `config/pipewire/hapax-*.conf` files are canonical for their
`node.name` values unless a future governed task replaces them. Generated files
under `config/pipewire/generated/pipewire/` are deployable only when they do not
collide with a canonical top-level node.

Run:

```bash
python3 scripts/check-audio-conf-unique-node-names.py
```

## Archived Sets

`generated-node-collisions/` contains generated or obsolete confs that declare
node names already owned by top-level canonical confs. Loading both the archived
file and its canonical counterpart creates name-colliding PipeWire nodes and
can make name-based links bind nondeterministically after a restart.

`s4-usb-send-quarantine/` contains TTS/S-4 USB-send routes contradicted by the
current mk5 analog insert topology:

```text
TTS -> voice-fx -> loudnorm -> mk5 OUT AUX2/3 -> S-4 analog insert
    -> mk5 IN AUX2/3 -> voice-wet -> livestream-tap
```

Reintroducing any archived S-4 USB voice-send path requires a fresh governed
task, a conflict review against the analog insert, and a witnessed deployment
receipt.
