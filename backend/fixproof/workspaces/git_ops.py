from pathlib import Path
import subprocess

from .errors import (
    DirtyRepositoryError,
    GitCommandError,
    InvalidRepositoryError,
)


DEFAULT_TIMEOUT = 30


def run_git(
    directory: Path,
    *args: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Run Git safely without invoking a shell."""

    directory = Path(directory).expanduser().resolve()

    if not directory.is_dir():
        raise InvalidRepositoryError(
            f"Directory does not exist: {directory}"
        )

    if timeout <= 0:
        raise ValueError("Git timeout must be positive.")

    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(directory),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitCommandError(
            "Git executable was not found."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitCommandError(
            f"Git command timed out after {timeout} seconds."
        ) from exc
    except OSError as exc:
        raise GitCommandError(
            f"Could not execute Git: {exc}"
        ) from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise GitCommandError(
            f"Git command failed ({result.returncode}): "
            f"{message}"
        )

    return result.stdout.rstrip("\r\n")


def get_repository_root(directory: Path) -> Path:
    """Resolve the root of a non-bare Git working tree."""

    directory = Path(directory).expanduser().resolve()

    is_bare = run_git(
        directory,
        "rev-parse",
        "--is-bare-repository",
    )

    if is_bare != "false":
        raise InvalidRepositoryError(
            "Bare Git repositories are not supported."
        )

    root = Path(
        run_git(directory, "rev-parse", "--show-toplevel")
    ).resolve()

    if not root.is_dir():
        raise InvalidRepositoryError(
            "Git repository root is not accessible."
        )

    return root


def get_head_commit(repository: Path) -> str:
    """Return the current commit SHA."""

    return run_git(
        repository,
        "rev-parse",
        "--verify",
        "HEAD",
    )


def get_working_tree_status(repository: Path) -> str:
    """Include tracked, untracked and staged changes."""

    return run_git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )


def assert_clean_repository(repository: Path) -> None:
    """Refuse to start from a modified repository."""

    status = get_working_tree_status(repository)

    if status:
        raise DirtyRepositoryError(
            "Repository has uncommitted or untracked changes. "
            "Commit or move the changes before creating "
            f"a FixProof workspace. Git status:\\n{status}"
        )

