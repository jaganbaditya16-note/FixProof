import subprocess

import pytest

from backend.fixproof.workspaces.errors import (
    DirtyRepositoryError,
    UnsafeWorkspaceError,
    WorkspaceExistsError,
)
from backend.fixproof.workspaces.manager import WorkspaceManager


def create_sample_repo(path):
    path.mkdir(parents=True)

    def git(*args):
        subprocess.run(
            ["git", *args],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "--initial-branch=main")
    git("config", "user.name", "FixProof Tests")
    git("config", "user.email", "tests@fixproof.local")

    (path / "README.md").write_text(
        "# Original project\n",
        encoding="utf-8",
    )

    git("add", "README.md")
    git("commit", "-m", "Initial commit")

    return path


@pytest.fixture
def project(tmp_path):
    repo = create_sample_repo(tmp_path / "project")
    workspace_root = tmp_path / "fixproof-workspaces"

    return repo, workspace_root


def test_create_isolated_workspace(project):
    repo, workspace_root = project
    manager = WorkspaceManager(workspace_root)

    original_file = (repo / "README.md").read_text(
        encoding="utf-8"
    )

    workspace = manager.create_workspace(
        repo,
        "builder-test",
    )

    assert workspace.path.is_dir()
    assert workspace.path != repo
    assert workspace.path.parent == workspace_root.resolve()
    assert (workspace.path / "README.md").read_text(
        encoding="utf-8"
    ) == original_file


def test_workspace_starts_at_original_commit(project):
    repo, workspace_root = project
    manager = WorkspaceManager(workspace_root)

    workspace = manager.create_workspace(
        repo,
        "baseline-test",
    )

    assert workspace.base_commit == subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
    ).strip()


def test_workspace_is_detached(project):
    repo, workspace_root = project
    manager = WorkspaceManager(workspace_root)

    workspace = manager.create_workspace(
        repo,
        "detached-test",
    )

    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=workspace.path,
        text=True,
    ).strip()

    assert branch == "HEAD"


def test_workspace_changes_do_not_modify_original(project):
    repo, workspace_root = project
    manager = WorkspaceManager(workspace_root)

    workspace = manager.create_workspace(
        repo,
        "isolation-test",
    )

    (workspace.path / "README.md").write_text(
        "# Changed by test\n",
        encoding="utf-8",
    )

    assert (repo / "README.md").read_text(
        encoding="utf-8"
    ) == "# Original project\n"


def test_inspect_workspace_detects_changes(project):
    repo, workspace_root = project
    manager = WorkspaceManager(workspace_root)

    workspace = manager.create_workspace(
        repo,
        "inspect-test",
    )

    snapshot = manager.inspect_workspace(workspace)

    assert snapshot.status == "clean"
    assert snapshot.dirty is False

    (workspace.path / "README.md").write_text(
        "# Modified\n",
        encoding="utf-8",
    )

    snapshot = manager.inspect_workspace(workspace)

    assert snapshot.status == "dirty"
    assert snapshot.dirty is True
    assert "README.md" in snapshot.changed_files


def test_dirty_original_repository_is_rejected(project):
    repo, workspace_root = project
    manager = WorkspaceManager(workspace_root)

    (repo / "uncommitted.txt").write_text(
        "Do not overwrite me",
        encoding="utf-8",
    )

    with pytest.raises(DirtyRepositoryError):
        manager.create_workspace(repo, "dirty-test")

    assert not (workspace_root / "dirty-test").exists()


def test_workspace_inside_original_repository_is_rejected(project):
    repo, _ = project

    unsafe_root = repo / ".fixproof-workspaces"
    manager = WorkspaceManager(unsafe_root)

    with pytest.raises(UnsafeWorkspaceError):
        manager.create_workspace(repo, "unsafe-test")

    assert not unsafe_root.exists()


def test_duplicate_workspace_is_rejected(project):
    repo, workspace_root = project
    manager = WorkspaceManager(workspace_root)

    manager.create_workspace(repo, "duplicate-test")

    with pytest.raises(WorkspaceExistsError):
        manager.create_workspace(repo, "duplicate-test")


def test_path_traversal_id_is_rejected(project):
    repo, workspace_root = project
    manager = WorkspaceManager(workspace_root)

    with pytest.raises(UnsafeWorkspaceError):
        manager.create_workspace(repo, "../outside")
