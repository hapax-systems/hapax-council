"""Typed blocked-witness evaluation. Does not unblock and does not live in the hashed lifecycle module."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml

BLOCKED_WITNESS_KINDS = frozenset({"path_exists", "ancestor_of_main", "receipt_fresh"})
BlockedWitnessVerdict = Literal["satisfied", "unsatisfied", "refuse"]


def evaluate_blocked_witness(
    frontmatter: Mapping[str, Any],
    *,
    now: datetime | None = None,
    git_repo: Path | None = None,
) -> BlockedWitnessVerdict:
    """Evaluate a typed blocked_witness. Unknown or untyped kinds refuse.

    This function only evaluates. ``cc-cascade-unblock`` still owns any status
    flip, and ``is_active_blocked_with_evidence`` remains the exemption guard
    (TRUE means do not mutate).
    """

    raw = frontmatter.get("blocked_witness")
    if not isinstance(raw, Mapping):
        return "refuse"
    kind = str(raw.get("kind") or "").strip()
    ref = str(raw.get("ref") or "").strip()
    if not kind or not ref:
        return "refuse"
    if kind not in BLOCKED_WITNESS_KINDS:
        return "refuse"
    if kind == "path_exists":
        return "satisfied" if Path(ref).expanduser().exists() else "unsatisfied"
    if kind == "ancestor_of_main":
        return _sha_is_ancestor_of_main(ref, git_repo=git_repo)
    if kind == "receipt_fresh":
        return _receipt_is_fresh(ref, now=now)
    return "refuse"


def _sha_is_ancestor_of_main(sha: str, *, git_repo: Path | None) -> BlockedWitnessVerdict:
    if not re.fullmatch(r"[0-9a-f]{7,64}", sha.strip().lower()):
        return "refuse"
    repo = git_repo or Path(os.environ.get("HAPAX_WITNESS_GIT_REPO") or ".")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, "origin/main"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "refuse"
    if result.returncode == 0:
        return "satisfied"
    if result.returncode == 1:
        return "unsatisfied"
    return "refuse"


def _receipt_is_fresh(ref: str, *, now: datetime | None) -> BlockedWitnessVerdict:
    path = Path(ref).expanduser()
    if not path.is_file():
        return "unsatisfied"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return "refuse"
    if not isinstance(payload, Mapping):
        return "refuse"
    observed = payload.get("observed_at")
    stale_after = payload.get("stale_after_seconds")
    if not observed or stale_after is None:
        return "refuse"
    try:
        observed_dt = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        if observed_dt.tzinfo is None:
            observed_dt = observed_dt.replace(tzinfo=UTC)
        horizon = int(stale_after)
    except (TypeError, ValueError):
        return "refuse"
    if horizon <= 0:
        return "refuse"
    moment = now if now is not None else datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if observed_dt > moment:
        return "refuse"
    if moment - observed_dt <= timedelta(seconds=horizon):
        return "satisfied"
    return "unsatisfied"
