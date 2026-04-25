"""Weblog draft composer — aggregates sources → markdown w/ frontmatter."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from shared.governance.omg_referent import safe_render

# Default vault path per cc-task design. Operator drafts land here; Phase B
# publisher (agents/omg_weblog_publisher) reads from the same directory
# after the operator flips ``approved: true`` in frontmatter.
DEFAULT_DRAFT_DIR: Path = Path.home() / "hapax-state" / "weblog-drafts"

# Default source directories. All are treated as optional — missing
# directories degrade gracefully to empty context (this is the
# "structural skeleton" Phase A contract).
DEFAULT_CHRONICLE_DIR: Path = Path.home() / "hapax-state" / "chronicle"
DEFAULT_PROGRAMMES_DIR: Path = Path.home() / "hapax-state" / "programmes"
DEFAULT_PRECEDENTS_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent / "axioms" / "precedents"
)


class PlaceholderSection(BaseModel):
    """A structural section in the draft skeleton — title + hint for the operator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    hint: str


class WeblogDraft(BaseModel):
    """Composed draft — becomes a markdown file in the vault."""

    model_config = ConfigDict(extra="forbid")

    iso_date: str = Field(description="YYYY-MM-DD; used as filename + frontmatter tag")
    title_seed: str = Field(description="Operator-editable seed for the post title")
    context_summary: str = Field(description="One-liner describing what sources were found")
    placeholder_sections: list[PlaceholderSection] = Field(default_factory=list)
    approved: bool = Field(default=False, description="Operator flips True to authorize publish")


def compose_iso_date_slug(raw: str) -> str:
    """Normalise an ISO date input (YYYY-MM-DD) to a filename slug.

    Raises ``ValueError`` on inputs that don't round-trip through
    :meth:`datetime.date.fromisoformat`.
    """
    return date.fromisoformat(raw).isoformat()


class WeblogComposer:
    """Aggregates sources into a :class:`WeblogDraft`.

    All source directories are optional. If a directory is missing or
    empty, the composer emits the skeleton section for that category
    with a note that no source material was available. This matches
    the cc-task's "never fully autonomous" posture — operator writes
    the prose, composer scaffolds the structure.
    """

    def __init__(
        self,
        *,
        chronicle_dir: Path = DEFAULT_CHRONICLE_DIR,
        programmes_dir: Path = DEFAULT_PROGRAMMES_DIR,
        precedents_dir: Path = DEFAULT_PRECEDENTS_DIR,
    ) -> None:
        self.chronicle_dir = chronicle_dir
        self.programmes_dir = programmes_dir
        self.precedents_dir = precedents_dir

    def _count_markdown_files(self, directory: Path) -> int:
        if not directory.is_dir():
            return 0
        return sum(1 for _ in directory.glob("*.md"))

    def _build_context_summary(
        self, chronicle_count: int, programme_count: int, precedent_count: int
    ) -> str:
        if chronicle_count == 0 and programme_count == 0 and precedent_count == 0:
            return "no chronicle / programme / precedent source material available for this window"
        parts: list[str] = []
        if chronicle_count:
            parts.append(f"{chronicle_count} chronicle entries")
        if programme_count:
            parts.append(f"{programme_count} completed programmes")
        if precedent_count:
            parts.append(f"{precedent_count} axiom precedents")
        return "; ".join(parts)

    def compose_draft(self, iso_date: str) -> WeblogDraft:
        """Aggregate sources → WeblogDraft. Pure function of current fs state."""
        iso = compose_iso_date_slug(iso_date)

        chronicle_count = self._count_markdown_files(self.chronicle_dir)
        programme_count = self._count_markdown_files(self.programmes_dir)
        precedent_count = self._count_markdown_files(self.precedents_dir)

        sections: list[PlaceholderSection] = [
            PlaceholderSection(
                title="Opening — what drew the attention",
                hint=(
                    "800-1800 words total target. Begin with the single "
                    "thread the month pulled on. Scientific register; "
                    "literary but not rhetorical."
                ),
            ),
            PlaceholderSection(
                title="Chronicle — what happened",
                hint=(
                    f"{chronicle_count} chronicle entries in window. "
                    "Summarise threads that recurred; avoid log-recital "
                    "(that's statuslog territory)."
                ),
            ),
            PlaceholderSection(
                title="Programme arcs — what completed",
                hint=(
                    f"{programme_count} completed programmes in source dir. "
                    "Name them by aesthetic intent, not ticket id."
                ),
            ),
            PlaceholderSection(
                title="Precedent — what stance shifted",
                hint=(
                    f"{precedent_count} axiom precedent entries available. "
                    "Only include a precedent if the post's argument needs it."
                ),
            ),
            PlaceholderSection(
                title="Closing — what's now in view",
                hint=(
                    "Forward-facing but not promissory. A paragraph on "
                    "what the next month's attention is drawn toward."
                ),
            ),
        ]

        title_seed = f"Weblog — {iso}"
        context = self._build_context_summary(chronicle_count, programme_count, precedent_count)

        return WeblogDraft(
            iso_date=iso,
            title_seed=title_seed,
            context_summary=context,
            placeholder_sections=sections,
            approved=False,
        )

    def write_to_vault(self, draft: WeblogDraft, output_dir: Path) -> Path:
        """Render :class:`WeblogDraft` to a markdown file.

        Creates ``output_dir`` if missing. Returns the written path.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{draft.iso_date}.md"

        lines: list[str] = [
            "---",
            f'title: "{draft.title_seed}"',
            f'iso_date: "{draft.iso_date}"',
            "type: weblog-draft",
            f"approved: {str(draft.approved).lower()}",
            "---",
            "",
            f"# {draft.title_seed}",
            "",
            f"_Composer context: {draft.context_summary}._",
            "",
        ]
        for section in draft.placeholder_sections:
            lines.append(f"## {section.title}")
            lines.append("")
            lines.append(f"<!-- hint: {section.hint} -->")
            lines.append("")
            lines.append("")

        # AUDIT-05: scan composed skeleton for legal-name leak before
        # writing to vault. Composer-side sources (chronicle entries,
        # programme summaries, axiom precedents) may contain operator-
        # name surface forms; failing fast here avoids the operator
        # editing leaked content downstream.
        rendered = "\n".join(lines)
        rendered = safe_render(rendered, segment_id=draft.iso_date)
        path.write_text(rendered, encoding="utf-8")
        return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose a weblog draft skeleton.")
    parser.add_argument(
        "--iso-date",
        default=date.today().isoformat(),
        help="YYYY-MM-DD for the draft (default: today)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_DRAFT_DIR,
        help=f"Output vault directory (default: {DEFAULT_DRAFT_DIR})",
    )
    args = parser.parse_args()

    composer = WeblogComposer()
    draft = composer.compose_draft(args.iso_date)
    path = composer.write_to_vault(draft, args.out)
    print(f"wrote {path}")
    return 0
