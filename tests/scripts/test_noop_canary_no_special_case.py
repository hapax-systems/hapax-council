"""Regression pin: the dispatch plane treats canary notes identically.

SI canary doctrine — same emitter/probe path, NO special-case code in
dispatch. If claim/gate/headless-dispatch code ever learns to recognize
no-op canaries, the probe measures nothing: a lane that handles decoys
specially is no longer being measured on real behavior.

The supply-side carrier (cc-task-offer-ready) is the ONE lawful touch
point — it mints/grades on its reconcile tick but never special-cases
how a minted note is offered, claimed, or dispatched.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DISPATCH_PLANE_FILES = (
    "scripts/cc-claim",
    "scripts/cc-close",
    "scripts/hapax-claude-headless",
    "hooks/scripts/cc-task-gate.sh",
    "hooks/scripts/cc-task-gate.impl.sh",
)

FORBIDDEN_TOKENS = ("noop_canary", "noop-canary", "noop canary")


def test_dispatch_plane_has_no_canary_special_casing() -> None:
    offenders: list[str] = []
    for rel in DISPATCH_PLANE_FILES:
        path = REPO_ROOT / rel
        assert path.is_file(), f"dispatch-plane file moved: {rel} (update this pin)"
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        offenders.extend(f"{rel}: {token!r}" for token in FORBIDDEN_TOKENS if token in text)
    assert not offenders, "dispatch plane must not special-case no-op canaries: " + "; ".join(
        offenders
    )
