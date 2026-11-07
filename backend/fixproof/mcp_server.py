import json
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .core.config import settings
from .workspaces.git_ops import (
    get_head_commit,
    get_repository_root,
    get_working_tree_status,
    run_git,
)


server = MCPServer(
    name="fixproof",
    title="FixProof MCP Server",
    description="Read-only project inspection tools for FixProof.",
    instructions=(
        "Inspect only the repository explicitly configured by the human. "
        "Do not attempt to modify files, commits, branches, or Git state. "
        "Patch approval and application are human-controlled operations."
    ),
    version="0.1.0",
)


@server.tool(
    name="inspect_project",
    title="Inspect configured project",
    description=(
        "Read the configured Git repository's root, current branch, "
        "HEAD commit, and working-tree status. Accepts no filesystem path "
        "from the calling agent and does not modify the repository."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=False,
)
def inspect_project() -> str:
    """Inspect only the human-configured repository."""

    configured_path: Path | None = settings.repository_path

    if configured_path is None:
        return json.dumps({
            "ok": False,
            "error": "No repository is configured.",
            "configuration": (
                "Set FIXPROOF_REPOSITORY_PATH to an absolute Git "
                "repository path in the FixProof environment."
            ),
        }, indent=2)

    configured_path = configured_path.expanduser()

    if not configured_path.is_absolute():
        return json.dumps({
            "ok": False,
            "error": "The configured repository path must be absolute.",
        }, indent=2)

    try:
        repository = get_repository_root(configured_path)
        head_commit = get_head_commit(repository)
        status = get_working_tree_status(repository)
        branch = run_git(repository, "branch", "--show-current")

        result = {
            "ok": True,
            "repository": str(repository),
            "branch": branch or "(detached HEAD)",
            "head_commit": head_commit,
            "working_tree_clean": not bool(status),
            "working_tree_status": status.splitlines(),
        }

        return json.dumps(result, indent=2)

    except Exception as exc:
        return json.dumps({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }, indent=2)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
