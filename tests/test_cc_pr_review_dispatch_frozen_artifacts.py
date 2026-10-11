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
import yaml

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


# ── U4b: an accepted frozen artifact is released (receipts minted, dropped to the inbox) ─────────

CASE = "CASE-SYSTEM-INTEGRITY-20260611"
HEAD = "artifact-sha256:" + "a" * 64
ISSUER = "review-team:claude,gemini,muse"


def _dossier(vault: Path, task_id: str, *, verdict: str = "quorum-accept", findings=()) -> None:
    data = {
        "dossier_schema": 1,
        "task_id": task_id,
        "head_sha": HEAD,
        "review_team_verdict": verdict,
        "authority_issuer": ISSUER,
        "reviewers": [
            {"id": "gemini-1", "family": "gemini", "verdict": "accept", "findings": list(findings)}
        ],
    }
    path = vault / "active" / f"{task_id}.review-dossier.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


class _Calls:
    def __init__(
        self, log: list[str], name: str, *, result: Any = None, raises: Exception | None = None
    ):
        self.log, self.name, self.result, self.raises = log, name, result, raises
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        self.log.append(self.name)
        if self.raises is not None:
            raise self.raises
        return self.result


def _release(
    root: Path,
    vault: Path,
    *,
    apply: bool = True,
    fingerprint=None,
    state: str | None = None,
    mint_raises: Exception | None = None,
    drop_raises: Exception | None = None,
):
    order: list[str] = []
    mint = _Calls(
        order,
        "mint",
        result={"head_sha": HEAD, "receipts": {"claim_review_current": {"state": "written"}}},
        raises=mint_raises,
    )
    drop = _Calls(order, "drop", result=root / "inbox" / "entry.json", raises=drop_raises)
    results = dispatch.release_accepted_artifacts(
        vault_root=vault,
        artifact_root=root,
        apply=apply,
        fingerprint=fingerprint or (lambda path, surfaces: FROZEN),
        pipeline_state=lambda path, surfaces: state,
        mint=mint,
        drop=drop,
    )
    return {r["task_id"]: r for r in results}, mint, drop, order


def test_an_accepted_frozen_row_is_minted_then_dropped(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry", findings=[{"severity": "minor", "title": "a nit"}])

    results, mint, drop, order = _release(root, vault)

    assert results["notebook-entry"]["status"] == "released"
    assert order == ["mint", "drop"]
    assert mint.calls == [
        (
            (),
            {
                "task_id": "notebook-entry",
                "artifact": root / ARTIFACT,
                "artifact_root": root,
                "authority_case": CASE,
            },
        )
    ]
    ((drop_args, drop_kwargs),) = drop.calls
    assert drop_args == (root / ARTIFACT,)
    assert drop_kwargs["surfaces"] == ["omg-weblog"]
    assert ISSUER in drop_kwargs["approver"] and HEAD in drop_kwargs["approver"]


def test_an_unreviewed_frozen_row_is_not_released(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)

    results, mint, drop, _ = _release(root, vault)

    assert results["notebook-entry"] == {
        "task_id": "notebook-entry",
        "status": "skipped",
        "reason": "no_review_dossier",
    }
    assert mint.calls == [] and drop.calls == []


@pytest.mark.parametrize("verdict", ["quorum-reject", "no-quorum", "blocked", ""])
def test_a_review_that_did_not_accept_releases_nothing(layout, verdict) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry", verdict=verdict)

    results, mint, drop, _ = _release(root, vault)

    assert results["notebook-entry"]["status"] == "skipped"
    assert results["notebook-entry"]["reason"] == f"verdict:{verdict}"
    assert mint.calls == [] and drop.calls == []


@pytest.mark.parametrize("severity", ["major", "critical", "Major"])
def test_a_major_or_critical_finding_holds_the_row_for_the_seat(layout, severity) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry", findings=[{"severity": severity, "title": "a real problem"}])

    results, mint, drop, _ = _release(root, vault)

    assert results["notebook-entry"]["status"] == "held"
    assert results["notebook-entry"]["reason"] == "major_findings_need_seat_release"
    assert mint.calls == [] and drop.calls == []


@pytest.mark.parametrize("state", ["inbox", "draft", "published", "failed"])
def test_an_artifact_already_in_the_publish_pipeline_is_not_released_again(layout, state) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry")

    results, mint, drop, _ = _release(root, vault, state=state)

    assert results["notebook-entry"]["status"] == "skipped"
    assert results["notebook-entry"]["reason"] == f"already_{state}"
    assert mint.calls == [] and drop.calls == []


def test_a_mint_refusal_drops_nothing(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry")

    results, mint, drop, _ = _release(
        root, vault, mint_raises=RuntimeError("mint_public_gate_artifact_changed:ENTRY.md")
    )

    assert results["notebook-entry"]["status"] == "held"
    assert (
        results["notebook-entry"]["reason"]
        == "mint_hold:mint_public_gate_artifact_changed:ENTRY.md"
    )
    assert len(mint.calls) == 1 and drop.calls == []


def test_a_drop_refusal_is_held_and_named(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry")

    results, mint, drop, _ = _release(
        root, vault, drop_raises=ValueError("publication_gate_receipt_unbound")
    )

    assert results["notebook-entry"]["status"] == "held"
    assert results["notebook-entry"]["reason"] == "drop_refused:publication_gate_receipt_unbound"
    assert len(mint.calls) == 1 and len(drop.calls) == 1


def test_without_apply_nothing_is_minted_or_dropped(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry")

    results, mint, drop, _ = _release(root, vault, apply=False)

    assert results["notebook-entry"]["status"] == "would_release"
    assert mint.calls == [] and drop.calls == []


def test_a_row_that_is_not_frozen_is_never_released(layout) -> None:
    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry")

    results, mint, drop, _ = _release(root, vault, fingerprint=lambda path, surfaces: "0" * 64)

    assert results["notebook-entry"]["reason"] == "not_frozen"
    assert mint.calls == [] and drop.calls == []


def test_the_defaults_are_the_publishers_own_check_mint_and_drop(
    layout, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import mint_public_gate_receipts
    import publish_vault_artifact

    root, vault = layout
    _row(vault, "notebook-entry", authority_case=CASE)
    _dossier(vault, "notebook-entry")
    state_root = tmp_path / "state"
    seen: dict[str, Any] = {}

    def pipeline_state(path: Path, surfaces: list[str], *, state_root: Path) -> None:
        seen["pipeline_state"] = (path, surfaces, state_root)

    def mint(**kwargs: Any) -> dict[str, Any]:
        seen["mint"] = kwargs
        return {"receipts": {}}

    def drop(path: Path, *, surfaces: list[str], approver: str, state_root: Path) -> Path:
        seen["drop"] = (path, surfaces, state_root)
        return state_root / "publish" / "inbox" / "entry.json"

    monkeypatch.setattr(publish_vault_artifact, "pipeline_state", pipeline_state)
    monkeypatch.setattr(publish_vault_artifact, "drop_to_inbox", drop)
    monkeypatch.setattr(mint_public_gate_receipts, "mint", mint)

    (result,) = dispatch.release_accepted_artifacts(
        vault_root=vault,
        artifact_root=root,
        apply=True,
        state_root=state_root,
        fingerprint=lambda path, surfaces: FROZEN,
    )

    assert result["status"] == "released"
    assert seen["pipeline_state"] == (root / ARTIFACT, ["omg-weblog"], state_root)
    assert seen["mint"]["receipt_root"] == publish_vault_artifact.PUBLIC_GATE_RECEIPT_ROOTS[0]
    assert seen["mint"]["task_id"] == "notebook-entry"
    assert seen["drop"] == (root / ARTIFACT, ["omg-weblog"], state_root)


def test_the_command_line_releases_accepted_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> list[dict[str, Any]]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(dispatch, "release_accepted_artifacts", fake)

    assert dispatch.main(["--release-accepted", "--apply"]) == 0
    assert seen["apply"] is True


def test_the_unit_releases_after_the_review_scan() -> None:
    service = (UNITS_DIR / "hapax-artifact-review-dispatch.service").read_text(encoding="utf-8")
    starts = [line for line in service.splitlines() if line.startswith("ExecStart=")]
    assert len(starts) == 2
    assert starts[0].endswith("--frozen-artifacts --apply")
    assert starts[1].endswith("--release-accepted --apply")


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
