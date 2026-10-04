"""Review-packet redaction of registered personal tokens (review-packet-redacts-scrubbed-pii-lines-20261004).

Before a review packet leaves to an external provider, any line carrying a registered principal
token (local registry, the SAME matcher the pre-push guard uses) is replaced by an opaque
sha256-keyed marker, so a privacy scrub can be reviewed without re-sending what it removes.

No real name appears in this test: every fixture uses SYNTHETIC tokens passed to the real matcher,
which is exactly how the redactor runs (tokens come from the registry at runtime, never literals).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_review_team():
    if "review_team" in sys.modules:
        return sys.modules["review_team"]
    scripts = REPO_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("review_team", scripts / "review_team.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_team"] = module
    spec.loader.exec_module(module)
    return module


rt = _load_review_team()

# Synthetic registered token — NOT a real name; stands in for a registry entry at test time.
_SYNTH = "Zsyntheticname"
_MARKER_PREFIX = "[REDACTED: registered token; line sha256 "


def _sha(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def test_added_and_deleted_token_lines_are_both_redacted_keeping_the_diff_prefix():
    text = (
        f"+ new line mentioning {_SYNTH} here\n"
        f"- removed line with {_SYNTH} too\n"
        "  unchanged context line\n"
        "+ added line with no registered token"
    )
    redacted, count = rt.redact_registered_tokens(text, [_SYNTH])
    assert count == 2, redacted
    assert _SYNTH not in redacted, "the registered token must not survive into the packet"
    lines = redacted.split("\n")
    # Critical: the unified-diff prefix is preserved so the packet stays a valid diff.
    assert lines[0] == f"+{_MARKER_PREFIX}" + _sha(f"+ new line mentioning {_SYNTH} here") + "]"
    assert lines[1] == f"-{_MARKER_PREFIX}" + _sha(f"- removed line with {_SYNTH} too") + "]"
    assert lines[2] == "  unchanged context line"
    assert lines[3] == "+ added line with no registered token"
    # Every content line still begins with a valid diff prefix after redaction.
    assert all(ln[:1] in ("+", "-", " ") for ln in lines)


def test_packet_without_a_registered_token_is_unchanged():
    text = "+ a diff line\n- another diff line\n  context"
    redacted, count = rt.redact_registered_tokens(text, [_SYNTH])
    assert count == 0
    assert redacted == text


def test_marker_carries_the_sha256_of_the_original_line_and_keeps_the_prefix():
    line = f"- secret removal of {_SYNTH}"
    redacted, count = rt.redact_registered_tokens(line, [_SYNTH])
    assert count == 1
    expected = _sha(line)
    assert redacted == f"-{_MARKER_PREFIX}{expected}]"  # the '-' prefix is preserved
    assert len(expected) == 64


def test_prose_line_without_a_diff_prefix_is_redacted_whole():
    # A PR body / task-note / prior-critical line has no +/-/space prefix: the whole line is the
    # marker (the matcher is not diff-specific; reused on prose).
    line = f"The submission from {_SYNTH} concerns a third party."
    redacted, count = rt.redact_registered_tokens(line, [_SYNTH])
    assert count == 1
    assert redacted == f"{_MARKER_PREFIX}{_sha(line)}]"
    assert _SYNTH not in redacted


def test_diff_structure_headers_are_left_intact():
    # File/hunk headers are structure, not added/deleted content; redacting them would corrupt the
    # diff. They pass through unchanged.
    text = (
        "diff --git a/f.py b/f.py\n"
        "@@ -1,2 +1,2 @@ def context\n"
        "--- a/f.py\n"
        "+++ b/f.py\n"
        f"- removed {_SYNTH}"
    )
    redacted, count = rt.redact_registered_tokens(text, [_SYNTH])
    lines = redacted.split("\n")
    assert lines[0] == "diff --git a/f.py b/f.py"
    assert lines[1] == "@@ -1,2 +1,2 @@ def context"
    assert lines[2] == "--- a/f.py" and lines[3] == "+++ b/f.py"
    assert lines[4].startswith("-" + _MARKER_PREFIX), "only the content line is redacted"
    assert count == 1


def test_redact_structure_redacts_nested_string_leaves():
    # prior_criticals is a list of finding dicts; a detail can quote a token-bearing diff line.
    prior = [
        {"title": "a finding", "detail": f"- quoted line with {_SYNTH}", "line": 7},
        {"title": "clean", "detail": "nothing sensitive", "line": 9},
    ]
    red, count = rt.redact_structure(prior, [_SYNTH])
    assert count == 1
    assert _SYNTH not in repr(red)
    assert red[0]["line"] == 7 and red[1]["detail"] == "nothing sensitive"
    assert red[0]["detail"].startswith("-" + _MARKER_PREFIX)


def test_empty_text_or_empty_names_is_a_noop():
    assert rt.redact_registered_tokens("", [_SYNTH]) == ("", 0)
    assert rt.redact_registered_tokens("some text", []) == ("some text", 0)


def test_load_principal_tokens_fails_closed_on_unreadable_registry(monkeypatch):
    """A registry read failure must raise, so a packet never leaves unredacted (fail-closed)."""
    monkeypatch.setattr(
        rt,
        "_PRINCIPAL_MATCHER",
        SimpleNamespace(registry_names=lambda root: ([], "the registry cannot be read")),
    )
    with pytest.raises(rt.PacketRedactionError):
        rt.load_principal_tokens(REPO_ROOT)


def test_load_principal_tokens_fails_closed_on_empty_registry(monkeypatch):
    """A loaded-but-EMPTY registry fails closed too (seat ruling (e)): an empty name set cannot be
    distinguished from a misconfiguration that silently disables the redactor."""
    monkeypatch.setattr(
        rt, "_PRINCIPAL_MATCHER", SimpleNamespace(registry_names=lambda root: ([], None))
    )
    with pytest.raises(rt.PacketRedactionError):
        rt.load_principal_tokens(REPO_ROOT)


def test_load_principal_tokens_returns_registry_names(monkeypatch):
    monkeypatch.setattr(
        rt,
        "_PRINCIPAL_MATCHER",
        SimpleNamespace(registry_names=lambda root: ([_SYNTH, "Qxtoken"], None)),
    )
    assert rt.load_principal_tokens(REPO_ROOT) == [_SYNTH, "Qxtoken"]


def test_synthesize_dossier_records_the_redaction_count():
    """The count is recorded in the dossier (the reviewable evidence of what was hidden)."""
    dossier = rt.synthesize_dossier(
        task_id="t",
        pr_number=1,
        head_sha="a" * 40,
        team_class="t2_standard",
        registry=rt.load_lens_registry(),
        reviews=[],
        lenses=("tests-cover-the-diff", "exit-predicate-adequacy", "doc-claims-recheck"),
        constituted_at="2026-10-04T00:00:00Z",
        packet_redactions=7,
    )
    assert dossier["packet_redactions"] == 7
