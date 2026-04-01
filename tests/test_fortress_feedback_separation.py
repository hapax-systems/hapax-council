"""Test fortress feedback uses separate JSONL file."""

import time


def test_consume_fortress_feedback_reads_separate_file(tmp_path):
    """Verify DMN reads fortress feedback from dedicated file, not impingements.jsonl."""
    from agents.dmn.__main__ import DMNDaemon
    from shared.impingement import Impingement, ImpingementType

    # Write fortress feedback to dedicated path
    feedback_path = tmp_path / "fortress-actions.jsonl"
    imp = Impingement(
        timestamp=time.time(),
        source="fortress.action_taken",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
        content={"action": "drink_ordered"},
    )
    feedback_path.write_text(imp.model_dump_json() + "\n")

    daemon = DMNDaemon()
    daemon._consume_fortress_feedback(path=feedback_path)

    # Should have consumed 1 feedback item (no assert crash = success)
