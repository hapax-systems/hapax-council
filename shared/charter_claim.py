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

from collections.abc import Mapping
from typing import Any

import yaml


def _norm(ref: str) -> str:
    return ref.strip().lstrip("./").rstrip("/")


def covers(prefix: str, ref: str) -> bool:
    """True when ``ref`` is the prefix or a path under it."""
    parent, child = _norm(prefix), _norm(ref)
    if not parent or not child:
        return False
    return child == parent or child.startswith(parent + "/")


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
    if child.get("parent_charter") != charter.get("task_id"):
        return False
    scope = _refs(charter.get("charter_scope"))
    refs = _refs(child.get("mutation_scope_refs"))
    if not scope or not refs:
        return False
    return all(any(covers(prefix, ref) for prefix in scope) for ref in refs)


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
