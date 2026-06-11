# hapax-daimonion drop-ins

Every drop-in in this directory is versioned, and every `HAPAX_*` env knob it
sets must have a reader in the source tree —
`tests/test_daimonion_dropin_config_truth.py` enforces this. The live
directory `~/.config/systemd/user/hapax-daimonion.service.d/` must contain
only symlinks into this directory; loose files there are shadow config and
get collapsed or deleted.

## Shadow-surface collapse ledger (2026-06-11, CASE-VOICE-FOUNDATION-20260610)

The 2026-06-10 voice foundation audit found nine unversioned files in the
live drop-in directory; two of four audited knobs were read by nothing.
Disposition of each:

| Live file | Disposition |
|---|---|
| `tts-backend.conf` | **Versioned** here. `HAPAX_TTS_BACKEND` was read by NOTHING (the selector only existed on quarantined PR #3727) — the selector is now real code in `agents/hapax_daimonion/tts.py`. The old comment's "Kokoro GPU primary, 40ms" claim was false (CPU, RTF 0.10–0.135x); the versioned comment states the truth. |
| `rode-input.conf` | **Deleted.** Pointed `HAPAX_AUDIO_INPUT_TARGET` at the Rode Wireless PRO RX, which is not on the USB bus — a live trap that only worked because `zz-stale-rode-runtime-mitigation.conf` sorted later and overrode it. |
| `zz-stale-rode-runtime-mitigation.conf` | **Versioned** as `audio-input.conf` (ReSpeaker XVF3800, the sole live STT mic). |
| `tts-target.conf` | **Deleted.** `HAPAX_TTS_TARGET` is legacy: `conversation_pipeline.py` reads it only to log "Ignoring legacy HAPAX_TTS_TARGET"; the fail-closed destination gate (`cpal/destination_channel.py`) owns routing per-utterance and does not consume it. |
| `opt-in-all.conf` | **Deleted.** `HAPAX_AUTONOMOUS_NARRATIVE_ENABLED` was read by nothing; the `autonomous_narrative/__init__.py` claim that compose.py checked it was false (now corrected). Narrative is default-ON, so the operator's 2026-04-25 enable-all intent holds without the knob. |
| `override.conf` | **Deleted.** Its stated purpose ("until PR #731 merges") is fulfilled: the main unit carries the identical OTel BSP caps and 12G/10G memory values. |
| `zz-capacity.conf` | **Versioned** as `capacity.conf` (12G-soft/16G-hard/4G-swap — the live values that superseded `override.conf`). |
| `aec.conf` | **Versioned** here unchanged (`HAPAX_AEC_ACTIVE` is read by `audio_input.py`). |
| `cpu-affinity.conf` | Was a byte-identical loose copy of the versioned file — replaced with a symlink. |

Non-`HAPAX_*` env vars in drop-ins (PyTorch/OTel/OMP/...) are consumed by
libraries, not hapax code; the conformance test allowlists those prefixes.
