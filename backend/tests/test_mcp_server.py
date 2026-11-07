import asyncio
import inspect
import json
import subprocess

import pytest

from backend.fixproof import mcp_server


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "mcp-test-repository"
    repo.mkdir()

    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "FixProof Tests"],
        cwd=repo,
        check=True,
    )

    subprocess.run(
        ["git", "config", "user.email", "tests@fixproof.local"],
        cwd=repo,
        check=True,
    )

    (repo / "README.md").write_text(
        "# MCP test repository\\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "Initial test commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


def test_inspect_project_without_configuration(monkeypatch):
    monkeypatch.setattr(
        mcp_server.settings,
        "repository_path",
        None,
    )

    result = json.loads(mcp_server.inspect_project())

    assert result["ok"] is False
    assert result["error"] == "No repository is configured."


def test_inspect_project_valid_repository(monkeypatch, sample_repo):
    monkeypatch.setattr(
        mcp_server.settings,
        "repository_path",
        sample_repo,
    )

    result = json.loads(mcp_server.inspect_project())

    assert result["ok"] is True
    assert result["repository"] == str(sample_repo.resolve())
    assert result["branch"] == "main"
    assert result["working_tree_clean"] is True
    assert result["working_tree_status"] == []
    assert len(result["head_commit"]) in (40, 64)


def test_inspect_project_reports_dirty_repository(
    monkeypatch,
    sample_repo,
):
    (sample_repo / "change.txt").write_text(
        "Uncommitted change",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mcp_server.settings,
        "repository_path",
        sample_repo,
    )

    result = json.loads(mcp_server.inspect_project())

    assert result["ok"] is True
    assert result["working_tree_clean"] is False
    assert any("change.txt" in line for line in result["working_tree_status"])


def test_inspect_project_rejects_missing_repository(
    monkeypatch,
    tmp_path,
):
    missing = tmp_path / "does-not-exist"

    monkeypatch.setattr(
        mcp_server.settings,
        "repository_path",
        missing,
    )

    result = json.loads(mcp_server.inspect_project())

    assert result["ok"] is False
    assert "InvalidRepositoryError" in result["error"]


def test_inspect_project_accepts_no_agent_arguments():
    signature = inspect.signature(mcp_server.inspect_project)

    assert len(signature.parameters) == 0


def test_mcp_tool_is_registered_read_only():
    tools = asyncio.run(mcp_server.server.list_tools())

    inspect_tool = next(
        tool for tool in tools
        if tool.name == "inspect_project"
    )

    assert inspect_tool.annotations is not None
    assert inspect_tool.annotations.read_only_hint is True
    assert inspect_tool.annotations.destructive_hint is False
    assert inspect_tool.annotations.idempotent_hint is True
    assert inspect_tool.annotations.open_world_hint is False
