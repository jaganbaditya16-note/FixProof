import re
from datetime import datetime, timezone
from pathlib import Path

from .errors import (
    DirtyRepositoryError,
    UnsafeWorkspaceError,
    WorkspaceExistsError,
    WorkspaceNotFoundError,
)
from .git_ops import (
    assert_clean_repository,
    get_head_commit,
    get_repository_root,
    get_working_tree_status,
    run_git,
)
from .models import Workspace, WorkspaceSnapshot


class WorkspaceManager:
    """Create and inspect isolated Git worktrees."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = (
            Path(workspace_root).expanduser().resolve()
        )

    @staticmethod
    def _validate_id(workspace_id: str) -> None:
        if not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}",
            workspace_id,
        ):
            raise UnsafeWorkspaceError(
                "Invalid workspace ID."
            )

    def create_workspace(
        self,
        repository: Path,
        workspace_id: str,
    ) -> Workspace:
        """Create a detached worktree from a clean baseline."""

        self._validate_id(workspace_id)

        repo = get_repository_root(repository)
        assert_clean_repository(repo)

        root = self.workspace_root.resolve()

        if root.is_relative_to(repo):
            raise UnsafeWorkspaceError(
                "Workspace storage cannot be inside "
                "the original repository."
            )

        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = root / workspace_id

        if destination.exists():
            raise WorkspaceExistsError(
                "Workspace destination already exists."
            )

        base_commit = get_head_commit(repo)

        run_git(
            repo,
            "worktree",
            "add",
            "--detach",
            str(destination),
            base_commit,
            timeout=120,
        )

        try:
            actual_root = get_repository_root(destination)
            actual_commit = get_head_commit(destination)

            if actual_root != destination.resolve():
                raise UnsafeWorkspaceError(
                    "Created worktree root does not match "
                    "the expected destination."
                )

            if actual_commit != base_commit:
                raise UnsafeWorkspaceError(
                    "Workspace commit differs from baseline."
                )

        except Exception:
            try:
                run_git(
                    repo,
                    "worktree",
                    "remove",
                    "--force",
                    str(destination),
                    timeout=60,
                )
            except Exception:
                pass
            raise

        return Workspace(
            workspace_id=workspace_id,
            repository=repo,
            path=destination.resolve(),
            base_commit=base_commit,
            created_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )

    def inspect_workspace(
        self,
        workspace: Workspace,
    ) -> WorkspaceSnapshot:
        """Inspect a registered workspace without modifying it."""

        self._validate_id(workspace.workspace_id)

        root = self.workspace_root.resolve()
        path = workspace.path.resolve()
        repository = get_repository_root(
            workspace.repository
        )

        if path.parent != root:
            raise UnsafeWorkspaceError(
                "Workspace is outside the managed directory."
            )

        if not path.is_dir():
            raise WorkspaceNotFoundError(
                "Workspace directory does not exist."
            )

        if get_repository_root(path) != path:
            raise UnsafeWorkspaceError(
                "Workspace Git root does not match its location."
            )

        worktree_list = run_git(
            repository,
            "worktree",
            "list",
            "--porcelain",
        )

        registered_paths = {
            Path(line.removeprefix("worktree ")).resolve()
            for line in worktree_list.splitlines()
            if line.startswith("worktree ")
        }

        if path not in registered_paths:
            raise WorkspaceNotFoundError(
                "Workspace is not registered as a Git worktree."
            )

        current_commit = get_head_commit(path)
        status_text = get_working_tree_status(path)

        changed_files = tuple(
            line[3:]
            for line in status_text.splitlines()
            if len(line) >= 4
        )

        return WorkspaceSnapshot(
            workspace_id=workspace.workspace_id,
            path=path,
            base_commit=workspace.base_commit,
            current_commit=current_commit,
            dirty=bool(status_text),
            changed_files=changed_files,
            status="dirty" if status_text else "clean",
        )

