import re
import subprocess

import pytest

from backend.fixproof.workspaces.errors import (
    DirtyRepositoryError,
    GitCommandError,
)
from backend.fixproof.workspaces.git_ops import (
    assert_clean_repository,
    get_head_commit,
    get_repository_root,
    run_git,
)


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "sample-repository"
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
        "# Test repository\n",
        encoding="utf-8",
    )

    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "Initial test commit")

    return repo


def test_repository_root_detection(sample_repo):
    nested = sample_repo / "nested"
    nested.mkdir()

    assert get_repository_root(nested) == sample_repo.resolve()


def test_head_commit_returns_valid_sha(sample_repo):
    commit = get_head_commit(sample_repo)

    assert re.fullmatch(r"[0-9a-f]{40,64}", commit)


def test_clean_repository_is_accepted(sample_repo):
    assert_clean_repository(sample_repo)


def test_untracked_file_is_rejected(sample_repo):
    (sample_repo / "unexpected.txt").write_text(
        "Uncommitted file",
        encoding="utf-8",
    )

    with pytest.raises(DirtyRepositoryError):
        assert_clean_repository(sample_repo)


def test_git_command_failure_is_reported(sample_repo):
    with pytest.raises(GitCommandError):
        run_git(sample_repo, "not-a-real-git-command")


def test_non_positive_timeout_is_rejected(sample_repo):
    with pytest.raises(ValueError):
        run_git(sample_repo, "status", timeout=0)
