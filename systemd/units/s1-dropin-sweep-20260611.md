# S1 drop-in sweep receipt - 2026-06-11

Task: `audit-w1-s1-release-pinning-20260611`
AuthorityCase: `CASE-AUDIT-W1-RESTART-CLASS`
Parent spec: `/home/hapax/Documents/Personal/30-areas/hapax/subsystem-audit-2026-06-11-v2/REPORT.md`

## Release-root pinning

The following S1 or S1-adjacent production units now execute repo code from
`%h/.cache/hapax/source-activation/worktree` rather than
`%h/projects/hapax-council`:

| Unit | Disposition |
|---|---|
| `hapax-audio-ducker.service` | `WorkingDirectory`, `PYTHONPATH`, source guard, and `ExecStart` pinned to source-activation `.venv`. |
| `hapax-audio-router.service` | Same; CUDA remains hidden. |
| `hapax-lufs-panic-cap.service` | Same; Prometheus exporter/resource limits unchanged. |
| `hapax-usb-router.service` | Script execution moved to the activated release tree. |
| `visual-layer-aggregator.service` | Same; existing memory profile unchanged. |
| `stimmung-sync.service` | Same; existing journal/resource profile unchanged. |
| `hapax-content-resolver.service` | Same; existing restart/memory profile unchanged. |
| `hapax-content-candidate-discovery.service` | Same; oneshot cadence and resource caps unchanged. |
| `hapax-imagination-loop.service` | Same; OMP/MKL caps unchanged. |
| `hapax-private-broadcast-echo-probe.service` | Probe script runs from the activated release tree. |
| `studio-fx-output.service` | Helper script runs from the activated release tree. |

`hapax-imagination.service` remains an installed Rust binary managed by
`hapax-rebuild-logos.service` and its build SHA receipt, but its formerly
drop-in-owned GPU selector is now versioned in the unit.

## Drop-in sweep

Repo-versioned drop-ins that intentionally survive:

| Unit | Versioned drop-ins | Provenance |
|---|---|---|
| `hapax-daimonion.service` | `aec.conf`, `audio-input.conf`, `capacity.conf`, `cpu-affinity.conf`, `gpu-pin.conf`, `shutdown-killmode.conf`, `tts-backend.conf` | Voice foundation collapse ledger in `hapax-daimonion.service.d/README.md`; all live knobs have code or library readers. |
| `hapax-broadcast-audio-health.service` | `90-source-activation-context.conf` | Pins the health producer to source activation. |
| `hapax-imagination.service` | `zzzz-screwm-reverie-source-only.conf` | Screwm/Quake consumes Reverie as a texture; unit now also versions `HAPAX_WGPU_ADAPTER_CONTAINS=5060`. |
| `hapax-v4l2-bridge.service` | `zzzz-screwm-quake-primary.conf` | DarkPlaces/Screwm primary route context. |
| `mediamtx.service` | `20-source-activation-worktree.conf` | Source-activation script root for MediaMTX. |
| `studio-compositor.service` | `cpu-affinity.conf`, `layout-mode-persist.conf`, `malloc-arena.conf`, `v4l2-bridge.conf` | Versioned compositor runtime overrides. |
| `pipewire.service`, `pipewire-pulse.service`, `wireplumber.service` | `cpu-affinity.conf` | Versioned audio-core CPU affinity. |
| `tabbyapi.service` | `gpu-pin.conf` | Versioned inference GPU pin. |
| `audio-recorder.service`, `contact-mic-recorder.service` | `archive-path.conf` | Versioned recorder archive paths. |
| `youtube-player.service` | `slot-count.conf` | Versioned player slot count. |

Former unversioned S1 local drop-ins are collapsed as follows:

| Unit | Former local drop-in class | Disposition |
|---|---|---|
| `hapax-daimonion.service` | `opt-in-all.conf`, `override.conf`, `rode-input.conf`, `tts-target.conf`, `zz-capacity.conf`, `zz-stale-rode-runtime-mitigation.conf` | Deleted or replaced by versioned files per `hapax-daimonion.service.d/README.md`. |
| `hapax-segment-prep.service` | `10-source-activation.conf` | Folded into the base unit; stale local copy is removed on deploy. |
| `hapax-darkplaces-v4l2.service` | Xvfb visible route / NVIDIA GLX route drop-ins | Folded into the base unit; stale local copies are removed on deploy. |
| `hapax-imagination.service` | GPU pin, dead JPEG cadence, and source-route drop-ins | GPU pin is versioned in the base unit; stale local copies are removed on deploy unless they match repo-versioned drop-ins. |
| `hapax-reverie.service` | `3d-mode.conf` | `HAPAX_3D_COMPOSITOR=1` is versioned in the base unit; stale local copy is removed on deploy. |
| `logos-api.service` | `source-worktree.conf`, `zz-source-activation.conf`, duplicate local source-root overrides | Base unit is already source-activation rooted; stale local copies are removed on deploy. |

Recheck commands:

```bash
python3 - <<'PY'
from pathlib import Path
root = Path("systemd/units")
rooting_keys = (
    "ExecCondition=",
    "ExecStartPre=",
    "ExecStart=",
    "ExecStartPost=",
    "ExecStop=",
    "WorkingDirectory=",
    "Environment=PYTHONPATH=",
    "Environment=PATH=",
)
for unit in [
    "hapax-audio-ducker.service",
    "hapax-audio-router.service",
    "hapax-lufs-panic-cap.service",
    "hapax-usb-router.service",
    "visual-layer-aggregator.service",
    "stimmung-sync.service",
    "hapax-content-resolver.service",
    "hapax-content-candidate-discovery.service",
    "hapax-imagination-loop.service",
    "hapax-private-broadcast-echo-probe.service",
    "studio-fx-output.service",
]:
    lines = [
        line.strip()
        for line in (root / unit).read_text().splitlines()
        if line.strip().startswith(rooting_keys)
    ]
    assert any("%h/.cache/hapax/source-activation/worktree" in line for line in lines), unit
    offenders = [
        line
        for line in lines
        if "%h/projects/hapax-council" in line
        or "/home/hapax/projects/hapax-council" in line
    ]
    assert not offenders, (unit, offenders)
print("release-root pinning ok")
PY

scripts/hapax-post-merge-deploy --report-coverage-stdin <<'EOF'
systemd/units/s1-dropin-sweep-20260611.md
systemd/units/hapax-audio-ducker.service
systemd/units/hapax-imagination.service
EOF
```
