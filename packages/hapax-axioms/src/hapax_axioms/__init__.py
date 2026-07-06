"""hapax-axioms — single-operator axiom enforcement library.

Public API for downstream projects:

>>> from hapax_axioms import (
...     load_axioms,
...     load_patterns,
...     scan_text,
...     scan_commit_message,
...     scan_file,
... )

The library bundles a frozen snapshot of the five constitution-published
axioms (single_user, executive_function, management_governance,
interpersonal_transparency, corporate_boundary) and the T0 violation
patterns extracted from the council repo's pre-commit gate. The original
spec at https://github.com/hapax-systems/hapax-constitution remains the
canonical, evolving source of truth.
"""

from __future__ import annotations

from hapax_axioms.checker import (
    Violation,
    scan_commit_message,
    scan_file,
    scan_text,
)
from hapax_axioms.models import (
    Axiom,
    AxiomBundle,
    AxiomScope,
    AxiomType,
    Implication,
    Pattern,
    PatternBundle,
    Tier,
)
from hapax_axioms.registry import (
    bundled_axioms_path,
    bundled_patterns_path,
    load_axioms,
    load_patterns,
)

__version__ = "0.1.0"

__all__ = [
    "Axiom",
    "AxiomBundle",
    "AxiomScope",
    "AxiomType",
    "Implication",
    "Pattern",
    "PatternBundle",
    "Tier",
    "Violation",
    "__version__",
    "bundled_axioms_path",
    "bundled_patterns_path",
    "load_axioms",
    "load_patterns",
    "scan_commit_message",
    "scan_file",
    "scan_text",
]
