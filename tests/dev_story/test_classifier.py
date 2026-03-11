"""Tests for session dimension classification."""

from __future__ import annotations

from agents.dev_story.classifier import (
    classify_env_topology,
    classify_interaction_mode,
    classify_session_scale,
    classify_work_type,
)


def test_classify_work_type_feature():
    commit_messages = ["feat: add widget", "feat: wire up API"]
    result = classify_work_type(commit_messages)
    assert result.value == "feature"
    assert result.confidence > 0.5


def test_classify_work_type_bugfix():
    commit_messages = ["fix: broken query", "fix: null check"]
    result = classify_work_type(commit_messages)
    assert result.value == "bugfix"


def test_classify_work_type_mixed():
    commit_messages = ["feat: add X", "fix: Y", "feat: Z"]
    result = classify_work_type(commit_messages)
    assert result.value == "feature"  # Majority wins


def test_classify_work_type_empty():
    result = classify_work_type([])
    assert result.value == "unknown"


def test_classify_interaction_mode_high_steering():
    user_msg_lengths = [5, 3, 2, 8, 4, 3, 2, 1, 6, 3]  # All short
    result = classify_interaction_mode(user_msg_lengths, parallel=False)
    assert result.value == "high-steering"


def test_classify_interaction_mode_autonomous():
    user_msg_lengths = [150, 200, 180, 250]  # All long
    result = classify_interaction_mode(user_msg_lengths, parallel=False)
    assert result.value == "autonomous"


def test_classify_interaction_mode_parallel():
    user_msg_lengths = [50, 60, 70]
    result = classify_interaction_mode(user_msg_lengths, parallel=True)
    assert "parallel" in result.value


def test_classify_env_topology_containerized():
    file_paths = ["Dockerfile.api", "docker-compose.yml", "agents/foo.py"]
    result = classify_env_topology(file_paths)
    assert result.value == "containerized"


def test_classify_env_topology_host():
    file_paths = ["systemd/units/foo.service", "agents/bar.py"]
    result = classify_env_topology(file_paths)
    assert result.value == "host-side"


def test_classify_env_topology_single_repo():
    file_paths = ["agents/foo.py", "shared/config.py", "tests/test_foo.py"]
    result = classify_env_topology(file_paths)
    assert result.value == "single-repo"


def test_classify_session_scale_single_file():
    file_paths = ["agents/foo.py"]
    result = classify_session_scale(file_paths)
    assert result.value == "single-file"


def test_classify_session_scale_cross_module():
    file_paths = ["agents/foo.py", "shared/config.py", "cockpit/api/routes/data.py"]
    result = classify_session_scale(file_paths)
    assert result.value == "cross-module"
