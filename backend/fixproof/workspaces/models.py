from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    repository: Path
    path: Path
    base_commit: str
    created_at: str


@dataclass(frozen=True)
class WorkspaceSnapshot:
    workspace_id: str
    path: Path
    base_commit: str
    current_commit: str
    dirty: bool
    changed_files: tuple[str, ...]
    status: Literal["clean", "dirty"]
