# WSL transcript custody

The Windows puller inventories `%USERPROFILE%`; that does not include a WSL distribution's Linux home.
Run the existing transcript CLI inside the distribution with `backup --capture`, followed by `verify`.
The capture uses the shared path table, including `.glmcp-claude`, rejects dangling or nested symlinks and
empty sources, excludes credential basenames and their backup variants, and captures SQLite through the
online backup API. Every regular file is hashed before backup and checked again through `restic dump`.
The existing count, missing-path and drop checks apply to the reconstructed capture listing.

`systemd/units/hapax-backup-transcripts-wsl.{service,timer}` binds Ubuntu 24.04 on dextra to the existing
encrypted NAS repository over pinned SSH/SFTP. Its host identity is `hapax-dextra-wsl-ubuntu24.04`, which
distinguishes the distro and the new capture format from the retained one-off `hapax-dextra-wsl` archive.
The first enrollment must reconcile its counts with that earlier archive; subsequent checks compare
captured paths and counts against the preceding snapshot. Both carry the never-pruned `tier1-transcripts`
tag. There is no forget/prune action in this service.

For first enrollment, run this comparison **on appendix**, where the NAS is mounted. List the baseline
host to confirm its timestamp and record the new successful snapshot's full ID. The retained September 30
baseline is pinned below; pass a newer retained baseline only after separately verifying its custody receipt.
For a pre-release candidate witness, set `NEW_SNAPSHOT` to that candidate's exact ID and `CUSTODY_SOURCE`
to its commit-addressed checkout; that does not activate it. After promotion use the active source root.

```bash
export PATH="$HOME/.local/bin:$PATH"
restic -r /mnt/nas/backups/restic --password-command 'hapax-secret backups/restic-password' \
  snapshots --host hapax-dextra-wsl --tag tier1-transcripts
export BASELINE_SNAPSHOT=02cbffd2b7e3c19a3438b86d023ed2704d69a3fe8bb7382cddb22af7207f23f6
export NEW_SNAPSHOT=FULL_ID_FROM_THE_SUCCESSFUL_RUN
export CUSTODY_SOURCE="$HOME/.cache/hapax/source-activation/worktree"
python3 - <<'PYCOMPARE'
import hashlib, json, os, pathlib, subprocess, sys, tarfile, tempfile
sys.path.insert(0, os.environ["CUSTODY_SOURCE"])
from scripts import transcript_custody as tc
base = ["restic", "-r", "/mnt/nas/backups/restic", "--password-command",
        "hapax-secret backups/restic-password", "dump", "--no-lock"]
with tempfile.TemporaryDirectory() as stage:
    archives = []
    for sid, name in [(os.environ["BASELINE_SNAPSHOT"], "/dextra-wsl-transcripts.tar"),
                      (os.environ["NEW_SNAPSHOT"], "/transcripts-consistent.tar")]:
        target = pathlib.Path(stage) / (str(len(archives)) + ".tar")
        with target.open("xb") as out:
            subprocess.run(base + [sid, name], stdout=out, check=True)
        archives.append(target)
    with tarfile.open(archives[0]) as tar:
        baseline = json.load(tar.extractfile("custody-manifest.json"))
        expected = {row["path"]: row for row in baseline["files"]}
        assert len(expected) == len(baseline["files"])
        observed = set()
        for member in tar:
            if member.name == "custody-manifest.json":
                continue
            assert member.isfile() and member.name in expected and member.name not in observed
            observed.add(member.name)
            digest = hashlib.sha256()
            with tar.extractfile(member) as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            assert member.size == expected[member.name]["bytes"]
            assert digest.hexdigest() == expected[member.name]["sha256"]
        assert observed == set(expected)
    with tarfile.open(archives[1]) as tar:
        paths, nodes = tc.read_capture(tar)
    counts = tc.count_snapshot(nodes, [path.real for path in paths])
    new = {path.declared.removeprefix("~/"): counts[path.real].files for path in paths}
    old = {row["path"]: row["files"] for row in baseline["paths"]}
    failures = {path: {"baseline": count, "new": new.get(path)}
                for path, count in old.items() if new.get(path, 0) < count}
    receipt = {"baseline": os.environ["BASELINE_SNAPSHOT"], "snapshot": os.environ["NEW_SNAPSHOT"],
               "baseline_counts": old, "new_counts": new, "failures": failures}
    print(json.dumps(receipt, indent=2))
    assert not failures, "Enrollment lost baseline files; reconcile before enabling the timer"
PYCOMPARE
```

Retain this JSON output beside the independent restore receipt. A missing path or lower count blocks first
enrollment; investigate actual missing files before accepting a deliberate cleanup. The existing same-host
verifier handles subsequent snapshots; it cannot substitute for this cross-host baseline comparison.

Install only from a merged, independently accepted council commit through the target's governed
source-activation binding, `%h/.cache/hapax/source-activation/worktree`. Preserve the previous
commit-addressed release. This service uses only Python's standard library, restic and the existing
`hapax-secret` forwarding interface; no reins key is copied. On WSL, use a bounded source-activation
profile instead of deploying appendix's unrelated services. Disabled candidate units may be staged for inspection with separate candidate commit/hash receipts.
At promotion replace them from the accepted active release and verify both hashes before enabling.
A candidate checkout is not an active release. Do not enable the timer until the active source root and installed units have matching
commit/hash receipts, pinned appendix SSH authentication works, and a manual custody run passes.

Recheck the installed source, units, scheduling and snapshot from dextra's Ubuntu distribution:

```bash
readlink -f ~/.cache/hapax/source-activation/worktree
git -C ~/.cache/hapax/source-activation/worktree rev-parse HEAD
sha256sum ~/.cache/hapax/source-activation/worktree/scripts/{hapax-transcript-custody,transcript_custody.py}
sha256sum ~/.config/systemd/user/hapax-backup-transcripts-wsl.{service,timer}
systemctl --user cat hapax-backup-transcripts-wsl.service
systemctl --user start hapax-backup-transcripts-wsl.service
systemctl --user show hapax-backup-transcripts-wsl.service -p Result -p ExecMainStatus
systemctl --user list-timers hapax-backup-transcripts-wsl.timer
journalctl --user -u hapax-backup-transcripts-wsl.service --since today --no-pager
RESTIC_REPOSITORY=sftp:hapax-appendix:/mnt/nas/backups/restic \
  HAPAX_TRANSCRIPT_HOST=hapax-dextra-wsl-ubuntu24.04 \
  HAPAX_TRANSCRIPT_SERVICE=hapax-backup-transcripts-wsl.service \
  python3 ~/.cache/hapax/source-activation/worktree/scripts/hapax-transcript-custody verify
restic -r sftp:hapax-appendix:/mnt/nas/backups/restic \
  --password-command 'hapax-secret backups/restic-password' snapshots \
  --host hapax-dextra-wsl-ubuntu24.04 --tag tier1-transcripts
```

Record the exact snapshot ID from that successful run. Independently run `restic dump SNAPSHOT
/transcripts-consistent.tar` from appendix's NAS repository, verify its manifest with
`transcript_custody.read_capture`, restore the Codex SQLite member into a new private directory and
run `PRAGMA quick_check`. A transport failure, truncated archive, hash/count drop or failed database
check leaves custody unaccepted; inspect the private failure receipt and repeat a new capture after
repairing the named source or link. Record the actual restored-file observations beside the installed
commit and unit hashes. Runtime acceptance is separate from this PR's source acceptance; the parent
hearth commission also includes device recovery and hardware acceptance and remains open.

The timer runs while WSL's user manager runs. It does not wake Windows or start an otherwise stopped
distribution. Surface a stopped or sleeping seat as unobserved; the Windows puller's separate 72-hour
bound is unchanged. Preserve the previous release and snapshots for rollback. Disabling this timer and
restoring the previous source-activation `worktree` binding must not delete any custody snapshot.

A live `wsl --export` interrupted dextra's running sessions on September 29. Do not use an export as this
recurring producer. A system recovery export needs an explicitly idle or stopped distribution. Validate
an existing export offline and import it under a different name with systemd, boot commands, interop and
automatic host mounts disabled before the first test boot. Preserve failed receipts; a process exit code
without the resulting VHDX and restored-file observations is not an import test.
