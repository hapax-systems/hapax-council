"""Smoke tests for agent loading and tool registration."""


def test_research_agent_loads():
    from agents.research import agent
    assert agent.model.model_name == "claude-sonnet"


def test_research_agent_has_tools():
    from agents.research import agent
    tool_names = [t.name for t in agent._function_toolset.tools.values()]
    assert "search_knowledge_base" in tool_names
    assert "search_samples" in tool_names


def test_code_review_agent_loads():
    from agents.code_review import agent
    assert agent.model.model_name == "claude-sonnet"


def test_research_deps_defaults():
    from agents.research import Deps, EMBEDDING_MODEL
    from qdrant_client import QdrantClient

    deps = Deps(qdrant=QdrantClient("http://localhost:6333"))
    assert deps.collection == "documents"
    assert deps.embedding_model == EMBEDDING_MODEL
