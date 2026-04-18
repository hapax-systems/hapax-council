# Rode Wireless Pro Integration — Design

**Status:** 🟣 SPEC (provisionally approved 2026-04-18)
**Last updated:** 2026-04-18
**Source:** [`docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md`](../research/2026-04-18-homage-follow-on-dossier.md) §2 — Task #133
**Priority:** HIGH (depends on #134)
**Dossier priority row:** 3

---

## 1. Goal

The operator is always voice-wired, including while roaming away from the Yeti desk position. The Rode Wireless Pro (UAC class-compliant USB receiver) becomes the preferred input source when present; the Yeti is the seated fallback; the `echo_cancel_capture` virtual source (produced by #134) is the last-resort soft fallback. Selection is automatic at daimonion startup and hot-swappable without restart when a transmitter is plugged in, unplugged, or its battery dies mid-session.

---

## 2. Hardware Enumeration (PipeWire 1.4.x, Arch 2026)

Rode Wireless Pro receiver enumerates driver-free as a USB Audio Class 1/2 device. Expected PipeWire source name:

```
alsa_input.usb-RODE_RODE_Wireless_PRO_RX_<serial>-00.analog-stereo
```

(Substring match against `RODE_Wireless_PRO` in `pactl list sources short` output is sufficient; serial and connector index vary.) The Lavalier II / Rode GO swap case produces the same RX-side device node — only the airborne transmitter differs, so no config change required for lav-mic swaps.

Input node is stereo by default; daimonion downmixes to mono via the existing `pw-cat --channels 1` invocation (`audio_input.py:93`).

---

## 3. Config Migration: `audio_input_source: list[str]`

Current (`agents/hapax_daimonion/config.py:71-73`):

```python
audio_input_source: str = (
    "alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo"
)
```

Target:

```python
audio_input_source: list[str] = [
    "RODE_Wireless_PRO",                                          # substring, roaming primary
    "Blue_Microphones_Yeti_Stereo_Microphone",                    # substring, seated fallback
    "echo_cancel_capture",                                        # #134 virtual source, last resort
]
```

Entries are **PipeWire source name substrings**, not exact device IDs — aligns with `multi_mic.py::discover_pipewire_sources` semantics and survives kernel device-index reshuffles.

**Legacy compatibility.** A `field_validator` on the config field wraps any scalar string into a one-element list so older `.envrc` / dotfile overrides keep working during the rollout window. Deprecation log line on first wrap, removal scheduled with the next config-model bump.

---

## 4. Discovery Helper — Reuse `multi_mic.py`

`agents/hapax_daimonion/multi_mic.py::discover_pipewire_sources(patterns)` already does exactly what we need: runs `pactl list sources short`, returns full source names whose name column matches any pattern substring, fails-soft to `[]` on subprocess error.

New helper:

```python
def select_primary_source(preferences: list[str]) -> str | None:
    """Return first available PipeWire source matching the ordered preference list."""
    for pattern in preferences:
        hits = discover_pipewire_sources([pattern])
        if hits:
            return hits[0]
    return None
```

Daimonion startup replaces `AudioInputStream(source_name=self.cfg.audio_input_source)` at `daemon.py:92` with:

```python
selected = select_primary_source(self.cfg.audio_input_source) or self.cfg.audio_input_source[-1]
self._audio_input = AudioInputStream(source_name=selected)
log.info("audio_input_source selected: %s", selected)
```

The `or self.cfg.audio_input_source[-1]` clause guarantees a source name is always passed; `AudioInputStream._run_reader` already retries with exponential backoff (`audio_input.py:96-130`), so a missing source at boot is recoverable.

---

## 5. Hot-Swap — systemd Path Unit on `/run/udev/data`

Runtime swap is a separate concern from startup selection. Design:

- **Trigger source.** `/run/udev/data/` entries are written by udev when any USB device appears or disappears. A systemd path unit watching that directory fires on every add/remove.
- **Response unit.** `hapax-daimonion-audio-reload.service` (oneshot) sends `SIGHUP` (or a custom UDS ping) to the daimonion; the daimonion re-runs `select_primary_source()` and swaps `AudioInputStream._source_name` if the selection changed.
- **Debounce.** Path unit uses `TriggerLimitIntervalSec=2` + `TriggerLimitBurst=3` to collapse plug/unplug chatter; daimonion-side re-selection is idempotent so spurious fires are cheap.
- **Graceful swap.** `AudioInputStream` gets a `swap_source(name: str)` method: terminates the current `pw-cat` process, updates `_source_name`, lets the existing retry loop respawn. Wake-word / VAD buffers drain and refill within ~2 s — acceptable, since the operator triggered the swap by physically moving a device.

Units land under `systemd/` (council worktree), installed via the existing systemd user-unit install flow.

---

## 6. Dependencies

- **#134 — Audio Pathways Complete Audit.** Provides the `echo_cancel_capture` virtual source that this spec lists as the last-resort fallback, and establishes the source-priority model that §3 extends. #134 must land first (the config model change is defined there).
- **hapax-daimonion config surface.** No other consumers of `audio_input_source` exist; grep confirms `daemon.py:92` is the single read site.

---

## 7. Firmware Note — Rode Central Mobile

The Rode Wireless Pro works driver-free out of the box. **Firmware updates** require the Rode Central Mobile Android app (no Linux client as of 2026-04). This is occasional (quarterly at most) and **out of scope for v1**: it is operator-side hardware maintenance, not a council integration concern. Documented here to prevent recurring "why doesn't hapax manage firmware" questions.

---

## 8. File-Level Plan

### Modified
- `agents/hapax_daimonion/config.py` — `audio_input_source: list[str]` with a legacy scalar-wrapping validator. Default list per §3.
- `agents/hapax_daimonion/daemon.py:92` — replace direct construction with `select_primary_source` call, log selection.
- `agents/hapax_daimonion/audio_input.py` — add `AudioInputStream.swap_source(name)` method.
- `agents/hapax_daimonion/multi_mic.py` — add `select_primary_source(preferences)` helper alongside existing `discover_pipewire_sources`.

### New
- `systemd/hapax-daimonion-audio-reload.path` — watches `/run/udev/data` with debounce.
- `systemd/hapax-daimonion-audio-reload.service` — oneshot that pings daimonion to re-select source.
- `tests/hapax_daimonion/test_source_selection.py` — unit tests for `select_primary_source` and the scalar-wrapping validator.
- `tests/hapax_daimonion/test_audio_input_swap.py` — verifies `swap_source` terminates the previous `pw-cat` and respawns against the new target.

---

## 9. Test Strategy

1. **Unit — selection order.** Mock `_pactl_output` in `multi_mic.discover_pipewire_sources`; supply outputs that match only Rode, only Yeti, only echo-cancel, and none; assert `select_primary_source` returns the correct entry or `None`.
2. **Unit — legacy scalar wrap.** Instantiate `DaimonionConfig(audio_input_source="alsa_input.usb-Blue_...")`; assert the field becomes a one-element list and a deprecation log line fires.
3. **Integration — swap lifecycle.** Start `AudioInputStream` against a fake source, invoke `swap_source("other_source")`, assert the `pw-cat` subprocess is terminated and a new one is launched with the new `--target`.
4. **Smoke — live hardware.** With the Rode receiver plugged in at daimonion start, confirm the startup log line reads `audio_input_source selected: alsa_input.usb-RODE_...`; unplug the receiver and confirm the path-unit trigger fires and the log reports a swap to the Yeti.

---

## 10. Rollback

- Revert `audio_input_source` to `str` in `config.py`; legacy validator makes this a one-line change.
- `systemctl --user disable --now hapax-daimonion-audio-reload.path` removes the hot-swap trigger; daimonion continues on whatever source was selected at its last start.
- The fallback-chain design means rollback is purely a feature removal — no data migration required.

---

## 11. Open Questions

- **Q1.** Does the `swap_source` transition drop the in-flight Silero VAD hangover window, or should we flush + reinitialize? Default: flush. Revisit if wake-word re-arm latency becomes audible.
- **Q2.** Should the Rode's own battery-low indicator (if exposed via HID descriptor) feed a stimmung signal? Scope creep for v1; flag as a follow-on once we see the actual HID report format under PipeWire 1.4.x.
- **Q3.** Is the `/run/udev/data` path unit the right trigger surface, or should we subscribe to pyudev inside daimonion? Path unit keeps daimonion deployment-agnostic and matches the existing systemd-heavy pattern in this repo.

---

## 12. Related

- **#134 — Audio Pathways Complete Audit** (hard dependency): [`2026-04-18-audio-pathways-audit-design.md`](./2026-04-18-audio-pathways-audit-design.md). Establishes the `audio_input_source: list[str]` shape and the `echo_cancel_capture` virtual source that §3 consumes.
- **#132 — Operator Sidechat** (downstream consumer): [`2026-04-18-operator-sidechat-design.md`](./2026-04-18-operator-sidechat-design.md). The private operator channel relies on whichever mic this spec selects; a roaming Rode capture is the canonical sidechat use case (operator walks away, keeps whispering).
- **Voice pipeline entry:** `agents/hapax_daimonion/audio_input.py`, `agents/hapax_daimonion/multi_mic.py`, `agents/hapax_daimonion/daemon.py:92`.
- **Dossier §2 #133** (source of record).
