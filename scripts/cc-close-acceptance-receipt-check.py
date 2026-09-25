#!/usr/bin/env python3
"""cc-close-acceptance-receipt-check — review-floor closure receipt gate.

Routing Phase 0.2 (REQ-20260609): ``frontier_review_required`` is only honest
if acceptance is enforced. Reads a cc-task .md file and returns:

- exit 0 when the task does not declare the review floor (top-level or
  ``route_metadata.quality_floor``) — non-review-floor flows are untouched.
- exit 0 when a valid signed acceptance receipt exists beside the note as
  ``<task_id>.acceptance.yaml`` carrying acceptor, verdict ``accepted``,
  timestamp, and an artifact ref.
- exit 2 when the receipt is missing, malformed, field-incomplete, or its
  verdict is not ``accepted`` — with the precise blockers and next actions
  on stderr.

Used by ``scripts/cc-close`` in the ``done`` path, before the note moves to
closed/. Verdicts other than ``accepted`` block: a rejected review is not a
closeable outcome.

HEAD BINDING. A receipt accepts one revision. Once a PR is in play (``--pr``,
the note's ``pr:``, or the receipt's own ``pr:``), the receipt must name that
PR and carry the full 40-hex ``head_sha`` it accepted, and that sha must equal
the PR's current head. A receipt from round 1 of a PR that has since moved is a
review of code that no longer exists; measured on PR 4668, where such a
receipt satisfied this gate twenty rounds later. "Could not verify the current
head" (gh unavailable, no network, no ``pr_repo``) is not "verified": it
refuses, and the repository is never guessed. A PR-less row has no head to
bind and passes, saying so.

Bypass: ``HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1`` (incident response only),
honored here so every caller shares one mechanism.

Failure mode: fail-OPEN on infrastructure errors reading the NOTE (missing /
unreadable file — a broken gate must not brick closures), but fail-CLOSED on
receipt problems (an absent or invalid receipt is exactly what this gate
exists to catch).
"""

from __future__ import annotations

import hmac
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.cc_task_pr_link import is_nullish, is_well_formed_repo  # noqa: E402
from shared.public_gate_receipts import PUBLIC_GATE_REVIEW_HEAD_RE  # noqa: E402
from shared.sdlc_lifecycle import (  # noqa: E402
    ACCEPTANCE_RECEIPT_REQUIRED_FIELDS,
    acceptance_receipt_blockers,
    acceptance_receipt_path,
    frontmatter_from_text,
    requires_acceptance_receipt,
)

#: ``(pr_number, owner/repo) -> current head sha``, or None when it cannot be observed.
HeadLookup = Callable[[str, str], str | None]


def gh_pr_head_sha(pr_number: str, repo: str) -> str | None:
    """The PR's current head as GitHub reports it, or None if it cannot be observed."""

    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--repo",
                repo,
                "--json",
                "headRefOid",
                "--jq",
                ".headRefOid",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _scalar(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().strip('"').strip("'")


def _pr_scalar(value: object) -> str:
    scalar = _scalar(value)
    return "" if is_nullish(scalar) else scalar.lstrip("#")


def receipt_head_blockers(
    frontmatter: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    cli_pr: str | None = None,
    cli_repo: str | None = None,
    head_lookup: HeadLookup = gh_pr_head_sha,
) -> tuple[tuple[str, ...], str]:
    """Bind an otherwise-valid receipt to the PR's current head.

    Returns ``(blockers, detail)``. ``detail`` describes what was bound on a pass.
    The network is consulted only once every locally checkable field is sound, so
    a malformed receipt or an absent repository never reaches a lookup.
    """

    task_pr = _pr_scalar(cli_pr) or _pr_scalar(frontmatter.get("pr"))
    receipt_pr = _pr_scalar(receipt.get("pr"))
    pr_number = task_pr or receipt_pr
    if not pr_number:
        return (), "no PR declared (note, receipt, or --pr): head binding does not apply"

    blockers: list[str] = []
    if not pr_number.isdigit():
        blockers.append(f"acceptance_receipt_pr_malformed:{pr_number}")
    if task_pr and receipt_pr and receipt_pr != task_pr:
        blockers.append(f"acceptance_receipt_pr_mismatch:receipt={receipt_pr}:task={task_pr}")

    receipt_head = _scalar(receipt.get("head_sha"))
    if is_nullish(receipt_head):
        blockers.append("acceptance_receipt_missing_field:head_sha")
    elif PUBLIC_GATE_REVIEW_HEAD_RE.fullmatch(receipt_head) is None:
        blockers.append(f"acceptance_receipt_head_sha_malformed:{receipt_head}")

    repo = _scalar(cli_repo) or _scalar(frontmatter.get("pr_repo"))
    if is_nullish(repo):
        blockers.append("acceptance_receipt_pr_repo_missing")
    elif not is_well_formed_repo(repo):
        blockers.append(f"acceptance_receipt_pr_repo_malformed:{repo}")

    if blockers:
        return tuple(blockers), ""

    current = _scalar(head_lookup(pr_number, repo))
    if PUBLIC_GATE_REVIEW_HEAD_RE.fullmatch(current) is None:
        return (f"acceptance_receipt_current_head_unverifiable:{repo}#{pr_number}",), ""
    if not hmac.compare_digest(receipt_head.casefold(), current.casefold()):
        return (
            f"acceptance_receipt_stale_head:receipt={receipt_head.casefold()}:"
            f"current={current.casefold()}",
        ), ""
    return (), f"bound to the current head {current[:12]} of {repo}#{pr_number}"


def _head_refusal(task_id: str, receipt: Path, blockers: tuple[str, ...]) -> str:
    lines = [
        f"cc-close BLOCKED: the acceptance receipt for '{task_id}' is not bound to the"
        " PR's current head:",
        "",
        *(f"  - {blocker}" for blocker in blockers),
        "",
        "A receipt accepts one revision. A later head of the same PR has not been",
        "reviewed, so the receipt cannot close it.",
        "",
        "Next action: re-run acceptance on the current head.",
        "  - review-team receipt: re-dispatch review for the PR",
        "    (scripts/cc-pr-review-dispatch.py); quorum-accept mints a receipt for the new head.",
        "  - operator or lane receipt: the acceptor reviews the current head and re-signs",
        f"    {receipt}",
        "    with 'pr: <N>' and 'head_sha: <full 40-hex current head>'.",
        "Do not edit head_sha to match by hand: that records acceptance of a revision",
        "nobody reviewed.",
    ]
    if any("unverifiable" in b or "pr_repo" in b for b in blockers):
        lines += [
            "",
            "The current head could not be observed. Set 'pr_repo: <owner>/<name>' on the",
            "note (or pass --repo), check `gh auth status`, then re-run. An unverifiable",
            "head is not a matching one.",
        ]
    lines += ["", "Bypass for incident response: HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1"]
    return "\n".join(lines)


def gate(
    path: Path,
    *,
    cli_pr: str | None = None,
    cli_repo: str | None = None,
    head_lookup: HeadLookup = gh_pr_head_sha,
) -> tuple[int, str]:
    """Return ``(exit_code, message)``; 0 permits closure, 2 blocks it."""

    if os.environ.get("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF") == "1":
        return 0, "acceptance-receipt gate disabled by HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1"

    if not path.is_file():
        return 0, f"fail-OPEN: source path missing or not a file ({path})"

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return 0, f"fail-OPEN: source unreadable ({exc})"

    frontmatter = frontmatter_from_text(text)
    if not requires_acceptance_receipt(frontmatter):
        return 0, "not a review-floor task — acceptance-receipt gate does not apply"

    blockers = acceptance_receipt_blockers(frontmatter, path)
    task_id = str(frontmatter.get("task_id") or path.stem)
    receipt = acceptance_receipt_path(path, task_id)
    if not blockers:
        # Re-read to bind the head. The receipt was validated a moment ago, so any
        # failure here means it changed or vanished in between; every outcome that is
        # not a mapping refuses with a typed blocker. That includes None: an empty
        # file, e.g. one truncated mid-write.
        head_blockers: tuple[str, ...]
        try:
            loaded = yaml.safe_load(receipt.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            head_blockers = (f"acceptance_receipt_malformed:{type(exc).__name__}",)
        else:
            if isinstance(loaded, Mapping):
                head_blockers, detail = receipt_head_blockers(
                    frontmatter,
                    loaded,
                    cli_pr=cli_pr,
                    cli_repo=cli_repo,
                    head_lookup=head_lookup,
                )
                if not head_blockers:
                    return 0, f"valid acceptance receipt present; {detail}"
            else:
                head_blockers = (
                    f"acceptance_receipt_malformed:not_a_mapping:{type(loaded).__name__}",
                )
        return 2, _head_refusal(task_id, receipt, head_blockers)

    lines = [
        f"cc-close BLOCKED: review-floor task '{task_id}' lacks a valid acceptance receipt:",
        "",
        *(f"  - {blocker}" for blocker in blockers),
        "",
        "frontier_review_required work closes only after a signed review. Have the",
        "acceptor (frontier reviewer or operator) record the verdict at:",
        f"  {receipt}",
        "with the minimal schema (all fields required):",
        f"  {', '.join(ACCEPTANCE_RECEIPT_REQUIRED_FIELDS)}",
        "e.g.:",
        "  acceptor: operator",
        "  verdict: accepted",
        "  timestamp: 2026-06-10T17:00:00Z",
        "  artifact: <PR URL / review note / evidence path>",
        "",
        "A verdict other than 'accepted' keeps the task open — address the review",
        "feedback instead of closing.",
        "",
        "Bypass for incident response: HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1",
    ]
    return 2, "\n".join(lines)


USAGE = (
    "usage: cc-close-acceptance-receipt-check.py <path-to-cc-task.md> [--pr N] [--repo OWNER/REPO]"
)


def main(argv: list[str]) -> int:
    args = argv[1:]
    options: dict[str, str] = {}
    positional: list[str] = []
    while args:
        arg = args.pop(0)
        if arg in ("--pr", "--repo"):
            if not args:
                print(USAGE, file=sys.stderr)
                return 64
            options[arg] = args.pop(0)
        else:
            positional.append(arg)
    if len(positional) != 1:
        print(USAGE, file=sys.stderr)
        return 64
    code, msg = gate(
        Path(positional[0]), cli_pr=options.get("--pr"), cli_repo=options.get("--repo")
    )
    if code != 0:
        print(msg, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
