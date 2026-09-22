"""Charter claims: one grant, obligated precise children.

Yard Crow is the demand surface where operator inflection enters once. It does
not yet mint claims. A charter is that inflection recorded as an entry: it
names a scope, it is not itself permission to edit, and it obligates a later
sub-claim inside that scope before a mutation counts as supported.

That is gap 2 of the append-only log. An entry that obligates the record makes
the absence of the discharge a well-formedness breach, checkable by anyone who
can read the entries. It is also CHANC's possession test: a declaration that
does not possess its support is not conformance. The checker reports the
breach. It does not refuse to record it. A log that refuses the anomaly cannot
show the anomaly.

The grant does not ask the operator again. Minting the child is the
coordinator's obligation, and it is the thing that keeps the work moving.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def _norm(ref: str) -> str | None:
    """Return a relative path, or None when the form can escape a prefix."""
    raw = ref.strip()
    if not raw or raw.startswith("/") or "\\" in raw:
        return None
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def covers(prefix: str, ref: str) -> bool:
    """True when ``ref`` is the prefix or a path under it.

    Forms that leave the prefix (``..``, absolute paths) are not covered.
    """
    parent, child = _norm(prefix), _norm(ref)
    if parent is None or child is None:
        return False
    return child == parent or child.startswith(parent + "/")


def sidecar_belongs_to(path: Path, task_id: str) -> bool:
    """True when a claim sidecar's parsed task id is exactly ``task_id``.

    Substring checks are not used. A neighboring id must not count as a match.
    """
    if not task_id or not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if path.name.startswith("cc-claim-dispatch-"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return False
        return payload.get("task_id") == task_id
    parts = text.split()
    if path.name.startswith("cc-claim-epoch-") and len(parts) >= 2:
        return parts[1] == task_id
    return text.strip() == task_id


def residue_without_active_lease(status: str) -> str:
    """What to do with dispatch residue when the active-lease file is absent.

    A live task (any non-terminal status, including missing) is a hold.
    Only a terminal task may be archived. Losing the lease file is not a release.
    The terminal set is the lifecycle module's, not a private subset.
    """
    from shared.sdlc_lifecycle import TASK_TERMINAL_STATUSES

    if status in TASK_TERMINAL_STATUSES:
        return "archive"
    return "hold"


def _frontmatter(text: str) -> Mapping[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    loaded = yaml.safe_load(text[4:end])
    return loaded if isinstance(loaded, dict) else {}


def _refs(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def child_may_mint(charter_text: str, child_text: str) -> bool:
    """True when the child names this charter and stays inside its scope.

    A child with an empty scope may not mint. Precision is the obligation.
    A child wider than the charter may not mint. The grant is not a blank check.
    """
    charter = _frontmatter(charter_text)
    child = _frontmatter(child_text)
    if str(charter.get("claim_form") or "") != "charter":
        return False
    charter_id = str(charter.get("task_id") or "").strip()
    parent = str(child.get("parent_charter") or "").strip()
    if not charter_id or parent != charter_id:
        return False
    scope = _refs(charter.get("charter_scope"))
    refs = _refs(child.get("mutation_scope_refs"))
    if not scope or not refs:
        return False
    return all(any(covers(prefix, ref) for prefix in scope) for ref in refs)


def write_obligation_report(
    destination: Path,
    breaches: list[str],
    *,
    charter_id: str,
) -> None:
    """Append one breach report. The mutation is not undone."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "hapax.charter-obligation-report.v1",
        "charter_id": charter_id,
        "breaches": breaches,
        "reported_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def obligation_breaches(
    charter_scope: list[str],
    child_scopes: list[list[str]],
    mutated_paths: list[str],
) -> list[str]:
    """Paths inside the charter that no child scope covers.

    A report. The mutation is still a fact. The missing child is the breach.
    """
    breaches: list[str] = []
    for path in mutated_paths:
        if not any(covers(prefix, path) for prefix in charter_scope):
            continue
        if any(covers(ref, path) for refs in child_scopes for ref in refs):
            continue
        breaches.append(path)
    return breaches
