import hashlib
import subprocess

import pytest

from backend.fixproof.verification.compare import (
    generate_evidence,
    _content_from_worktree,
)
from backend.fixproof.workspaces.manager import WorkspaceManager


@pytest.fixture
def evidence_workspace(tmp_path):
    repo = tmp_path / "sample-project"
    repo.mkdir()

    def git(*args):
        subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "--initial-branch=main")
    git("config", "user.name", "FixProof Tests")
    git("config", "user.email", "tests@fixproof.local")

    (repo / "README.md").write_text(
        "# Original version\n",
        encoding="utf-8",
    )

    (repo / "remove.txt").write_text(
        "This file will be deleted.\n",
        encoding="utf-8",
    )

    (repo / ".gitignore").write_text(
        ".env\n",
        encoding="utf-8",
    )

    git("add", ".")
    git("commit", "-m", "Initial evidence test")

    manager = WorkspaceManager(
        tmp_path / "workspaces"
    )

    workspace = manager.create_workspace(
        repo,
        "evidence-test",
    )

    return repo, workspace


def test_detects_modified_added_and_deleted_files(
    evidence_workspace,
):
    repo, workspace = evidence_workspace

    (workspace.path / "README.md").write_text(
        "# Modified version\n",
        encoding="utf-8",
    )

    (workspace.path / "remove.txt").unlink()

    (workspace.path / "new file.txt").write_text(
        "New content\n",
        encoding="utf-8",
    )

    manifest = generate_evidence(workspace)

    changes = {
        item.path: item
        for item in manifest.files
    }

    assert changes["README.md"].change_type == "modified"
    assert changes["remove.txt"].change_type == "deleted"
    assert changes["new file.txt"].change_type == "added"


def test_file_hashes_match_actual_content(evidence_workspace):
    repo, workspace = evidence_workspace

    original = "# Original version\n".encode()
    modified = "# Modified version\n".encode()

    (workspace.path / "README.md").write_bytes(modified)

    manifest = generate_evidence(workspace)

    item = next(
        item for item in manifest.files
        if item.path == "README.md"
    )

    assert item.before_sha256 == hashlib.sha256(
        original
    ).hexdigest()

    assert item.after_sha256 == hashlib.sha256(
        modified
    ).hexdigest()


def test_binary_file_is_detected(evidence_workspace):
    repo, workspace = evidence_workspace

    binary_content = b"\x00\x01\x02\x03\xff"

    (workspace.path / "image.bin").write_bytes(
        binary_content
    )

    manifest = generate_evidence(workspace)

    item = next(
        item for item in manifest.files
        if item.path == "image.bin"
    )

    assert item.is_binary is True
    assert item.after_sha256 == hashlib.sha256(
        binary_content
    ).hexdigest()


def test_manifest_hash_is_deterministic(evidence_workspace):
    repo, workspace = evidence_workspace

    (workspace.path / "README.md").write_text(
        "# Deterministic test\n",
        encoding="utf-8",
    )

    first = generate_evidence(workspace)
    second = generate_evidence(workspace)

    assert first.patch_sha256 == second.patch_sha256


def test_original_repository_advance_is_rejected(
    evidence_workspace,
):
    repo, workspace = evidence_workspace

    (repo / "new-original-file.txt").write_text(
        "Original repository advanced.\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "."],
        cwd=repo,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-m", "Advance original repository"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(RuntimeError, match="moved"):
        generate_evidence(workspace)


def test_ignored_agent_file_is_not_silently_omitted(
    evidence_workspace,
):
    repo, workspace = evidence_workspace

    secret_file = workspace.path / ".env"
    secret_file.write_text(
        "API_KEY=synthetic-test-secret\n",
        encoding="utf-8",
    )

    manifest = generate_evidence(workspace)

    ignored_entries = [
        item for item in manifest.files
        if item.path == ".env"
    ]

    assert ignored_entries
    assert manifest.complete is False
    assert any(
        ".env" in warning
        for warning in manifest.warnings
    )


def test_path_traversal_is_rejected(evidence_workspace, tmp_path):
    _, workspace = evidence_workspace

    outside = tmp_path / "outside.txt"
    outside.write_text("Private data", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Unsafe workspace file path"):
        _content_from_worktree(workspace.path, "../outside.txt")


def test_external_symlink_target_is_not_read(
    evidence_workspace,
    tmp_path,
):
    _, workspace = evidence_workspace

    outside = tmp_path / "private.txt"
    outside.write_text("SYNTHETIC_PRIVATE_DATA", encoding="utf-8")

    link = workspace.path / "external-link.txt"

    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"Windows symlink permission unavailable: {exc}")

    captured = _content_from_worktree(
        workspace.path,
        "external-link.txt",
    )

    assert b"SYNTHETIC_PRIVATE_DATA" not in captured
