"""Tests for ``scripts/hapax-invariant-touch-report`` + ``config/invariant-manifest.yaml``.

Phase 0.3 (routing-phase0-invariant-manifest-20260609): protected invariants
codified as a machine-readable manifest (invariant -> path globs -> checker
command) plus a pre-review touch report that says which invariants a diff/PR
touches. Fail-closed: unresolvable diff paths and dead manifest globs are
flagged, never silently dropped.

Operator inflection 2026-06-10: a third class ``operator_coupled`` (surfaces
whose correctness depends on continuous operator aesthetic/directorial
judgment) with policy ``dispatch_mode: interactive_only``, ``auto_merge:
never``, ``evidence: visual``; the touch report lists those touches in their
own section.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-invariant-touch-report"
MANIFEST_PATH = REPO_ROOT / "config" / "invariant-manifest.yaml"


def _load_module() -> ModuleType:
    if "hapax_invariant_touch_report" in sys.modules:
        return sys.modules["hapax_invariant_touch_report"]
    loader = importlib.machinery.SourceFileLoader("hapax_invariant_touch_report", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hapax_invariant_touch_report"] = module
    loader.exec_module(module)
    return module


itr = _load_module()


# ---------------------------------------------------------------------------
# Manifest: schema + acceptance coverage
# ---------------------------------------------------------------------------


def test_manifest_loads_and_is_fail_closed() -> None:
    raw = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["unknown_path_policy"] == "flag"


def test_manifest_module_loader_validates() -> None:
    manifest = itr.load_manifest(MANIFEST_PATH)
    assert manifest.invariants, "manifest must declare at least one invariant"
    for inv in manifest.invariants:
        assert inv.globs, f"invariant {inv.id} has no globs"


@pytest.mark.parametrize(
    ("sample_path", "expected_invariant"),
    [
        ("config/pipewire/hapax-broadcast-master.conf", "audio-routing"),
        ("config/wireplumber/98-hapax-link-deny.conf", "audio-routing"),
        ("scripts/hapax-audio-routing-check", "audio-routing"),
        ("axioms/registry.yaml", "axiom-registry"),
        ("shared/governance/consent.py", "consent-governance"),
        (
            "config/publication-hardening/known-entities.yaml",
            "publication-hardening",
        ),
        # self-protection: manifest rot is governance rot
        ("config/invariant-manifest.yaml", "invariant-manifest"),
        ("scripts/hapax-invariant-touch-report", "invariant-manifest"),
    ],
)
def test_acceptance_coverage(sample_path: str, expected_invariant: str) -> None:
    """Manifest covers at least: audio routing, axiom registry,
    consent/governance, pipewire configs, publication-hardening."""
    manifest = itr.load_manifest(MANIFEST_PATH)
    touches = itr.classify_paths(manifest, [sample_path])
    touched_ids = {t.invariant.id for t in touches}
    assert expected_invariant in touched_ids


def test_operator_coupled_class_policy() -> None:
    """Operator directive 2026-06-10: interactive-only, never auto-merged,
    visual evidence."""
    manifest = itr.load_manifest(MANIFEST_PATH)
    policy = manifest.classes["operator_coupled"].policy
    assert policy["dispatch_mode"] == "interactive_only"
    assert policy["auto_merge"] == "never"
    assert policy["evidence"] == "visual"


@pytest.mark.parametrize(
    "sample_path",
    [
        "agents/studio_compositor/compositor.py",
        "agents/studio_compositor/segment_director.py",
        "agents/screwm_self_perception/analyzer.py",
        "agents/scribble_strip_ward/__init__.py",
        "agents/parametric_modulation_heartbeat/heartbeat.py",
        "config/darkplaces/v4l2loopback-hapax.conf",
        "config/screwm-quake-surface-contracts.json",
        "config/compositor-layouts/default.json",
        "config/layouts/garage-door.json",
        "assets/quake/maps/screwm.map",
        "config/ward_enhancement_profiles.yaml",
    ],
)
def test_operator_coupled_globs_cover_directive_surfaces(sample_path: str) -> None:
    manifest = itr.load_manifest(MANIFEST_PATH)
    touches = itr.classify_paths(manifest, [sample_path])
    classes = {t.invariant.cls for t in touches}
    assert "operator_coupled" in classes, f"{sample_path} must classify as operator_coupled"


def test_manifest_globs_all_resolve_in_repo_tree() -> None:
    """Fail-closed manifest health: a glob matching nothing in the repo means
    a protected surface moved and protection silently lapsed."""
    manifest = itr.load_manifest(MANIFEST_PATH)
    repo_paths = (
        subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    dead = itr.dead_globs(manifest, repo_paths)
    assert dead == [], f"manifest globs match nothing in repo: {dead}"


def test_manifest_checkers_exist() -> None:
    """Every checker-bearing invariant references scripts/tests that exist."""
    manifest = itr.load_manifest(MANIFEST_PATH)
    missing = itr.missing_checker_paths(manifest, REPO_ROOT)
    assert missing == [], f"checker references missing paths: {missing}"


def test_command_classes_require_checker(tmp_path: Path) -> None:
    """protected_invariant without a checker is a manifest error (fail-closed)."""
    bad = {
        "schema_version": 1,
        "unknown_path_policy": "flag",
        "classes": {"protected_invariant": {"description": "x"}},
        "invariants": [
            {
                "id": "no-checker",
                "class": "protected_invariant",
                "description": "x",
                "globs": ["config/**"],
                "checker": None,
            }
        ],
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(itr.ManifestError):
        itr.load_manifest(path)


def test_unknown_class_is_manifest_error(tmp_path: Path) -> None:
    bad = {
        "schema_version": 1,
        "unknown_path_policy": "flag",
        "classes": {"protected_invariant": {"description": "x"}},
        "invariants": [
            {
                "id": "mystery",
                "class": "not_a_class",
                "description": "x",
                "globs": ["config/**"],
                "checker": "scripts/x",
            }
        ],
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(itr.ManifestError):
        itr.load_manifest(path)


# ---------------------------------------------------------------------------
# Glob semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("glob", "path", "matches"),
    [
        ("config/pipewire/**", "config/pipewire/a.conf", True),
        ("config/pipewire/**", "config/pipewire/golden/b.conf", True),
        ("config/pipewire/**", "config/pipewireX/a.conf", False),
        ("config/screwm-*.json", "config/screwm-quake-media-mounts.json", True),
        ("config/screwm-*.json", "config/sub/screwm-x.json", False),
        ("CLAUDE.md", "CLAUDE.md", True),
        ("CLAUDE.md", "vscode/CLAUDE.md", False),
        ("**/CLAUDE.md", "vscode/CLAUDE.md", True),
        ("**/CLAUDE.md", "CLAUDE.md", True),
        ("scripts/hapax-audio-routing-check", "scripts/hapax-audio-routing-check", True),
    ],
)
def test_glob_semantics(glob: str, path: str, matches: bool) -> None:
    assert itr.path_matches(path, glob) is matches


# ---------------------------------------------------------------------------
# Diff parsing (fail-closed)
# ---------------------------------------------------------------------------

FIXTURE_DIFF_AUDIO = """\
diff --git a/config/pipewire/hapax-broadcast-master.conf b/config/pipewire/hapax-broadcast-master.conf
index 1111111..2222222 100644
--- a/config/pipewire/hapax-broadcast-master.conf
+++ b/config/pipewire/hapax-broadcast-master.conf
@@ -1,3 +1,4 @@
 context.modules = [
+    # comment
 ]
diff --git a/README.md b/README.md
index 3333333..4444444 100644
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 # readme
+more
"""

FIXTURE_DIFF_NEW_AND_DELETED = """\
diff --git a/agents/studio_compositor/new_ward.py b/agents/studio_compositor/new_ward.py
new file mode 100644
index 0000000..5555555
--- /dev/null
+++ b/agents/studio_compositor/new_ward.py
@@ -0,0 +1 @@
+x = 1
diff --git a/axioms/old.yaml b/axioms/old.yaml
deleted file mode 100644
index 6666666..0000000
--- a/axioms/old.yaml
+++ /dev/null
@@ -1 +0,0 @@
-gone: true
"""

FIXTURE_DIFF_RENAME = """\
diff --git a/shared/governance/consent.py b/shared/governance/consent_v2.py
similarity index 98%
rename from shared/governance/consent.py
rename to shared/governance/consent_v2.py
index 7777777..8888888 100644
--- a/shared/governance/consent.py
+++ b/shared/governance/consent_v2.py
@@ -1 +1 @@
-old
+new
"""

FIXTURE_DIFF_MALFORMED_HEADER = """\
diff --git mangled-header-no-paths
index 9999999..aaaaaaa 100644
@@ -1 +1 @@
-x
+y
"""


def test_paths_from_diff_basic() -> None:
    paths, unresolved = itr.paths_from_diff(FIXTURE_DIFF_AUDIO)
    assert "config/pipewire/hapax-broadcast-master.conf" in paths
    assert "README.md" in paths
    assert unresolved == []


def test_paths_from_diff_new_and_deleted() -> None:
    paths, unresolved = itr.paths_from_diff(FIXTURE_DIFF_NEW_AND_DELETED)
    assert "agents/studio_compositor/new_ward.py" in paths
    assert "axioms/old.yaml" in paths
    assert "/dev/null" not in paths
    assert unresolved == []


def test_paths_from_diff_rename_keeps_both_sides() -> None:
    paths, unresolved = itr.paths_from_diff(FIXTURE_DIFF_RENAME)
    assert "shared/governance/consent.py" in paths
    assert "shared/governance/consent_v2.py" in paths
    assert unresolved == []


def test_paths_from_diff_flags_malformed_header() -> None:
    """Fail-closed: a diff header we cannot resolve is flagged, not dropped."""
    paths, unresolved = itr.paths_from_diff(FIXTURE_DIFF_MALFORMED_HEADER)
    assert paths == []
    assert unresolved, "malformed header must land in unresolved"


# ---------------------------------------------------------------------------
# Report content
# ---------------------------------------------------------------------------


def test_report_operator_coupled_has_own_section() -> None:
    manifest = itr.load_manifest(MANIFEST_PATH)
    report = itr.build_report(
        manifest,
        paths=[
            "agents/studio_compositor/compositor.py",
            "config/pipewire/hapax-broadcast-master.conf",
            "README.md",
        ],
        unresolved=[],
    )
    text = itr.render_text(report)
    assert "OPERATOR-COUPLED" in text
    assert "dispatch_mode: interactive_only" in text
    assert "auto_merge: never" in text
    assert "evidence: visual" in text
    # protected invariant section names the checker command
    assert "audio-routing" in text
    assert "scripts/hapax-audio-routing-check" in text


def test_report_json_format() -> None:
    manifest = itr.load_manifest(MANIFEST_PATH)
    report = itr.build_report(
        manifest,
        paths=["axioms/registry.yaml"],
        unresolved=["???bad-line"],
    )
    payload = json.loads(itr.render_json(report))
    touched_ids = {t["invariant"] for t in payload["touches"]}
    assert "axiom-registry" in touched_ids
    assert payload["unresolved_paths"] == ["???bad-line"]
    by_id = {t["invariant"]: t for t in payload["touches"]}
    assert by_id["axiom-registry"]["class"] == "governance_protected"
    assert by_id["axiom-registry"]["checker"]


def test_report_clean_diff_has_no_touches() -> None:
    manifest = itr.load_manifest(MANIFEST_PATH)
    report = itr.build_report(manifest, paths=["README.md"], unresolved=[])
    assert not report.touches


# ---------------------------------------------------------------------------
# CLI behavior (advisory vs --strict, fail-closed exits)
# ---------------------------------------------------------------------------


def _run_cli(
    *args: str, stdin: str = "", manifest: Path | None = None
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT)]
    if manifest is not None:
        cmd += ["--manifest", str(manifest)]
    cmd += list(args)
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, cwd=REPO_ROOT)


def test_cli_advisory_exit_zero_on_touch() -> None:
    result = _run_cli(stdin=FIXTURE_DIFF_AUDIO)
    assert result.returncode == 0, result.stderr
    assert "audio-routing" in result.stdout


def test_cli_strict_exit_nonzero_on_touch() -> None:
    result = _run_cli("--strict", stdin=FIXTURE_DIFF_AUDIO)
    assert result.returncode == 1
    assert "audio-routing" in result.stdout


def test_cli_strict_exit_zero_when_clean() -> None:
    clean_diff = FIXTURE_DIFF_AUDIO.split("diff --git a/README.md")[1]
    clean_diff = "diff --git a/README.md" + clean_diff
    result = _run_cli("--strict", stdin=clean_diff)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_strict_exit_nonzero_on_unresolved() -> None:
    """Fail-closed: unresolved paths are a strict violation even with no touch."""
    result = _run_cli("--strict", stdin=FIXTURE_DIFF_MALFORMED_HEADER)
    assert result.returncode == 1
    assert "unresolved" in result.stdout.lower()


def test_cli_empty_stdin_fails_closed() -> None:
    result = _run_cli(stdin="")
    assert result.returncode == 3


def test_cli_missing_manifest_fails_closed(tmp_path: Path) -> None:
    result = _run_cli(stdin=FIXTURE_DIFF_AUDIO, manifest=tmp_path / "nope.yaml")
    assert result.returncode == 3


def test_paths_from_pr_uses_gh_name_only() -> None:
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> str:
        calls.append(cmd)
        return "config/pipewire/a.conf\nREADME.md\n"

    paths = itr.paths_from_pr(4321, runner=fake_runner)
    assert paths == ["config/pipewire/a.conf", "README.md"]
    assert calls and "4321" in calls[0]
