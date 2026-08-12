"""The producer must not claim a consumer it does not have.

Two findings meet here, and both are about the same failure: a statement that was true once,
stopped being true, and had nothing watching it.

1. ``hapax-codex-quota-admission``'s docstring said its receipts were "consumed by
   hapax-quota-telemetry-writer". That writer scans admission receipts for agy, Claude and GLMCP
   only. ``hapax.codex_quota_admission.v1`` occurs in exactly one file — the producer.
2. Every documented governed dispatch that names a below-frontier model must carry its reason,
   because the frontier-selection guard now exits 6 without one. The Spark route did not, so the
   single documented Spark command failed every time it was run.

Both are pinned by scanning the tree rather than by asserting a constant, because a constant is
exactly what went stale in the first place.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER = REPO_ROOT / "scripts/hapax-codex-quota-admission"
DISPATCH = REPO_ROOT / "scripts/hapax-methodology-dispatch"
SCHEMA = "hapax.codex_quota_admission.v1"

#: Models the frontier guard will refuse without a stated reason. Kept as a literal list rather
#: than derived from the guard, so a change to the guard's frontier constant cannot silently
#: reclassify a documented command as fine.
BELOW_FRONTIER_MARKERS = ("codex-spark", "gpt-5.3", "gpt-5.5")


def _platform_paths() -> dict:
    """Load the dispatch module and hand back its PLATFORM_PATHS as Python built them."""
    spec = importlib.util.spec_from_loader(
        "hapax_methodology_dispatch_under_test",
        importlib.machinery.SourceFileLoader(
            "hapax_methodology_dispatch_under_test", str(DISPATCH)
        ),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return getattr(module, "PLATFORM_PATHS", {})


def _consumers_of_schema() -> list[Path]:
    hits: list[Path] = []
    for candidate in (
        *REPO_ROOT.glob("scripts/*"),
        *REPO_ROOT.glob("shared/*.py"),
        *REPO_ROOT.glob("agents/**/*.py"),
    ):
        if not candidate.is_file() or candidate.resolve() == PRODUCER.resolve():
            continue
        try:
            if SCHEMA in candidate.read_text(encoding="utf-8", errors="ignore"):
                hits.append(candidate)
        except OSError:
            continue
    return hits


def test_the_docstring_does_not_claim_a_consumer_that_does_not_exist() -> None:
    """The exact false sentence, refused by name.

    It read "positive receipts are consumed by ``scripts/hapax-quota-telemetry-writer`` before
    that route is treated as quota-fresh" — written by analogy to the Claude and agy writers,
    where it is true. Analogy is not measurement.
    """
    head = PRODUCER.read_text(encoding="utf-8")[:6000]
    consumers = _consumers_of_schema()

    if not consumers:
        # The sentence may be QUOTED (the correction above quotes it to say what was wrong); it
        # may not be ASSERTED. Same distinction as a comment naming a removed sentinel.
        claims = [
            line
            for line in head.splitlines()
            if "receipts are consumed by" in line and "previously read" not in line
        ]
        assert not claims, (
            f"the docstring claims consumption while nothing reads the schema: {claims}"
        )
        assert "NOTHING CONSUMES THESE RECEIPTS YET" in head, (
            "the inert state must be stated where someone reading the command will see it"
        )


def test_the_runtime_notice_fires_while_the_receipt_is_inert(tmp_path: Path) -> None:
    """A docstring nobody opens cannot prevent the mistake the docstring caused.

    An operator mints a receipt to unblock a held route; nothing changes; nothing says why. The
    notice is the only part of that story delivered at the moment the mistake is made.
    """
    if _consumers_of_schema():
        return

    result = subprocess.run(
        [
            sys.executable,
            str(PRODUCER),
            "--evidence-ref",
            "codex-subscription-headroom-observed-20260812t0000z",
            "--receipt-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert "nothing consumes" in result.stderr.lower()
    assert "it will still be held" in result.stderr, (
        "the notice must name the consequence, not just the fact"
    )
    assert "Next:" in result.stderr


def test_the_notice_retires_itself_when_a_consumer_lands() -> None:
    """The half that keeps this from becoming its own stale claim.

    If someone wires a consumer, the warning must stop on its own — no flag to flip, no comment
    to update. This test is the thing that fails if it does not.
    """
    consumers = _consumers_of_schema()
    if not consumers:
        return

    head = PRODUCER.read_text(encoding="utf-8")[:6000]
    assert "NOTHING CONSUMES THESE RECEIPTS YET" not in head, (
        f"{[str(p.relative_to(REPO_ROOT)) for p in consumers]} now reads {SCHEMA}; the "
        "producer still says nothing does"
    )


def test_every_documented_dispatch_below_frontier_states_its_reason() -> None:
    """The Spark break, generalised.

    The guard refuses a below-frontier selection with no stated reason, which is correct. What
    was wrong was a published command that could not satisfy it — so the single documented
    governed Spark dispatch exited 6 every time. Asserting this for one route would leave the
    next one to be found by a reviewer; asserting it for all of them does not.
    """
    # LOAD THE MODULE; DO NOT REGEX THE SOURCE. Two earlier versions of this assertion were
    # false greens, each for its own reason, and both would have shipped the break:
    #
    #   1. Searching a 600-character window around each match found HAPAX_CODEX_MODEL_REASON in
    #      the explanatory COMMENT above the entry, so the test passed with the fix reverted.
    #   2. Matching string literals missed it entirely: the command is written as two adjacent
    #      literals, and the fragment carrying `gpt-5.3-codex-spark` does not contain
    #      `hapax-codex`, so no pattern over literals ever examined it.
    #
    # The value an operator copies is the CONCATENATED string Python builds. That is the artifact
    # to check, and the only way to see it is to import the thing.
    paths = _platform_paths()
    assert paths, "no PLATFORM_PATHS loaded; re-derive this assertion"

    # `.launcher`, read without a default. A `getattr(p, "command", "")` here returned "" for
    # every entry and the test passed over an empty input set — the third false green in this
    # one assertion, and the same failure as the two above: a check that examined nothing.
    commands = [p.launcher for p in paths.values()]
    assert any("hapax-codex" in cmd for cmd in commands), (
        "no codex launcher commands found; the field this assertion reads has moved"
    )
    # Codex launcher invocations only. The `launcher` field is prose for routes that have no
    # launcher — one reads "receipt-only CapabilityIO/BudgetAuthorityAdapter route for LiteLLM
    # alias gpt-5.5-or", which carries a model name and invokes nothing. The frontier guard lives
    # in the codex launchers, so those are the commands it can refuse.
    offenders = [
        cmd
        for cmd in commands
        if "hapax-codex" in cmd
        and any(marker in cmd for marker in BELOW_FRONTIER_MARKERS)
        and "HAPAX_CODEX_MODEL_REASON" not in cmd
    ]

    assert not offenders, (
        "these documented commands select a below-frontier model with no stated reason, so the "
        f"frontier guard exits 6 on every run: {offenders}"
    )
