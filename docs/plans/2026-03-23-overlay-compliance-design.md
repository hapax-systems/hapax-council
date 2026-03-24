# Overlay Design Language Compliance: Design Document

**Date:** 2026-03-23
**Scope:** Fix deviations in SignalPip, OperatorVitals, ZoneCard, ZoneOverlay, ClassificationInspector

---

## Fixes (15 actionable code changes)

### Batch A: Signal System
1. SignalPip pip sizes: 6/7/8/10 → 6/8/10 per §5.2
2. ZoneCard severity color: amber-400 → yellow-400 per §3.7
3. ZoneOverlay: add voice_session and system_state zones per §3.3
4. ZoneOverlay: enforce max 3 signals per zone

### Batch B: OperatorVitals
5. Stress pip animation: 1s → 1.5s per §5.2
6. Physiological load bar: add orange-400 step (green/yellow/orange/red) per §3.7
7. Phone battery bar: add orange-400 step per §3.7

### Batch C: Classification Inspector
8. Canvas backgrounds: rgba(0,0,0,X) → derive from palette["zinc-950"] per §8.2
9. Overlay background opacity: 92% → 88% (match InvestigationOverlay)
10. Color fallback: "#888" → palette["zinc-500"]
11. Slider accent: Tailwind class → inline style with palette per §2
