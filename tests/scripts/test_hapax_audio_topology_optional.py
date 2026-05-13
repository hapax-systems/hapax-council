import importlib.machinery
import importlib.util
from pathlib import Path

from shared.audio_topology import Node, NodeKind


def load_script():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "hapax-audio-topology"
    loader = importlib.machinery.SourceFileLoader("hapax_audio_topology", str(script_path))
    spec = importlib.util.spec_from_loader("hapax_audio_topology", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


hapax_audio_topology = load_script()


def test_classify_declared_missing_node_optional():
    node = Node(id="test", kind=NodeKind.TAP, pipewire_name="test", optional=True)
    classification = hapax_audio_topology._classify_declared_missing_node(node)
    assert classification == "optional-hardware-absent"


def test_classify_declared_missing_node_not_optional():
    node = Node(id="test", kind=NodeKind.TAP, pipewire_name="test", optional=False)
    classification = hapax_audio_topology._classify_declared_missing_node(node)
    assert classification is None


def test_classify_declared_missing_edge_optional_target():
    source = Node(id="source", kind=NodeKind.TAP, pipewire_name="source", optional=False)
    target = Node(id="target", kind=NodeKind.TAP, pipewire_name="target", optional=True)
    declared_by_name = {"source": source, "target": target}
    classification = hapax_audio_topology._classify_declared_missing_edge(
        "source", "target", declared_by_name
    )
    assert classification == "depends-on-optional-hardware-absent"
