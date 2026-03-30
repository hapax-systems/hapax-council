"""Apply fixes to files, git commit, and notify."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import HAPAX_HOME
from .models import ApplyResult, FixReport

log = logging.getLogger("drift_detector")


def _resolve_doc_path(doc_file: str) -> Path | None:
    """Resolve a doc_file reference (may use ~) to an absolute Path."""
    expanded = Path(doc_file.replace("~", str(HAPAX_HOME)))
    if expanded.is_file():
        return expanded
    p = Path(doc_file)
    if p.is_file():
        return p
    return None


def apply_fixes(fix_report: FixReport) -> ApplyResult:
    """Apply fixes directly to documentation files."""
    result = ApplyResult()
    changed: set[str] = set()

    for fix in fix_report.fixes:
        path = _resolve_doc_path(fix.doc_file)
        if path is None:
            result.skipped += 1
            result.errors.append(f"File not found: {fix.doc_file}")
            continue

        try:
            content = path.read_text()
        except OSError as e:
            result.skipped += 1
            result.errors.append(f"Cannot read {fix.doc_file}: {e}")
            continue

        count = content.count(fix.original)
        if count == 0:
            result.skipped += 1
            result.errors.append(
                f"Original text not found in {fix.doc_file}: {fix.original[:60]}..."
            )
            continue
        if count > 1:
            result.skipped += 1
            result.errors.append(
                f"Original text found {count} times in {fix.doc_file} (ambiguous): "
                f"{fix.original[:60]}..."
            )
            continue

        new_content = content.replace(fix.original, fix.corrected, 1)
        try:
            path.write_text(new_content)
            result.applied += 1
            changed.add(str(path))
        except OSError as e:
            result.skipped += 1
            result.errors.append(f"Cannot write {fix.doc_file}: {e}")

    result.changed_files = sorted(changed)
    return result


def git_commit_fixes(changed_files: list[str], fix_count: int) -> bool:
    """Commit changed documentation files with a conventional commit message."""
    if not changed_files:
        return False

    repos: dict[str, list[str]] = {}
    for fpath in changed_files:
        try:
            git_root = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(Path(fpath).parent),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if git_root.returncode == 0:
                root = git_root.stdout.strip()
                repos.setdefault(root, []).append(fpath)
            else:
                log.warning("Not in a git repo: %s", fpath)
        except Exception:
            log.warning("Could not determine git root for %s", fpath)

    committed = False
    for root, files in repos.items():
        try:
            subprocess.run(
                ["git", "add"] + files,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            msg = (
                f"docs: auto-fix {len(files)} documentation drift item(s)\n\n"
                f"Applied by drift_detector --fix --apply.\n"
                f"Files: {', '.join(Path(f).name for f in files)}\n\n"
                f"Co-Authored-By: Claude <noreply@anthropic.com>"
            )
            result = subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                committed = True
                log.info("Committed drift fixes in %s", root)
            else:
                log.warning("Git commit failed in %s: %s", root, result.stderr)
        except Exception as e:
            log.warning("Git commit error in %s: %s", root, e)

    return committed


def notify_fixes(apply_result: ApplyResult, committed: bool) -> None:
    """Send notification about applied drift fixes."""
    try:
        from .notify import send_notification
    except ImportError:
        log.debug("shared.notify not available, skipping notification")
        return

    if apply_result.applied == 0:
        return

    title = f"Drift auto-fix: {apply_result.applied} applied"
    body_parts = [
        f"Applied {apply_result.applied} fix(es) to {len(apply_result.changed_files)} file(s).",
    ]
    if apply_result.skipped:
        body_parts.append(f"Skipped {apply_result.skipped} (see logs).")
    if committed:
        body_parts.append("Changes committed to git.")
    body_parts.append("Files: " + ", ".join(Path(f).name for f in apply_result.changed_files))

    try:
        send_notification(title=title, body=" ".join(body_parts), priority="default")
    except Exception:
        log.debug("Notification send failed (non-critical)")
