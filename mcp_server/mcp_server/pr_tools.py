"""MCP helper for fetching a task's pull request writing context."""

from .core_client import Core


def get_pr_context(core: Core, task_id: int) -> dict:
    """Fetch access-controlled PR drafting context for a task.

    This is read-only. It does not create or publish a pull request. The core
    API omits pending, rejected, superseded, and verbatim records from the
    drafting context and enforces task and repository visibility.
    """
    return core.get(f"/api/tasks/{task_id}/pr-context")
