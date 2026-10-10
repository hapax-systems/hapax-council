#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: hapax-worktree-gc.sh [options]

Remove stale, clean Hapax git worktrees whose branches have already been
merged into the base ref. Alert via ntfy for unmerged worktrees older than the
alert threshold.

Options:
  --repo PATH                 Canonical repo to inspect
                              (default: $HAPAX_WORKTREE_GC_REPO or
                              ~/projects/hapax-council)
  --base-ref REF              Merge target ref (default: origin/main)
  --clean-age-seconds N       Auto-remove threshold (default: 172800 = 48h)
  --alert-age-seconds N       Unmerged alert threshold (default: 604800 = 7d)
  --release-keep N            Source-activation releases kept regardless of age, newest
                              first, not counting the active/candidate release (default: 5)
  --releases-only             Run ONLY the release pass: no orphan-spawn reaper, no registry
                              pre-pass, no merged-worktree sweep, no unmerged alerts
                              (also: HAPAX_WORKTREE_GC_RELEASES_ONLY=1)
  --now EPOCH                 Override current epoch seconds, for tests
  --ntfy-url URL              Full ntfy topic URL for alerts
  --no-fetch                  Do not refresh origin/main before checking merges
  --dry-run                   List actions without removing or alerting
  -h, --help                  Show this help
EOF
}

die() {
    printf 'hapax-worktree-gc: %s\n' "$*" >&2
    exit 2
}

is_uint() {
    [[ "${1:-}" =~ ^[0-9]+$ ]]
}

format_age() {
    local seconds="$1"
    local days hours minutes
    days=$((seconds / 86400))
    hours=$(((seconds % 86400) / 3600))
    minutes=$(((seconds % 3600) / 60))

    if ((days > 0)); then
        printf '%dd%02dh' "$days" "$hours"
    elif ((hours > 0)); then
        printf '%dh%02dm' "$hours" "$minutes"
    else
        printf '%dm' "$minutes"
    fi
}

protected_branch() {
    case "$1" in
        refs/heads/main|refs/heads/master|refs/heads/production|refs/heads/release)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

send_ntfy_alert() {
    local body="$1"

    if ((dry_run)); then
        printf 'hapax-worktree-gc: dry-run would alert via ntfy:\n%s\n' "$body"
        return 0
    fi

    if [[ -z "$ntfy_url" ]]; then
        printf 'hapax-worktree-gc: ntfy alert skipped; no URL configured\n' >&2
        return 0
    fi

    if ! command -v curl >/dev/null 2>&1; then
        printf 'hapax-worktree-gc: ntfy alert skipped; curl not found\n' >&2
        return 0
    fi

    curl -fsS \
        -H "Title: Hapax stale unmerged worktrees" \
        -H "Priority: high" \
        -H "Tags: warning" \
        --data-binary "$body" \
        "$ntfy_url" >/dev/null 2>&1 || \
        printf 'hapax-worktree-gc: ntfy alert failed for %s\n' "$ntfy_url" >&2
    # Governed incident record alongside the ntfy channel.
    "$(dirname "$(readlink -f "$0")")/hapax-alert" high "Hapax stale unmerged worktrees" "$body" --tag worktree --record-only
}

repo="${HAPAX_WORKTREE_GC_REPO:-$HOME/projects/hapax-council}"
base_ref="${HAPAX_WORKTREE_GC_BASE_REF:-origin/main}"
clean_age_seconds="${HAPAX_WORKTREE_GC_CLEAN_AGE_SECONDS:-172800}"
alert_age_seconds="${HAPAX_WORKTREE_GC_ALERT_AGE_SECONDS:-604800}"
release_keep="${HAPAX_WORKTREE_GC_RELEASE_KEEP:-5}"
releases_only="${HAPAX_WORKTREE_GC_RELEASES_ONLY:-0}"
now="${HAPAX_WORKTREE_GC_NOW:-}"
dry_run=0
fetch_first=1

ntfy_base="${HAPAX_WORKTREE_GC_NTFY_BASE_URL:-${NTFY_BASE_URL:-http://localhost:8090}}"
ntfy_topic="${HAPAX_WORKTREE_GC_NTFY_TOPIC:-hapax-worktree-gc}"
ntfy_url="${HAPAX_WORKTREE_GC_NTFY_URL:-${ntfy_base%/}/${ntfy_topic}}"

while (($#)); do
    case "$1" in
        --repo)
            (($# >= 2)) || die "--repo requires a path"
            repo="$2"
            shift 2
            ;;
        --base-ref)
            (($# >= 2)) || die "--base-ref requires a ref"
            base_ref="$2"
            shift 2
            ;;
        --clean-age-seconds)
            (($# >= 2)) || die "--clean-age-seconds requires a value"
            clean_age_seconds="$2"
            shift 2
            ;;
        --alert-age-seconds)
            (($# >= 2)) || die "--alert-age-seconds requires a value"
            alert_age_seconds="$2"
            shift 2
            ;;
        --release-keep)
            (($# >= 2)) || die "--release-keep requires a value"
            release_keep="$2"
            shift 2
            ;;
        --now)
            (($# >= 2)) || die "--now requires epoch seconds"
            now="$2"
            shift 2
            ;;
        --ntfy-url)
            (($# >= 2)) || die "--ntfy-url requires a URL"
            ntfy_url="$2"
            shift 2
            ;;
        --no-fetch)
            fetch_first=0
            shift
            ;;
        --releases-only)
            releases_only=1
            shift
            ;;
        --dry-run)
            dry_run=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

is_uint "$clean_age_seconds" || die "--clean-age-seconds must be an integer"
is_uint "$alert_age_seconds" || die "--alert-age-seconds must be an integer"
is_uint "$release_keep" || die "--release-keep must be an integer"
[[ "$releases_only" == "0" || "$releases_only" == "1" ]] || \
    die "HAPAX_WORKTREE_GC_RELEASES_ONLY must be 0 or 1"
if ((releases_only)); then
    # Release-only activation (2026-09-25): the orphan reaper, the registry pre-pass and the
    # merged-worktree sweep act on every lane worktree; a dry run on appendix showed the registry
    # reap alone would remove 110 worktrees, one of them the ExecStart tree of an enabled unit.
    # They stay off until reviewed; the release pass (age + count cap + lock/live/unit/dirty
    # guards) runs alone.
    printf 'hapax-worktree-gc: releases-only mode (orphan reaper, registry pre-pass and merged-worktree sweep skipped)\n'
fi
if [[ -z "$now" ]]; then
    now="$(date +%s)"
fi
is_uint "$now" || die "--now must be epoch seconds"

[[ -d "$repo" ]] || die "repo not found: $repo"
repo="$(cd "$repo" && pwd -P)"
git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1 || \
    die "not a git worktree: $repo"

if ((fetch_first)); then
    # --prune drops stale remote-tracking refs for branches GitHub auto-deleted on merge
    # (delete_branch_on_merge), so the mirror backlog self-clears every cycle.
    git -C "$repo" fetch --prune --quiet origin >/dev/null 2>&1 || true
fi

# Pre-pass: reap orphaned agent spawn-trees whose owning tmux session is gone.
# The lane-reaper only sees LIVE tmux sessions, so a lane that died ungracefully
# leaves its spawn-shell + MCP children parked in its worktree, which makes the
# live-PID guard below REFUSE the (now-merged) worktree forever. Clearing those
# orphans here is what unblocks the GC's per-worktree removal in the same run
# (root cause of the 2026-06-27 pileup: removable=7 removed=0 live_refused=7).
# Best-effort and self-limiting (live tmux panes are protected); never blocks GC.
orphan_reaper="$(dirname "$(readlink -f "$0")")/hapax-orphan-spawn-reaper.py"
if ((! releases_only)) && [[ "${HAPAX_WORKTREE_GC_REAP_ORPHANS:-1}" == "1" && -x "$orphan_reaper" ]]; then
    if ((dry_run)); then
        "$orphan_reaper" --dry-run || true
    else
        "$orphan_reaper" || true
    fi
fi

# Registry-governed pre-pass: this is what makes the DURABLE GC cycle governed by EXPLICIT lifecycle
# status, not age+clean+merged inference. It registers every worktree (backfill), captures the set of
# registry-PROTECTED paths (pins + infra/active/merging) so the legacy sweep below cannot reap them by
# inference, then reaps the ones the registry classifies done/abandoned — non-live, clean, stale,
# registered — keeping branches, so a session that stopped working without follow-through is reaped next
# cycle and the pileup cannot recur. Runs with the BARE system python3 (shared.worktree_registry is
# stdlib-only, no venv needed). The open-PR signal needs `gh`; when unavailable (this systemd unit
# carries no GH_TOKEN) classify fails CLOSED — only `done`/merged lanes are reaped.
#   registry_mode=governed : pre-pass OK -> the legacy sweep SKIPS every protected path (status wins).
#   registry_mode=failed   : pre-pass errored -> the legacy sweep reaps NOTHING by inference (fail-closed)
#                            + alerts; a broken registry must not silently degrade to the inference
#                            behavior the lifecycle predicate forbids.
#   registry_mode=off      : HAPAX_WORKTREE_GC_REGISTRY=0 -> legacy pure-inference (explicit opt-out).
registry_cli="$(dirname "$(readlink -f "$0")")/hapax-worktree-register"
declare -A registry_protected_set=()
registry_mode="off"
registry_prepass_failed=0
if ((! releases_only)) && [[ "${HAPAX_WORKTREE_GC_REGISTRY:-1}" == "1" && -f "$registry_cli" ]]; then
    idle_h="${HAPAX_WORKTREE_GC_REGISTRY_IDLE_HOURS:-48}"
    registry_mode="failed"  # assume failure until backfill AND protected-paths both succeed
    if HAPAX_WORKTREE_GC_REPO="$repo" python3 "$registry_cli" backfill >/dev/null 2>&1; then
        protected_raw=""
        if protected_raw="$(HAPAX_WORKTREE_GC_REPO="$repo" python3 "$registry_cli" \
            protected-paths 2>/dev/null)"; then
            while IFS= read -r pp; do
                if [[ -n "$pp" ]]; then
                    registry_protected_set["$pp"]=1
                fi
            done <<<"$protected_raw"
            # reap is NON-fatal to governance: protected-paths already succeeded, so the protected set +
            # the legacy-sweep gate are intact even if reap errors mid-loop. But surface the error rather
            # than swallow it — done/abandoned lanes simply go unreaped this cycle (next cycle retries).
            if ((dry_run)); then
                HAPAX_WORKTREE_GC_REPO="$repo" python3 "$registry_cli" reap \
                    --min-idle-hours "$idle_h" \
                    || printf 'hapax-worktree-gc: WARN registry reap (dry-run) errored — not fatal, protection intact. Next: run `HAPAX_WORKTREE_GC_REPO=%s python3 %s reap --min-idle-hours %s` directly to see the error.\n' "$repo" "$registry_cli" "$idle_h" >&2
            else
                HAPAX_WORKTREE_GC_REPO="$repo" python3 "$registry_cli" reap --apply \
                    --min-idle-hours "$idle_h" \
                    || printf 'hapax-worktree-gc: WARN registry reap errored — done/abandoned lanes unreaped this cycle (not fatal, protection intact). Next: run `HAPAX_WORKTREE_GC_REPO=%s python3 %s reap --min-idle-hours %s` to see the error, then `%s --apply ...` once fixed.\n' "$repo" "$registry_cli" "$idle_h" "$registry_cli" >&2
            fi
            registry_mode="governed"
        fi
    fi
    if [[ "$registry_mode" == "failed" ]]; then
        registry_prepass_failed=1
        printf 'hapax-worktree-gc: registry pre-pass FAILED — fail-closed, inference reaping disabled this cycle\n' >&2
    fi
fi

if ((dry_run || releases_only)); then
    printf 'hapax-worktree-gc: dry-run or releases-only skips global git worktree prune\n'
else
    git -C "$repo" worktree prune
fi

if ! git -C "$repo" rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null; then
    if git -C "$repo" rev-parse --verify --quiet "main^{commit}" >/dev/null; then
        base_ref="main"
    elif git -C "$repo" rev-parse --verify --quiet "master^{commit}" >/dev/null; then
        base_ref="master"
    else
        die "base ref not found: $base_ref"
    fi
fi

tmp_worktree_list="$(mktemp)"
trap 'rm -f "$tmp_worktree_list"' EXIT
git -C "$repo" worktree list --porcelain >"$tmp_worktree_list"

scanned=0
old_merged_clean=0
removed=0
old_unmerged=0
skipped=0
live_refused=0
release_refused=0
alert_lines=()

# Surface a fail-closed registry pre-pass (set above, before counters exist) through the normal alert
# channel: the legacy sweep ran inference-disabled this cycle, so the operator must fix the registry.
if ((registry_prepass_failed)); then
    alert_lines+=("- registry pre-pass FAILED (HAPAX_WORKTREE_GC_REGISTRY=1): the lifecycle-status pre-pass errored, so the legacy age+clean+merged sweep ran FAIL-CLOSED (no inference reaping) this cycle. Next: run \`python3 $registry_cli list\` to see the Python/registry error (import path or corrupt record), fix it, then re-run hapax-worktree-gc.sh.")
fi

# Live-PID guard. The release-GC ghost (audit 2026-06-11, F1/F1R): a release
# dir was deleted while logos-api still executed from it, leaving the process
# serving 500s from a gutted tree for ~2.5 days. Never remove a worktree that
# any live process references via /proc/<pid>/cwd, /proc/<pid>/exe, or a file
# mapping in /proc/<pid>/maps. maps is required, not optional: a daemon run
# from a release .venv has exe = the uv-managed interpreter (the venv's python
# is a symlink outside the release) and may have cwd elsewhere, so only its
# mapped .so files name the release (2026-09-25 appendix reap: release d689ba7c
# was live by maps alone). Same-user processes only (other users' proc entries
# are outside this same-user systemd estate). Unknown same-user visibility holds.
#
# Prints space-separated "pid(kind)" descriptors for live processes whose
# cwd/exe resolve to (or under) the given real path. Empty output = no refs.
# Scans /proc per removal candidate so the answer is fresh at decision time.
live_refs_for_path() {
    local dir="$1"
    local proc_root="${HAPAX_WORKTREE_GC_PROC_ROOT:-/proc}"
    # FAIL CLOSED (review #4094-1): if detection itself dies (python3 absent,
    # OOM, half-deployed venv), the function emits a sentinel so callers
    # REFUSE the delete. An unverifiable dir is treated as live, never free.
    local out rc
    out="$(python3 - "$proc_root" "$dir" <<'PY'
import os
import sys

root, want = sys.argv[1], sys.argv[2]
try:
    pids = sorted((p for p in os.listdir(root) if p.isdigit()), key=int)
except OSError:
    sys.exit(3)  # unreadable proc root = detection failure, fail CLOSED
refs = []
for pid in pids:
    try:
        if os.stat(os.path.join(root, pid)).st_uid != os.geteuid():
            continue
    except FileNotFoundError:
        continue  # Process exited after enumeration.
    except OSError as exc:
        refs.append(f"DETECTION-FAILED:{pid}(stat):{exc.errno}")
        continue
    for kind in ("cwd", "exe"):
        try:
            target = os.readlink(os.path.join(root, pid, kind))
        except FileNotFoundError:
            continue
        except OSError as exc:
            refs.append(f"DETECTION-FAILED:{pid}({kind}):{exc.errno}")
            continue
        target = target.removesuffix(" (deleted)")
        target = os.path.realpath(target)
        if target == want or target.startswith(want + "/"):
            refs.append(f"{pid}({kind})")
    try:
        with open(os.path.join(root, pid, "maps"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                fields = line.rstrip("\n").split(None, 5)
                if len(fields) < 6:
                    continue
                mapped = os.path.realpath(fields[5].removesuffix(" (deleted)"))
                if mapped.startswith(want + "/"):
                    refs.append(f"{pid}(maps)")
                    break
    except FileNotFoundError:
        if os.path.exists(os.path.join(root, pid)):
            refs.append(f"DETECTION-FAILED:{pid}(maps):missing")
    except OSError as exc:
        refs.append(f"DETECTION-FAILED:{pid}(maps):{exc.errno}")
    try:
        fds = os.listdir(os.path.join(root, pid, "fd"))
        for fd in fds:
            try:
                target = os.readlink(os.path.join(root, pid, "fd", fd))
            except FileNotFoundError:
                continue  # FD closed between enumeration and readlink.
            target = os.path.realpath(target.removesuffix(" (deleted)"))
            if target == want or target.startswith(want + "/"):
                refs.append(f"{pid}(fd)")
                break
    except FileNotFoundError:
        if os.path.exists(os.path.join(root, pid)):
            refs.append(f"DETECTION-FAILED:{pid}(fd):missing")
    except OSError as exc:
        refs.append(f"DETECTION-FAILED:{pid}(fd):{exc.errno}")
print(" ".join(refs), end="")
PY
)"
    rc=$?
    if (( rc != 0 )); then
        printf 'DETECTION-FAILED:rc=%s' "$rc"
        return 0
    fi
    printf '%s' "$out"
}

# Release-worktree retention. source-activate adds one detached worktree per
# activation under .../source-activation/releases/<sha> and only ever runs
# `git worktree prune` (removes missing-dir entries, never present-but-stale
# ones), so the releases dir grows unbounded (observed: 142). Reap stale release
# snapshots here, keeping the active + candidate release (from current.json).
release_retain_shas=""
release_reference_unknown=""
current_seen=0
for sacur in \
    "${HAPAX_SOURCE_ACTIVATION_CURRENT:-$HOME/.cache/hapax/source-activation/current.json}" \
    /data/cache/hapax/source-activation/current.json; do
    [[ -e "$sacur" || -L "$sacur" ]] || continue
    current_seen=1
    if current_shas="$(python3 - "$sacur" <<'PY_CURRENT'
import json, os, sys
with open(sys.argv[1]) as fh:
    d = json.load(fh)
assert isinstance(d, dict) and d, "empty current record"
assert any(d.get(k) for k in ("active_source_path", "active_source_head", "candidate_source_path", "candidate_source_head")), "current identity absent"
for k in ("active_source_path", "active_source_head", "candidate_source_path", "candidate_source_head"):
    v = d.get(k)
    if v is not None:
        assert isinstance(v, str) and v, "invalid current reference"
        print(os.path.basename(v.rstrip("/")))
PY_CURRENT
)"; then
        release_retain_shas+=" ${current_shas//$'\n'/ }"
    else
        release_reference_unknown="current-readback-unavailable:$sacur"
    fi
done
if ((! current_seen)); then
    release_reference_unknown="current-readback-missing"
fi

# Unit-reference guard for releases: a unit, drop-in or timer that names a release
# path (ExecStart=, WorkingDirectory=, Environment=...) would break on its next start
# if the release were removed, even with no process alive right now. Prints the
# referencing files space-separated; empty output = no references. Unreadable or
# absent dirs are skipped (grep -s).
unit_refs_for_path() {
    python3 - "$1" <<'PY_UNITS'
import os
import re
import subprocess
import sys
from pathlib import Path

want = os.path.realpath(sys.argv[1])
home = str(Path.home())
runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.geteuid()}")
dirs = os.environ.get("HAPAX_WORKTREE_GC_UNIT_DIRS", ":".join((
    home + "/.config/systemd/user", "/etc/systemd", "/usr/lib/systemd/user",
    runtime + "/systemd/user", runtime + "/systemd/transient",
    runtime + "/systemd/generator", runtime + "/systemd/generator.early",
    runtime + "/systemd/generator.late",
)))


def references(text):
    text = text.replace("%h", home).replace("%t", runtime)
    for raw in re.findall(r"/[^\s\"';{}]+", text):
        path = os.path.realpath(raw)
        if path == want or path.startswith(want + "/"):
            return True
    return False


try:
    visited = set()
    for directory in filter(None, dirs.split(":")):
        if not os.path.lexists(directory):
            continue
        def failed(exc):
            raise exc
        for root, children, files in os.walk(directory, followlinks=True, onerror=failed):
            real = os.path.realpath(root)
            if real in visited:
                children[:] = []
                continue
            visited.add(real)
            for name in files:
                fp = Path(root) / name
                if fp.resolve() == Path("/dev/null"):
                    continue  # masked unit
                if references(fp.read_text()):
                    print(fp)
    # Manager readback includes transient units and effective drop-in properties.
    units = subprocess.run(["systemctl", "--user", "list-units", "--all", "--plain",
                            "--no-legend", "--no-pager"], check=True, capture_output=True,
                           text=True, timeout=15).stdout
    names = [line.split()[0] for line in units.splitlines() if line.strip()]
    if names:
        effective = subprocess.run(["systemctl", "--user", "show", "--no-pager",
            "--property=Id,ExecStart,ExecStartPre,ExecStartPost,ExecStop,ExecStopPost,WorkingDirectory,Environment,EnvironmentFiles,RootDirectory,BindPaths,BindReadOnlyPaths", *names],
            check=True, capture_output=True, text=True, timeout=30).stdout
        for block in effective.split("\n\n"):
            if references(block):
                unit = next((line[3:] for line in block.splitlines() if line.startswith("Id=")), "unknown-unit")
                print("effective:" + unit)
except Exception as exc:
    print(f"UNIT-DETECTION-FAILED:{type(exc).__name__}:{exc}")
PY_UNITS
}

# Read retained Gate-0B roots and existing projections without retiring custody.
custody_refs_for_path() {
    python3 - "$1" <<'PY_CUSTODY'
import json
import os
import re
import sys
from pathlib import Path

want = os.path.realpath(sys.argv[1])
sha = Path(want).name
home = Path.home()
cache = home / ".cache/hapax"
registry = Path(os.environ.get("HAPAX_WORKTREE_REGISTRY_DIR", cache / "worktree-registry"))
roots = [registry, cache / "claim-publications", cache / "claim-publication-receipts",
         cache / "execution-admission", home / ".local/share/hapax/claim-publications",
         home / ".local/share/hapax/execution-invocations"]


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for part in value.values():
            yield from strings(part)
    elif isinstance(value, list):
        for part in value:
            yield from strings(part)


def references(value):
    for text in strings(value):
        if sha in text or want in text:
            return True  # conservative SHA/path reference, including embedded payloads
        for raw in re.findall(r"/[^\s\"';{}]+", text):
            path = os.path.realpath(raw)
            if path == want or path.startswith(want + "/"):
                return True
    return False


try:
    files = [p for p in cache.iterdir() if p.name.startswith("cc-claim-dispatch-") and p.suffix == ".json"] if cache.exists() else []
    for directory in roots:
        if not os.path.lexists(directory):
            continue
        def failed(exc):
            raise exc
        for root, children, names in os.walk(directory, onerror=failed):
            if any((Path(root) / name).is_symlink() for name in children):
                raise ValueError(f"unknown custody symlink: {root}")
            files.extend(Path(root) / name for name in names if name.endswith(".json"))
    for fp in files:
        record = json.loads(fp.read_text())
        if not isinstance(record, dict):
            raise ValueError(f"unknown custody record shape: {fp}")
        if references(record):
            print("custody:" + str(fp))
except Exception as exc:
    print(f"CUSTODY-UNKNOWN:{type(exc).__name__}:{exc}")
PY_CUSTODY
}

# release_tree_state <release-path>
# Classifies a release worktree before removal. Line 1 is the verdict:
#   clean      nothing modified, untracked or unclassified ignored
#   mode-only  only tracked files whose MODE changed, with identical content: the stray
#              `chmod +x` class (2026-09-25: 6 of 33 reaped releases carried exactly
#              `mode change 100644 => 100755 scripts/hapax-determine`); the paths follow,
#              one per line, relative to the release root
#   dirty      anything else (content edit, untracked file, staged change, unreadable
#              status); line 2 names the first offending entry
# Fails CLOSED: any git error classifies as dirty, so the release is kept.
release_tree_state() {
    python3 - "$1" <<'PY'
import subprocess
import sys

path = sys.argv[1]


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", path, *args], capture_output=True, check=True
    ).stdout


try:
    status = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    # Ignoring a leaf does not establish regenerability, even for a .venv.
    ignored = git("ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    if ignored:
        print("dirty")
        print("unclassified-ignored-payload " + ignored.split(b"\0")[0].decode(errors="replace"))
        sys.exit(0)
    if not status:
        print("clean")
        sys.exit(0)
    paths = []
    for entry in (e for e in status.split(b"\0") if e):
        xy, name = entry[:2], entry[3:]
        if xy != b" M" or b"\n" in name:
            print("dirty")
            print(f"status {xy.decode(errors='replace')!r} {name.decode(errors='replace')}")
            sys.exit(0)
        paths.append(name)
    numstat = {}
    for rec in (r for r in git("diff", "--numstat", "-z").split(b"\0") if r):
        added, deleted, name = rec.split(b"\t", 2)
        numstat[name] = (added, deleted)
    raw_fields = git("diff", "--raw", "-z", "--no-abbrev").split(b"\0")
    modes = {}
    for meta, name in zip(raw_fields[0::2], raw_fields[1::2], strict=False):
        if meta.startswith(b":"):
            src_mode, dst_mode = meta[1:].split(b" ")[:2]
            modes[name] = (src_mode, dst_mode)
    for name in paths:
        src_dst = modes.get(name)
        regular = (b"100644", b"100755")
        if (
            numstat.get(name) != (b"0", b"0")
            or src_dst is None
            or src_dst[0] == src_dst[1]
            or src_dst[0] not in regular
            or src_dst[1] not in regular
        ):
            print("dirty")
            print(f"content-or-type-change {name.decode(errors='replace')}")
            sys.exit(0)
    print("mode-only")
    for name in paths:
        print(name.decode())
except Exception as exc:  # noqa: BLE001 - fail closed on any classification error
    print("dirty")
    print(f"classification-failed {type(exc).__name__}: {exc}")
PY
}

# branch_remote_deleted <repo> <bare-branch-name>
# True (0) iff a LOCAL branch was SQUASH/REBASE-merged on GitHub, detected GIT-ONLY
# (no `gh`: the deploy systemd unit carries no GH_TOKEN, so a gh-gated arm would
# fail-closed and never reap in production — the env this must work in). Squash
# merges do NOT make the branch an ancestor of base, so ancestry detection misses
# them — the council's default merge method — and they accumulate forever. The
# git-only signal is GitHub's own `delete_branch_on_merge=true`: on MERGE (and only
# on merge — a closed-without-merge PR is NOT auto-deleted) GitHub deletes the remote
# branch, which `fetch --prune` then drops. So a local branch that (1) still tracks
# origin (it was pushed for a PR) AND (2) has lost its `origin/<name>` ref was
# auto-deleted on merge. Residual false-positive: an operator MANUALLY deleting the
# remote of a closed-unmerged branch — narrow, and gated behind clean + age + no-live
# + reflog recovery (90d). A never-pushed local branch has no tracking config, so it
# can never match (it is judged by ancestry alone).
branch_remote_deleted() {
    local repo="$1" name="$2" remote merge_ref
    [[ -n "$name" && "$name" != detached:* ]] || return 1
    # (1) was pushed AS origin/<name>: upstream remote is origin AND its merge ref is
    # refs/heads/<name>. A branch that merely TRACKS a different ref (e.g.
    # `git checkout -b x origin/main` → remote=origin, merge=refs/heads/main) has no
    # origin/x ref at all; treating that absence as "deleted" would force-delete live
    # unmerged work. The merge-ref guard closes that data-loss false-positive.
    remote="$(git -C "$repo" config --get "branch.${name}.remote" 2>/dev/null)" || return 1
    [[ "$remote" == "origin" ]] || return 1
    merge_ref="$(git -C "$repo" config --get "branch.${name}.merge" 2>/dev/null)" || return 1
    [[ "$merge_ref" == "refs/heads/${name}" ]] || return 1
    # (2) remote counterpart gone (auto-deleted on merge + pruned this run)
    ! git -C "$repo" rev-parse --verify --quiet "refs/remotes/origin/${name}" >/dev/null 2>&1
}

# branch_content_merged <repo> <branch-ref> <base_ref>
# True (0) iff merging <branch-ref> into <base_ref> adds NOTHING — i.e. the branch's
# content is already fully present in base. POSITIVE merge evidence, not a remote-
# state heuristic: a squash/rebase merge breaks ancestry but leaves the content in
# base, so merge-tree against base yields base's own tree. Conversely a branch that
# was closed-WITHOUT-merge or had its remote MANUALLY deleted still carries real
# unique commits, so the merge adds them (or conflicts) and the tree differs — it is
# NOT content-merged and must never be force-deleted. Git-only (no GH_TOKEN) and
# purely ref-based, so it is correct from a detached deploy worktree whose HEAD lags
# base_ref. This guard makes branch_remote_deleted's residual false-positive (manual
# remote delete of unmerged work) non-destructive.
branch_content_merged() {
    local repo="$1" branch="$2" base="$3" base_tree out rc merged_tree
    base_tree="$(git -C "$repo" rev-parse --verify --quiet "${base}^{tree}")" || return 1
    # merge-tree --write-tree prints the merged tree OID on line 1; a NONZERO exit
    # means the merge conflicts => the branch is not cleanly contained => unmerged.
    out="$(git -C "$repo" merge-tree --write-tree "$base" "$branch" 2>/dev/null)"
    rc=$?
    ((rc == 0)) || return 1
    merged_tree="${out%%$'\n'*}"
    [[ -n "$merged_tree" && "$merged_tree" == "$base_tree" ]]
}

process_worktree() {
    local path="$worktree_path"
    local branch="$branch_ref"
    local head="$head_sha"
    local locked="$locked_reason"
    local real_path mtime age status branch_label merged clean remove_note

    [[ -n "$path" ]] || return 0
    scanned=$((scanned + 1))

    if [[ ! -d "$path" ]]; then
        printf 'hapax-worktree-gc: skip missing worktree path: %s\n' "$path"
        skipped=$((skipped + 1))
        return 0
    fi

    real_path="$(cd "$path" && pwd -P)"
    if [[ "$real_path" == "$repo" ]]; then
        return 0
    fi

    if ! mtime="$(stat -c %Y "$path" 2>/dev/null)"; then
        printf 'hapax-worktree-gc: skip path without stat mtime: %s\n' "$path"
        skipped=$((skipped + 1))
        return 0
    fi

    if ((now > mtime)); then
        age=$((now - mtime))
    else
        age=0
    fi

    if [[ -n "$branch" ]]; then
        branch_label="${branch#refs/heads/}"
    elif [[ -n "$head" ]]; then
        branch_label="detached:${head:0:12}"
    else
        branch_label="detached:unknown"
    fi

    if [[ -z "$branch" ]]; then
        # Reap stale source-activation release worktrees (detached snapshots of
        # main) only when ranked beyond the rollback retention floor, except the
        # active/candidate release. Age never overrides the promised newest-N
        # minimum; over-cap candidates still pass every removal guard.
        if [[ "$real_path" == */source-activation/releases/* && -n "$head" ]]; then
            local rel_sha="${real_path##*/}"
            local over_cap="${release_over_cap[$real_path]:-}"
            [[ -z "${release_holds[$real_path]:-}" ]] || return 0
            if [[ -n "$release_reference_unknown" ]]; then
                printf 'hapax-worktree-gc: hold release %s (%s)\n' "$path" "$release_reference_unknown"
                return 0
            fi
            if ((age < clean_age_seconds)); then
                printf 'hapax-worktree-gc: retain release %s (age below threshold)\n' "$path"
                return 0
            fi
            if ((age >= clean_age_seconds)) && [[ -n "$over_cap" ]] \
                && [[ " $release_retain_shas " != *" $rel_sha "* ]]; then
                old_merged_clean=$((old_merged_clean + 1))
                printf 'hapax-worktree-gc: removable release %s age=%s%s\n' \
                    "$path" "$(format_age "$age")" "${over_cap:+ over-cap(keep=$release_keep)}"
                if [[ -n "$locked" ]]; then
                    printf 'hapax-worktree-gc: skip locked release: %s (%s)\n' "$path" "$locked"
                    skipped=$((skipped + 1))
                    return 0
                fi
                if ! git -C "$repo" merge-base --is-ancestor "$head" "$base_ref"; then
                    printf 'hapax-worktree-gc: hold release %s (unmerged source)\n' "$path"
                    return 0
                fi
                local custody_refs
                custody_refs="$(custody_refs_for_path "$real_path")" || custody_refs="CUSTODY-UNKNOWN:reader-failed"
                if [[ -n "$custody_refs" ]]; then
                    release_refused=$((release_refused + 1))
                    printf 'hapax-worktree-gc: hold release %s (%s)\n' "$path" "$custody_refs"
                    return 0
                fi
                local live_refs
                live_refs="$(live_refs_for_path "$real_path")"
                if [[ -n "$live_refs" ]]; then
                    live_refused=$((live_refused + 1))
                    printf 'hapax-worktree-gc: refuse live release %s (live: %s)\n' \
                        "$path" "$live_refs"
                    if [[ "$live_refs" == DETECTION-FAILED* ]]; then
                        alert_lines+=("- $path ($branch_label), age $(format_age "$age"), release GC REFUSED: live-process detection FAILED ($live_refs) — fix python3//proc on this host; the dir is kept unverified, do not force-GC")
                    else
                        alert_lines+=("- $path ($branch_label), age $(format_age "$age"), release GC REFUSED: live process references ($live_refs) — restart the binder onto the current release before GC")
                    fi
                    return 0
                fi
                local unit_refs
                unit_refs="$(unit_refs_for_path "$real_path")" || unit_refs="UNIT-DETECTION-FAILED:reader-failed"
                if [[ -n "$unit_refs" ]]; then
                    release_refused=$((release_refused + 1))
                    printf 'hapax-worktree-gc: refuse unit-referenced release %s (units: %s)\n' \
                        "$path" "$unit_refs"
                    alert_lines+=("- $path ($branch_label), age $(format_age "$age"), release GC REFUSED: referenced by $unit_refs — repoint the unit onto the current release before GC")
                    return 0
                fi
                # Never `worktree remove --force`: force would silently discard a real diff
                # someone left in a release. Only the stray-mode class is repaired (restore the
                # committed mode, re-check clean); anything else is refused and alerted.
                local tree_state verdict
                tree_state="$(release_tree_state "$real_path")"
                verdict="${tree_state%%$'\n'*}"
                if [[ "$verdict" == "mode-only" ]]; then
                    local -a mode_paths=()
                    mapfile -t mode_paths < <(printf '%s\n' "$tree_state" | tail -n +2)
                    if ((dry_run)); then
                        printf 'hapax-worktree-gc: dry-run would restore stray mode in release %s: %s\n' \
                            "$path" "${mode_paths[*]}"
                        printf 'hapax-worktree-gc: dry-run would remove release %s\n' "$path"
                        return 0
                    fi
                    if git --literal-pathspecs -C "$real_path" checkout -- "${mode_paths[@]}" \
                        && [[ "$(release_tree_state "$real_path")" == "clean" ]]; then
                        printf 'hapax-worktree-gc: restored stray mode in release %s: %s\n' \
                            "$path" "${mode_paths[*]}"
                        verdict="clean"
                    else
                        verdict="dirty"
                        tree_state=$'dirty\nmode restore did not leave the tree clean'
                    fi
                fi
                if [[ "$verdict" != "clean" ]]; then
                    release_refused=$((release_refused + 1))
                    printf 'hapax-worktree-gc: refuse dirty release %s (%s)\n' \
                        "$path" "$(printf '%s\n' "$tree_state" | sed -n 2p)"
                    alert_lines+=("- $path ($branch_label), age $(format_age "$age"), release GC REFUSED: tree not clean ($(printf '%s\n' "$tree_state" | sed -n 2p)) — inspect by hand; never --force")
                    return 0
                fi
                if ((dry_run)); then
                    printf 'hapax-worktree-gc: dry-run would remove release %s\n' "$path"
                else
                    local remove_out
                    if remove_out="$(git -C "$repo" worktree remove "$path" 2>&1)"; then
                        removed=$((removed + 1))
                        printf 'hapax-worktree-gc: removed release %s\n' "$path"
                    else
                        release_refused=$((release_refused + 1))
                        printf 'hapax-worktree-gc: refuse release %s: git worktree remove failed: %s\n' \
                            "$path" "$remove_out"
                        alert_lines+=("- $path ($branch_label), release GC REFUSED by git: $remove_out")
                    fi
                fi
                return 0
            fi
        fi
        if ((releases_only)); then
            return 0
        fi
        if ((age >= alert_age_seconds)); then
            old_unmerged=$((old_unmerged + 1))
            alert_lines+=("- $path ($branch_label), age $(format_age "$age"), no branch attached")
        fi
        return 0
    fi

    if ((releases_only)); then
        return 0
    fi

    if protected_branch "$branch"; then
        return 0
    fi

    clean=0
    # --no-optional-locks (GIT_OPTIONAL_LOCKS=0): like the registry probe's is_clean(), this legacy
    # clean-check must NOT refresh the index stat cache on disk. mtime_age_seconds() reads the index
    # mtime as the abandonment clock, and this sweep runs every 6h on every worktree; without the flag
    # it would reset a sub-48h idle lane's clock each cycle so it never crosses the abandoned threshold.
    if status="$(git -C "$path" --no-optional-locks status --porcelain=v1 --untracked-files=all)" \
        && [[ -z "$status" ]]; then
        clean=1
    fi

    # A branch is "merged" (its work is in base) if EITHER its commits are ancestors
    # of base_ref (merge-commit / fast-forward merges) OR it was squash/rebase-merged
    # — detected by the conjunction of (a) GitHub auto-deleted + we pruned its remote
    # (branch_remote_deleted; ancestry MISSES squash merges, the council's default)
    # AND (b) the branch's content is positively present in base (branch_content_merged).
    # The content check is REQUIRED, not optional: branch_remote_deleted alone has a
    # data-loss false-positive (a closed-without-merge PR or a manual
    # `git push origin --delete` leaves identical local state but with REAL unmerged
    # commits), and the reaping path force-deletes the local ref with `-D`. Requiring
    # positive content evidence means an unmerged branch whose remote merely vanished
    # is NOT classed as merged and is never force-deleted. Both signals are evaluated
    # against base_ref / refs, NOT the local HEAD — important because the deploy GC
    # runs from a detached activation worktree whose HEAD lags base_ref.
    merged=0
    if git -C "$repo" merge-base --is-ancestor "$branch" "$base_ref" >/dev/null 2>&1; then
        merged=1
    elif branch_remote_deleted "$repo" "$branch_label" \
        && branch_content_merged "$repo" "$branch" "$base_ref"; then
        merged=1
    fi

    if ((age >= clean_age_seconds && clean && merged)); then
        # Lifecycle-status authority (PR #4337): the REGISTRY, not age+clean+merged inference, decides
        # removability for registered lanes. governed -> skip any registry-protected path (an explicit
        # pin, or an in-use infra/active/merging lane) so inference never overrides status. failed ->
        # skip ALL inference reaping (fail-closed: a registry meant to govern but broken must not
        # degrade to the inference behavior the predicate forbids). off -> legacy inference (opt-out).
        if [[ "$registry_mode" == "governed" && -n "${registry_protected_set[$real_path]:-}" ]]; then
            printf 'hapax-worktree-gc: keep %s — registry-protected lifecycle status overrides inference\n' \
                "$path"
            skipped=$((skipped + 1))
            return 0
        fi
        if [[ "$registry_mode" == "failed" ]]; then
            printf 'hapax-worktree-gc: keep %s — registry unavailable, fail-closed (no inference reap)\n' \
                "$path"
            skipped=$((skipped + 1))
            return 0
        fi
        old_merged_clean=$((old_merged_clean + 1))
        printf 'hapax-worktree-gc: removable %s branch=%s age=%s base=%s\n' \
            "$path" "$branch_label" "$(format_age "$age")" "$base_ref"

        if [[ -n "$locked" ]]; then
            printf 'hapax-worktree-gc: skip locked removable worktree: %s (%s)\n' \
                "$path" "$locked"
            skipped=$((skipped + 1))
            return 0
        fi

        local live_refs
        live_refs="$(live_refs_for_path "$real_path")"
        if [[ -n "$live_refs" ]]; then
            live_refused=$((live_refused + 1))
            printf 'hapax-worktree-gc: refuse live worktree %s (live: %s)\n' \
                "$path" "$live_refs"
            alert_lines+=("- $path ($branch_label), age $(format_age "$age"), worktree GC REFUSED: live process references ($live_refs)")
            return 0
        fi

        if ((dry_run)); then
            printf 'hapax-worktree-gc: dry-run would remove %s\n' "$path"
        else
            git -C "$repo" worktree remove "$path"
            printf 'hapax-worktree-gc: removed %s\n' "$path"
            removed=$((removed + 1))
            # Delete the now-orphaned LOCAL branch ref with `-D`, NOT `-d`. This is safe
            # ONLY because the merged predicate above now requires POSITIVE content
            # evidence (branch_content_merged): merged=1 means the branch's content is
            # provably in base_ref (ancestry) or that the squash landed AND the merge
            # adds nothing to base. `git branch -d` cannot be used here: it re-checks
            # ancestry against the branch's upstream or the CURRENT HEAD, and the deploy
            # GC runs from a detached activation worktree whose HEAD lags base_ref, so
            # `-d` wrongly REFUSES an already-merged branch (and refuses every squash-
            # merged branch, which is never an ancestor of anything). So `-D` executes a
            # verdict that the content gate already proved; it never force-deletes work
            # that is not already in base. Use the BARE name (branch_label) — $branch is
            # the full refs/heads/<name> ref, which `git branch` would not match.
            # Worktree-remove must precede the delete (git refuses to delete a checked-out
            # branch); if the `-D` then fails, WARN loudly — never swallow.
            if [[ -n "$branch_label" ]]; then
                if git -C "$repo" branch -D "$branch_label" >/dev/null 2>&1; then
                    printf 'hapax-worktree-gc: deleted merged local branch %s\n' "$branch_label"
                else
                    printf 'hapax-worktree-gc: WARN could not delete merged local branch %s\n' \
                        "$branch_label" >&2
                fi
            fi
        fi
        return 0
    fi

    if ((age >= alert_age_seconds && ! merged)); then
        old_unmerged=$((old_unmerged + 1))
        remove_note="clean"
        if ((clean == 0)); then
            remove_note="dirty"
        fi
        if [[ -n "$locked" ]]; then
            remove_note="$remove_note, locked"
        fi
        alert_lines+=("- $path ($branch_label), age $(format_age "$age"), $remove_note, not merged into $base_ref")
    fi
}

# Partial roots never rank as rollback slots; inventory failure stops GC.
declare -A release_over_cap=() release_holds=()
release_rank_input=""
if ! release_inventory="$(python3 - "$tmp_worktree_list" <<'PY_INVENTORY'
import os
import subprocess
import sys
from pathlib import Path

records = {}
for block in Path(sys.argv[1]).read_text().strip().split("\n\n"):
    fields = dict(line.split(" ", 1) if " " in line else (line, "") for line in block.splitlines())
    path = fields.get("worktree", "")
    if "/source-activation/releases/" in path:
        records[os.path.realpath(path)] = fields
roots = {str(Path(p).parent) for p in records}
roots.update(filter(None, os.environ.get("HAPAX_WORKTREE_GC_RELEASE_ROOTS", ":".join((
    str(Path.home() / ".cache/hapax/source-activation/releases"),
    os.environ.get("HAPAX_SOURCE_ACTIVATE_RELEASES_DIR", "/store-fast/hapax/source-activation/releases"),
    "/data/cache/hapax/source-activation/releases",
))).split(":")))
paths = set(records)
for root in roots:
    try:
        with os.scandir(root) as entries:
            paths.update(os.path.abspath(p.path) for p in entries if p.is_dir() or p.is_symlink())
    except FileNotFoundError:
        continue
protected = {"3a2664d48fefce563e595e3eac0354988dfc0979", "8c0aaa53d436c2a973d745b1f767a27db2cb0b62"}  # pragma: allowlist secret
for path in sorted(paths):
    if any(c in path for c in "\n\t"):
        raise ValueError("unrepresentable release path")
    fields = records.get(path)
    reason = ""
    if not fields:
        reason = "unregistered-report-only"
    elif not Path(path, ".git").is_file() or Path(path).is_symlink():
        reason = "partial-report-only"
    else:
        result = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel", "HEAD"],
                                capture_output=True, text=True)
        if result.returncode or result.stdout.splitlines() != [path, fields.get("HEAD")]:
            reason = "partial-identity-unknown"
        elif "branch" in fields:
            reason = "branch-custody"
    if Path(path).name in protected:
        reason = (reason + ":protected-fixture") if reason else "protected-fixture-report-only"
    if reason:
        print("hold", path, reason, sep="\t")
    else:
        print("rank", path, int(os.stat(path).st_mtime), sep="\t")
PY_INVENTORY
)"; then
    die "release inventory unavailable; inspect release roots before retrying (no removals)"
fi
while IFS=$'\t' read -r disposition rel_path detail; do
    [[ -n "$rel_path" ]] || continue
    if [[ "$disposition" == hold ]]; then
        release_holds["$rel_path"]="$detail"
        printf 'hapax-worktree-gc: hold release %s (%s)\n' "$rel_path" "$detail"
    elif [[ " $release_retain_shas " == *" ${rel_path##*/} "* ]]; then
        printf 'hapax-worktree-gc: retain release %s (active/candidate)\n' "$rel_path"
    else
        release_rank_input+="${detail} ${rel_path}"$'\n'
    fi
done <<<"$release_inventory"
if [[ -n "$release_rank_input" ]]; then
    _rank=0
    while IFS= read -r _ranked; do
        [[ -n "$_ranked" ]] || continue
        _rank=$((_rank + 1))
        if ((_rank > release_keep)); then
            release_over_cap["${_ranked#* }"]=1
        else
            printf 'hapax-worktree-gc: retain release %s (newest-%s rollback)\n' "${_ranked#* }" "$release_keep"
        fi
    done < <(printf '%s' "$release_rank_input" | sort -rn -k1,1)
fi

worktree_path=""
head_sha=""
branch_ref=""
locked_reason=""

while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ -z "$line" ]]; then
        process_worktree
        worktree_path=""
        head_sha=""
        branch_ref=""
        locked_reason=""
        continue
    fi

    case "$line" in
        worktree\ *)
            if [[ -n "$worktree_path" ]]; then
                process_worktree
                head_sha=""
                branch_ref=""
                locked_reason=""
            fi
            worktree_path="${line#worktree }"
            ;;
        HEAD\ *)
            head_sha="${line#HEAD }"
            ;;
        branch\ *)
            branch_ref="${line#branch }"
            ;;
        locked)
            locked_reason="locked"
            ;;
        locked\ *)
            locked_reason="${line#locked }"
            ;;
    esac
done <"$tmp_worktree_list"

process_worktree

if ((${#alert_lines[@]} > 0)); then
    alert_body="Unmerged Hapax worktrees older than $(format_age "$alert_age_seconds") need review:"
    for line in "${alert_lines[@]}"; do
        alert_body+=$'\n'"$line"
    done
    send_ntfy_alert "$alert_body"
fi

printf 'hapax-worktree-gc: scanned=%d removable=%d removed=%d live_refused=%d release_refused=%d stale_unmerged=%d skipped=%d\n' \
    "$scanned" "$old_merged_clean" "$removed" "$live_refused" "$release_refused" "$old_unmerged" "$skipped"
