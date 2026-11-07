class WorkspaceError(Exception):
    """Base exception for workspace management."""


class InvalidRepositoryError(WorkspaceError):
    """Repository is missing, invalid, or unsafe to use."""


class DirtyRepositoryError(WorkspaceError):
    """Original repository has uncommitted changes."""


class WorkspaceExistsError(WorkspaceError):
    """Workspace destination already exists."""


class WorkspaceNotFoundError(WorkspaceError):
    """Requested workspace does not exist."""


class UnsafeWorkspaceError(WorkspaceError):
    """Workspace operation would violate safety rules."""


class GitCommandError(WorkspaceError):
    """A Git operation failed."""
