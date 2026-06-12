"""Canaries for the jsonl-writer gate (anti-theses: prove it fires AND
prove it passes legitimate patterns — a gate without both is theater)."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "check-jsonl-writers.py"

sys.path.insert(0, str(REPO / "scripts"))


def _load_gate():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_evasion_canary_unregistered_writer_is_caught():
    gate = _load_gate()
    src = 'def w():\n    with open("/tmp/rogue-ledger.jsonl", "a") as f:\n        f.write("x")\n'
    problems = gate.check_file(
        REPO / "agents" / "fake.py", covered=set(), src_lines=src.splitlines()
    )
    assert len(problems) == 1
    assert "rogue-ledger.jsonl" in problems[0]


def test_deadlock_canary_registered_writer_passes():
    gate = _load_gate()
    src = 'def w():\n    with open("/tmp/dispatch-trace.jsonl", "a") as f:\n        f.write("x")\n'
    problems = gate.check_file(
        REPO / "agents" / "fake.py",
        covered={"/tmp/dispatch-trace.jsonl"},
        src_lines=src.splitlines(),
    )
    assert problems == []


def test_deadlock_canary_exempt_pragma_passes():
    gate = _load_gate()
    src = 'f = open("/tmp/oneshot-debug.jsonl", "a")  # jsonl-rotation: exempt(test scratch)\n'
    problems = gate.check_file(
        REPO / "agents" / "fake.py", covered=set(), src_lines=src.splitlines()
    )
    assert problems == []


def test_registered_basename_does_not_cover_unrelated_path():
    gate = _load_gate()
    src = (
        'EVENTS = Path("/dev/shm/hapax-public-events/events.jsonl")\n'
        "def w():\n"
        '    with EVENTS.open("a") as f:\n'
        '        f.write("x")\n'
    )
    problems = gate.check_file(
        REPO / "agents" / "fake.py",
        covered={"/dev/shm/hapax-broadcast/events.jsonl"},
        src_lines=src.splitlines(),
    )
    assert len(problems) == 1
    assert "/dev/shm/hapax-public-events/events.jsonl" in problems[0]


def test_registered_path_covers_name_bound_writer():
    gate = _load_gate()
    src = (
        'EVENT_DIR = Path("/dev/shm/hapax-broadcast")\n'
        'EVENT_FILE = EVENT_DIR / "events.jsonl"\n'
        "def w():\n"
        '    with EVENT_FILE.open("a") as f:\n'
        '        f.write("x")\n'
    )
    problems = gate.check_file(
        REPO / "agents" / "fake.py",
        covered={"/dev/shm/hapax-broadcast/events.jsonl"},
        src_lines=src.splitlines(),
    )
    assert problems == []


def test_registered_path_covers_conditional_default_alias():
    gate = _load_gate()
    src = (
        'DEFAULT_PAYMENT_LOG_PATH = Path(os.environ.get("X", "/dev/shm/hapax-monetization/events.jsonl"))\n'
        "def append_event(log_path=None):\n"
        "    target = log_path if log_path is not None else DEFAULT_PAYMENT_LOG_PATH\n"
        '    with target.open("a") as f:\n'
        '        f.write("x")\n'
    )
    problems = gate.check_file(
        REPO / "agents" / "fake.py",
        covered={"/dev/shm/hapax-monetization/events.jsonl"},
        src_lines=src.splitlines(),
    )
    assert problems == []


def test_registered_path_covers_constructor_default_attribute():
    gate = _load_gate()
    src = (
        'DEFAULT_PUBLIC_EVENT_PATH = Path("/dev/shm/hapax-public-events/events.jsonl")\n'
        "class Broker:\n"
        "    def __init__(self, public_event_path=DEFAULT_PUBLIC_EVENT_PATH):\n"
        "        self.public_event_path = public_event_path\n"
        "    def write(self):\n"
        '        with self.public_event_path.open("a") as f:\n'
        '            f.write("x")\n'
    )
    problems = gate.check_file(
        REPO / "shared" / "fake.py",
        covered={"/dev/shm/hapax-public-events/events.jsonl"},
        src_lines=src.splitlines(),
    )
    assert problems == []


def test_registered_basename_without_resolved_path_is_ambiguous():
    gate = _load_gate()
    src = (
        "def write(directory):\n"
        '    with (directory / "events.jsonl").open("a") as f:\n'
        '        f.write("x")\n'
    )
    problems = gate.check_file(
        REPO / "shared" / "fake.py",
        covered={"/dev/shm/hapax-broadcast/events.jsonl"},
        src_lines=src.splitlines(),
    )
    assert len(problems) == 1
    assert "events.jsonl" in problems[0]


def test_live_tree_is_clean():
    result = subprocess.run(
        [sys.executable, str(GATE)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
