# cc-pr-merge-watcher opt-out runtime witness

Date: 2026-07-09

Scope: PR #4472 / `cc-task-sdlc-wave3d-20260709`

Purpose: provide a durable live-runtime-composition witness for the merge-watcher
`close_on_pr_merge: false` path. The production reconciliation function was invoked
against an isolated temporary vault fixture containing the reviewed task frontmatter
shape. The GitHub runner was stubbed to report PR #4472 as `MERGED`; the run used
`dry_run=True` and a temporary repo root, so it could not mutate the real vault or execute the real
`scripts/cc-close`.

Recheck command:

```bash
uv run python - <<'PY'
from __future__ import annotations

import importlib.util
import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

repo = Path(".").resolve()
script = repo / "scripts" / "cc-pr-merge-watcher.py"
module_name = "cc_pr_merge_watcher_witness"
spec = importlib.util.spec_from_file_location(module_name, script)
watcher = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[module_name] = watcher
spec.loader.exec_module(watcher)

note_name = "cc-task-sdlc-wave3d-20260709.md"
task_note_text = """---
task_id: cc-task-sdlc-wave3d-20260709
status: pr_open
pr: 4472
close_on_pr_merge: false
---

fixture body: multi-PR lane remains open until the lane owner closes explicitly
"""


class Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.cc_close_invocations: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            path = cmd[6]
            match = re.fullmatch(r"repos/hapax-systems/hapax-council/pulls/(\d+)", path)
            if match:
                payload = {
                    "number": int(match.group(1)),
                    "state": "closed",
                    "merged": True,
                    "merged_at": "2026-07-09T12:50:00Z",
                    "draft": False,
                }
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd and str(cmd[0]).endswith("/scripts/cc-close"):
            self.cc_close_invocations.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "closed\n", "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")


with tempfile.TemporaryDirectory(prefix="cc-pr-merge-watcher-witness-") as td:
    root = Path(td)
    vault = root / "vault"
    active = vault / "active"
    active.mkdir(parents=True)
    note = active / note_name
    note.write_text(task_note_text, encoding="utf-8")

    fake_repo = root / "repo"
    (fake_repo / "scripts").mkdir(parents=True)
    (fake_repo / "scripts" / "cc-close").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_repo / "scripts" / "cc-close").chmod(0o755)

    runner = Runner()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    counters = watcher.reconcile_stale_pr_states(
        vault_root=vault,
        repo_root=fake_repo,
        dry_run=True,
        runner=runner,
    )
    print("fixture_frontmatter_pr", "4472")
    print("fixture_frontmatter_close_on_pr_merge", "false")
    print("stubbed_pr_state", "MERGED")
    print("dry_run", True)
    print("counters", json.dumps(counters, sort_keys=True))
    print("gh_calls", len([call for call in runner.calls if call[:2] == ["gh", "api"]]))
    print("cc_close_invocations", len(runner.cc_close_invocations))
    print("note_still_active_contains_pr_open", "status: pr_open" in note.read_text())
PY
```

Observed output:

```text
INFO:cc-pr-merge-watcher:task cc-task-sdlc-wave3d-20260709 declares close_on_pr_merge: false — lane owner closes explicitly
fixture_frontmatter_pr 4472
fixture_frontmatter_close_on_pr_merge false
stubbed_pr_state MERGED
dry_run True
counters {"closed": 0, "repaired": 0, "scanned": 1, "stale": 0}
gh_calls 1
cc_close_invocations 0
note_still_active_contains_pr_open True
```

Live timer composition observation:

```text
systemctl --user status hapax-cc-pr-merge-watcher.timer hapax-cc-pr-merge-watcher.service --no-pager
timer: active (waiting), enabled; next trigger was scheduled for 2026-07-09 08:15:29 CDT
service: inactive (dead), last run completed successfully at 2026-07-09 08:06:24 CDT

systemctl --user cat hapax-cc-pr-merge-watcher.service hapax-cc-pr-merge-watcher.timer --no-pager
ExecStart=$HOME/.local/bin/uv --directory $HOME/.cache/hapax/source-activation/worktree run python scripts/cc-pr-merge-watcher.py --repo-root $HOME/.cache/hapax/source-activation/worktree
WorkingDirectory=$HOME/.cache/hapax/source-activation/worktree
timer: OnBootSec=3min; OnUnitActiveSec=9min; RandomizedDelaySec=45s; AccuracySec=30s
```

Interpretation:

- The production stale-PR reconciliation path reached the merged-PR closure branch.
- The task note's `close_on_pr_merge: false` frontmatter declined the close.
- No `cc-close` command was invoked.
- The fixture note remained `status: pr_open`.
- The live timer is enabled and executes the source-activation worktree.

Limit: the opt-out probe is isolated and dry-run because PR #4472 is not merged. The live timer observation proves the production composition route and cadence, not that the currently activated source already contains the PR branch. Release sequencing must deploy source activation after merge before relying on the timer for this opt-out.
