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

if ((dry_run)); then
    printf 'hapax-worktree-gc: dry-run skips git worktree prune\n'
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
alert_lines=()

# Live-PID guard. The release-GC ghost (audit 2026-06-11, F1/F1R): a release
# dir was deleted while logos-api still executed from it, leaving the process
# serving 500s from a gutted tree for ~2.5 days. Never remove a worktree that
# any live process maps via /proc/<pid>/cwd or /proc/<pid>/exe. Same-user
# processes only (readlink on other users' proc entries fails silently), which
# covers the systemd --user estate that binds these dirs.
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
    for kind in ("cwd", "exe"):
        try:
            target = os.readlink(os.path.join(root, pid, kind))
        except OSError:
            continue
        target = target.removesuffix(" (deleted)")
        if target == want or target.startswith(want + "/"):
            refs.append(f"{pid}({kind})")
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
for sacur in \
    "${HAPAX_SOURCE_ACTIVATION_CURRENT:-}" \
    "$HOME/.cache/hapax/source-activation/current.json" \
    /data/cache/hapax/source-activation/current.json; do
    [[ -n "$sacur" && -r "$sacur" ]] || continue
    while IFS= read -r _sha; do
        [[ -n "$_sha" ]] && release_retain_shas+=" $_sha"
    done < <(python3 -c '
import json, os, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for k in ("active_source_path", "active_source_head", "candidate_source_path"):
    v = d.get(k)
    if isinstance(v, str) and v:
        print(os.path.basename(v))
' "$sacur" 2>/dev/null)
    break
done

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
        # main) once older than the clean threshold, except the active/candidate
        # release. Root-cause fix for unbounded release accumulation.
        if [[ "$real_path" == */source-activation/releases/* && -n "$head" ]]; then
            local rel_sha="${real_path##*/}"
            if ((age >= clean_age_seconds)) && [[ " $release_retain_shas " != *" $rel_sha "* ]]; then
                old_merged_clean=$((old_merged_clean + 1))
                printf 'hapax-worktree-gc: removable release %s age=%s\n' \
                    "$path" "$(format_age "$age")"
                if [[ -n "$locked" ]]; then
                    printf 'hapax-worktree-gc: skip locked release: %s (%s)\n' "$path" "$locked"
                    skipped=$((skipped + 1))
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
                if ((dry_run)); then
                    printf 'hapax-worktree-gc: dry-run would remove release %s\n' "$path"
                else
                    git -C "$repo" worktree remove --force "$path"
                    removed=$((removed + 1))
                    printf 'hapax-worktree-gc: removed release %s\n' "$path"
                fi
                return 0
            fi
        fi
        if ((age >= alert_age_seconds)); then
            old_unmerged=$((old_unmerged + 1))
            alert_lines+=("- $path ($branch_label), age $(format_age "$age"), no branch attached")
        fi
        return 0
    fi

    if protected_branch "$branch"; then
        return 0
    fi

    clean=0
    if status="$(git -C "$path" status --porcelain=v1 --untracked-files=all)" && [[ -z "$status" ]]; then
        clean=1
    fi

    # A branch is "merged" (its work is in base) if EITHER its commits are ancestors
    # of base_ref (merge-commit / fast-forward merges) OR it was squash/rebase-merged
    # and GitHub auto-deleted + we pruned its remote (branch_remote_deleted; ancestry
    # MISSES squash merges, the council's default — without this arm the GC never
    # reaps squash-merged worktrees, which all fall through to the unmerged-alert
    # path). Both signals are evaluated against base_ref / the remote, NOT against the
    # local HEAD — important because the deploy GC runs from a detached activation
    # worktree whose HEAD lags base_ref.
    merged=0
    if git -C "$repo" merge-base --is-ancestor "$branch" "$base_ref" >/dev/null 2>&1; then
        merged=1
    elif branch_remote_deleted "$repo" "$branch_label"; then
        merged=1
    fi

    if ((age >= clean_age_seconds && clean && merged)); then
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
            # Delete the now-orphaned LOCAL branch ref with `-D`, NOT `-d`. merged=1 is
            # guaranteed here, and the merged predicate was evaluated AUTHORITATIVELY
            # against base_ref / the remote. `git branch -d` instead re-checks ancestry
            # against the branch's upstream or the CURRENT HEAD — and the deploy GC runs
            # from a detached activation worktree whose HEAD lags base_ref, so `-d`
            # wrongly REFUSES an already-merged branch (and refuses every squash-merged
            # branch, which is never an ancestor of anything). So `-d` is the bug, not
            # the safety: the authoritative predicate is the gate; `-D` just executes
            # its verdict. Use the BARE name (branch_label) — $branch is the full
            # refs/heads/<name> ref, which `git branch` would not match. Worktree-remove
            # must precede the delete (git refuses to delete a checked-out branch); if
            # the `-D` then fails, WARN loudly — never swallow.
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

printf 'hapax-worktree-gc: scanned=%d removable=%d removed=%d live_refused=%d stale_unmerged=%d skipped=%d\n' \
    "$scanned" "$old_merged_clean" "$removed" "$live_refused" "$old_unmerged" "$skipped"
