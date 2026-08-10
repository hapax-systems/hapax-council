#!/usr/bin/env python3
"""K0 kernel manifest conformance checker + drift-pin (R0.4).

Enforces, fail-closed, the criteria written in K0-FIXED-POINT-SPEC.md:

  C1  manifest_digest matches recomputation                   (spec §5 — the drift-pin)
  C2  every member carries a circularity justification        (spec §2.2)
  C3  no member is installable by a governed act              (falsifier 1)
  C4  every member declares demote: canary                    (spec §2.5 / falsifier 5)
  C5  all mandatory lever classes covered; optional typed     (R0.8 / falsifier 4)
  C6  every declared artifact exists and matches its digest   (kernel identity is byte-exact)
  C7  P-1 facts appear as facts, never as members             (spec §2.4)
  C8  ids unique and well-formed; decomposed members name law and data

Exit 0 = conformant. Exit 1 = violations (listed), or C6 unevaluated without
--allow-skipped-artifacts. Exit 2 = the manifest could not be read.

    k0_manifest_check.py [--manifest PATH] [--repo-root PATH] [--update-digest]
                         [--allow-skipped-artifacts]

--update-digest rewrites manifest_digest in place. Kernel law changing must be a deliberate act,
so this is never run implicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # fail-closed: an unevaluable predicate denies (K0.1)
    print("FAIL: PyYAML is required to evaluate the manifest; refusing to pass unevaluated.")
    raise SystemExit(2) from None

DIGEST_FIELD = "manifest_digest"
DIGEST_PLACEHOLDER = "PENDING"


def canonical_digest(manifest: dict[str, Any]) -> str:
    """sha256 over a canonical JSON serialisation, with the digest field itself excluded.

    Canonical = sorted keys, tight separators, UTF-8. Excluding the field is what makes the pin
    a fixed point rather than a self-reference.
    """
    body = {k: v for k, v in manifest.items() if k != DIGEST_FIELD}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def check(manifest: dict[str, Any], repo_roots: dict[str, Path]) -> tuple[list[str], list[str]]:
    """Returns (violations, skipped). Artifacts in repos with no mapped root are SKIPPED and
    reported as such — an unchecked digest is never counted as a passing one."""
    violations: list[str] = []
    skipped: list[str] = []
    members: list[dict[str, Any]] = manifest.get("members") or []
    facts: list[dict[str, Any]] = manifest.get("pre_kernel_facts") or []
    classes: dict[str, str] = manifest.get("lever_classes") or {}

    # C1 — the drift-pin
    recorded = manifest.get(DIGEST_FIELD)
    actual = canonical_digest(manifest)
    if recorded == DIGEST_PLACEHOLDER:
        violations.append(
            f"C1 {DIGEST_FIELD} is {DIGEST_PLACEHOLDER!r}; run --update-digest to pin"
        )
    elif recorded != actual:
        violations.append(
            f"C1 kernel law drifted: {DIGEST_FIELD} is {recorded!r} but the manifest hashes to "
            f"{actual!r}. If the change was deliberate, re-pin with --update-digest."
        )

    if not members:
        violations.append("C2 manifest declares no members; an empty kernel cannot be conformant")

    seen_ids: set[str] = set()
    for member in members:
        mid = member.get("id", "<no id>")

        # C8 — identity
        if mid in seen_ids:
            violations.append(f"C8 duplicate member id {mid!r}")
        seen_ids.add(mid)
        if not str(mid).startswith("K0."):
            violations.append(f"C8 member id {mid!r} is not of the form K0.N")

        # C2 — justification
        if not str(member.get("circularity") or "").strip():
            violations.append(f"C2 {mid} has no circularity justification (spec §2.2)")

        # C3 — not installable
        if member.get("installable_by_governed_act") is not False:
            violations.append(
                f"C3 {mid} is not marked installable_by_governed_act: false — a single "
                "non-circular installation path disqualifies a candidate (falsifier 1)"
            )

        # C4 — demotable
        if member.get("demote") != "canary":
            violations.append(
                f"C4 {mid} must declare demote: canary — demote-never-delete (spec §2.5); "
                "a member that cannot be demoted is permanent infrastructure, not kernel"
            )

        # C5a — class is declared
        lever = member.get("lever_class")
        if lever not in classes:
            violations.append(f"C5 {mid} declares unknown lever_class {lever!r}")

        # C8b — decomposition names both sides
        decomposition = member.get("decomposition")
        if decomposition is not None:
            for side in ("law", "data"):
                if not str(decomposition.get(side) or "").strip():
                    violations.append(f"C8 {mid} decomposition does not name its {side} part")

        # C6 — artifact identity, resolved per declaring repo
        for artifact in member.get("artifacts") or []:
            path, digest = artifact.get("path"), artifact.get("sha256")
            repo = artifact.get("repo")
            if not path or not digest:
                violations.append(f"C6 {mid} artifact needs both path and sha256")
                continue
            if not repo:
                violations.append(f"C6 {mid} artifact {path} declares no repo")
                continue
            root = repo_roots.get(repo)
            if root is None:
                skipped.append(f"{mid} {repo}:{path} (no --repo-root for {repo!r})")
                continue
            target = root / path
            if not target.exists():
                violations.append(f"C6 {mid} artifact absent under {root}: {path}")
                continue
            actual_digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual_digest != digest:
                violations.append(
                    f"C6 {mid} artifact {path} is {actual_digest[:16]}… but the manifest pins "
                    f"{str(digest)[:16]}…"
                )

    # C5b — mandatory class coverage
    covered = {m.get("lever_class") for m in members}
    for name, status in classes.items():
        if status == "mandatory" and name not in covered:
            violations.append(
                f"C5 mandatory lever class {name!r} has no K0 member (R0.8 boot column)"
            )
        if (
            status != "mandatory"
            and name not in covered
            and status
            not in {
                "degenerate-but-typed",
                "weak-form",
            }
        ):
            violations.append(f"C5 optional class {name!r} is uncovered and not typed as absent")

    # C7 — tier discipline
    fact_ids = {f.get("id") for f in facts}
    for bad in fact_ids & seen_ids:
        violations.append(f"C7 {bad} appears as both a pre-kernel fact and a K0 member (spec §2.4)")
    for fact in facts:
        if not str(fact.get("rationale") or "").strip():
            violations.append(f"C7 pre-kernel fact {fact.get('id')!r} has no rationale")

    return violations, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument("--manifest", type=Path, default=here / "k0-manifest.yaml")
    parser.add_argument(
        "--repo-root",
        action="append",
        default=[],
        metavar="REPO=PATH",
        help="map a declaring repo to a checkout for C6, e.g. hapax-council=~/projects/... ; "
        "repeatable. Artifacts in unmapped repos are reported as SKIPPED, never as passing.",
    )
    parser.add_argument("--update-digest", action="store_true")
    parser.add_argument(
        "--allow-skipped-artifacts",
        action="store_true",
        help=(
            "report conformant even when C6 artifact checks could not be evaluated. "
            "Structure-only; asserts you know kernel identity went unchecked."
        ),
    )
    args = parser.parse_args()

    try:
        manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"FAIL: cannot read manifest {args.manifest}: {exc}")
        return 2
    if not isinstance(manifest, dict):
        print(f"FAIL: manifest {args.manifest} is not a mapping")
        return 2

    if args.update_digest:
        digest = canonical_digest(manifest)
        text = args.manifest.read_text(encoding="utf-8")
        old = manifest.get(DIGEST_FIELD, DIGEST_PLACEHOLDER)
        args.manifest.write_text(
            text.replace(f'{DIGEST_FIELD}: "{old}"', f'{DIGEST_FIELD}: "{digest}"'),
            encoding="utf-8",
        )
        print(f"pinned {DIGEST_FIELD}: {digest}")
        return 0

    repo_roots: dict[str, Path] = {}
    for mapping in args.repo_root:
        if "=" not in mapping:
            print(f"FAIL: --repo-root expects REPO=PATH, got {mapping!r}")
            return 2
        name, _, raw = mapping.partition("=")
        repo_roots[name] = Path(raw).expanduser()

    violations, skipped = check(manifest, repo_roots)
    members = manifest.get("members") or []
    for entry in skipped:
        print(f"  SKIPPED artifact check: {entry}")
    if violations:
        print(f"K0 manifest NON-CONFORMANT — {len(violations)} violation(s):")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    # UNEVALUABLE DENIES. C6 is kernel IDENTITY — byte-exactness of the members. A run without
    # --repo-root skips every C6 check, and this previously still printed "conformant" and exited 0,
    # so the cheapest invocation produced the most reassuring answer. That is the failure mode this
    # whole object exists to prevent: on 2026-08-10 the first run WITH repo roots found four drifted
    # members that the bare run had reported as conformant since 2026-07-30.
    #
    # Same doctrine host_floor.py states for the OS floor: "a probe that cannot determine a version
    # does not get to assume it is new enough."
    if skipped and not args.allow_skipped_artifacts:
        print(
            f"K0 manifest INDETERMINATE — {len(skipped)} artifact check(s) could not be evaluated."
        )
        print(
            "  Kernel identity is byte-exact, so an unevaluated C6 is not a pass. Re-run with "
            "--repo-root REPO=PATH for each repo named above, or --allow-skipped-artifacts to "
            "assert you want structure-only."
        )
        return 1
    print(
        f"K0 manifest conformant: {len(members)} members, "
        f"{len(manifest.get('pre_kernel_facts') or [])} pre-kernel facts, "
        f"kernel_version {manifest.get('kernel_version')!r}"
    )
    print(f"  manifest_digest {manifest.get(DIGEST_FIELD)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
