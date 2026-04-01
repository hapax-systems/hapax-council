"""Test ConsentGatedReader wiring in conversation pipeline."""


def test_pipeline_calls_filter_tool_result():
    """Conversation pipeline must call consent_reader.filter_tool_result."""
    source = open("agents/hapax_daimonion/conversation_pipeline.py").read()
    assert "filter_tool_result" in source, (
        "conversation_pipeline must call consent_reader.filter_tool_result for tool results"
    )
