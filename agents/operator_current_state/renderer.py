"""Markdown renderer for the private Operator Now surface."""

from __future__ import annotations

from pathlib import Path

from agents.operator_current_state.state import OperatorCurrentState, write_state_atomic

DEFAULT_PAGE_PATH = (
    Path.home()
    / "Documents"
    / "Personal"
    / "20-projects"
    / "hapax-requests"
    / "_dashboard"
    / "operator-now.md"
)


def render_markdown(state: OperatorCurrentState) -> str:
    freshness_state = "fresh" if state.readiness.value == "ready" else "source_unknown"
    lines = [
        "---",
        "type: hapax-operator-current-state",
        "title: Operator Now",
        "status: generated",
        f"generated_at: {state.generated_at.isoformat()}",
        f"generated_by: {state.generated_by}",
        f"freshness_state: {freshness_state}",
        f"ttl_seconds: {state.ttl_seconds}",
        "public_current: false",
        "tags:",
        "  - hapax",
        "  - operator-now",
        "  - generated",
        "  - freshness",
        "---",
        "",
        "# Operator Now",
        "",
        "## Trust Contract",
        "",
        f"- Readiness: `{state.readiness.value}`",
        f"- Generated at: `{state.generated_at.isoformat()}`",
        f"- TTL seconds: `{state.ttl_seconds}`",
        "- Public projection: `false`",
        "",
    ]
    if state.readiness.blockers:
        lines.extend(["### Blockers", ""])
        for blocker in state.readiness.blockers:
            lines.append(
                f"- `{blocker.source}`: {blocker.reason} "
                f"({blocker.predicate_family}={blocker.predicate_value})"
            )
        lines.append("")
    lines.extend(
        [
            "### Source Status",
            "",
            "| Source | State | Required | Path |",
            "| --- | --- | --- | --- |",
        ]
    )
    for name, status in sorted(state.source_status.items()):
        lines.append(
            f"| `{name}` | `{status.predicate_value}` | `{status.required}` | `{status.path}` |"
        )
    lines.append("")

    sections = [
        ("Need To Know Right Now", "know"),
        ("Need To Do Right Now", "do"),
        ("Decisions Needed", "decide"),
        ("What To Expect", "expect"),
        ("Watch / Uncertain", "watch"),
    ]
    for heading, cls in sections:
        lines.extend([f"## {heading}", ""])
        items = [item for item in state.items if item.class_ == cls]
        if not items:
            if cls in {"do", "decide"} and state.readiness.value != "ready":
                lines.append("Unknown because required source freshness failed.")
            else:
                lines.append("None.")
            lines.append("")
            continue
        lines.extend(["| Item | Status | Source | Confidence |", "| --- | --- | --- | --- |"])
        for item in items:
            lines.append(
                f"| {item.summary} | `{item.status}` | `{item.source_ref}` | `{item.confidence}` |"
            )
        lines.append("")

    lines.extend(["## Evidence Receipts", ""])
    for item in state.items:
        lines.append(f"- `{item.id}` -> `{item.evidence_ref}`")
    lines.append("")
    return "\n".join(lines)


def write_outputs(state: OperatorCurrentState, *, state_path: Path, page_path: Path) -> bool:
    if not write_state_atomic(state, state_path):
        return False
    try:
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(render_markdown(state), encoding="utf-8")
    except OSError:
        return False
    return True
