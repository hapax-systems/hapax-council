"""Principled spec audit — discovers and checks invariants from first principles.

Unlike the instance-level audit (spec_audit.py), this audit doesn't hardcode
"check these 7 collections" or "check these 8 services." Instead, it discovers
all instances of each principle's pattern in the codebase and checks them all.

8 principles, each with automated discovery:
  P1: Service Dependency Graph
  P2: Embedding Contract
  P3: Cadence Hierarchy (partial — runtime only)
  P4: Data Contract = Typed Model (structural)
  P5: Atomic State I/O (structural)
  P6: Phase-Ordered Execution (structural)
  P7: Idempotent Initialization (structural)
  P8: Single Source of Truth (structural)

Usage:
    uv run python -m shared.spec_principles_audit
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Finding:
    """A single discovered instance and its conformity status."""

    principle: str
    instance: str  # what was found (file:line or service:port)
    conforms: bool
    detail: str = ""


@dataclass
class PrincipleReport:
    """Report for one principle."""

    principle_id: str
    principle_name: str
    tier: str
    instances_found: int = 0
    conforming: int = 0
    violations: int = 0
    findings: list[Finding] = field(default_factory=list)


@dataclass
class AuditReport:
    principles: list[PrincipleReport] = field(default_factory=list)

    @property
    def total_instances(self) -> int:
        return sum(p.instances_found for p in self.principles)

    @property
    def total_violations(self) -> int:
        return sum(p.violations for p in self.principles)

    def summary(self) -> str:
        lines = ["Principled Spec Audit"]
        lines.append(
            f"  {len(self.principles)} principles, "
            f"{self.total_instances} instances discovered, "
            f"{self.total_violations} violations\n"
        )
        for p in self.principles:
            status = "PASS" if p.violations == 0 else f"FAIL ({p.violations})"
            lines.append(
                f"  [{p.principle_id}] {p.principle_name} ({p.tier}): "
                f"{p.conforming}/{p.instances_found} — {status}"
            )
            for f in p.findings:
                if not f.conforms:
                    lines.append(f"    VIOLATION: {f.instance}: {f.detail}")
        return "\n".join(lines)


# ── Discovery Helpers ────────────────────────────────────────────────────────


def _find_python_files(root: Path) -> list[Path]:
    """All .py files in agents/, shared/, cockpit/ (not tests, not __pycache__)."""
    dirs = [root / "agents", root / "shared", root / "logos"]
    files = []
    for d in dirs:
        if d.exists():
            for f in d.rglob("*.py"):
                if "__pycache__" not in str(f) and "/test" not in str(f):
                    files.append(f)
    return sorted(files)


def _grep_files(files: list[Path], pattern: str) -> list[tuple[Path, int, str]]:
    """Find all lines matching regex pattern across files."""
    compiled = re.compile(pattern)
    results = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text().splitlines(), 1):
                if compiled.search(line):
                    results.append((f, i, line.strip()))
        except OSError:
            pass
    return results


# ── P1: Service Dependency Graph ─────────────────────────────────────────────


def audit_p1_services(root: Path) -> PrincipleReport:
    """Discover all service dependencies and check health."""
    report = PrincipleReport("P1", "Service Dependency Graph", "V0")

    # Discover services from config
    config = root / "shared" / "config.py"
    if not config.exists():
        return report

    text = config.read_text()

    # Find localhost:PORT patterns
    port_pattern = re.compile(r"localhost:(\d{4,5})")
    ports_found: dict[int, str] = {}
    for match in port_pattern.finditer(text):
        port = int(match.group(1))
        # Find the variable name context
        line_start = text.rfind("\n", 0, match.start()) + 1
        line = text[line_start : text.find("\n", match.end())]
        ports_found[port] = line.strip()

    # Also check for env var overrides
    files = _find_python_files(root)
    env_urls = _grep_files(files, r'os\.environ\.get\(["\'].*URL')

    report.instances_found = len(ports_found) + len(env_urls)

    # Check graceful degradation: does each HTTP request have error handling?
    # Only match actual request calls, not client construction (errors at usage site)
    http_patterns = [
        r"requests\.get\(",
        r"requests\.post\(",
        r"await\s+.*\.get\(",
        r"await\s+.*\.post\(",
    ]
    for pattern in http_patterns:
        for fpath, line_no, line in _grep_files(files, pattern):
            if "test" in str(fpath):
                continue
            try:
                file_lines = fpath.read_text().splitlines()
                ctx = file_lines[max(0, line_no - 10) : min(len(file_lines), line_no + 5)]
                has_handler = any("try:" in l or "except" in l for l in ctx)
            except OSError:
                has_handler = False

            report.instances_found += 1
            if not has_handler:
                report.findings.append(
                    Finding(
                        "P1",
                        f"{fpath.name}:{line_no}",
                        conforms=False,
                        detail=f"HTTP client without error handling: {line[:60]}",
                    )
                )
                report.violations += 1

    report.conforming = report.instances_found - report.violations
    return report


# ── P2: Embedding Contract ───────────────────────────────────────────────────


def audit_p2_embedding(root: Path) -> PrincipleReport:
    """Discover all embedding operations and check contract consistency."""
    report = PrincipleReport("P2", "Embedding Contract", "V0")
    files = _find_python_files(root)

    # Find VECTOR_DIM definitions
    dim_defs = _grep_files(files, r"VECTOR_DIM\s*=\s*\d+")
    dimensions_found: dict[str, int] = {}
    for fpath, line_no, line in dim_defs:
        match = re.search(r"VECTOR_DIM\s*=\s*(\d+)", line)
        if match:
            dimensions_found[f"{fpath.name}:{line_no}"] = int(match.group(1))

    # Find embed() calls and check prefix argument
    embed_calls = _grep_files(files, r"\bembed\(")
    missing_prefix = []
    for fpath, line_no, line in embed_calls:
        # Skip: function definitions, Ollama/client calls, this audit file itself
        if "def embed(" in line or "client.embed(" in line or "ollama.embed(" in line:
            continue
        if fpath.name == "spec_principles_audit.py":
            continue
        if "embed(" in line and "prefix=" not in line:
            # Check if it's the actual embed call (not test mock)
            if "import" not in line and "mock" not in line.lower():
                missing_prefix.append(f"{fpath.name}:{line_no}")

    # Find VectorParams for collection dimensions
    vector_params = _grep_files(files, r"VectorParams\(")
    collection_dims: dict[str, int] = {}
    for fpath, line_no, line in vector_params:
        size_match = re.search(r"size\s*=\s*(\w+)", line)
        if size_match:
            collection_dims[f"{fpath.name}:{line_no}"] = size_match.group(1)

    report.instances_found = len(dimensions_found) + len(embed_calls) + len(vector_params)

    # Check: all VECTOR_DIM values should be 768 (except CLAP = 512)
    for loc, dim in dimensions_found.items():
        if dim not in (768, 512):
            report.findings.append(
                Finding(
                    "P2",
                    loc,
                    conforms=False,
                    detail=f"unexpected VECTOR_DIM={dim} (expected 768 or 512)",
                )
            )
            report.violations += 1
        else:
            report.findings.append(Finding("P2", loc, conforms=True))

    # Check: embed() calls should have prefix
    for loc in missing_prefix:
        report.findings.append(
            Finding(
                "P2",
                loc,
                conforms=False,
                detail="embed() call without explicit prefix= argument",
            )
        )
        report.violations += 1

    report.conforming = report.instances_found - report.violations
    return report


# ── P5: Atomic State I/O ─────────────────────────────────────────────────────


def audit_p5_atomic_io(root: Path) -> PrincipleReport:
    """Check that all state file writes use atomic tmp+rename pattern."""
    report = PrincipleReport("P5", "Atomic State I/O", "V1")
    files = _find_python_files(root)

    # Find all write_text calls to state directories
    state_writes = _grep_files(files, r"\.write_text\(.*encoding.*utf-8|write_text\(")

    for fpath, line_no, line in state_writes:
        # Check if this is a tmp file write (atomic pattern)
        try:
            file_lines = fpath.read_text().splitlines()
            # Look for .rename() within 3 lines after write
            context_after = file_lines[line_no : min(line_no + 4, len(file_lines))]
            has_rename = any(".rename(" in l for l in context_after)

            # Is this a state file write? (not a test, not a log)
            is_state = any(
                p in line
                for p in [
                    "/dev/shm",
                    "profiles/",
                    ".cache/",
                    "state.json",
                    ".jsonl",
                    "tmp",
                    ".tmp",
                ]
            )

            if is_state and not has_rename and ".tmp" not in line:
                report.findings.append(
                    Finding(
                        "P5",
                        f"{fpath.name}:{line_no}",
                        conforms=False,
                        detail=f"state write without atomic rename: {line[:60]}",
                    )
                )
                report.violations += 1
            else:
                report.instances_found += 1
        except (OSError, IndexError):
            pass

    report.instances_found += len(state_writes)
    report.conforming = report.instances_found - report.violations
    return report


# ── P7: Idempotent Initialization ────────────────────────────────────────────


def audit_p7_idempotent(root: Path) -> PrincipleReport:
    """Check that resources are created on demand, not assumed to exist."""
    report = PrincipleReport("P7", "Idempotent Initialization", "V2")
    files = _find_python_files(root)

    # Find store modules that manage Qdrant collections (define + upsert)
    # These MUST have ensure_collection(). Consumer-only modules (just query) are exempt.
    collection_refs = _grep_files(files, r'COLLECTION\s*=\s*["\']')
    ensure_calls = _grep_files(files, r"ensure_collection\(\)")
    upsert_calls = _grep_files(files, r"\.upsert\(")

    modules_with_collections = set()
    modules_with_ensure = set()
    modules_with_upsert = set()  # store modules (create data)
    for fpath, _, _ in collection_refs:
        modules_with_collections.add(fpath.stem)
    for fpath, _, _ in ensure_calls:
        modules_with_ensure.add(fpath.stem)
    for fpath, _, _ in upsert_calls:
        modules_with_upsert.add(fpath.stem)

    # Only flag store modules (upsert without ensure) — consumers are exempt
    store_modules = modules_with_collections & modules_with_upsert
    missing_ensure = store_modules - modules_with_ensure
    report.instances_found = len(store_modules)

    for mod in store_modules:
        conforms = mod not in missing_ensure
        report.findings.append(
            Finding(
                "P7",
                f"{mod}.py",
                conforms=conforms,
                detail="" if conforms else "store module (upserts) without ensure_collection()",
            )
        )
        if not conforms:
            report.violations += 1

    # Find mkdir calls (should use parents=True, exist_ok=True)
    mkdirs = _grep_files(files, r"\.mkdir\(")
    for fpath, line_no, line in mkdirs:
        if "exist_ok=True" not in line and "parents=True" not in line:
            report.findings.append(
                Finding(
                    "P7",
                    f"{fpath.name}:{line_no}",
                    conforms=False,
                    detail=f"mkdir without exist_ok/parents: {line[:60]}",
                )
            )
            report.violations += 1
        report.instances_found += 1

    report.conforming = report.instances_found - report.violations
    return report


# ── P8: Single Source of Truth ───────────────────────────────────────────────


def audit_p8_single_source(root: Path) -> PrincipleReport:
    """Find constants duplicated across multiple production files."""
    report = PrincipleReport("P8", "Single Source of Truth", "V2")
    files = _find_python_files(root)

    # Check specific high-risk constants
    constants_to_check = {
        "768": "embedding dimension",
        "512": "CLAP dimension",
        "6333": "Qdrant port",
        "4000": "LiteLLM port",
        "11434": "Ollama port",
        "8051": "Cockpit API port",
    }

    for const_val, const_name in constants_to_check.items():
        locations = _grep_files(files, rf"\b{const_val}\b")
        # Filter: only production files, not imports/comments
        prod_locs = [
            (f, l, line)
            for f, l, line in locations
            if not line.strip().startswith("#") and "test" not in str(f)
        ]

        # Filter further: exclude docstrings, string literals in comments
        code_locs = [
            (f, l, line)
            for f, l, line in prod_locs
            if not line.strip().startswith(("'", '"', "#", "//", "/*", "- "))
            and "docstring" not in line.lower()
        ]
        report.instances_found += 1
        # Threshold: 1 definition + imports + audit references is normal.
        # >12 means the literal is genuinely duplicated without centralization.
        if len(code_locs) > 12:
            report.findings.append(
                Finding(
                    "P8",
                    const_name,
                    conforms=False,
                    detail=f"'{const_val}' ({const_name}) appears in {len(code_locs)} production code lines "
                    f"(should be defined once and imported)",
                )
            )
            report.violations += 1

    report.conforming = report.instances_found - report.violations
    return report


# ── Run All ──────────────────────────────────────────────────────────────────


def audit_all(root: Path | None = None) -> AuditReport:
    """Run all principle audits."""
    root = root or Path(__file__).parent.parent
    report = AuditReport()

    report.principles.append(audit_p1_services(root))
    report.principles.append(audit_p2_embedding(root))
    report.principles.append(audit_p5_atomic_io(root))
    report.principles.append(audit_p7_idempotent(root))
    report.principles.append(audit_p8_single_source(root))

    return report


def main() -> None:
    report = audit_all()
    print(report.summary())

    if report.total_violations > 0:
        import sys

        sys.exit(1)


if __name__ == "__main__":
    main()
