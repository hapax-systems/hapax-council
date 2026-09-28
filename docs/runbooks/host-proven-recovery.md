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
After merge, `hapax-post-merge-deploy` publishes the script and installs the
auto-enabled user units.
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
fields. Each lane starts inside its own systemd scope at the recorded memory
limits, with soft NOFILE=65536. Readback checks the live process role,
transcript, session ID, cgroup limits, and `/proc/<pid>/limits`; a lane with a
lower soft NOFILE is refused. Existing tmux sessions are checked without
replacement. The report
names units started, lanes restored, lanes already live, and every failure.
Invalid manifests are refused and reported. Re-running restore on a complete
same-boot state is a no-op.

The appendix root drop-ins, zram override, and Docker limit are owned by
codex-worktree's P0-1 (#4937/#4951). Their current live values and preimages
are recorded in the appendix postmortem. Do not use this recovery runbook to
change those ceilings.

## Choose a reboot proof target

Before any controlled reboot, search the open incident rows for the target
host and read each matching row. A host with an unresolved reset, hardware,
storage, or service incident needs a separate seat ruling before it can be a
proof target. Record the selection and ruling in the proof log. Aperture was
chosen on 2026-09-28 while its GPU/context and hardware-reset p0 row was open;
the controlled reboot was followed by a five-second fault boot and an AMD
data-fabric sync-flood reset. The recovery watcher worked, but that host was
an unsuitable proof target. Do not repeat the reboot as a recovery test.

## 2026-09-28 proof

- Appendix dry run at 22:38Z: 19/19 live panes parsed, including `dev1-seat`,
  `dev21`, and 16 Codex lanes; all had valid role, transcript, inbox, and
  memory-scope readbacks. The live coordinator scope was bounded at 5G/7G/1G
  without restarting it. The installed boot service returned success on the
  same boot with all 19 already live. Appendix has **not** been rebooted under
  this new mechanism.
- The 22:38Z live containment values and their authority correction are
  recorded in the postmortem. This P0-2/3 source covers recovery only.
- Aperture preboot manifest pinned boot
  `4b66a0a7-2e53-442e-ba31-fcda2736b3fc`, with active
  `fleet-review.service` (enabled) and `fleet-review-tailnet.service`
  (static). A controlled reboot changed it to
  `877be5fc-b7c9-4017-91e0-2bb0d13baacd`, after a five-second fault boot.
  At 22:48:27Z the boot
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
