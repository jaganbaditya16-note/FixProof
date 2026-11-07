from dataclasses import dataclass
from typing import Literal


ChangeType = Literal[
    "added",
    "modified",
    "deleted",
    "renamed",
    "untracked",
]


@dataclass(frozen=True)
class FileChangeEvidence:
    path: str
    change_type: ChangeType

    previous_path: str | None = None

    before_sha256: str | None = None
    after_sha256: str | None = None

    before_bytes: int = 0
    after_bytes: int = 0

    is_binary: bool = False
    is_symlink: bool = False


@dataclass(frozen=True)
class EvidenceManifest:
    schema_version: str
    workspace_id: str
    repository: str

    base_commit: str
    workspace_commit: str

    patch_sha256: str
    generated_at: str

    files: tuple[FileChangeEvidence, ...]

    warnings: tuple[str, ...] = ()
    truncated: bool = False
    complete: bool = True
