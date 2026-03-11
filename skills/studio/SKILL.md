---
name: studio
description: Check music production infrastructure. Use when the user asks about MIDI, audio devices, studio setup, or runs /studio.
---

Check music production infrastructure:

1. ALSA MIDI ports: run `aconnect -l` and show connected ports
2. Audio devices: run `aplay -l` and summarize
3. Virtual MIDI: verify snd-virmidi is loaded (`lsmod | grep virmidi`)
4. MIDI MCP server: check if running
5. Any audio-related Docker containers

Report connections between MCP MIDI Out and hardware devices.
