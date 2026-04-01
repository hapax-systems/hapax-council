"""Test fortress writes action feedback to dedicated file."""


def test_fortress_actions_path_constant():
    """Verify fortress uses the correct dedicated actions path."""
    source = open("agents/fortress/__main__.py").read()
    assert "fortress-actions.jsonl" in source, (
        "Fortress must write to dedicated actions file, not impingements.jsonl"
    )


def test_fortress_does_not_write_to_impingements_jsonl():
    """Verify fortress no longer writes action_taken to the shared impingements file."""
    source = open("agents/fortress/__main__.py").read()
    # The fortress consumer still reads from impingements.jsonl (line 86),
    # but action_taken feedback should go to fortress-actions.jsonl
    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "fortress-actions" in line or "action_taken" not in line:
            continue
        # If we find action_taken near impingements.jsonl, that's wrong
        context = "\n".join(lines[max(0, i - 3) : i + 3])
        if "impingements.jsonl" in context and "action_taken" in context:
            raise AssertionError(
                f"Fortress still writes action_taken to impingements.jsonl:\n{context}"
            )
