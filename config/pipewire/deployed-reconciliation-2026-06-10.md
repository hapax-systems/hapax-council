# PipeWire Deployed-Dir Reconciliation - 2026-06-10

Task: `voice-p0-pipewire-conf-dedupe-20260610`
AuthorityCase: `CASE-VOICE-FOUNDATION-20260610`

This is a deployment runbook only. This task did not mutate
`~/.config/pipewire/pipewire.conf.d/` and did not restart PipeWire.

## Current Diff Report

Read-only inventory on 2026-06-10 found loadable deployed twins that declare
the same `node.name` values as canonical repo files:

```text
10-contact-mic.conf                duplicates hapax-contact-mic.conf
music-duck-mk5.conf                duplicates hapax-music-duck-mk5.conf
music-loudnorm.conf                duplicates hapax-music-loudnorm.conf
pc-loudnorm.conf                   duplicates hapax-pc-loudnorm.conf
tts-loudnorm.conf                  duplicates hapax-voice-fx-loudnorm.conf
yt-loudnorm.conf                   duplicates hapax-yt-loudnorm.conf
```

The deployed directory also contains many `.bak*`, `.disabled*`, and
`.replaced*` fossils. Those files are outside PipeWire's normal `*.conf` load
set only when their basename no longer ends with `.conf`, but leaving them in
the conf.d directory makes future reconciliation error-prone.

Contradicted S-4 USB voice-send fossils observed in source and/or deployed
state:

```text
hapax-tts-to-s4.conf
hapax-voice-s4-hardware.conf
hapax-yt-to-s4-bridge.conf.disabled
```

## Operator-Window Runbook

Do this only in an operator-present audio maintenance window. Do not restart
PipeWire while live OBS/program output depends on the current graph.

```bash
RUN_ID=20260610-voice-p0-pipewire-conf-dedupe
CONF_DIR="$HOME/.config/pipewire/pipewire.conf.d"
ARCHIVE="$HOME/.config/pipewire/archive/$RUN_ID"
mkdir -p "$ARCHIVE/fossils" "$ARCHIVE/node-collisions" "$ARCHIVE/s4-usb-send-quarantine"

cd "$CONF_DIR"

for file in \
  10-contact-mic.conf \
  music-duck-mk5.conf \
  music-loudnorm.conf \
  pc-loudnorm.conf \
  tts-loudnorm.conf \
  yt-loudnorm.conf
do
  [ ! -e "$file" ] || mv -- "$file" "$ARCHIVE/node-collisions/"
done

for file in \
  hapax-tts-to-s4.conf \
  hapax-voice-s4-hardware.conf \
  hapax-yt-to-s4-bridge.conf.disabled
do
  [ ! -e "$file" ] || mv -- "$file" "$ARCHIVE/s4-usb-send-quarantine/"
done

find "$CONF_DIR" -maxdepth 1 -type f \
  \( -name "*.bak*" -o -name "*.disabled*" -o -name "*.replaced*" -o -name "*.SUPERSEDED-*" \) \
  -exec mv --target-directory "$ARCHIVE/fossils" -- {} +
```

After archiving, verify before restart:

```bash
python3 /home/hapax/projects/hapax-council--cx-gold/scripts/check-audio-conf-unique-node-names.py \
  --deployed-dir "$CONF_DIR"
```

When OBS/program output is safe to interrupt, restart through the existing safe
path and verify the live graph:

```bash
/home/hapax/projects/hapax-council--cx-gold/scripts/hapax-audio-safe-restart
/home/hapax/projects/hapax-council--cx-gold/scripts/hapax-audio-routing-check
```

Rollback is a file move from `$ARCHIVE` back into `$CONF_DIR`, followed by the
same operator-window restart and routing check.
