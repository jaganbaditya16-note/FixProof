import hashlib
import os
import subprocess
import tempfile

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.fixproof.verification.compare import generate_evidence
from backend.fixproof.workspaces.git_ops import (
    get_head_commit,
    get_repository_root,
)
from backend.fixproof.workspaces.models import Workspace


MAX_PATCH_SIZE = 25 * 1024 * 1024


@dataclass(frozen=True)
class PatchArtifact:
    workspace_id: str
    base_commit: str
    manifest_sha256: str
    patch_sha256: str
    patch_bytes: bytes
    file_count: int
    created_at: str


def _run_git(
    directory: Path,
    env: dict[str, str],
    *args: str,
) -> bytes:
    """Execute Git using an isolated temporary index."""

    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(directory),
            env=env,
            capture_output=True,
            shell=False,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Patch generation timed out."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Could not execute Git: {exc}"
        ) from exc

    if result.returncode != 0:
        message = result.stderr.decode(
            "utf-8",
            errors="replace",
        )
        raise RuntimeError(
            f"Patch Git operation failed: {message}"
        )

    return result.stdout


def generate_patch(
    workspace: Workspace,
    expected_manifest_sha256: str,
) -> PatchArtifact:
    """Generate a binary-safe Git patch tied to current evidence."""

    repository = get_repository_root(
        workspace.repository
    )

    if get_head_commit(repository) != workspace.base_commit:
        raise RuntimeError(
            "Original repository changed. Patch generation blocked."
        )

    manifest = generate_evidence(workspace)

    if not manifest.complete:
        raise RuntimeError(
            "Evidence is incomplete. Resolve all warnings "
            "before generating an approvable patch."
        )

    if manifest.patch_sha256 != expected_manifest_sha256:
        raise RuntimeError(
            "Evidence changed. Generate a new review."
        )

    env = os.environ.copy()

    with tempfile.TemporaryDirectory(
        prefix="fixproof-index-"
    ) as temporary_directory:

        index_path = Path(temporary_directory) / "index"

        env["GIT_INDEX_FILE"] = str(index_path)

        _run_git(
            workspace.path,
            env,
            "read-tree",
            workspace.base_commit,
        )

        _run_git(
            workspace.path,
            env,
            "add",
            "-A",
            "--",
            ".",
        )

        patch = _run_git(
            workspace.path,
            env,
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-renames",
            "--no-ext-diff",
            "--no-color",
            workspace.base_commit,
            "--",
        )

    if len(patch) > MAX_PATCH_SIZE:
        raise RuntimeError(
            "Generated patch exceeds the 25 MB limit."
        )

    patch_hash = hashlib.sha256(patch).hexdigest()

    return PatchArtifact(
        workspace_id=workspace.workspace_id,
        base_commit=workspace.base_commit,
        manifest_sha256=manifest.patch_sha256,
        patch_sha256=patch_hash,
        patch_bytes=patch,
        file_count=len(manifest.files),
        created_at=datetime.now(
            timezone.utc
        ).isoformat(),
    )
