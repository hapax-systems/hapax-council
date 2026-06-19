"""Local-only HKP research viewer.

The viewer is a support surface over cache-only HKP bundles. It reads HKP shadow
bundles and derived indexes from ``~/.cache/hapax`` and writes local reports
under ``~/.cache/hapax/hkp-reports``. It does not mutate source authority, vault
authority, dashboards, Qdrant, dispatch, close/release gates, runtime state,
public surfaces, or provider-spend state.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.hkp_bundle_export import default_index_root, default_shadow_root
from shared.hkp_bundle_schema import (
    VALIDATOR_VERSION,
    HkpConceptFrontmatter,
    validate_bundle,
)

CONSUMER_NAME = "research_viewer"
SUPPORT_LABEL = "support_non_authoritative_projection_state"
REPORT_DIRNAME = "hkp-reports"
FORBIDDEN_REPORT_FIELDS = frozenset({"body", "private_source_path", "secret"})
POLICY_ALLOWLISTED_REPORT_FIELDS = frozenset({"title", "description", "source_refs", "authority"})
POLICY_FORBIDDEN_FIELD_ALIASES = {
    "freshness": frozenset({"freshness_state", "source_freshness"}),
    "posture": frozenset(
        {"privacy_class", "egress_state", "public_export_allowed", "denied_consumers"}
    ),
    "validator_findings": frozenset({"findings"}),
}
REPORT_ROW_FIELDS = frozenset(
    {
        "record_type",
        "support_label",
        "bundle_id",
        "bundle_uid",
        "output_tree_hash",
        "validator_version",
        "validator_ok",
        "concept_uid",
        "concept_path",
        "type",
        "title",
        "description",
        "source_refs",
        "authority",
        "source_freshness",
        "freshness_state",
        "privacy_class",
        "egress_state",
        "public_export_allowed",
        "denied_consumers",
        "findings",
    }
)
_SAFE_REPORT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
__all__ = [
    "REPORT_ROW_FIELDS",
    "SUPPORT_LABEL",
    "HkpResearchViewerResult",
    "build_research_viewer_report",
    "default_report_root",
]


@dataclass(frozen=True)
class HkpResearchViewerResult:
    report_dir: Path
    markdown_path: Path
    json_path: Path
    payload: dict[str, Any]

    @property
    def ok(self) -> bool:
        return bool(self.payload.get("ok"))

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.payload,
            "report_dir": str(self.report_dir),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
        }


def default_report_root() -> Path:
    return Path.home() / ".cache" / "hapax" / REPORT_DIRNAME


def build_research_viewer_report(
    bundle_refs: list[str | Path] | tuple[str | Path, ...] | None = None,
    *,
    shadow_root: Path | None = None,
    index_root: Path | None = None,
    report_root: Path | None = None,
    report_id: str | None = None,
    generated_at: str | None = None,
) -> HkpResearchViewerResult:
    """Build a local support-only report for HKP shadow bundles."""

    generated_at = generated_at or _now_utc()
    shadow_root = shadow_root or default_shadow_root()
    index_root = index_root or default_index_root()
    report_root = report_root or default_report_root()
    _ensure_cache_child(shadow_root, default_shadow_root(), "HKP research viewer bundle input")
    _ensure_cache_child(index_root, default_index_root(), "HKP research viewer index input")
    _ensure_cache_child(report_root, default_report_root(), "HKP research viewer report output")

    bundles = _resolve_bundle_refs(bundle_refs or (), shadow_root=shadow_root)
    if not bundles:
        raise ValueError(
            f"no HKP bundles found under {shadow_root}; next-action: pass bundle ids or "
            "generate HKP shadow bundles before running the viewer"
        )

    report_id = _safe_report_id(report_id or _default_report_id(generated_at))
    report_dir = report_root / report_id
    _ensure_cache_child(report_dir, default_report_root(), "HKP research viewer report output")
    _reject_symlink_components(
        report_dir, "HKP research viewer report output", trusted_root=report_root
    )
    if report_dir.exists() and not report_dir.is_dir():
        raise ValueError(
            f"HKP research viewer report output path must be a directory: {report_dir}; "
            "next-action: remove the non-directory cache path or choose another --report-id"
        )
    report_dir.mkdir(parents=True, exist_ok=True)

    bundle_reports = [
        _bundle_report(bundle, shadow_root=shadow_root, index_root=index_root) for bundle in bundles
    ]
    payload = {
        "ok": all(bundle["validator_ok"] for bundle in bundle_reports),
        "record_type": "research_viewer_report",
        "consumer": CONSUMER_NAME,
        "support_label": SUPPORT_LABEL,
        "generated_at": generated_at,
        "report_id": report_id,
        "bundle_count": len(bundle_reports),
        "row_count": sum(len(bundle["rows"]) for bundle in bundle_reports),
        "validator_version": VALIDATOR_VERSION,
        "shadow_root": str(_absolute_without_symlink_resolution(shadow_root)),
        "index_root": str(_absolute_without_symlink_resolution(index_root)),
        "bundles": bundle_reports,
    }
    _assert_no_forbidden_report_fields(payload)
    markdown_path = report_dir / "report.md"
    json_path = report_dir / "report.json"
    _write_text_atomic(markdown_path, _markdown_report(payload), trusted_root=report_root)
    _write_text_atomic(
        json_path, json.dumps(payload, indent=2, sort_keys=True) + "\n", trusted_root=report_root
    )
    return HkpResearchViewerResult(
        report_dir=report_dir,
        markdown_path=markdown_path,
        json_path=json_path,
        payload=payload,
    )


def _bundle_report(bundle: Path, *, shadow_root: Path, index_root: Path) -> dict[str, Any]:
    _assert_bundle_read_boundary(bundle, shadow_root=shadow_root)
    validation = validate_bundle(bundle)
    manifest = _read_yaml(bundle / "_hkp" / "manifest.yaml", trusted_root=shadow_root)
    policy = _read_yaml(bundle / "_hkp" / "consumer_policy.yaml", trusted_root=shadow_root)
    index_rows = _read_index_rows(index_root / f"{bundle.name}.jsonl", trusted_root=index_root)
    index_findings = [
        _finding_summary(row, bundle=bundle)
        for row in index_rows
        if row.get("record_type") == "finding"
    ]
    validation_findings = [
        _finding_summary(finding.as_dict(), bundle=bundle) for finding in validation.findings
    ]
    consumer_row = _consumer_policy_row(policy)
    _assert_research_viewer_consumer_allowed(manifest, consumer_row, bundle=bundle)
    policy_allowed_fields = _policy_allowed_output_fields(consumer_row)
    policy_forbidden_fields = _policy_forbidden_output_fields(consumer_row)
    denied_consumers = _denied_consumers(manifest, policy)
    rows: list[dict[str, Any]] = []
    for concept_path in _concept_paths(bundle, shadow_root=shadow_root):
        concept = _read_concept(concept_path)
        _assert_research_viewer_concept_allowed(concept, concept_path=concept_path)
        subject_findings = [
            finding
            for finding in [*index_findings, *validation_findings]
            if finding.get("subject") in {concept.concept_uid, concept_path.name}
            or finding.get("path") in {concept_path.name, f"concepts/{concept_path.name}"}
        ]
        row = _concept_row(
            concept,
            bundle_id=bundle.name,
            manifest=manifest,
            validator_ok=validation.ok,
            denied_consumers=sorted(
                set(denied_consumers) | set(concept.posture.forbidden_consumers)
            ),
            findings=subject_findings,
        )
        row = _apply_consumer_policy(
            row,
            allowed_fields=policy_allowed_fields,
            forbidden_fields=policy_forbidden_fields,
        )
        _assert_no_forbidden_report_fields(row, extra_forbidden=policy_forbidden_fields)
        disallowed = sorted(set(row) - REPORT_ROW_FIELDS)
        if disallowed:
            raise ValueError(
                "HKP research viewer row contains disallowed fields: "
                + ", ".join(disallowed)
                + "; next-action: narrow the report projection before emitting"
            )
        rows.append(row)

    bundle_findings = [*index_findings, *validation_findings]
    bundle_report = {
        "record_type": "bundle",
        "support_label": SUPPORT_LABEL,
        "bundle_id": bundle.name,
        "bundle_uid": manifest.get("bundle_uid"),
        "output_tree_hash": manifest.get("output_tree_hash"),
        "validator_version": VALIDATOR_VERSION,
        "validator_ok": validation.ok,
        "concept_count": len(rows),
        "edge_count": _jsonl_row_count(bundle / "_hkp" / "edges.jsonl", trusted_root=shadow_root),
        "denied_consumers": denied_consumers,
        "finding_count": len(bundle_findings),
        "findings": bundle_findings,
        "rows": rows,
    }
    bundle_report = _apply_consumer_policy(
        bundle_report,
        allowed_fields=policy_allowed_fields,
        forbidden_fields=policy_forbidden_fields,
    )
    _assert_no_forbidden_report_fields(bundle_report, extra_forbidden=policy_forbidden_fields)
    return bundle_report


def _concept_row(
    concept: HkpConceptFrontmatter,
    *,
    bundle_id: str,
    manifest: dict[str, Any],
    validator_ok: bool,
    denied_consumers: list[str],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "record_type": "concept",
        "support_label": SUPPORT_LABEL,
        "bundle_id": bundle_id,
        "bundle_uid": manifest.get("bundle_uid"),
        "output_tree_hash": manifest.get("output_tree_hash"),
        "validator_version": VALIDATOR_VERSION,
        "validator_ok": validator_ok,
        "concept_uid": concept.concept_uid,
        "concept_path": concept.concept_path,
        "type": concept.type,
        "title": concept.title,
        "description": concept.description,
        "source_refs": [
            _source_ref_summary(ref.model_dump(mode="json")) for ref in concept.source_refs
        ],
        "authority": _authority_summary(concept.authority.model_dump(mode="json")),
        "source_freshness": sorted({ref.freshness_state for ref in concept.source_refs}),
        "freshness_state": concept.freshness.state,
        "privacy_class": concept.posture.privacy_class,
        "egress_state": concept.posture.egress_state,
        "public_export_allowed": concept.posture.public_export_allowed,
        "denied_consumers": denied_consumers,
        "findings": findings,
    }


def _source_ref_summary(source_ref: dict[str, Any]) -> dict[str, Any]:
    return {
        key: source_ref.get(key)
        for key in (
            "ref_id",
            "data_role",
            "source_authority_class",
            "uri",
            "content_hash",
            "freshness_state",
            "observed_at",
            "checked_at",
            "stale_after",
        )
    }


def _authority_summary(authority: dict[str, Any]) -> dict[str, Any]:
    return {
        "level": authority.get("level"),
        "may_authorize": bool(authority.get("may_authorize")),
        "ceiling_family": authority.get("ceiling_family"),
        "ceiling": authority.get("ceiling"),
        "promotion_required": authority.get("promotion_required"),
    }


def _read_concept(path: Path) -> HkpConceptFrontmatter:
    parsed = parse_frontmatter_with_diagnostics(path)
    if not parsed.ok or parsed.frontmatter is None:
        raise ValueError(
            f"HKP research viewer cannot parse concept frontmatter: {path}; "
            "next-action: validate or regenerate the HKP bundle first"
        )
    return HkpConceptFrontmatter.model_validate(parsed.frontmatter)


def _read_yaml(path: Path, *, trusted_root: Path) -> dict[str, Any]:
    _reject_symlink_components(path, "HKP research viewer bundle input", trusted_root=trusted_root)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(
            f"HKP research viewer cannot read YAML artifact {path}: {exc}; "
            "next-action: validate or regenerate the HKP bundle first"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError(
            f"HKP research viewer expected mapping YAML at {path}; "
            "next-action: validate or regenerate the HKP bundle first"
        )
    return loaded


def _read_index_rows(path: Path, *, trusted_root: Path) -> list[dict[str, Any]]:
    _reject_symlink_components(path, "HKP research viewer index input", trusted_root=trusted_root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"HKP derived index is not valid JSONL at {path}:{line_no}: {exc}; "
                "next-action: rebuild the derived index"
            ) from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _consumer_policy_row(policy: dict[str, Any]) -> dict[str, Any]:
    for row in policy.get("consumers") or []:
        if isinstance(row, dict) and row.get("consumer") == CONSUMER_NAME:
            return row
    raise ValueError(
        f"HKP consumer policy lacks {CONSUMER_NAME} row; next-action: regenerate the bundle "
        "with a fail-closed consumer policy"
    )


def _assert_research_viewer_consumer_allowed(
    manifest: dict[str, Any], consumer_row: dict[str, Any], *, bundle: Path
) -> None:
    allowed = set(manifest.get("allowed_consumers") or [])
    forbidden = set(manifest.get("forbidden_consumers") or [])
    if CONSUMER_NAME not in allowed or CONSUMER_NAME in forbidden:
        raise ValueError(
            f"HKP bundle {bundle.name} does not allow {CONSUMER_NAME}; next-action: "
            "regenerate the bundle with an explicit research_viewer allow row before viewing"
        )
    if consumer_row.get("default") != "allow_read_only":
        raise ValueError(
            f"HKP consumer policy for {bundle.name} denies {CONSUMER_NAME}; next-action: "
            "regenerate the bundle with research_viewer default allow_read_only before viewing"
        )


def _assert_research_viewer_concept_allowed(
    concept: HkpConceptFrontmatter, *, concept_path: Path
) -> None:
    allowed = set(concept.posture.allowed_consumers)
    forbidden = set(concept.posture.forbidden_consumers)
    if CONSUMER_NAME not in allowed or CONSUMER_NAME in forbidden:
        raise ValueError(
            f"HKP concept posture denies {CONSUMER_NAME}: {concept_path.name}; "
            "next-action: regenerate or purge the bundle before viewing"
        )


def _policy_allowed_output_fields(consumer_row: dict[str, Any]) -> frozenset[str]:
    return frozenset(str(field) for field in consumer_row.get("allowed_fields") or [])


def _policy_forbidden_output_fields(consumer_row: dict[str, Any]) -> frozenset[str]:
    forbidden = {str(field) for field in consumer_row.get("forbidden_fields") or []}
    expanded = set(forbidden)
    for field in forbidden:
        expanded.update(POLICY_FORBIDDEN_FIELD_ALIASES.get(field, ()))
    return frozenset(expanded)


def _apply_consumer_policy(
    value: dict[str, Any],
    *,
    allowed_fields: frozenset[str],
    forbidden_fields: frozenset[str],
) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    for key, item in value.items():
        if key in forbidden_fields or key in FORBIDDEN_REPORT_FIELDS:
            continue
        if key in POLICY_ALLOWLISTED_REPORT_FIELDS and key not in allowed_fields:
            continue
        filtered[key] = item
    return filtered


def _denied_consumers(manifest: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    denied = set(manifest.get("forbidden_consumers") or [])
    for row in policy.get("consumers") or []:
        if isinstance(row, dict) and row.get("default") == "deny":
            denied.add(str(row.get("consumer")))
    return sorted(consumer for consumer in denied if consumer)


def _finding_summary(row: dict[str, Any], *, bundle: Path) -> dict[str, Any]:
    path = str(row.get("path") or "")
    if path:
        path = _safe_bundle_relative_path(path, bundle)
    subject = str(row.get("subject") or path)
    return {
        "severity": str(row.get("severity") or "warning"),
        "code": str(row.get("code") or "unknown"),
        "subject": subject,
        "path": path,
        "message": str(row.get("message") or ""),
    }


def _safe_bundle_relative_path(value: str, bundle: Path) -> str:
    candidate = Path(value)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(bundle.resolve()).as_posix()
    except ValueError:
        return "[outside-bundle-path-redacted]"


def _resolve_bundle_refs(
    bundle_refs: tuple[str | Path, ...], *, shadow_root: Path
) -> tuple[Path, ...]:
    shadow_root = _absolute_without_symlink_resolution(shadow_root)
    if not bundle_refs:
        if not shadow_root.exists():
            return ()
        if not shadow_root.is_dir():
            raise ValueError(
                f"HKP research viewer bundle input must be a directory: {shadow_root}; "
                "next-action: pass a valid HKP shadow root"
            )
        for path in shadow_root.iterdir():
            _reject_symlink_components(
                path, "HKP research viewer bundle input", trusted_root=shadow_root
            )
        return tuple(
            path
            for path in sorted(shadow_root.iterdir(), key=lambda item: item.name)
            if path.is_dir() and (path / "_hkp" / "manifest.yaml").is_file()
        )
    bundles: list[Path] = []
    for ref in bundle_refs:
        raw = Path(ref).expanduser()
        path = raw if raw.is_absolute() else shadow_root / raw
        path = _absolute_without_symlink_resolution(path)
        _ensure_cache_child(path, shadow_root, "HKP research viewer bundle input")
        _assert_bundle_read_boundary(path, shadow_root=shadow_root)
        if not path.is_dir() or not (path / "_hkp" / "manifest.yaml").is_file():
            raise ValueError(
                f"HKP research viewer bundle input is not a bundle directory: {path}; "
                "next-action: pass a bundle id under the HKP shadow root or a valid bundle path"
            )
        bundles.append(path)
    return tuple(bundles)


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# HKP Local Research Viewer Report",
        "",
        f"Generated: `{payload['generated_at']}`",
        f"Consumer: `{payload['consumer']}`",
        f"Support label: `{payload['support_label']}`",
        f"Validator version: `{payload['validator_version']}`",
        "",
        "This report is support-non-authoritative projection state. It is not a",
        "dispatcher input, close/release gate, source authority, runtime loader,",
        "dashboard, Qdrant/RAG input, public export, or provider-spend artifact.",
        "",
        "## Bundles",
        "",
        "| Bundle | Validator | Concepts | Edges | Output tree hash | Denied consumers | Findings |",
        "|---|---|---:|---:|---|---|---:|",
    ]
    for bundle in payload["bundles"]:
        denied = ", ".join(bundle.get("denied_consumers") or [])
        lines.append(
            "| `{bundle_id}` | {validator} | {concepts} | {edges} | `{hash}` | {denied} | {findings} |".format(
                bundle_id=bundle["bundle_id"],
                validator="ok" if bundle["validator_ok"] else "fail",
                concepts=bundle["concept_count"],
                edges=bundle["edge_count"],
                hash=bundle.get("output_tree_hash", "[withheld]"),
                denied=denied,
                findings=bundle.get("finding_count", 0),
            )
        )
    lines.extend(["", "## Rows", ""])
    for bundle in payload["bundles"]:
        lines.extend(
            [
                f"### {bundle['bundle_id']}",
                "",
                "| Concept | Type | Freshness | Source freshness | Privacy / egress | Denied consumers | Findings |",
                "|---|---|---|---|---|---|---:|",
            ]
        )
        for row in bundle["rows"]:
            source_freshness = ", ".join(row.get("source_freshness") or [])
            denied = ", ".join(row.get("denied_consumers") or [])
            privacy = (
                f"{row.get('privacy_class', '[withheld]')} / "
                f"{row.get('egress_state', '[withheld]')}"
            )
            lines.append(
                "| {title} | `{type}` | `{freshness}` | `{source_freshness}` | `{privacy}` | {denied} | {findings} |".format(
                    title=_md_cell(row.get("title", "[withheld]")),
                    type=row.get("type", "[withheld]"),
                    freshness=row.get("freshness_state", "[withheld]"),
                    source_freshness=source_freshness,
                    privacy=privacy,
                    denied=_md_cell(denied),
                    findings=len(row.get("findings") or []),
                )
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _md_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _jsonl_row_count(path: Path, *, trusted_root: Path) -> int:
    _reject_symlink_components(path, "HKP research viewer bundle input", trusted_root=trusted_root)
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _write_text_atomic(path: Path, value: str, *, trusted_root: Path) -> None:
    _reject_symlink_components(path, "HKP research viewer report output", trusted_root=trusted_root)
    tmp_path = path.with_name(f".{path.name}.tmp")
    _reject_symlink_components(
        tmp_path, "HKP research viewer report output", trusted_root=trusted_root
    )
    if tmp_path.exists():
        tmp_path.unlink()
    tmp_path.write_text(value, encoding="utf-8")
    tmp_path.replace(path)


def _safe_report_id(report_id: str) -> str:
    if not _SAFE_REPORT_ID_RE.match(report_id) or ".." in Path(report_id).parts:
        raise ValueError(
            f"report_id is not a safe cache path component: {report_id!r}; next-action: "
            "use letters, digits, dot, underscore, colon, or hyphen"
        )
    return report_id


def _default_report_id(generated_at: str) -> str:
    safe_timestamp = generated_at.replace("-", "").replace(":", "")
    return f"hkp-research-viewer-{safe_timestamp}"


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_cache_child(path: Path, cache_root: Path, label: str) -> None:
    path = _absolute_without_symlink_resolution(path)
    cache_root = _absolute_without_symlink_resolution(cache_root)
    if path != cache_root and not _is_relative_to(path, cache_root):
        raise ValueError(
            f"{label} must be under {cache_root}; next-action: omit the path to use "
            "the default cache location or pass a path under that cache root"
        )
    _reject_symlink_components(path, label, trusted_root=cache_root)


def _assert_bundle_read_boundary(bundle: Path, *, shadow_root: Path) -> None:
    _ensure_cache_child(bundle, shadow_root, "HKP research viewer bundle input")
    for path in (
        bundle,
        bundle / "_hkp",
        bundle / "_hkp" / "manifest.yaml",
        bundle / "_hkp" / "consumer_policy.yaml",
        bundle / "_hkp" / "edges.jsonl",
        bundle / "concepts",
    ):
        _reject_symlink_components(
            path, "HKP research viewer bundle input", trusted_root=shadow_root
        )


def _concept_paths(bundle: Path, *, shadow_root: Path) -> tuple[Path, ...]:
    concepts_root = bundle / "concepts"
    _reject_symlink_components(
        concepts_root, "HKP research viewer bundle input", trusted_root=shadow_root
    )
    if not concepts_root.is_dir():
        return ()
    paths = tuple(sorted(concepts_root.glob("*.md"), key=lambda item: item.name))
    for path in paths:
        _reject_symlink_components(
            path, "HKP research viewer bundle input", trusted_root=shadow_root
        )
    return paths


def _absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _reject_symlink_components(path: Path, label: str, *, trusted_root: Path) -> None:
    path = _absolute_without_symlink_resolution(path)
    current = _absolute_without_symlink_resolution(trusted_root)
    if current.is_symlink():
        raise ValueError(
            f"{label} must not traverse symlink component: {current}; next-action: "
            "remove the symlink or choose a real directory under the Hapax cache root"
        )
    parts = path.relative_to(current).parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(
                f"{label} must not traverse symlink component: {current}; next-action: "
                "remove the symlink or choose a real directory under the Hapax cache root"
            )


def _assert_no_forbidden_report_fields(
    value: Any, *, extra_forbidden: frozenset[str] = frozenset()
) -> None:
    if isinstance(value, dict):
        bad = sorted((FORBIDDEN_REPORT_FIELDS | extra_forbidden) & set(value))
        if bad:
            raise ValueError(
                "HKP research viewer attempted to emit forbidden fields: "
                + ", ".join(bad)
                + "; next-action: keep body/path/secret data out of viewer output"
            )
        for item in value.values():
            _assert_no_forbidden_report_fields(item, extra_forbidden=extra_forbidden)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forbidden_report_fields(item, extra_forbidden=extra_forbidden)
