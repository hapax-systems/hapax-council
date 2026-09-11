# Activating the backup units through governed source activation

Replace the earlier “pull the checkout on podium” step with the governed
source-activation flow below. Do not run either backup unit from a mutable
`~/projects` checkout.

After this PR merges to `main`, run or wait for the existing source-activation
service on podium:

```bash
systemctl --user start hapax-source-activate.service
systemctl --user --no-pager --full status hapax-source-activate.service
```

The source-activation deploy must advance
`~/.cache/hapax/source-activation/worktree` to the merged `origin/main` commit,
install/reload the changed user units, and leave both backup services loaded
from that activation root. Record this non-secret evidence in the PR before
calling runtime activation complete:

```bash
git -C ~/.cache/hapax/source-activation/worktree rev-parse HEAD
jq '{status, deploy_status, origin_main_sha, active_source_head, active_source_path}' \
  ~/.cache/hapax/source-activation/current.json
systemctl --user show hapax-backup-local.service hapax-backup-remote.service \
  -p FragmentPath -p ExecStart -p Result -p ExecMainStatus
systemctl --user is-enabled hapax-backup-local.timer hapax-backup-remote.timer
systemctl --user is-active hapax-backup-local.timer hapax-backup-remote.timer
systemctl --user list-timers hapax-backup-local.timer hapax-backup-remote.timer
```

Do not claim a successful runtime backup from static tests. After the next
scheduled runs (or an explicitly authorized manual run), append the following
receipt without credential output:

```bash
systemctl --user show hapax-backup-local.service hapax-backup-remote.service \
  -p Result -p ExecMainCode -p ExecMainStatus -p ExecMainStartTimestamp \
  -p ExecMainExitTimestamp
journalctl --user -u hapax-backup-local.service -u hapax-backup-remote.service \
  --since today --no-pager
```
