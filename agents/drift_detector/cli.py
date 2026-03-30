"""CLI entry point for drift_detector."""

from __future__ import annotations

import argparse
import sys

from opentelemetry import trace

from .config import AI_AGENTS_DIR, HAPAX_HOME, PROFILES_DIR

_tracer = trace.get_tracer(__name__)


async def main() -> None:
    with _tracer.start_as_current_span(
        "drift.detect",
        attributes={"agent.name": "drift_detector", "agent.repo": "hapax-council"},
    ):
        return await _main_impl()


async def _main_impl() -> None:
    """Implementation of main, wrapped by OTel span."""
    parser = argparse.ArgumentParser(
        description="Documentation drift detector — LLM-powered comparison of docs vs reality",
        prog="python -m agents.drift_detector",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument(
        "--fix", action="store_true", help="Generate corrected documentation fragments"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply fixes directly to files (requires --fix)"
    )
    args = parser.parse_args()

    if args.apply and not args.fix:
        print("--apply requires --fix", file=sys.stderr)
        sys.exit(1)

    from .agent import detect_drift, format_human
    from .docs import load_docs
    from .fix_apply import apply_fixes, git_commit_fixes, notify_fixes
    from .fixes import format_fixes, generate_fixes
    from .introspect import generate_manifest

    print("Collecting infrastructure manifest...", file=sys.stderr)
    manifest = await generate_manifest()

    print("Analyzing drift...", file=sys.stderr)
    report = await detect_drift(manifest)

    if args.fix:
        docs = load_docs()
        print("Generating fixes...", file=sys.stderr)
        fix_report = await generate_fixes(report, docs)

        if args.apply:
            print("Applying fixes...", file=sys.stderr)
            apply_result = apply_fixes(fix_report)

            # Auto-regenerate screen context if drift detected
            screen_drift = [i for i in report.drift_items if "screen_context.md" in i.doc_file]
            if screen_drift:
                try:
                    import subprocess

                    regen_result = subprocess.run(
                        ["uv", "run", "python", "scripts/generate_screen_context.py"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=str(AI_AGENTS_DIR),
                    )
                    if regen_result.returncode == 0:
                        import logging

                        logging.getLogger("drift_detector").info(
                            "Auto-regenerated screen analyzer context"
                        )
                except Exception as exc:
                    import logging

                    logging.getLogger("drift_detector").warning(
                        "Failed to auto-regenerate screen context: %s", exc
                    )

            committed = git_commit_fixes(apply_result.changed_files, apply_result.applied)
            notify_fixes(apply_result, committed)

            print(
                f"Applied: {apply_result.applied}, Skipped: {apply_result.skipped}", file=sys.stderr
            )
            if apply_result.errors:
                for err in apply_result.errors:
                    print(f"  Skip: {err}", file=sys.stderr)
            if committed:
                print("Changes committed to git.", file=sys.stderr)

            # Re-scan after applying fixes so drift-report.json reflects current state
            if apply_result.applied > 0:
                print("Re-scanning after fixes...", file=sys.stderr)
                report = await detect_drift(manifest)
                report_path = PROFILES_DIR / "drift-report.json"
                report_path.write_text(report.model_dump_json(indent=2))
                print(
                    f"Updated {report_path.name}: {len(report.drift_items)} items remaining",
                    file=sys.stderr,
                )

            if args.json:
                print(apply_result.model_dump_json(indent=2))
            else:
                print(
                    f"\nDrift auto-fix complete. {apply_result.applied} applied, {len(report.drift_items)} remaining."
                )
                if apply_result.changed_files:
                    for f in apply_result.changed_files:
                        short = f.replace(str(HAPAX_HOME), "~")
                        print(f"  Updated: {short}")
        elif args.json:
            print(fix_report.model_dump_json(indent=2))
        else:
            print(format_fixes(fix_report))
    elif args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(format_human(report))
