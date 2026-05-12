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
    git -C "$repo" fetch --quiet origin main >/dev/null 2>&1 || true
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
alert_lines=()

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

    merged=0
    if git -C "$repo" merge-base --is-ancestor "$branch" "$base_ref" >/dev/null 2>&1; then
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

        if ((dry_run)); then
            printf 'hapax-worktree-gc: dry-run would remove %s\n' "$path"
        else
            git -C "$repo" worktree remove "$path"
            printf 'hapax-worktree-gc: removed %s\n' "$path"
            removed=$((removed + 1))
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

printf 'hapax-worktree-gc: scanned=%d removable=%d removed=%d stale_unmerged=%d skipped=%d\n' \
    "$scanned" "$old_merged_clean" "$removed" "$old_unmerged" "$skipped"
