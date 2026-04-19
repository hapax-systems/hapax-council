# Notification Loopback Leak — Investigation + Fix Options (audit 4.6)

**Date:** 2026-04-20
**Status:** Investigation + 4 fix options; recommended path identified; ship after operator selects.
**Detected by:** `scripts/audit-audio-topology.sh` (PR #1109).
**Severity:** HIGH — operator-private chimes audible to broadcast audience.

---

## §1. The leak

`pw-link --links` shows:
```
output.loopback.sink.role.notification:output_FL  →  hapax-livestream:playback_FL
output.loopback.sink.role.notification:output_FR  →  hapax-livestream:playback_FR
```

Audit catalog §4.6 invariant: "Chime sink not in broadcast graph." Currently violated.

The notification loopback is a WirePlumber role-based aggregator created by
`~/.config/wireplumber/wireplumber.conf.d/50-hapax-voice-duck.conf`. It accepts
any client stream tagged `media.role = "Notification"` and routes it to any
matching `Audio/Sink`. WirePlumber's `find-media-role-sink-target.lua`
auto-discovers `hapax-livestream` as a target because it is a registered
`Audio/Sink` with no exclusion property set.

Why this exists at all: the original 3-loopback design (multimedia + notification +
assistant) was tuned for ducking via the Assistant priority — notifications need
to land on operator's own monitor so they hear chimes. The fact that
`hapax-livestream` is ALSO grabbing them is an unintended side-effect of
WirePlumber's broad target-discovery default.

---

## §2. Fix options

### Option A — Pin notification loopback target to the physical 24c device (RECOMMENDED)

Add `target.object` to the notification loopback's `playback.props` so it
explicitly attaches ONLY to the physical 24c output, not to any virtual
sink including `hapax-livestream` / `hapax-private`.

Edit `~/.config/wireplumber/wireplumber.conf.d/50-hapax-voice-duck.conf`,
add to the notification loopback definition:

```
playback.props = {
  target.object = "alsa_output.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo"
  node.passive = true
}
```

**Pros:**
- Cleanest semantics — notification audio goes to the physical device, period.
- No new files needed.
- Symmetric: same pattern can pin multimedia + assistant to specific targets later.

**Cons:**
- Tied to operator's specific audio interface device-id. If the 24c is replaced,
  the device-id changes and the pin breaks.
- Means notifications no longer auto-route to whatever is "default sink" — operator
  can't easily switch monitor headphones via wireplumber default.

### Option B — Set `policy.role-based.target = false` on hapax-livestream + hapax-private; route multimedia + assistant explicitly

Make `hapax-livestream` opt OUT of role-based linking entirely; route music + TTS
to it via per-client `target.object` overrides.

**Pros:**
- Most isolated — `hapax-livestream` only receives traffic it's been explicitly
  told to receive.

**Cons:**
- Significant downstream rewiring: every TTS playback, every music client must
  now explicitly target hapax-livestream. Operator's current pattern of routing
  by media.role would break.
- Higher blast radius than Option A.

### Option C — Add per-sink `device.intended-roles` exclusion

Set `hapax-livestream`'s `capture.props.device.intended-roles` to
`[ "Music", "Movie", "Game", "Multimedia" ]` — explicitly excluding "Notification".

**Pros:**
- Targeted to the specific exclusion needed.
- Symmetric with the loopback's own `device.intended-roles` declaration.

**Cons:**
- WirePlumber's role-target matching uses the loopback's intended-roles vs the
  sink's accepted-roles, but the documented mechanism for this pairing is sparse.
  Behavior may not be consistent across wireplumber versions.

### Option D — Runtime mitigation: oneshot systemd unit that deletes the link

Write a oneshot systemd user unit that runs at every boot + after pipewire restart
and explicitly calls `pw-link -d <output> <input>` for the offending pair.

**Pros:**
- No WirePlumber config changes; works reliably regardless of WP version.
- Easy to observe (log lines explicit).

**Cons:**
- Bandaid — root cause (WirePlumber's broad target discovery) remains.
- Per operator: "no bandaids, no fake-resolves, root-cause fixes." This option
  fails the bar.

---

## §3. Recommendation

**Option A** (pin notification loopback target). It addresses the root mechanism
(target auto-discovery) directly while preserving operator's existing routing
patterns for multimedia + assistant. The device-id coupling cost is acceptable
because the 24c is the operator's permanent audio anchor.

If operator selects Option A, the implementation is:

1. Edit `~/.config/wireplumber/wireplumber.conf.d/50-hapax-voice-duck.conf`,
   add `target.object` to the notification loopback's `playback.props` block.
2. `systemctl --user restart wireplumber`
3. Verify: `pw-link --links | grep -E '^output.loopback.sink.role.notification' | grep hapax-livestream`
   → must return zero rows.
4. Verify: `scripts/audit-audio-topology.sh` exit 0.
5. Listening test: trigger desktop notification, confirm audible on operator
   headphones, confirm absent from broadcast capture.

PR follow-up commit will land both the conf change AND the verification snapshot.

---

## §4. Why I am not shipping the fix in this PR

- The fix touches operator-side wireplumber config that I do not have an
  authoritative repo template for (`50-hapax-voice-duck.conf` is the canonical
  source but it lives in the operator's home, not the repo).
- Option choice has user-facing implications (Option A pins the device-id;
  operator may prefer C or B for portability reasons).
- Half-baked WirePlumber lua (my earlier attempt) failed the operator's
  "no bandaids" bar.

This research doc is the artefact alpha can hand back to operator for option
selection. The audit script (this PR's other deliverable) provides the
verification harness.

---

## §5. References

- `scripts/audit-audio-topology.sh` (this PR) — leak-detection harness
- `~/.config/wireplumber/wireplumber.conf.d/50-hapax-voice-duck.conf` — root config
- `~/.config/pipewire/pipewire.conf.d/hapax-stream-split.conf` — hapax-livestream sink def
- `~/.cache/hapax/relay/delta-to-alpha-leak-fix-20260419.md` — delta escalation
- WirePlumber `policy.linking.role-based.*` — see /usr/share/wireplumber/scripts/linking/
