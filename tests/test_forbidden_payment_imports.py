"""Forbidden-import CI guard for payment-processor client libraries.

Per cc-task ``leverage-money-stripe-payment-link-REFUSED``: Stripe
Connect KYC is operator-physical (government ID upload, bank-account
verification, 1099-K threshold). Not daemon-tractable under
``feedback_full_automation_or_no_engagement`` (operator constitutional
directive 2026-04-25T22:30Z).

The receipt mechanism for LICENSE-REQUEST is replaced by:
- Lightning / Nostr Zaps via Alby / LNbits self-hosted (no KYC)
- Liberapay recurring sub-threshold (no KYC)

This guard scans for imports of payment-processor SDKs that would
require KYC bootstrap. Any match fails the build.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

FORBIDDEN_IMPORTS: Final[tuple[str, ...]] = (
    # Per cc-task leverage-money-stripe-payment-link-REFUSED
    "stripe",
    # Per cc-task leverage-money-paypal-REFUSED (anticipated; KYC also operator-physical)
    "paypalrestsdk",
    "paypal-checkout-serversdk",
    # Per cc-task leverage-money-square-REFUSED (anticipated; same KYC posture)
    "squareup",
    "square",
    # Per cc-task leverage-REFUSED-patreon-sponsorship — subscriber-relationship-management
    "patreon",
    "patreon_python",
    "patreon-python",
)
"""Python clients for refused monetization surfaces.

The KYC-blocked clients (stripe / paypal / square) are refused because
KYC bootstrap (government ID + bank verification + 1099-K threshold)
is operator-physical. Patreon is refused because its tier-perks model
+ subscriber-relationship management is operator-physical. The
authorized money paths are Lightning / Nostr Zaps + Liberapay
(no KYC, no tiers, no subscriber-comms)."""

SCAN_ROOTS: Final[tuple[str, ...]] = (
    "agents",
    "shared",
    "scripts",
    "logos",
)


_IMPORT_PATTERN_TEMPLATE = r"^\s*(?:from\s+{lib}\s+import|import\s+{lib})\b"


def _scan_for_forbidden_imports(
    forbidden: tuple[str, ...] = FORBIDDEN_IMPORTS,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[tuple[Path, str, int, str]]:
    """Walk the source tree looking for any forbidden payment-processor import."""
    findings: list[tuple[Path, str, int, str]] = []
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        for py_file in root.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for lib in forbidden:
                pattern = _IMPORT_PATTERN_TEMPLATE.format(lib=re.escape(lib.replace("-", "_")))
                for line_no, line in enumerate(text.splitlines(), 1):
                    if re.search(pattern, line):
                        findings.append((py_file, lib, line_no, line))
    return findings


class TestForbiddenPaymentImportGuard:
    def test_codebase_has_no_forbidden_payment_imports(self) -> None:
        """Codebase must not import stripe, paypalrestsdk, squareup."""
        findings = _scan_for_forbidden_imports()
        assert findings == [], (
            "Forbidden payment-processor library imports detected:\n"
            + "\n".join(
                f"  {path}:{line_no}: {line.strip()} (lib: {lib})"
                for path, lib, line_no, line in findings
            )
            + "\n\n"
            "Per leverage-money-*-REFUSED cc-tasks, payment-processor "
            "KYC is operator-physical (government ID + bank verification + "
            "1099-K threshold). Use Lightning/Nostr Zaps or Liberapay "
            "recurring sub-threshold instead."
        )

    def test_scanner_detects_stripe_import(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        bad_file = agents_dir / "bad.py"
        bad_file.write_text("import stripe\n")
        findings = _scan_for_forbidden_imports(repo_root=tmp_path)
        assert len(findings) == 1
        assert findings[0][1] == "stripe"

    def test_scanner_detects_from_stripe_import(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        bad_file = agents_dir / "bad.py"
        bad_file.write_text("from stripe import Charge\n")
        findings = _scan_for_forbidden_imports(repo_root=tmp_path)
        assert len(findings) == 1

    def test_scanner_skips_non_scan_dirs(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        bad_file = docs_dir / "ignored.py"
        bad_file.write_text("import stripe\n")
        findings = _scan_for_forbidden_imports(repo_root=tmp_path)
        assert findings == []
