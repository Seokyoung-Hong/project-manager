"""Read-only context for writing a task's pull request description."""

from ninja import Router

from github.pr_context import build_pr_context

from ..context import task_or_404

router = Router(tags=["pull request context"])


@router.get("/{task_id}/pr-context", response=dict)
def get_task_pr_context(request, task_id: int):
    """Return confirmed/effective decision context without publishing a PR."""
    task = task_or_404(request, task_id)
    return build_pr_context(task, actor=request.auth)
