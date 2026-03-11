# tests/test_axiom_derivation.py
"""Tests for shared.axiom_derivation."""

from shared.axiom_derivation import (
    build_derivation_prompt,
    merge_self_consistent,
    parse_implications_output,
)


class TestBuildPrompt:
    def test_includes_axiom_text(self):
        prompt = build_derivation_prompt(
            axiom_id="single_user",
            axiom_text="This is a single-user system.",
            codebase_context="File tree: agents/, shared/, cockpit/",
        )
        assert "single-user system" in prompt
        assert "textualist" in prompt.lower() or "Textualist" in prompt

    def test_includes_interpretive_canons(self):
        prompt = build_derivation_prompt(
            axiom_id="test",
            axiom_text="Test.",
            codebase_context="",
        )
        assert "purposivist" in prompt.lower() or "Purposivist" in prompt
        assert "absurdity" in prompt.lower() or "Absurdity" in prompt


class TestParseOutput:
    def test_parses_yaml_implications(self):
        output = (
            "```yaml\n"
            "implications:\n"
            "  - id: su-001\n"
            "    tier: T0\n"
            '    text: "No multi-user auth"\n'
            "    enforcement: block\n"
            "    canon: textualist\n"
            "  - id: su-002\n"
            "    tier: T1\n"
            '    text: "No user switching"\n'
            "    enforcement: review\n"
            "    canon: purposivist\n"
            "```\n"
        )
        impls = parse_implications_output(output)
        assert len(impls) == 2
        assert impls[0]["id"] == "su-001"
        assert impls[0]["tier"] == "T0"

    def test_handles_no_yaml_block(self):
        impls = parse_implications_output("No implications found.")
        assert impls == []


class TestMergeSelfConsistent:
    def test_majority_vote_keeps_consensus(self):
        runs = [
            [
                {
                    "id": "su-001",
                    "tier": "T0",
                    "text": "No multi-user auth",
                    "enforcement": "block",
                    "canon": "textualist",
                }
            ],
            [
                {
                    "id": "su-001",
                    "tier": "T0",
                    "text": "No multi-user auth",
                    "enforcement": "block",
                    "canon": "textualist",
                }
            ],
            [
                {
                    "id": "su-001",
                    "tier": "T1",
                    "text": "No multi-user auth",
                    "enforcement": "review",
                    "canon": "textualist",
                }
            ],
        ]
        merged = merge_self_consistent(runs)
        su001 = [i for i in merged if i["id"] == "su-001"]
        assert len(su001) == 1
        assert su001[0]["tier"] == "T0"

    def test_unique_implications_all_kept(self):
        runs = [
            [{"id": "su-001", "tier": "T0", "text": "A", "enforcement": "block", "canon": "t"}],
            [{"id": "su-002", "tier": "T1", "text": "B", "enforcement": "review", "canon": "t"}],
            [
                {"id": "su-001", "tier": "T0", "text": "A", "enforcement": "block", "canon": "t"},
                {"id": "su-003", "tier": "T2", "text": "C", "enforcement": "warn", "canon": "t"},
            ],
        ]
        merged = merge_self_consistent(runs)
        ids = {i["id"] for i in merged}
        assert "su-001" in ids  # appears in 2/3 runs
