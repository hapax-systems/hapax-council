---
name: studio
description: Check music production infrastructure. Auto-run when: operator mentions MIDI, audio, music production, beats, or studio setup, when audio/MIDI errors appear in tool output (PostToolUse suggests it), or user asks about studio. Invoke proactively without asking.
---

Check music production infrastructure:

```bash
aconnect -l 2>/dev/null
```

```bash
aplay -l 2>/dev/null
```

```bash
lsmod | grep -i virmidi
```

```bash
docker ps --filter "name=midi" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null
```

Report MIDI port connections, audio device availability, virtual MIDI status, and any MIDI Docker containers. Summarize what is connected and what is missing.
