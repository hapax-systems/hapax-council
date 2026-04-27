# Audio-stability systemd drop-ins

Persistent CPU affinity for the audio + livestream pipeline.

## Why

Documented live 2026-04-27: under heavy load (load avg 14–15) the
studio-compositor python at 250–380% CPU was preempting pipewire's
data-loop threads, causing periodic audio dropouts visible on the
L-12 USB output meter (1–1.5 blips/s). PipeWire data-loops run at
SCHED_FIFO 88 — should preempt SCHED_OTHER, but under sustained CPU
saturation across all 16 logical cores the data-loop occasionally
landed on a contended core and missed its quantum deadline.

Fix: pin the audio data-loops to dedicated logical cores {6, 7, 14, 15}
(physical cores 6+7 with their SMT siblings on AMD Ryzen 7 7700X) and
exclude the studio-compositor from those cores. Operator-confirmed live
that this reduces the dropout rate to "shorter blips, less frequent"
when applied via runtime `taskset`. These drop-ins make it persistent.

## Install

```sh
mkdir -p ~/.config/systemd/user/pipewire.service.d
mkdir -p ~/.config/systemd/user/wireplumber.service.d
mkdir -p ~/.config/systemd/user/pipewire-pulse.service.d
mkdir -p ~/.config/systemd/user/studio-compositor.service.d

cp pipewire-cpu-affinity.conf       ~/.config/systemd/user/pipewire.service.d/cpu-affinity.conf
cp wireplumber-cpu-affinity.conf    ~/.config/systemd/user/wireplumber.service.d/cpu-affinity.conf
cp pipewire-pulse-cpu-affinity.conf ~/.config/systemd/user/pipewire-pulse.service.d/cpu-affinity.conf
cp studio-compositor-cpu-affinity.conf ~/.config/systemd/user/studio-compositor.service.d/cpu-affinity.conf

systemctl --user daemon-reload
systemctl --user restart pipewire pipewire-pulse wireplumber studio-compositor
```

## Verify

```sh
# data-loop threads should be SCHED_FIFO and pinned to {6,7,14,15} (mask c0c0)
for pid in $(pgrep -x "pipewire|wireplumber|pipewire-pulse"); do
  for tid in $(ls /proc/$pid/task/); do
    name=$(cat /proc/$pid/task/$tid/comm)
    if [[ "$name" == data-loop* ]]; then
      mask=$(taskset -p $tid | grep -oE "[0-9a-f]+$")
      echo "$name (pid=$pid tid=$tid): mask=$mask"
    fi
  done
done
# expected: mask=c0c0 for every data-loop

# compositor pinned away from {6,7,14,15} (mask 3f3f)
taskset -p $(pgrep -f "agents.studio_compositor$" | head -1)
# expected: mask 3f3f
```

## Rollback

Delete the four drop-in files and `daemon-reload + restart`.

## Why these specific cores

AMD Ryzen 7 7700X has 8 physical cores (0–7) + SMT siblings (8–15). All
on a single CCD, single NUMA node. Cores 6 + 7 + their siblings 14 + 15
are typically less contended than core 0 (which handles many hardware
IRQs). The 4-CPU pool gives the audio data-loops headroom for any short
spike without needing to migrate; the compositor still has 12 logical
cores to thrash, which empirically is more than enough.
