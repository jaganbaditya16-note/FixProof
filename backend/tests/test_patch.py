import hashlib
import subprocess

import pytest

from backend.fixproof.verification.compare import generate_evidence
from backend.fixproof.verification.patch import generate_patch
from backend.fixproof.workspaces.manager import WorkspaceManager


@pytest.fixture
def patch_workspace(tmp_path):
    repo = tmp_path / "patch-project"
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
        "Original content\n",
        encoding="utf-8",
    )

    (repo / ".gitignore").write_text(
        ".env\n",
        encoding="utf-8",
    )

    git("add", ".")
    git("commit", "-m", "Initial commit")

    manager = WorkspaceManager(
        tmp_path / "workspaces"
    )

    workspace = manager.create_workspace(
        repo,
        "patch-test",
    )

    return repo, workspace


def test_patch_contains_real_code_changes(patch_workspace):
    _, workspace = patch_workspace

    (workspace.path / "README.md").write_text(
        "Updated content\n",
        encoding="utf-8",
    )

    (workspace.path / "new file.txt").write_text(
        "New file content\n",
        encoding="utf-8",
    )

    manifest = generate_evidence(workspace)

    artifact = generate_patch(
        workspace,
        manifest.patch_sha256,
    )

    assert b"Updated content" in artifact.patch_bytes
    assert b"New file content" in artifact.patch_bytes
    assert artifact.file_count == 2


def test_patch_hash_matches_actual_bytes(patch_workspace):
    _, workspace = patch_workspace

    (workspace.path / "README.md").write_text(
        "Hash verification\n",
        encoding="utf-8",
    )

    manifest = generate_evidence(workspace)

    artifact = generate_patch(
        workspace,
        manifest.patch_sha256,
    )

    expected_hash = hashlib.sha256(
        artifact.patch_bytes
    ).hexdigest()

    assert artifact.patch_sha256 == expected_hash


def test_patch_generation_does_not_change_real_index(
    patch_workspace,
):
    _, workspace = patch_workspace

    (workspace.path / "README.md").write_text(
        "Unstaged change\n",
        encoding="utf-8",
    )

    before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace.path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    manifest = generate_evidence(workspace)

    generate_patch(
        workspace,
        manifest.patch_sha256,
    )

    after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace.path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert before == after


def test_modified_workspace_invalidates_old_evidence(
    patch_workspace,
):
    _, workspace = patch_workspace

    (workspace.path / "README.md").write_text(
        "First version\n",
        encoding="utf-8",
    )

    old_manifest = generate_evidence(workspace)

    (workspace.path / "README.md").write_text(
        "Changed after review\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Evidence changed"):
        generate_patch(
            workspace,
            old_manifest.patch_sha256,
        )


def test_ignored_file_blocks_patch_generation(
    patch_workspace,
):
    _, workspace = patch_workspace

    (workspace.path / ".env").write_text(
        "API_KEY=synthetic-test-value\n",
        encoding="utf-8",
    )

    manifest = generate_evidence(workspace)

    assert manifest.complete is False
    assert any(".env" in warning for warning in manifest.warnings)

    with pytest.raises(RuntimeError, match="incomplete"):
        generate_patch(
            workspace,
            manifest.patch_sha256,
        )



def test_patch_applies_to_clean_repository_copy(patch_workspace, tmp_path):
    repo, workspace = patch_workspace

    (workspace.path / "README.md").write_text(
        "Reviewed updated content\n",
        encoding="utf-8",
    )

    (workspace.path / "new file.txt").write_text(
        "New approved file\n",
        encoding="utf-8",
    )

    manifest = generate_evidence(workspace)
    artifact = generate_patch(workspace, manifest.patch_sha256)

    target = tmp_path / "application-copy"

    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(repo), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )

    check = subprocess.run(
        ["git", "apply", "--check", "--binary"],
        cwd=target,
        input=artifact.patch_bytes,
        capture_output=True,
        check=False,
    )

    assert check.returncode == 0, check.stderr.decode(
        "utf-8", errors="replace"
    )

    subprocess.run(
        ["git", "apply", "--binary"],
        cwd=target,
        input=artifact.patch_bytes,
        check=True,
        capture_output=True,
    )

    assert (target / "README.md").read_text(
        encoding="utf-8"
    ) == "Reviewed updated content\n"

    assert (target / "new file.txt").read_text(
        encoding="utf-8"
    ) == "New approved file\n"

    assert (repo / "README.md").read_text(
        encoding="utf-8"
    ) == "Original content\n"


def test_binary_patch_applies_correctly(patch_workspace, tmp_path):
    repo, workspace = patch_workspace

    binary_content = bytes(range(256)) + b"\x00FIXPROOF"

    (workspace.path / "image.bin").write_bytes(binary_content)

    manifest = generate_evidence(workspace)

    binary_evidence = next(
        item for item in manifest.files
        if item.path == "image.bin"
    )

    assert binary_evidence.is_binary is True

    artifact = generate_patch(workspace, manifest.patch_sha256)

    assert b"GIT binary patch" in artifact.patch_bytes

    target = tmp_path / "binary-application-copy"

    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(repo), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "apply", "--check", "--binary"],
        cwd=target,
        input=artifact.patch_bytes,
        check=True,
        capture_output=True,
    )

    subprocess.run(
        ["git", "apply", "--binary"],
        cwd=target,
        input=artifact.patch_bytes,
        check=True,
        capture_output=True,
    )

    assert (target / "image.bin").read_bytes() == binary_content
