#!/usr/bin/env python3
"""hapax_transcript_scrub — scrub secrets/PII from a transcript (CS stage-0 tool).

Reads text from a FILE argument (or stdin), applies the transcript-grade scrubber
(``shared.transcript_scrubber``), and writes the scrubbed text to stdout. With
``--assert`` it additionally runs the fail-closed ``assert_clean`` gate and exits
non-zero if any residual secret/PII survives — the same gate the Continuity
Substrate distillation pipeline runs before persisting or serving a bundle.

Usage::

    uv run python scripts/hapax_transcript_scrub.py TRANSCRIPT.jsonl
    cat ~/.cache/hapax/claude-headless/alpha/output.jsonl \\
        | uv run python scripts/hapax_transcript_scrub.py --assert
"""

from __future__ import annotations

import argparse
import sys

from shared.transcript_scrubber import ResidualSecretError, assert_clean, scrub


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hapax_transcript_scrub")
    parser.add_argument("file", nargs="?", help="input transcript file (default: stdin)")
    parser.add_argument(
        "--assert",
        dest="do_assert",
        action="store_true",
        help="run the fail-closed assert_clean gate after scrubbing (exit 1 on residual)",
    )
    parser.add_argument(
        "--no-pii",
        action="store_true",
        help="do not redact operator PII (secrets are always redacted)",
    )
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    else:
        text = sys.stdin.read()

    redact_pii = not args.no_pii
    result = scrub(text, redact_pii=redact_pii)
    if args.do_assert:
        try:
            assert_clean(result.text, redact_pii=redact_pii)
        except ResidualSecretError as exc:
            print(f"hapax_transcript_scrub: FAIL-CLOSED — {exc}", file=sys.stderr)
            return 1
    sys.stdout.write(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
