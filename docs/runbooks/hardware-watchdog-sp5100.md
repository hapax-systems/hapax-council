# Hardware Watchdog (SP5100-TCO) — Arm / Verify / Rollback

Authority: CASE-AUDIT-W0-HAZARD, Wave 0.1 of
`30-areas/hapax/subsystem-audit-2026-06-11-v2/interview-readiness-wave-plan.md`.
Hazard: a kernel hard-hang on either 24/7 host had **no reset path** — the
hardware watchdog was denylisted by the distro and never armed.

Hosts: **podium** + **appendix** (both AMD Ryzen / CachyOS; the SP5100/SB800
TCO timer is the chipset watchdog, driver `sp5100_tco`).

## Mechanism

Three files, all repo-versioned, installed by
`scripts/install-hardware-watchdog.sh`:

| Repo source | Installed at | Role |
|---|---|---|
| `config/modprobe.d/blacklist.conf` | `/etc/modprobe.d/blacklist.conf` | **Un-denylist.** Shadows the cachyos-settings vendor file of the same name (kmod gives /etc full precedence per-basename). Keeps `iTCO_wdt` blacklisted, drops `sp5100_tco`. |
| `config/modules-load.d/hapax-watchdog.conf` | `/etc/modules-load.d/hapax-watchdog.conf` | Loads `sp5100_tco` at boot. |
| `systemd/system/system.conf.d/10-hapax-watchdog.conf` | `/etc/systemd/system.conf.d/10-hapax-watchdog.conf` | `RuntimeWatchdogSec=60s` — PID 1 opens `/dev/watchdog0`, sets the hardware timeout to 60s, pets every 30s. Hard-hang ⇒ chipset hard-reset. |

Why the shadow file is required: `blacklist` directives are cumulative and
cannot be negated by another modprobe.d file, and `systemd-modules-load`
applies blacklists even to explicit `modules-load.d` entries
(`KMOD_PROBE_APPLY_BLACKLIST`). This is why the 2026-03 podium attempt
(`/etc/modules-load.d/watchdog.conf` + an `install --ignore-install`
override + `RuntimeWatchdogSec=30` edited directly into
`/etc/systemd/system.conf`) sat inert for ~3 months: the module was only
loadable by hand. The installer removes those superseded artifacts.

`nowayout=0` (driver default, confirmed in dmesg on both hosts): closing the
device with the magic character disarms the timer, so disarm/rollback does
not require a reboot. With the hardware present, systemd's
`RebootWatchdogSec` (default 10min) also becomes effective during reboots.

## Install / re-apply

On each host, from a current checkout:

```bash
scripts/install-hardware-watchdog.sh --dry-run   # preview
scripts/install-hardware-watchdog.sh             # install + arm + verify
scripts/install-hardware-watchdog.sh --check     # drift check (cron-safe)
```

Apply mode restarts `systemd-modules-load.service`, then
`systemctl daemon-reexec` so PID 1 re-reads the drop-in and arms the
watchdog — no reboot needed. The script verifies and exits non-zero on
failure.

## Verify (exit predicates)

```bash
test -e /dev/watchdog && echo armed-device-present        # exit 0 required
cat /sys/class/watchdog/watchdog0/state                   # → active
cat /sys/class/watchdog/watchdog0/identity                # → SP5100 TCO timer
systemctl show -p RuntimeWatchdogUSec                     # → 1min
sudo fuser -v /dev/watchdog0                              # → PID 1 (systemd)
journalctl -b _PID=1 | grep -i "hardware watchdog"        # → Using hardware watchdog /dev/watchdog0 …
```

A true end-to-end test (`echo c > /proc/sysrq-trigger` ⇒ host hard-resets
within ~60s) is deliberately **not** automated — operator-initiated only,
during a declared maintenance window.

## Rollback (re-denylist)

Per host, in this order:

```bash
# 1. Remove the arming config
sudo rm /etc/systemd/system.conf.d/10-hapax-watchdog.conf
sudo rm /etc/modules-load.d/hapax-watchdog.conf
sudo rm /etc/modprobe.d/blacklist.conf        # vendor denylist resumes effect

# 2. Disarm: PID 1 re-reads config (now watchdog=off) and closes the
#    device with magic close (nowayout=0 ⇒ timer stops)
sudo systemctl daemon-reexec

# 3. Confirm disarmed, then unload
cat /sys/class/watchdog/watchdog0/state       # → inactive
sudo rmmod sp5100_tco
test -e /dev/watchdog || echo rolled-back
```

Step 2 must precede step 3: never `rmmod` while the timer is `active`.
After step 1 the rollback is reboot-persistent regardless.

## Maintenance caveats

- **cachyos-settings upgrades**: the shadow file fully masks the vendor
  `/usr/lib/modprobe.d/blacklist.conf`. After an upgrade, diff the vendor
  file against `config/modprobe.d/blacklist.conf` and fold in any new
  vendor blacklist entries (none expected to conflict — keep `sp5100_tco`
  un-denylisted).
- **Timeout tuning**: 60s was chosen for the first arm (podium routinely
  runs load-avg >15; spurious reset on the production rig is the worse
  failure). Tighten to 30s only after a clean multi-week soak: journal must
  be free of PID-1 watchdog errors and the hosts free of unexplained
  resets.
- **Vendor comment "(Required for Ryzen cpus)"** in the blacklist refers to
  old `sp5100_tco` breakage on early Ryzen; the driver initializes cleanly
  on both hosts (dmesg: `Using 0xfeb00000 for watchdog MMIO address`,
  kernels 6.18 LTS and 7.0.9).

## History

- 2026-03-23: podium-only attempt (modules-load + install-override +
  direct system.conf edit) — inert for the reason above; artifacts removed
  by this packet's installer.
- 2026-06-11: armed on both hosts (audit-w0-watchdog-arm-20260611,
  CASE-AUDIT-W0-HAZARD).
