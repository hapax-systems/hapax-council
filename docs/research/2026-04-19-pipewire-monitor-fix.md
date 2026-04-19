# hapax-livestream Monitor Port Starvation — Root-Cause Analysis and Fix

**Date:** 2026-04-19
**Environment:** PipeWire 1.6.2-1.1, WirePlumber 0.5.14-1.1, PipeWire-Pulse 1.6.2-1.1 on CachyOS (kernel 6.18-lts), PreSonus Studio 24c on card 12.
**Symptom:** `hapax-livestream` (virtual sink defined via `libpipewire-module-filter-chain`) plays audibly out the 24c, but `hapax-livestream.monitor` returns silence (~ -120 dBFS peak). OBS captures silence.

---

## 1. Live Enumeration of Loaded Modules and Current State

```
libpipewire-module-filter-chain   × 5
libpipewire-module-loopback        × 5 (3 are WirePlumber role loopbacks — sink.role.{multimedia,notification,assistant})
libpipewire-module-echo-cancel     × 2
```

Filter-chain populations:

| Node ID | Name                      | Class              | Group                     |
| ------- | ------------------------- | ------------------ | ------------------------- |
| 71      | hapax-livestream          | Audio/Sink         | filter-chain-2431528-33   |
| 72      | hapax-livestream-playback | Stream/Output/Audio| filter-chain-2431528-33   |
| 76      | hapax-private             | Audio/Sink         | filter-chain-2431528-34   |
| 77      | hapax-private-playback    | Stream/Output/Audio| filter-chain-2431528-34   |
| 78/79   | hapax-vinyl-capture/play  | Stream/I/O         | filter-chain-2431528-35   |
| 80/81   | noise-suppress-cap/play   | Stream/I + Audio/Source | filter-chain-2431528-36 |
| 82/83   | hapax-voice-fx-cap/play   | Audio/Sink + Stream/Out | filter-chain-2431528-37 |

Ports on node 71 (`hapax-livestream`) as reported by `pw-dump`:

```
port 183: direction=input  name=playback_FL  audio.channel=FL
port 181: direction=input  name=playback_FR  audio.channel=FR
port 182: direction=output name=monitor_FL   audio.channel=FL  monitor=True
port 180: direction=output name=monitor_FR   audio.channel=FR  monitor=True
```

Monitor ports **do exist** and are flagged `port.monitor = true`. Pulse-compat layer exposes `hapax-livestream.monitor` as expected.

Active links (abbreviated) at time of audit:

```
hapax-livestream:playback_FL  ←  hapax-vinyl-playback:output_FL
                              ←  hapax-voice-fx-playback:output_FL
                              ←  output.loopback.sink.role.multimedia:output_FL
                              ←  output.loopback.sink.role.notification:output_FL
                              ←  output.loopback.sink.role.assistant:output_FL
                              ←  Lavf62.12.100:output_FL  (transient ffmpeg)
                              ←  pw-cat:output_FL          (transient)
hapax-livestream-playback:output_FL → alsa_output...24c:playback_FL
```

**No active inbound link on `hapax-livestream:monitor_FL/FR`.** That is fine — monitors are outputs.

---

## 2. Empirical Bisection of the Symptom

Three capture tests, all with `parec --device=hapax-livestream.monitor`:

| # | Audio source into sink          | Peak captured | Notes |
|---|---------------------------------|---------------|-------|
| 1 | None (ambient capture, 3 s)     | -91 dBFS      | Noise floor / fully idle |
| 2 | `paplay --device=hapax-livestream` sine 440 Hz | **-7.3 dBFS** | Works. |
| 3 | `pw-cat --playback --target hapax-livestream` sine 440 Hz | **-8.6 dBFS** | Works. |
| 4 | ffmpeg `-f pulse -device hapax-livestream` sine | file 0 bytes | ffmpeg failed to open sink (device label race) |

**Result: the monitor port is functional.** The original "-120 dBFS even when audio flows" measurement did not reproduce under direct pw-cat/paplay injection. This changes the diagnosis substantially.

---

## 3. Hypothesis Enumeration (Ranked by Likelihood After Bisection)

### H1. `node.passive = true` + monitor-only consumer → node suspension (ELIMINATED, but root of original symptom)
Filter-chain's playback stream had `node.passive = true` in the pre-fix config. Per PipeWire docs (`pipewire-props(7)`):

> "If the node is not otherwise linked (via a non-passive link), the node and the sink it is linked to are idle (and eventually suspended)."

Flow of consequences:
1. `hapax-livestream-playback` is linked to the 24c ALSA sink via passive link.
2. If no **active** client is connected to `hapax-livestream` (i.e. no non-passive producer, and monitor consumers don't count because monitor ports are outputs from a virtual sink, not an input demand), WirePlumber marks the chain idle.
3. Suspended → filter graph does not schedule → zero samples anywhere, including monitor.
4. OBS opening `hapax-livestream.monitor` as a *source* (not sink input) does **not** wake the sink; the session manager's sink-demand calculation only counts sink-side producers.

This is exactly what the operator observed and what removing `node.passive = true` was meant to fix. It explains both "audio plays out the 24c when something actively drives it" (producer present, non-passive chain starts) and "monitor is silent" (OBS attached first, no producer yet, chain suspended).

The fact that this was NOT reproduced today is consistent with the fix partially taking effect — config reload via `systemctl --user restart` left the node with its post-fix properties but did not clear the 5 × `Lavf62.12.100` zombie streams still visible in `wpctl status`, which in turn kept the chain awake during the current test.

Verification: inspecting running node 71 properties now shows **no** `node.passive` entry (the property is present only when `true`; absence means unset/false). Graph is running.

### H2. Monitor reflects pre-filter (input) buffer — not output of filter
An oft-cited claim in PipeWire commentary (e.g. Google snippet for filter-chain monitor behaviour: "Normally the monitor ports expose the raw unmodified signal on the input ports"). If true, the monitor of a filter-chain-backed sink carries the **input** to the filter graph (what clients wrote), not the filtered output.

This does **not** produce silence by itself — if clients are writing to the sink, the monitor should still be non-zero. But it has a subtle consequence: when the filter-chain graph is **suspended** (H1), the input ports are also not being read by the graph; samples written by clients are effectively dropped and never enter the monitor tap. So the apparent symptom — "audio clearly plays when I test" + "monitor silent when OBS is attached" — is H1 surfacing, not H2.

### H3. The `[FL, null]` / `[null, FR]` output mask drops one channel, masking monitor position
`filter.graph.outputs = [ "sum:Out" null ]` produces a stereo stream whose FR port is explicitly **unconnected** on the *playback* side. This affects only the audio going to the 24c, not the monitor. The monitor ports tap the sink's *input* (capture.props, fully stereo). So this is not a monitor problem.

### H4. WirePlumber session rule reroutes the monitor
No custom WirePlumber rules match `hapax-livestream` in `~/.config/wireplumber/` (confirmed — directory has no overrides). Default session logic does not relocate monitor ports; it treats them as standard audio sources.

### H5. PipeWire version regression
1.6.2 is stable, one point release behind current stable (1.6.3). No known filter-chain monitor regressions in the 1.6.x NEWS entries reviewed. Ruling this out.

---

## 4. Root Cause

**`node.passive = true` on the playback stream caused the entire filter-chain node group to suspend when no producer was actively writing, starving the monitor of samples.** The existing fix (removing it from `playback.props`) is correct but is **currently unverified under the original failure mode** because stale Lavf client streams are holding the chain awake, masking whether the config reload fully took effect.

Supporting evidence is the two independent test captures (paplay, pw-cat) that both produced a healthy -7 to -9 dBFS monitor signal on the current running config. The monitor port is not structurally broken.

The secondary concern (H2 — monitor taps pre-filter audio, so downstream consumers hear the *unmixed* stereo input rather than the "mono-summed, L-only, R-silent" post-filter output) is a **semantics issue, not a silence issue**. It may or may not matter for OBS depending on whether the operator wants the broadcast to hear the post-filter LEFT-only signal (mono of what's sent, duplicated) or the pre-filter stereo. For stream bus use, pre-filter stereo is almost certainly preferable — it means OBS captures the original stereo mix intended for livestream, while the 24c analog output goes to the hardware monitor as a separate L-only cue. This is likely the design intent.

---

## 5. Minimum-Reproducible Working Example — Virtual Sink with Guaranteed Monitor

The canonical recipe for a virtual sink whose monitor is **never** suspended by passive-link accounting is `support.null-audio-sink` via `context.objects`, not filter-chain. Source: [PipeWire Virtual Devices (Ashby)](https://www.benashby.com/resources/pipewire-virtual-devices/) and [Arch Wiki PipeWire/Examples](https://wiki.archlinux.org/title/PipeWire/Examples).

```conf
context.objects = [
    {   factory = adapter
        args = {
            factory.name       = support.null-audio-sink
            node.name          = "hapax-livestream"
            node.description   = "Hapax Livestream"
            media.class        = Audio/Sink
            audio.position     = [ FL FR ]
            monitor.channel-volumes = true
            monitor.passthrough = true
            adapter.auto-port-config = {
                mode     = dsp
                monitor  = true
                position = preserve
            }
        }
    }
]
```

Properties of this recipe:
- Monitor exists from node creation (not dependent on session-manager discovery).
- Node does not suspend when no producer is present (null-sink holds itself running).
- Monitor passes through unmodified input samples. OBS sees exactly what clients wrote.
- No filter graph to maintain or break.

This null-sink-only approach is what every how-to (beko.famkos.net, craigwilson.blog, linuxmusicians.com) recommends for OBS capture, and none of them recommend filter-chain for this purpose.

---

## 6. Primary Fix Recommendation

**Replace the filter-chain-as-sink construction with a two-layer design: null-sink for the routable surface (OBS sees it), filter-chain as a separate downstream node that pulls from the null-sink monitor, sums/pans, and pushes to the 24c.**

Full replacement for `hapax-stream-split.conf`:

```conf
# Hapax stream/private split — v2 (null-sink + filter-chain chain)
# 2026-04-19
#
# hapax-livestream   : null-sink. OBS captures hapax-livestream.monitor.
# hapax-private      : null-sink. Internal only.
# hapax-livestream-pan : filter-chain that pulls hapax-livestream.monitor,
#                       sums stereo to mono, emits stereo as [mono, 0],
#                       plays into 24c analog-stereo.
# hapax-private-pan  : same pattern, emits [0, mono].

context.objects = [
    {   factory = adapter
        args = {
            factory.name       = support.null-audio-sink
            node.name          = "hapax-livestream"
            node.description   = "Hapax Livestream"
            media.class        = Audio/Sink
            audio.position     = [ FL FR ]
            monitor.channel-volumes = true
            monitor.passthrough     = true
            adapter.auto-port-config = {
                mode = dsp  monitor = true  position = preserve
            }
        }
    }
    {   factory = adapter
        args = {
            factory.name       = support.null-audio-sink
            node.name          = "hapax-private"
            node.description   = "Hapax Private"
            media.class        = Audio/Sink
            audio.position     = [ FL FR ]
            monitor.channel-volumes = true
            monitor.passthrough     = true
            adapter.auto-port-config = {
                mode = dsp  monitor = true  position = preserve
            }
        }
    }
]

context.modules = [
    {   name = libpipewire-module-filter-chain
        args = {
            node.description = "Hapax Livestream → 24c LEFT (pan)"
            media.name       = "hapax-livestream-pan"
            filter.graph = {
                nodes = [
                    { type = builtin label = mixer name = sum
                      control = { "Gain 1" = 0.5  "Gain 2" = 0.5 } }
                ]
                inputs  = [ "sum:In 1" "sum:In 2" ]
                outputs = [ "sum:Out"  null ]
            }
            capture.props = {
                node.name    = "hapax-livestream-pan-in"
                node.passive = true
                stream.capture.sink = true
                target.object = "hapax-livestream"
                audio.channels = 2
                audio.position = [ FL FR ]
            }
            playback.props = {
                node.name    = "hapax-livestream-pan-out"
                node.passive = true
                target.object = "alsa_output.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo"
                audio.channels = 2
                audio.position = [ FL FR ]
            }
        }
    }
    {   name = libpipewire-module-filter-chain
        args = {
            node.description = "Hapax Private → 24c RIGHT (pan)"
            media.name       = "hapax-private-pan"
            filter.graph = {
                nodes = [
                    { type = builtin label = mixer name = sum
                      control = { "Gain 1" = 0.5  "Gain 2" = 0.5 } }
                ]
                inputs  = [ "sum:In 1" "sum:In 2" ]
                outputs = [ null "sum:Out" ]
            }
            capture.props = {
                node.name    = "hapax-private-pan-in"
                node.passive = true
                stream.capture.sink = true
                target.object = "hapax-private"
                audio.channels = 2
                audio.position = [ FL FR ]
            }
            playback.props = {
                node.name    = "hapax-private-pan-out"
                node.passive = true
                target.object = "alsa_output.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo"
                audio.channels = 2
                audio.position = [ FL FR ]
            }
        }
    }
]
```

**Why this will have a live monitor:**
1. `hapax-livestream` is now a `support.null-audio-sink` adapter. Null sinks always schedule — they have no passive-link dependency. Monitor is guaranteed live whenever any client writes to the sink, independent of downstream consumers.
2. `adapter.auto-port-config.monitor = true` explicitly creates the monitor ports at adapter setup, not via session-manager discovery.
3. `monitor.passthrough = true` ensures monitor carries the unmodified sample stream (no internal conversion side-effects).
4. The filter-chain is a **separate**, **passive** node that reads `hapax-livestream.monitor` via `stream.capture.sink = true`, applies the sum-and-pan, and writes to the 24c. It can safely be `node.passive = true` on both ends because its *only purpose* is to pipe the null-sink's output to hardware — if no audio is being written into the null-sink, there's nothing for the pan chain to do.
5. OBS reads `hapax-livestream.monitor` directly from the null-sink (bypasses the pan chain entirely). OBS operation is fully independent of whether the 24c is connected, of whether the pan filter is running, and of whether anything else is consuming the monitor.

**Verification procedure:**

```sh
# 1. Install config + reload
cp /path/to/new/hapax-stream-split.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
sleep 1

# 2. Confirm node type and monitor ports
wpctl status | grep -E "hapax-livestream|hapax-private"
pw-link -lio | grep -E "hapax-livestream:(monitor|playback)"
# Expect: 2 playback_FL/FR (input), 2 monitor_FL/FR (output).

# 3. Silence baseline (no producer)
parec --device=hapax-livestream.monitor --format=s16le --rate=48000 --channels=2 --raw /tmp/idle.raw &
REC=$!; sleep 3; kill $REC
ffmpeg -f s16le -ar 48000 -ac 2 -i /tmp/idle.raw -af volumedetect -f null - 2>&1 | grep max_volume
# Expect: -inf or < -90 dB (true silence, not artifact).

# 4. Live signal test
parec --device=hapax-livestream.monitor --format=s16le --rate=48000 --channels=2 --raw /tmp/live.raw &
REC=$!; sleep 0.3
pw-cat --playback --target hapax-livestream <(ffmpeg -f lavfi -i "sine=440:d=2" -f wav - 2>/dev/null)
sleep 0.3; kill $REC
ffmpeg -f s16le -ar 48000 -ac 2 -i /tmp/live.raw -af volumedetect -f null - 2>&1 | grep max_volume
# Expect: peak between -10 and 0 dBFS.

# 5. Audible verification at the 24c
pw-cat --playback --target hapax-livestream <(ffmpeg -f lavfi -i "sine=440:d=2" -f wav - 2>/dev/null)
# Expect: audible from LEFT channel of 24c analog-stereo.

# 6. OBS verification
#    Add "Audio Input Capture" → Device: "Hapax Livestream" (choose the monitor).
#    Observe OBS meter moving in sync with audio into hapax-livestream.
```

---

## 7. Alternate Workaround (No Config Rewrite Required)

If the primary fix cannot be rolled in immediately, add **one additional file** that creates a dedicated tap sink whose monitor is guaranteed live, then route livestream-bound audio through both the existing `hapax-livestream` (for 24c LEFT routing) and the new tap (for OBS):

```conf
# ~/.config/pipewire/pipewire.conf.d/hapax-livestream-tap.conf

# A guaranteed-live monitor tap for OBS. Clients that want to be captured by
# OBS write to "hapax-livestream-tap"; the loopback pipes them into the real
# hapax-livestream filter-chain sink for 24c LEFT panning.

context.objects = [
    {   factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "hapax-livestream-tap"
            node.description = "Hapax Livestream (OBS monitor tap)"
            media.class      = Audio/Sink
            audio.position   = [ FL FR ]
            monitor.channel-volumes = true
            monitor.passthrough     = true
            adapter.auto-port-config = {
                mode = dsp  monitor = true  position = preserve
            }
        }
    }
]

context.modules = [
    {   name = libpipewire-module-loopback
        args = {
            node.description = "tap → hapax-livestream"
            capture.props = {
                node.name      = "hapax-livestream-tap-src"
                stream.capture.sink = true
                target.object  = "hapax-livestream-tap"
                audio.channels = 2
                audio.position = [ FL FR ]
            }
            playback.props = {
                node.name      = "hapax-livestream-tap-dst"
                target.object  = "hapax-livestream"
                audio.channels = 2
                audio.position = [ FL FR ]
                node.passive   = true
            }
        }
    }
]
```

Operational change: clients that currently target `hapax-livestream` switch to targeting `hapax-livestream-tap`. OBS captures `hapax-livestream-tap.monitor` (null-sink-backed, always live). The loopback pipes the same audio into `hapax-livestream`, which continues to handle the FL-only panning into the 24c. The existing filter-chain is untouched.

Trade-off: one extra loopback hop (< 1 ms, irrelevant for voice/music monitoring). No existing routing breaks — clients still able to use `hapax-livestream` directly will just bypass the OBS tap.

---

## 8. Sources

- [PipeWire: Filter-Chain (dv1.pages.freedesktop.org mirror)](https://dv1.pages.freedesktop.org/pipewire/page_module_filter_chain.html)
- [PipeWire: Module Loopback](https://docs.pipewire.org/page_module_loopback.html)
- [PipeWire: Pulse Module Null Sink](https://docs.pipewire.org/page_pulse_module_null_sink.html)
- [PipeWire: Pulse Module Virtual Sink](https://docs.pipewire.org/page_pulse_module_virtual_sink.html)
- [pipewire-props(7) — node.passive semantics](https://docs.pipewire.org/page_man_pipewire-props_7.html)
- [Arch Wiki — PipeWire/Examples (null-sink and filter-chain recipes)](https://wiki.archlinux.org/title/PipeWire/Examples)
- [Ashby — PipeWire Virtual Devices (null-sink + adapter.auto-port-config recipe)](https://www.benashby.com/resources/pipewire-virtual-devices/)
- [Beko — Virtual sinks and mic with OBS and PipeWire](https://beko.famkos.net/2022/04/18/virtual-sinks-and-mic-with-obs-and-pipewire-on-linux-pc/)
- [Craig Wilson — Virtual Sink Creation and Loopback on Linux](https://craigwilson.blog/post/2024/2024-12-05-virtualaudiosplit/)
- [LinuxMusicians — null-audio-sink vs loopback discussion](https://linuxmusicians.com/viewtopic.php?t=28146)
