"""Canary battery for the consumer-existence gate (UNWIRED-WORK / A1 class closure).

Per the anti-theses of the failure-taxonomy spec (2026-06-11):
  (i)  formalism shape matters — the gate must be EFFECT-BASED (AST /
       structured parse), so evasion canaries assert that comments,
       docstrings, test-only consumers, and dynamic names cannot satisfy it;
  (ii) formalism composition is a failure surface — deadlock canaries assert
       a sanctioned exit always exists (same-PR consumer, reasoned allowlist,
       no-producer pass-through).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check-producer-consumers.py"


def load_gate_module():
    spec = importlib.util.spec_from_file_location("check_producer_consumers", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── Unit layer: effect-based detection primitives ─────────────────────


def test_find_collection_writes_literal_kwarg_and_positional() -> None:
    gate = load_gate_module()
    source = (
        "client.upsert(collection_name='affordances', points=pts)\n"
        "client.create_collection('episodes', vectors_config=cfg)\n"
    )
    writes = gate.find_collection_writes(source, Path("shared/x.py"))
    found = {(w.collection, w.method) for w in writes}
    assert ("affordances", "upsert") in found
    assert ("episodes", "create_collection") in found


def test_find_collection_writes_resolves_module_constant() -> None:
    gate = load_gate_module()
    source = (
        "COLLECTION_NAME = 'spiral-consequences'\n"
        "def persist(points):\n"
        "    get_qdrant().upsert(collection_name=COLLECTION_NAME, points=points)\n"
    )
    writes = gate.find_collection_writes(source, Path("shared/x.py"))
    assert {(w.collection, w.method) for w in writes} == {("spiral-consequences", "upsert")}


def test_find_collection_writes_dynamic_name_is_unresolvable() -> None:
    gate = load_gate_module()
    source = (
        "def persist(name, points):\n"
        "    client.upsert(collection_name=f'{name}-suffix', points=points)\n"
    )
    writes = gate.find_collection_writes(source, Path("shared/x.py"))
    assert len(writes) == 1
    assert writes[0].collection is None  # fail-closed downstream


def test_find_collection_reads_ignores_comments_and_docstrings() -> None:
    """Evasion canary (unit layer): prose mentions are not consumers."""
    gate = load_gate_module()
    source = (
        '"""This module reads the affordances collection."""\n'
        "# client.search(collection_name='affordances')\n"
        "x = 1\n"
    )
    assert gate.find_collection_reads(source, Path("shared/x.py")) == set()

    real = "client.query_points(collection_name='affordances', query=q)\n"
    assert gate.find_collection_reads(real, Path("shared/y.py")) == {"affordances"}


def test_is_agent_entry() -> None:
    gate = load_gate_module()
    main_guard = "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
    assert gate.is_agent_entry(Path("agents/foo/__main__.py"), "pass\n") is True
    assert gate.is_agent_entry(Path("agents/foo.py"), main_guard) is True
    assert gate.is_agent_entry(Path("agents/foo/helpers.py"), "x = 1\n") is False
    assert gate.is_agent_entry(Path("shared/foo.py"), main_guard) is False


def test_unit_references_module_only_via_exec_directives() -> None:
    """Evasion canary (unit layer): comments and Description= are not runners."""
    gate = load_gate_module()
    wired = "[Service]\nExecStart=/home/hapax/.local/bin/uv run python -m agents.foo --auto\n"
    comment_only = "[Service]\n# ExecStart=python -m agents.foo\nExecStart=/bin/true\n"
    description_only = (
        "[Unit]\nDescription=runs agents.foo nightly\n[Service]\nExecStart=/bin/true\n"
    )
    assert gate.unit_references_module(wired, "agents.foo") is True
    assert gate.unit_references_module(comment_only, "agents.foo") is False
    assert gate.unit_references_module(description_only, "agents.foo") is False


def test_find_publisher_surfaces() -> None:
    gate = load_gate_module()
    source = (
        "class MastoPublisher(BasePublisher):\n"
        "    SURFACE = 'mastodon-post'\n"
        "\n"
        "class AbstractKit(BasePublisher):\n"
        "    pass\n"
        "\n"
        "class CatalogEntry(_PublisherModel):\n"
        "    SURFACE = 'not-a-surface'\n"
    )
    surfaces = gate.find_publisher_surfaces(source, Path("shared/x.py"))
    by_class = {s.class_name: s.surface for s in surfaces}
    assert by_class.get("MastoPublisher") == "mastodon-post"
    # abstract intermediate: detected but with no surface slug
    assert by_class.get("AbstractKit") in (None, "")
    # pydantic-model base is not a publisher surface
    assert "CatalogEntry" not in by_class


def test_allowlist_entry_requires_reason(tmp_path: Path) -> None:
    """Deadlock canary precondition: the sanctioned exit is governed, not silent."""
    gate = load_gate_module()
    path = tmp_path / "allow.json"
    path.write_text(json.dumps({"entries": [{"pattern": "collection:foo"}]}))
    with pytest.raises(gate.AllowlistError):
        gate.load_allowlist(path)

    path.write_text(
        json.dumps({"entries": [{"pattern": "collection:foo", "reason": "dead-drop by design"}]})
    )
    entries = gate.load_allowlist(path)
    assert len(entries) == 1


# ── End-to-end layer: sandbox-merge canaries (fixture git repos) ──────


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=canary",
        "-c",
        "user.email=canary@test",
        "commit",
        "-q",
        "-m",
        message,
        "--no-verify",
    )
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("fixture\n")
    _commit_all(repo, "base")
    return repo


def run_gate(repo: Path, base_sha: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--diff-range", f"{base_sha}..HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_red_canary_collection_writer_without_reader_blocks(repo: Path) -> None:
    """The §4.1 class canary: merge a no-consumer producer → gate must block."""
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "shared" / "writer.py").write_text(
        "client.upsert(collection_name='orphan-patterns', points=[])\n"
    )
    _commit_all(repo, "add writer")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "orphan-patterns" in result.stdout


def test_green_canary_same_pr_reader_passes(repo: Path) -> None:
    """Deadlock canary: a consumer wired in the same PR is a sanctioned path."""
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "shared" / "writer.py").write_text(
        "client.upsert(collection_name='wired-patterns', points=[])\n"
    )
    (repo / "shared" / "reader.py").write_text(
        "hits = client.search(collection_name='wired-patterns', query_vector=v)\n"
    )
    _commit_all(repo, "add writer+reader")
    result = run_gate(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_evasion_canary_test_only_reader_blocks(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "tests").mkdir()
    (repo / "shared" / "writer.py").write_text(
        "client.upsert(collection_name='test-consumed', points=[])\n"
    )
    (repo / "tests" / "test_writer.py").write_text(
        "hits = client.search(collection_name='test-consumed', query_vector=v)\n"
    )
    _commit_all(repo, "add writer + test-only reader")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "test-consumed" in result.stdout


def test_evasion_canary_prose_mention_blocks(repo: Path) -> None:
    """A regex gate would pass this; the effect-based gate must not."""
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "shared" / "writer.py").write_text(
        "client.upsert(collection_name='prose-only', points=[])\n"
    )
    (repo / "shared" / "consumer_doc.py").write_text(
        '"""Consumer: reads prose-only via client.search(collection_name=\'prose-only\')."""\n'
        "# client.scroll(collection_name='prose-only')\n"
        "x = 1\n"
    )
    _commit_all(repo, "add writer + prose-only 'consumer'")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "prose-only" in result.stdout


def test_evasion_canary_dynamic_collection_name_fails_closed(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "shared" / "writer.py").write_text(
        "def persist(name, points):\n"
        "    client.upsert(collection_name=f'{name}-x', points=points)\n"
    )
    _commit_all(repo, "add dynamic writer")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "unresolvable" in result.stdout.lower() or "dynamic" in result.stdout.lower()


def test_red_canary_agent_without_runner_blocks(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "agents").mkdir()
    (repo / "agents" / "orphan_agent.py").write_text(
        "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
    )
    _commit_all(repo, "add agent")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "agents.orphan_agent" in result.stdout


def test_green_canary_agent_with_same_pr_unit_passes(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "agents").mkdir()
    (repo / "systemd" / "units").mkdir(parents=True)
    (repo / "agents" / "wired_agent.py").write_text(
        "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
    )
    (repo / "systemd" / "units" / "wired-agent.service").write_text(
        "[Service]\nExecStart=/usr/bin/env python -m agents.wired_agent --auto\n"
    )
    _commit_all(repo, "add agent + unit")
    result = run_gate(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_green_canary_package_init_normalizes_to_package(repo: Path) -> None:
    """Regression: agents/pkg/__init__.py with a main guard is consumed via the
    PACKAGE name (the voice_witness_watchdog shape), not 'pkg.__init__'."""
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "agents" / "pkg").mkdir(parents=True)
    (repo / "systemd" / "units").mkdir(parents=True)
    (repo / "agents" / "pkg" / "__init__.py").write_text(
        "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
    )
    (repo / "agents" / "pkg" / "__main__.py").write_text("from agents.pkg import main\nmain()\n")
    (repo / "systemd" / "units" / "pkg.service").write_text(
        "[Service]\nExecStart=/usr/bin/env uv run python -m agents.pkg\n"
    )
    _commit_all(repo, "add package agent + unit")
    result = run_gate(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_evasion_canary_unit_comment_reference_blocks(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "agents").mkdir()
    (repo / "systemd" / "units").mkdir(parents=True)
    (repo / "agents" / "ghost_agent.py").write_text(
        "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
    )
    (repo / "systemd" / "units" / "ghost.service").write_text(
        "[Service]\n# ExecStart=python -m agents.ghost_agent\nExecStart=/bin/true\n"
    )
    _commit_all(repo, "add agent + commented-out unit")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "agents.ghost_agent" in result.stdout


def test_red_canary_surface_without_contract_or_consumer_blocks(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "shared" / "newsurface.py").write_text(
        "class NewSurfacePublisher(BasePublisher):\n    SURFACE = 'new-surface'\n"
    )
    _commit_all(repo, "add surface")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "new-surface" in result.stdout


def test_green_canary_surface_with_contract_and_importer_passes(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "axioms" / "contracts" / "publication").mkdir(parents=True)
    (repo / "shared" / "newsurface.py").write_text(
        "class NewSurfacePublisher(BasePublisher):\n    SURFACE = 'new-surface'\n"
    )
    (repo / "axioms" / "contracts" / "publication" / "new-surface.yaml").write_text(
        "surface: new-surface\n"
    )
    (repo / "shared" / "runner.py").write_text(
        "from shared.newsurface import NewSurfacePublisher\n"
    )
    _commit_all(repo, "add surface + contract + importer")
    result = run_gate(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_deadlock_canary_reasoned_allowlist_passes(repo: Path) -> None:
    """Anti-thesis (ii): the gate composes with a working, governed escape hatch."""
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "scripts").mkdir()
    (repo / "shared" / "writer.py").write_text(
        "client.upsert(collection_name='intentional-deaddrop', points=[])\n"
    )
    (repo / "scripts" / "producer-consumer-allowlist.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "pattern": "collection:intentional-deaddrop",
                        "reason": "external system reads this collection",
                    }
                ]
            }
        )
    )
    _commit_all(repo, "add allowlisted writer")
    result = run_gate(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_allowlist_without_reason_blocks(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared").mkdir()
    (repo / "scripts").mkdir()
    (repo / "shared" / "writer.py").write_text(
        "client.upsert(collection_name='silent-exempt', points=[])\n"
    )
    (repo / "scripts" / "producer-consumer-allowlist.json").write_text(
        json.dumps({"entries": [{"pattern": "collection:silent-exempt"}]})
    )
    _commit_all(repo, "add writer + reasonless allowlist entry")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "reason" in result.stdout.lower()


def test_no_producer_pr_passes(repo: Path) -> None:
    """Deadlock canary: the gate must not refuse work that adds no producers."""
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("just docs\n")
    (repo / "shared").mkdir()
    (repo / "shared" / "util.py").write_text("def add(a, b):\n    return a + b\n")
    _commit_all(repo, "docs + plain module")
    result = run_gate(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_modified_file_only_new_writer_sites_trip(repo: Path) -> None:
    """Pre-existing writer sites are not retroactively gated (no B9 ratchet)."""
    (repo / "shared").mkdir()
    (repo / "shared" / "store.py").write_text(
        "client.upsert(collection_name='legacy-collection', points=[])\n"
    )
    base = _commit_all(repo, "pre-existing writer")
    (repo / "shared" / "store.py").write_text(
        "client.upsert(collection_name='legacy-collection', points=[])\n"
        "client.upsert(collection_name='brand-new', points=[])\n"
    )
    _commit_all(repo, "modify: add second writer")
    result = run_gate(repo, base)
    assert result.returncode == 1
    assert "brand-new" in result.stdout
    assert "legacy-collection" not in result.stdout
