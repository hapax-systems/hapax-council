# Host recovery after controlled or accidental reboot

Task: `host-affecting-work-carries-proven-recovery-20260928`. The host-local
manifest is the declaration of what must return. Record it before work that may
reboot or wedge the host. The same watcher runs at boot and on a retry timer;
it does not require a planned-reboot marker or a live agent.

## Install and declare

After a governed source release, invoke
`~/.cache/hapax/source-activation/worktree/scripts/install-host-recovery`.
It checks the active-source receipt, release commit, and clean tracked recovery
files. It refuses `--source`, `--install`, and destination/systemctl overrides.
Use `--prepare` to copy the script and four units into stable home paths, then
`--check` to compare every copy. Use `--activate` only under separately admitted
runtime authority: it repeats the byte check, reloads the user manager, enables
the boot restore service **without starting it now**, starts the capture timer,
and enables the retry timer while leaving it stopped until reboot. Finally
`--check-active` reads back those enabled/active states. Pass
`--report-host hapax-appendix` at each step on aperture. A direct activation
without prepared matching files refuses before any systemctl call. Post-merge
deploy may publish the release-pinned script and units; their `Hapax-Parked`
markers leave both timers disabled until explicit activation. A later change
to either timer parks it again for a new check and activation. The restore
service has no auto-enable marker. Verify the installed script bytes against the
accepted release after deployment, especially on appendix, where the old
installed SHA-256 `8106d294…` differed from held source `4b228e88…`.
The timer records live `hapax-codex-*` and `hapax-claude-*` tmux panes every
minute. A pane is admitted only with an explicit transcript UUID, a matching
role and inbox, measured sandbox/approval or permission mode, and a dedicated
user cgroup with MemoryHigh=5G,
MemoryMax=7G, and MemorySwapMax=1G. It records the original session identity
where present; otherwise the explicit transcript UUID becomes that identity.
Captured shell commands and prompts are never stored or replayed. A legacy
manifest lacking session modes can be refreshed from a live lane on the same
boot; restore refuses to relaunch it without a measured mode.

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

On appendix, every capture also records `hapax-lane-idle-watchdog.timer` as
**disabled**, including while it is inactive. Restore checks that it remains
disabled and inactive and never starts or enables it. An enabled or active
timer appears as a named recovery failure; do not recapture that drift as the
desired state. The first capture after installing this version adds the policy
to the host-local manifest; do not declare this inactive timer with `--unit`.

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

The Sep 29 Codex successor has the exact binding `dev1-seat-codex` /
`hapax-codex-seat` / `lanebus/dev1`. The Claude `dev1-seat` /
`hapax-claude-dev1-seat` binding is separate. Capture retains saved missing
panes for crash recovery, so a recapture does not retire either binding or
confer coordinator authority on a restored pane. Check the current seat
charter and disposition before deciding which recovered pane may coordinate.

For an appendix dry run that exercises lane reconstruction without stopping a
live pane, first capture and verify the current owner-only manifest, and choose
one lane name present in it. Record the manifest SHA-256 and `tmux has-session`
readback. Run:

```sh
~/.local/bin/hapax-host-recovery restore --dry-run \
  --simulate-missing-lane hapax-codex-openmarket
```

The JSON must report `dry_run: true`, the chosen lane in both `simulated_missing`
and `restored` (a **planned** restore), no `failed` entry, and no real
`new-session`, unit start, report, or manifest stamp. Recompute the manifest hash
and read back the same live tmux pane afterward. A missing or undeclared lane
name refuses. This proves bounded command reconstruction for the selected
manifest entry; it does not prove a real post-boot launch. The focused test
`test_dry_run_simulates_missing_live_lane_without_mutation` checks that the
same-boot fast path is bypassed and the manifest remains byte-identical.

The appendix root drop-ins, zram override, and Docker limit are owned by
codex-worktree's P0-1 (#4937/#4951). Their current live values and preimages
are recorded in the appendix postmortem. Do not use this recovery runbook to
change those ceilings.

The 2026-09-28 appendix watcher install, containment, and same-boot check
occurred while the parent row still recorded S1. The repair readback in
`frame/POSTMORTEM-20260928-appendix-watchdog-reset.md` records each before and
after value: watcher script/units absent → installed and enabled, manifest
absent → 19 measured lanes, and coordinator memory scope unbounded → 5G/7G/1G.
The later unit refresh at 23:17Z made the source/installed unit check pass;
same-boot restore saw 19 already-live lanes and zero failures. Those are
postimages, not retroactive authorization. The parent claim existed, but no
act-specific pre-challenge/ISAM record or S1→S6 transition was found for the
appendix acts. Release adjudication must resolve that authority gap separately;
this source repair performs no live install or runtime action.

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
