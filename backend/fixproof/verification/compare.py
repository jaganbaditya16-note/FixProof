import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .models import (
    EvidenceManifest,
    FileChangeEvidence,
)
from backend.fixproof.workspaces.git_ops import (
    get_head_commit,
    get_repository_root,
    run_git,
)
from backend.fixproof.workspaces.manager import WorkspaceManager


MAX_FILE_SIZE = 10 * 1024 * 1024
GIT_TIMEOUT = 120


def _git_bytes(directory: Path, *args: str) -> bytes:
    """Run Git without decoding or modifying its output."""

    result = subprocess.run(
        ["git", *args],
        cwd=str(directory),
        capture_output=True,
        shell=False,
        timeout=GIT_TIMEOUT,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Git evidence operation failed: "
            + result.stderr.decode("utf-8", errors="replace")
        )

    return result.stdout


def _content_from_worktree(
    workspace_path: Path,
    relative_path: str,
) -> bytes:
    """Read a regular file or symlink without following symlinks."""

    root = workspace_path.resolve(strict=True)

    if (
        not relative_path
        or "\x00" in relative_path
        or "\\" in relative_path
    ):
        raise RuntimeError("Unsafe workspace file path.")

    relative = PurePosixPath(relative_path)

    if (
        relative.is_absolute()
        or any(part in ("", ".", "..") for part in relative.parts)
        or (relative.parts and ":" in relative.parts[0])
    ):
        raise RuntimeError("Unsafe workspace file path.")

    target = root.joinpath(*relative.parts)

    try:
        parent = target.parent.resolve(strict=True)
        parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "File parent escapes or is missing from workspace."
        ) from exc

    if target.is_symlink():
        return os.fsencode(os.readlink(target))

    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "File resolves outside the workspace."
        ) from exc

    if not target.is_file():
        raise RuntimeError(
            f"Changed file is missing or unsupported: {relative_path}"
        )

    return target.read_bytes()


def _content_from_commit(
    repository: Path,
    commit: str,
    relative_path: str,
) -> bytes:
    """Retrieve the original file content from Git."""

    return _git_bytes(
        repository,
        "show",
        f"{commit}:{relative_path}",
    )


def _hash_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _is_binary(content: bytes) -> bool:
    """Detect common binary content using a NUL-byte check."""

    return b"\x00" in content[:8192]


def _read_diff_entries(
    repository: Path,
    base_commit: str,
) -> list[tuple[str, str]]:
    """Return tracked changed files without relying on quoted paths."""

    raw = _git_bytes(
        repository,
        "diff",
        "--name-status",
        "-z",
        "--no-renames",
        base_commit,
        "--",
    )

    fields = raw.split(b"\x00")
    entries = []

    index = 0

    while index < len(fields):
        if not fields[index]:
            index += 1
            continue

        status = fields[index].decode("ascii")
        index += 1

        if index >= len(fields):
            raise RuntimeError("Incomplete Git diff entry.")

        path = os.fsdecode(fields[index])
        index += 1

        entries.append((status[0], path))

    return entries


def _read_untracked_entries(workspace: Path) -> list[str]:
    raw = _git_bytes(
        workspace,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )

    return [
        os.fsdecode(item)
        for item in raw.split(b"\x00")
        if item
    ]


def _read_ignored_entries(workspace: Path) -> list[str]:
    """Find ignored files created in the workspace."""

    raw = _git_bytes(
        workspace,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
    )

    return [
        os.fsdecode(item)
        for item in raw.split(b"\x00")
        if item
    ]


def _file_evidence(
    repository: Path,
    workspace: Path,
    base_commit: str,
    change_type: str,
    path: str,
) -> FileChangeEvidence:
    before = None
    after = None

    if change_type not in ("added", "untracked"):
        before = _content_from_commit(
            repository,
            base_commit,
            path,
        )

    if change_type != "deleted":
        after = _content_from_worktree(
            workspace,
            path,
        )

    before_hash = (
        _hash_content(before)
        if before is not None
        else None
    )

    after_hash = (
        _hash_content(after)
        if after is not None
        else None
    )

    binary = (
        _is_binary(before or b"")
        or _is_binary(after or b"")
    )

    is_symlink = (workspace / path).is_symlink()

    return FileChangeEvidence(
        path=path,
        change_type=change_type,
        before_sha256=before_hash,
        after_sha256=after_hash,
        before_bytes=len(before) if before is not None else 0,
        after_bytes=len(after) if after is not None else 0,
        is_binary=binary,
        is_symlink=is_symlink,
    )


def generate_evidence(
    workspace,
) -> EvidenceManifest:
    """Generate a deterministic manifest of workspace changes."""

    manager = WorkspaceManager(
        workspace.path.parent
    )

    snapshot = manager.inspect_workspace(workspace)

    repository = get_repository_root(
        workspace.repository
    )

    base_commit = workspace.base_commit

    original_commit = get_head_commit(repository)

    if original_commit != base_commit:
        raise RuntimeError(
            "Original repository has moved from the "
            "workspace baseline. Evidence must be reviewed "
            "against the original baseline before proceeding."
        )

    tracked_entries = _read_diff_entries(
        workspace.path,
        base_commit,
    )

    untracked_paths = _read_untracked_entries(
        workspace.path
    )

    ignored_paths = _read_ignored_entries(
        workspace.path
    )

    evidence = []

    for status, path in tracked_entries:
        change_types = {
            "A": "added",
            "M": "modified",
            "D": "deleted",
            "T": "modified",
        }

        if status not in change_types:
            raise RuntimeError(
                f"Unsupported Git change status: {status}"
            )

        evidence.append(
            _file_evidence(
                repository,
                workspace.path,
                base_commit,
                change_types[status],
                path,
            )
        )

    for path in untracked_paths:
        evidence.append(
            _file_evidence(
                repository,
                workspace.path,
                base_commit,
                "added",
                path,
            )
        )

    for path in ignored_paths:
        if path in untracked_paths:
            continue

        evidence.append(
            _file_evidence(
                repository,
                workspace.path,
                base_commit,
                "untracked",
                path,
            )
        )

    evidence.sort(key=lambda item: item.path)

    warnings = []
    complete = True
    truncated = False

    for item in evidence:
        if item.is_symlink:
            warnings.append(
                f"Symbolic link requires explicit review: {item.path}"
            )
            complete = False

        if item.change_type == "untracked":
            warnings.append(
                f"Ignored file requires explicit review: {item.path}"
            )
            complete = False

        if max(item.before_bytes, item.after_bytes) > MAX_FILE_SIZE:
            warnings.append(
                f"Large file requires additional review: {item.path}"
            )
            complete = False
            truncated = True

    canonical_data = {
        "workspace_id": workspace.workspace_id,
        "base_commit": base_commit,
        "files": [
            {
                "path": item.path,
                "change_type": item.change_type,
                "before_sha256": item.before_sha256,
                "after_sha256": item.after_sha256,
            }
            for item in evidence
        ],
    }

    canonical_json = json.dumps(
        canonical_data,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    patch_hash = hashlib.sha256(
        canonical_json
    ).hexdigest()

    return EvidenceManifest(
        schema_version="1.0",
        workspace_id=workspace.workspace_id,
        repository=str(repository),
        base_commit=base_commit,
        workspace_commit=snapshot.current_commit,
        patch_sha256=patch_hash,
        generated_at=datetime.now(
            timezone.utc
        ).isoformat(),
        files=tuple(evidence),
        warnings=tuple(warnings),
        truncated=truncated,
        complete=complete,
    )
