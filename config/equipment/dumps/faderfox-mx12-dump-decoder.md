# Faderfox MX12 SysEx dump format (reverse-engineered 2026-06-10)
Capture: setup mode -> hold green btn 7 -> SndA (all setups, USB only). Restore: rEc mode (btn 8) + send .syx.
Format: 3-byte records `[tag, 0x2H, 0x1L]` -> value = H<<4|L. Tag 0x4D = memory stream; others = header.
Memory: 36 blocks x 384 bytes (30 setups + 6 system). Block = 6 rows x (12 records x 5B + 4B header).
Record: [channel-1, cc, lower, upper, mode]. Row order: potA, potB, FADERS, btnC, btnD, encoder.
## Device truth at dump time
- Setup 01 = THE custom profile: faders 2-12 = ch2-12 CC95 (bridge-mapped); **fader 1 CLOBBERED to ch1 CC1**
  (matches pot A1's factory assignment — learn accident). Repair: learn-mode + emit ch1 CC95 via MX12 MIDI-in.
- potB-1 also carries a stray ch1 CC95.
- All other setups factory (channel gradient confirms: setup N saturated with N-1).
## Witnesses landed against this dump
- 2026-06-10 wet-return: s4_wet_return_signal=true
- 2026-06-10 faderfox: 246 mapped events, drift=false (fader 2 ride)
