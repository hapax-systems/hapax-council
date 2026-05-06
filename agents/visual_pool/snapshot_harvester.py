"""Harvest compositor camera snapshots into the local visual pool.

The Sierpinski renderer reads broadcast-safe local assets from
``~/hapax-pool/visual/operator-cuts``. This module copies current compositor
camera snapshots from ``/dev/shm/hapax-compositor`` into that tier and writes
strict ``VisualPoolSidecar`` YAML beside each frame.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from agents.visual_pool.repository import (
    DEFAULT_VISUAL_POOL_ROOT,
    LocalVisualPool,
    VisualPoolSidecar,
)

DEFAULT_COMPOSITOR_SHM_DIR = Path("/dev/shm/hapax-compositor")
OPERATOR_CUTS_DIR = "operator-cuts"
SNAPSHOT_NAME_RE = re.compile(r"^(?P<camera>c920|brio)-(?P<role>[a-z0-9_.-]+)\.jpg$")


@dataclass(frozen=True)
class SnapshotHarvestResult:
    """One harvested compositor snapshot."""

    source_path: Path
    asset_path: Path
    sidecar_path: Path
    sha256: str
    copied: bool
    sidecar_written: bool
    dry_run: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("source_path", "asset_path", "sidecar_path"):
            data[key] = str(data[key])
        return data


def discover_snapshot_sources(shm_dir: Path | str = DEFAULT_COMPOSITOR_SHM_DIR) -> list[Path]:
    """Return current BRIO/C920 compositor JPEG snapshots."""

    root = Path(shm_dir).expanduser()
    if not root.is_dir():
        return []
    sources: list[Path] = []
    for path in sorted(root.iterdir()):
        if path.is_file() and SNAPSHOT_NAME_RE.match(path.name):
            sources.append(path)
    return sources


def harvest_snapshots(
    *,
    shm_dir: Path | str = DEFAULT_COMPOSITOR_SHM_DIR,
    pool_root: Path | str = DEFAULT_VISUAL_POOL_ROOT,
    dry_run: bool = False,
    force: bool = False,
) -> list[SnapshotHarvestResult]:
    """Copy current compositor snapshots into ``operator-cuts`` with sidecars."""

    pool = LocalVisualPool(pool_root)
    sources = discover_snapshot_sources(shm_dir)
    if not sources:
        return []

    if not dry_run:
        pool.ensure_layout()
    dest_dir = pool.root / OPERATOR_CUTS_DIR

    results: list[SnapshotHarvestResult] = []
    for source_path in sources:
        match = SNAPSHOT_NAME_RE.match(source_path.name)
        if match is None:
            continue

        asset_path = dest_dir / source_path.name
        sidecar_path = asset_path.with_suffix(".yaml")
        source_digest = _sha256(source_path)
        should_copy = force or not asset_path.exists() or _sha256(asset_path) != source_digest
        sidecar = _build_sidecar(
            source_path, source_digest, match.group("camera"), match.group("role")
        )
        sidecar_payload = _sidecar_yaml(sidecar)
        sidecar_written = (
            force
            or not sidecar_path.exists()
            or (sidecar_path.read_text(encoding="utf-8") != sidecar_payload)
        )

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if should_copy:
                _atomic_copy(source_path, asset_path)
            if sidecar_written:
                _atomic_write_text(sidecar_path, sidecar_payload)

        results.append(
            SnapshotHarvestResult(
                source_path=source_path,
                asset_path=asset_path,
                sidecar_path=sidecar_path,
                sha256=source_digest,
                copied=should_copy,
                sidecar_written=sidecar_written,
                dry_run=dry_run,
            )
        )

    return results


def _build_sidecar(
    source_path: Path,
    source_digest: str,
    camera: str,
    role: str,
) -> VisualPoolSidecar:
    role_tag = _tag(role)
    return VisualPoolSidecar(
        content_risk="tier_0_owned",
        source=OPERATOR_CUTS_DIR,
        broadcast_safe=True,
        aesthetic_tags=[
            "sierpinski",
            "operator-cut",
            "camera-snapshot",
            camera,
            role_tag,
        ],
        motion_density=0.15,
        color_palette=[],
        duration_seconds=0.0,
        title=f"{camera.upper()} {role_tag.replace('-', ' ')} snapshot",
        license="operator-owned",
        provenance_url=f"file://{source_path}",
        homage_class="sierpinski",
        motion_profile="static",
        public_posture="live",
        wcs_evidence_refs=(
            f"shm:{source_path}",
            f"sha256:{source_digest}",
        ),
        routable_destinations=("sierpinski",),
    )


def _sidecar_yaml(sidecar: VisualPoolSidecar) -> str:
    payload = sidecar.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(payload, sort_keys=False)


def _atomic_copy(source_path: Path, dest_path: Path) -> None:
    tmp_path = dest_path.with_name(f".{dest_path.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source_path, tmp_path)
        os.replace(tmp_path, dest_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tag(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower()).strip("-")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visual-pool-snapshot-harvester.py",
        description="Harvest /dev/shm compositor snapshots into ~/hapax-pool/visual/operator-cuts.",
    )
    parser.add_argument(
        "--shm-dir",
        type=Path,
        default=Path(os.environ.get("HAPAX_COMPOSITOR_SHM_DIR", DEFAULT_COMPOSITOR_SHM_DIR)),
    )
    parser.add_argument(
        "--pool-root",
        type=Path,
        default=Path(os.environ.get("HAPAX_VISUAL_POOL_ROOT", DEFAULT_VISUAL_POOL_ROOT)),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    results = harvest_snapshots(
        shm_dir=args.shm_dir,
        pool_root=args.pool_root,
        dry_run=args.dry_run,
        force=args.force,
    )
    if args.json_output:
        print(json.dumps([result.to_json_dict() for result in results], indent=2))
    elif not results:
        print(f"no compositor snapshots found in {args.shm_dir}")
    else:
        copied = sum(1 for result in results if result.copied)
        sidecars = sum(1 for result in results if result.sidecar_written)
        print(
            f"harvested {len(results)} compositor snapshots "
            f"({copied} copied, {sidecars} sidecars written) into {args.pool_root}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
