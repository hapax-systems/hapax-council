from pathlib import Path


def test_no_raw_notify_send():
    """CI grep-guard: High-priority alerts must route through hapax-alert.

    Fails any producer emitting raw 'notify-send' instead of 'hapax-alert'.
    """
    root = Path(__file__).parent.parent.parent
    agents_dir = root / "agents"

    violations = []

    # We only care about Python files in agents/
    for py_file in agents_dir.rglob("*.py"):
        if "probes_alerting.py" in py_file.name or "_sufficiency_probes.py" in py_file.name:
            # Tests or probes that just assert string presence are exempt
            continue

        content = py_file.read_text(encoding="utf-8")
        if "notify-send" in content:
            violations.append(str(py_file.relative_to(root)))

    assert not violations, f"Raw notify-send found (must use hapax-alert): {violations}"
