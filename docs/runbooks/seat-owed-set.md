---
title: Seat owed set
date: 2026-09-25
authority_case: CASE-SYSTEM-INTEGRITY-20260611
status: runbook
mutation_surface: source_docs
---

# Seat owed set

The owed set is the control point. Section 5 of the seat note is narrative.

CLEAR-READY and YIELD checkpoints paste the generated block above the narrative:

```bash
hapax-seat-owed-set --commit WORKTREE --text-block
```

An item leaves the set only by a disposition on its own record. A line in the checkpoint does not remove it. Age does not remove it. Items created at or after the activation instant are `new` (disposition within 30 minutes). Older items, and items whose `created_at` does not parse, are `backlog` (one disposition within 24 hours of activation).

The seat SessionStart hook matches `startup`, `resume`, and `clear`. It fires when `HAPAX_AGENT_ROLE` equals the process role named in the §0 incumbent row. It does not scan the task store. It reads `~/.cache/hapax/seat-owed-set-summary.txt`, states that file's age, and prints the full-list path. If the file is missing, it prints one unavailable line and that path. The existing 15-minute `lanebus-staleness-sweep` timer refreshes the file from the activation worktree (`~/.cache/hapax/source-activation/worktree`), which deploy points at the release tree on merge. The drop-in source is `systemd/units/lanebus-staleness-sweep.service.d/seat-owed-set.conf`. The base unit is `Type=oneshot`, so the second `ExecStart` is valid, and it has no leading `-`.

Recheck after deploy:

```bash
systemctl --user cat lanebus-staleness-sweep.service
test ! -e ~/.config/systemd/user/lanebus-staleness-sweep.service.d/seat-owed-set.conf
test ! -L ~/.local/bin/hapax-seat-owed-set
```

The live drop-in and the branch symlink were removed at 2026-09-25T03:31Z. Until merge, the SessionStart command finds no binary and its `|| true` is silent. The bus inbox stays the `family/name` token on that row. The summary lists new rows and undisposed bus asks in full, then backlog counts per class and the oldest 15 backlog rows.

A bus ask is disposed by a receipt, or by a seat drop in the sender's inbox that carries a disposition token (`granted`, `held:`, `declined`, `deferred_until:`, `done`, or `admitted`) and whose `re:` names the drop (filename, stem, or a shared `#NNNN`) or whose later `created_at` shares `thread`. A reply that only names the ask does not dispose it. The refresh opens only that sender's inbox, and only files newer than the ask. The injection states the residual of that rule. A line in section 5 does not dispose an ask.

While `m103_in_force: true` in `30-areas/hapax/frame/seat-stop-decisions.yaml`, startup and resume for every role, and clear for the seat, also inject `CONDUCTOR: stop yours now:` with that role's stop command. The source copy of the decision file is `config/seat-stop-decisions.yaml`.
