"""cc-pr-review-dispatch --frozen-artifacts: a frozen publication artifact is reviewed without a seat.

A publication row declares its artifact frozen by naming the file in ``artifact:`` and recording the
publisher's fingerprint of it in ``artifact_fingerprint``. The scan reviews exactly those rows and
skips every other publication row with its reason; review_artifact keeps its own skip of a dossier
that is fresh for the bytes, so a frozen row is reviewed once per head.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO_ROOT / "scripts"
UNITS_DIR = REPO_ROOT / "systemd" / "units"
for entry in (REPO_ROOT, _SCRIPTS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def _load(name: str, filename: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dispatch = _load("cc_pr_review_dispatch", "cc-pr-review-dispatch.py")

ARTIFACT = "30-areas/hapax/frame/notebook/ENTRY.md"
FROZEN = "f" * 64


def _row(vault: Path, task_id: str, **fields: Any) -> Path:
    front: dict[str, Any] = {
        "type": "cc-task",
        "task_id": task_id,
        "status": "claimed",
        "kind": "publication",
        "pr": None,
        "artifact": ARTIFACT,
        "artifact_fingerprint": FROZEN,
        "target_surfaces": ["omg-weblog"],
    }
    front.update(fields)
    lines = ["---"]
    for key, value in front.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"- {item}" for item in value)
        elif value is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f"{key}: {value}")
    lines += ["---", "", f"# {task_id}", ""]
    note = vault / "active" / f"{task_id}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("\n".join(lines), encoding="utf-8")
    return note


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], dict[str, Any]]] = []

    def __call__(self, task_id: str, artifact_paths: list[Any], **kwargs: Any) -> dict[str, Any]:
        self.calls.append((task_id, [str(p) for p in artifact_paths], kwargs))
        return {"status": "dispatched", "task_id": task_id}


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "Personal"
    vault = root / "20-projects" / "hapax-cc-tasks"
    artifact = root / ARTIFACT
    artifact.parent.mkdir(parents=True)
    artifact.write_text("---\ntitle: Entry\n---\nBody.\n", encoding="utf-8")
    # A real file just outside the root: only the escape guard keeps "../outside.md" out.
    (tmp_path / "outside.md").write_text("---\ntitle: Outside\n---\nBody.\n", encoding="utf-8")
    return root, vault


def _scan(root: Path, vault: Path, *, fingerprint=None, review=None, apply: bool = True):
    review = review or _Recorder()
    results = dispatch.review_frozen_artifacts(
        vault_root=vault,
        artifact_root=root,
        apply=apply,
        fingerprint=fingerprint or (lambda path, surfaces: FROZEN),
        review=review,
    )
    return {r["task_id"]: r for r in results}, review


def test_a_frozen_publication_row_is_reviewed_with_exactly_its_artifact(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry")

    results, review = _scan(root, vault)

    assert results["notebook-entry"]["status"] == "dispatched"
    assert [(task, paths) for task, paths, _ in review.calls] == [("notebook-entry", [ARTIFACT])]
    assert review.calls[0][2]["apply"] is True


def test_the_fingerprint_is_taken_over_the_rows_target_surfaces(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", target_surfaces=["omg-weblog", "bluesky-post"])
    seen: list[tuple[Path, list[str]]] = []

    def fingerprint(path: Path, surfaces: list[str]) -> str:
        seen.append((path, surfaces))
        return FROZEN

    _scan(root, vault, fingerprint=fingerprint)

    assert seen == [(root / ARTIFACT, ["omg-weblog", "bluesky-post"])]


def test_bytes_that_differ_from_the_declared_freeze_are_not_reviewed(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry")

    results, review = _scan(root, vault, fingerprint=lambda path, surfaces: "0" * 64)

    assert results["notebook-entry"] == {
        "task_id": "notebook-entry",
        "status": "skipped",
        "reason": "not_frozen",
    }
    assert review.calls == []


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"pr": 5101}, "pr_bound"),
        ({"status": "done"}, "status:done"),
        ({"status": "offered"}, "status:offered"),
        ({"artifact": "30-areas/hapax/frame/notebook/MISSING.md"}, "artifact_not_a_file"),
        ({"artifact": "../outside.md"}, "artifact_not_a_file"),
        # An absolute spelling of the real artifact is refused, never reinterpreted under the root.
        ({"artifact": "/" + ARTIFACT}, "artifact_not_a_file"),
        ({"artifact": "[[ENTRY]]"}, "artifact_not_a_file"),
        ({"artifact_fingerprint": "null"}, "no_artifact_fingerprint"),
        ({"target_surfaces": "null"}, "no_target_surfaces"),
    ],
)
def test_a_publication_row_that_is_not_frozen_is_skipped_with_its_reason(
    layout, fields, reason
) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", **fields)

    results, review = _scan(root, vault)

    assert results["notebook-entry"]["status"] == "skipped"
    assert results["notebook-entry"]["reason"] == reason
    assert review.calls == []


def test_a_row_that_is_not_a_publication_is_ignored(layout) -> None:
    root, vault = layout
    _row(vault, "some-implementation-row", kind="implementation")

    results, review = _scan(root, vault)

    assert results == {}
    assert review.calls == []


def test_a_fingerprint_that_cannot_be_taken_is_a_skip_not_a_review(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry")

    def broken(path: Path, surfaces: list[str]) -> str:
        raise ValueError("Publication-Allowed must be explicitly true")

    results, review = _scan(root, vault, fingerprint=broken)

    assert results["notebook-entry"]["status"] == "skipped"
    assert results["notebook-entry"]["reason"].startswith("fingerprint_unavailable:")
    assert review.calls == []


def test_the_command_line_scans_frozen_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> list[dict[str, Any]]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(dispatch, "review_frozen_artifacts", fake)

    assert dispatch.main(["--frozen-artifacts", "--apply"]) == 0
    assert seen["apply"] is True


def test_the_scan_runs_in_its_own_unit_with_the_review_environment_only() -> None:
    service = (UNITS_DIR / "hapax-artifact-review-dispatch.service").read_text(encoding="utf-8")
    # Directives only: the unit's comments name the file it must never load.
    lines = [line for line in service.splitlines() if line and not line.startswith("#")]
    assert "Type=oneshot" in lines
    env_files = [line for line in lines if line.startswith("EnvironmentFile=")]
    assert env_files == ["EnvironmentFile=-/run/user/%U/hapax-public-gate-authority.env"]
    assert all("hapax-secrets.env" not in line for line in lines)
    assert any(
        line.startswith("ExecStart=") and "--frozen-artifacts --apply" in line for line in lines
    )
    timer = (UNITS_DIR / "hapax-artifact-review-dispatch.timer").read_text(encoding="utf-8")
    assert timer.startswith("# Hapax-Auto-Enable: true\n")
    assert "Unit=hapax-artifact-review-dispatch.service" in timer.splitlines()
    assert "WantedBy=timers.target" in timer.splitlines()
