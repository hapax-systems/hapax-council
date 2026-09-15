"""One reading of a cc-task note's governed frontmatter, for every consumer of it.

Three places need the same answer to "what does this note declare, and is that
answer decidable": cc-close's precondition check (before any mutating gate runs),
cc-close's writer (against the bytes it rewrites), and cc-hygiene's note scan
(before it recommends deleting runtime state).

They had two-and-a-half readings between them, and each divergence was a finding:

* the writer regexed the whole note, so a body line decided a precondition;
* the duplicate-key check matched only unquoted keys, so ``"status":`` beside
  ``status:`` read as one key;
* ``parse_task_note`` accepted duplicate keys silently, so a note declaring
  ``status: in_progress`` then ``status: refused`` scanned as cleanly ``refused``
  and the live↔declared join advised retiring a live lane's marker — a path
  cc-close's own duplicate validation cannot protect, because ``refused`` never
  reaches cc-close.

Duplicates are decided THROUGH YAML, so every spelling YAML unifies is unified
here, and a scan that cannot complete REFUSES rather than reporting "no
duplicates": those are different facts, and only one of them is safe to act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from shared.frontmatter import parse_frontmatter_with_diagnostics

#: The fields cc-close reads or rewrites, and the ones the hygiene join decides on.
#: A duplicate elsewhere in the frontmatter is the vault's business; a duplicate
#: here makes "what does this note say" undecidable for a destructive action.
GOVERNED_KEYS: tuple[str, ...] = ("task_id", "status", "completed_at", "updated_at", "pr")


@dataclass(frozen=True)
class GovernedFrontmatter:
    """A decided reading, or a stated reason there is none."""

    frontmatter: dict | None = None
    body: str = ""
    duplicate_keys: tuple[str, ...] = ()
    error: str | None = None
    #: The frontmatter block's raw text, delimiters excluded — what a line rewrite
    #: must be confined to.
    block: str = ""
    rest: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True only when the reading is BOTH successful and unambiguous."""
        return self.error is None and not self.duplicate_keys and self.frontmatter is not None


class _DuplicateRecordingLoader(yaml.SafeLoader):
    """SafeLoader that records repeated mapping keys instead of taking the last.

    A SUBCLASS of SafeLoader, so no arbitrary-type tag becomes constructible: the
    hook counts keys and delegates to ``SafeLoader.construct_mapping``.
    """


def _mapping_recording_duplicates(loader, node, deep=False):  # type: ignore[no-untyped-def]
    # flatten_mapping FIRST, which is what SafeConstructor does: it resolves `<<:`
    # merge keys. Constructing key nodes without it hits the merge tag and raises,
    # and a handler that answered by discarding the duplicates it had found would be
    # a validator failing open on valid input.
    loader.flatten_mapping(node)
    seen: set = set()
    for key_node, _value in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in seen:
                loader.hapax_duplicate_keys.add(key)  # type: ignore[attr-defined]
            seen.add(key)
        except TypeError:  # unhashable key: not a governed field, not our business
            continue
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_DuplicateRecordingLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_recording_duplicates
)


def read_governed_frontmatter(
    path_or_text: Path | str, *, governed_keys: tuple[str, ...] = GOVERNED_KEYS
) -> GovernedFrontmatter:
    """Parse a note's frontmatter and decide whether its governed fields are readable."""
    text = (
        path_or_text.read_text(encoding="utf-8") if isinstance(path_or_text, Path) else path_or_text
    )

    if not text.startswith("---"):
        return GovernedFrontmatter(error="document does not start with YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        return GovernedFrontmatter(error="frontmatter closing marker is missing")
    block, rest = text[3:end], text[end:]

    parsed = parse_frontmatter_with_diagnostics(text)
    if not parsed.ok or parsed.frontmatter is None:
        return GovernedFrontmatter(
            error=f"{parsed.error_kind}: {parsed.error_message}", block=block, rest=rest
        )

    loader = _DuplicateRecordingLoader(block)
    loader.hapax_duplicate_keys = set()  # type: ignore[attr-defined]
    try:
        loader.get_single_data()
    except yaml.YAMLError as exc:
        # REFUSE, never clear. "The scan could not complete" is not "there were no
        # duplicates", and the successful parse above does not license the
        # difference: this loader answers a question that one does not.
        return GovernedFrontmatter(
            error=f"duplicate-key scan did not complete: {exc}", block=block, rest=rest
        )
    finally:
        loader.dispose()

    dupes = tuple(
        sorted(str(k) for k in loader.hapax_duplicate_keys if k in governed_keys)  # type: ignore[attr-defined]
    )
    return GovernedFrontmatter(
        frontmatter=parsed.frontmatter,
        body=parsed.body,
        duplicate_keys=dupes,
        block=block,
        rest=rest,
    )


def scalar(reading: GovernedFrontmatter, key: str) -> str:
    """One governed field as a stripped string; "" when absent or null."""
    value = (reading.frontmatter or {}).get(key)
    return "" if value is None else str(value).strip()
