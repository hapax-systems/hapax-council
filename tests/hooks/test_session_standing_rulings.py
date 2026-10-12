"""The SessionStart hook session-standing-rulings.sh prints the operator's standing rulings,
byte for byte, and nothing else.

The section is the accepted wording (row E7, its R6): three rulings, each quoted from its
stored record with the record's sha256 cited. Its sha256 is pinned here, so any change to
the text fails until a newly accepted wording replaces the pin. A paraphrase is the failure
this guards against: the rulings exist because paraphrases of them drifted.

The size is pinned too. Claude Code saves a long hook output to a file and shows the model
only its opening ~2,000 characters (measured 2026-10-11), which is why the rulings are their
own hook rather than a section of session-context.sh's much longer preamble.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "scripts" / "session-standing-rulings.sh"

# The R6 text block with its trailing newline: seven lines, 1,772 bytes, 1,764 characters.
SECTION_SHA256 = (
    "8475fc398877729b0b12e4ae16b94491d628508afc488a90ea0f4ccea9bfe80e"  # pragma: allowlist secret
)
SECTION_BYTES = 1772
SHOWN_WHOLE_CHARS = 2000

# Each quoted ruling's stored source record, cited by its sha256 prefix.
SOURCE_CITATIONS = (
    "sha256 c1ad9cb1…",  # 2026-10-10T14:39:22.241Z
    "sha256 105d538c…",  # 2026-10-11T18:29:29.411Z
    "sha256 f1fe77f9…",  # 2026-10-11T18:33:08.902Z
    "sha256 eae9853f…",  # 2026-10-11T18:33:51.248Z
)


def run_hook(payload: str) -> str:
    """Run the hook with the given stdin payload; return stdout. Any failure fails the test."""
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (
        f"hook exited {proc.returncode} for payload {payload!r}; stderr: {proc.stderr[:400]}"
    )
    assert proc.stderr == "", f"hook wrote to stderr: {proc.stderr[:400]}"
    return proc.stdout


def startup() -> str:
    return run_hook(json.dumps({"source": "startup", "session_id": "s1"}))


def test_output_is_the_accepted_text_byte_for_byte():
    data = startup().encode("utf-8")
    assert len(data) == SECTION_BYTES
    assert hashlib.sha256(data).hexdigest() == SECTION_SHA256


def test_each_quoted_ruling_cites_its_source_record():
    out = startup()
    for citation in SOURCE_CITATIONS:
        assert out.count(citation) == 1, f"{citation} is not cited exactly once"


def test_output_fits_inside_what_the_model_is_shown():
    assert len(startup()) < SHOWN_WHOLE_CHARS


def test_same_output_for_every_source_and_payload():
    """After a compaction above all: that is when a summary has replaced the record."""
    expected = startup()
    payloads = [
        json.dumps({"source": source, "session_id": "s1"})
        for source in ("resume", "clear", "compact", "fork")
    ]
    for payload in [*payloads, "", "not json at all"]:
        assert run_hook(payload) == expected, f"output differs for payload {payload!r}"


def test_hook_is_executable():
    """Claude Code runs a registered hook by its path, so the bit is part of the contract,
    in the checkout and in the tracked mode."""
    assert os.access(HOOK, os.X_OK)
    staged = subprocess.run(
        [
            "git",
            "-C",
            str(REPO),
            "ls-files",
            "-s",
            "--",
            "hooks/scripts/session-standing-rulings.sh",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if staged.returncode == 0 and staged.stdout:
        assert staged.stdout.startswith("100755 "), staged.stdout
