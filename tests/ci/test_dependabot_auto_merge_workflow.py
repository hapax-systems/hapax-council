from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "dependabot-auto-merge.yml"
REPO_SCOPE = '--repo "$GH_REPO"'


def _workflow_steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["auto-merge"]["steps"]


def _logical_shell_commands(script: str) -> list[str]:
    commands: list[str] = []
    current: list[str] = []
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith("\\"):
            current.append(line[:-1].strip())
            continue
        current.append(line)
        commands.append(" ".join(current))
        current = []
    if current:
        commands.append(" ".join(current))
    return commands


def test_dependabot_label_creation_is_repo_scoped() -> None:
    label_create_commands = [
        command
        for step in _workflow_steps()
        for command in _logical_shell_commands(str(step.get("run", "")))
        if command.startswith("gh label create needs-human ")
    ]
    assert len(label_create_commands) == 2
    assert all(REPO_SCOPE in command for command in label_create_commands)


def test_dependabot_pr_label_edit_is_repo_scoped() -> None:
    pr_edit_commands = [
        command
        for step in _workflow_steps()
        for command in _logical_shell_commands(str(step.get("run", "")))
        if command.startswith("gh pr edit ") and '--add-label "needs-human"' in command
    ]
    assert len(pr_edit_commands) == 2
    assert all(REPO_SCOPE in command for command in pr_edit_commands)


def test_dependabot_labeling_steps_define_repo_env() -> None:
    repo_scoped_steps = {
        "Auto-merge minor/patch",
        "Ensure needs-human label exists",
        "Label major updates",
    }
    steps_by_name = {step.get("name"): step for step in _workflow_steps()}
    assert repo_scoped_steps <= set(steps_by_name)
    for name in repo_scoped_steps:
        env = steps_by_name[name].get("env")
        assert isinstance(env, dict)
        assert env.get("GH_REPO") == "${{ github.repository }}"
