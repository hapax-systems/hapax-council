# DarkPlaces renderer soak / suitability gate

The DarkPlaces/Screwm GL renderer is **attended-only** after the 2026-05-23 AMD
data-fabric sync-flood host hard-reset
([audit](../audits/2026-05-23-screwm-quake-runtime-reset-containment.md)). The
30-second `darkplaces-attended-smoke.sh` was the only suitability check; this
gate adds the **1-hour crash-free soak** that must PASS before the renderer may
be promoted to run behind the persistent `~/.config/hapax/enable-darkplaces-runtime`
gate.

## Why a soak gate

The sync-flood class can hard-reset the host before any monitor reacts, so the
gate is **fail-closed and pass-authorizes**: a PASS authorizes creating the gate;
the gate never authorizes the soak. The soak runs the renderer under a
single-command `HAPAX_DARKPLACES_RUNTIME_ACK=1` (containment intact if it aborts),
and a single data-fabric/Xid kernel line is an **instant FAIL** — no tolerance.

## Components

| File | Role |
|------|------|
| `shared/darkplaces_soak.py` | Tested decision core: fault detection, PASS/FAIL verdict, hardware fingerprint, receipt, promote decision. **All safety decisions live here** (`tests/test_darkplaces_soak.py`). |
| `scripts/darkplaces-soak.py` | Live CLI: `monitor` (the per-second loop), `promote`, `fingerprint`. |
| `scripts/darkplaces-soak.sh` | Attended orchestrator: preconditions → launch renderer → stream evidence → run the monitor. |
| `scripts/darkplaces-promote.sh` | Creates the gate file iff a fresh PASS receipt matches the current hardware fingerprint. |

## Running it (operator-attended only)

```bash
# 1. Confirm the renderer is contained (gate ABSENT) and you are present.
ls ~/.config/hapax/enable-darkplaces-runtime   # must NOT exist

# 2. Run the 1h soak (Xvfb path is display-safe). ACK gates the attended window.
HAPAX_DARKPLACES_SMOKE_ACK=1 scripts/darkplaces-soak.sh --xvfb --duration-s 3600

# 3. On PASS, promote to ATTENDED runtime (creates the gate file iff fresh+matching):
scripts/darkplaces-promote.sh
```

Evidence + the `receipt.json` land under
`~/hapax-state/hardware-validation/darkplaces-soak-<ts>-<pid>/`.

## PASS criteria (all, continuously, for the full duration)

1. Zero hardware-risk kernel lines (`data fabric|sync flood|NVRM: Xid|GPU has
   fallen off|hardware error|fatal`) — a single hit is an instant FAIL.
2. Renderer + feeder alive, no respawn.
3. `GL_RENDERER` pinned to the expected GPU (5060 Ti / index 1) — no mid-run
   GPU re-selection.
4. Frame production never stalled beyond `--max-frame-age-s` (default 5s).
5. GPU under thermal/VRAM fail bands.
6. No host reset — checked via the receipt's `end_marker` (absent ⇒ the soak was
   killed mid-write, e.g. a reset ⇒ the pass is not trusted).

## Promotion is fingerprinted and time-boxed

`darkplaces-promote.sh` refuses unless the latest receipt is `status=pass`, has an
`end_marker`, matches the **current** hardware fingerprint (GPU name | driver |
PCI — a driver upgrade or GPU swap invalidates a prior pass), and is fresh
(default ≤24h). A PASS clears **ATTENDED** runtime only.

> **Unattended boot-enable is a separate tier-2 step** — it requires a
> repeat/overnight pass AND the 2026-05-23 reset cause being understood. Do not
> add the `hapax-darkplaces*` units to boot auto-start until then.
