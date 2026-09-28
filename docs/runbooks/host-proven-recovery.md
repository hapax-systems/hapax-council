# Host recovery after controlled or accidental reboot

Task: `host-affecting-work-carries-proven-recovery-20260928`. The host-local
manifest is the declaration of what must return. Record it before work that may
reboot or wedge the host. The same watcher runs at boot and on a retry timer;
it does not require a planned-reboot marker or a live agent.

## Install and declare

On appendix, run `scripts/install-host-recovery --install` from an activated
source tree. The installer copies the script and four units into stable home
paths, reloads the user manager, and enables the capture timer, boot restore
service, and retry timer. `--check` verifies the installed copies and enablement.
The timer records live `hapax-codex-*` and `hapax-claude-*` tmux panes every
minute. A pane is admitted only with an explicit transcript UUID, a matching
role and inbox, and a dedicated user cgroup with MemoryHigh=5G,
MemoryMax=7G, and MemorySwapMax=1G. It records the original session identity
where present; otherwise the explicit transcript UUID becomes that identity.
Captured shell commands and prompts are never stored or replayed.

For named services, declare the live desired state before host work:

```sh
~/.local/bin/hapax-host-recovery capture \
  --unit user:fleet-review.service \
  --unit user:fleet-review-tailnet.service
```

`system:` is also accepted for root-managed units, using noninteractive sudo
on restore. The unit must be active when declared. The manifest records its
current enablement and restores it only if that state still matches. A local
manifest is owner-only, atomically replaced, and checked by SHA-256 before
any restore action. A capture cannot erase the last desired state when all
lanes are absent, or overwrite a manifest from a boot whose recovery has not
completed.

On aperture, where the vault is not mounted, install with
`--report-host hapax-appendix`. The restorer sends its done mail to appendix
over Tailscale SSH, and independently posts to `hapax-ops` on ntfy. A failed
delivery leaves the old boot ID in the manifest so the retry timer tries again.
The local mail remains in `~/.local/state/hapax/host-recovery/mail/`.

## Restore and readback

The boot service restores declared units first. It then recreates only missing
tmux lanes from allowlisted provider, role, transcript, workdir, and inbox
fields. Each lane starts inside its own systemd scope at the recorded limits.
Readback checks the live process role, transcript, session ID, and cgroup
limits. Existing tmux sessions are checked without replacement. The report
names units started, lanes restored, lanes already live, and every failure.
Invalid manifests are refused and reported. Re-running restore on a complete
same-boot state is a no-op.

The appendix-specific host containment installer is
`scripts/install-appendix-host-containment --install`; `--check` reads back its
root drop-ins and live values. It admits only `hapax-appendix` with measured
MemTotal in 59–61 GiB. The user tree has a 38G maximum, `system.slice` a 20G
maximum, leaving over 2G for kernel/unreclaimable memory. The
`hapax-llama-gptoss` Docker container is capped at 8G RAM/10G total swap.
A later udev rule wins over CachyOS's 30-zram rule, and the installer triggers
zram0 and reads back `vm.swappiness=10`. It backs up each replaced root file.

## 2026-09-28 proof

- Appendix dry run at 22:38Z: 19/19 live panes parsed, including `dev1-seat`,
  `dev21`, and 16 Codex lanes; all had valid role, transcript, inbox, and
  memory-scope readbacks. The live coordinator scope was bounded at 5G/7G/1G
  without restarting it. The installed boot service returned success on the
  same boot with all 19 already live. Appendix has **not** been rebooted under
  this new mechanism.
- Appendix containment was installed at 22:38Z. `--check` read back user
  MemoryHigh=32G/MemoryMax=38G, system MemoryHigh=16G/MemoryMax=20G,
  swappiness 10 after a zram change trigger, and Docker 8G/10G.
- Aperture preboot manifest pinned boot
  `4b66a0a7-2e53-442e-ba31-fcda2736b3fc`, with active
  `fleet-review.service` (enabled) and `fleet-review-tailnet.service`
  (static). A controlled reboot changed it to
  `877be5fc-b7c9-4017-91e0-2bb0d13baacd`. At 22:48:27Z the boot
  restorer started the missing tailnet proxy; both units then read active,
  and the tailnet review endpoint's `/health` returned `{"status":"ok"}` from
  appendix. Its report reached `lanebus/dev1/20260928T224827Z-host-recovery-aperture-2993.md`
  and the `hapax-ops` ntfy topic. The manifest was stamped with the new boot
  only after report delivery.
- The focused test suite passed 13 cases. Deliberate mutations of the boot
  guard, scope ceiling, unit active check, bounded launch command, hash check,
  absent-tmux handling, and report-before-stamp order each made its matching
  test red, then all tests passed after restoring the source.

The root cause of appendix's 21:49Z watchdog expiry remains unproved; the
postmortem is `frame/POSTMORTEM-20260928-appendix-watchdog-reset.md` in the
canonical vault. The controlled proof shows the new mechanism restored a
missing nonproduction service. Appendix's next real reboot is still the first
end-to-end test of its tmux lane restoration after a boot.
