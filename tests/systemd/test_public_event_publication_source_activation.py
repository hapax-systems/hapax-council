"""Source-activation pins for public-event publication services."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
ACTIVATION_WORKTREE = "%h/.cache/hapax/source-activation/worktree"
PRIMARY_CHECKOUT = "%h/projects/hapax-council"

PUBLIC_EVENT_PUBLICATION_UNITS = (
    ("hapax-arena-post.service", "agents.cross_surface.arena_post"),
    ("hapax-bluesky-post.service", "agents.cross_surface.bluesky_post"),
    ("hapax-mastodon-post.service", "agents.cross_surface.mastodon_post"),
    (
        "hapax-weblog-publish-public-event-producer.service",
        "agents.weblog_publish_public_event_producer",
    ),
)


def _execution_lines(unit_name: str) -> list[str]:
    text = (UNITS_DIR / unit_name).read_text(encoding="utf-8")
    return [
        line
        for line in text.splitlines()
        if line.startswith(
            ("ExecStart=", "WorkingDirectory=", "Environment=PATH=", "Environment=PYTHONPATH=")
        )
    ]


def test_hn_public_event_publication_units_use_source_activation() -> None:
    for unit_name, module_name in PUBLIC_EVENT_PUBLICATION_UNITS:
        lines = _execution_lines(unit_name)
        joined = "\n".join(lines)

        assert lines, f"{unit_name} has no execution lines to verify"
        assert PRIMARY_CHECKOUT not in joined, f"{unit_name} still executes from primary checkout"
        assert f"WorkingDirectory={ACTIVATION_WORKTREE}" in joined
        assert f"Environment=PYTHONPATH={ACTIVATION_WORKTREE}" in joined
        assert f"ExecStart={ACTIVATION_WORKTREE}/.venv/bin/python -m {module_name}" in joined
