from nano_claude.core.workspace import build_workspace_view, get_plan_doc, resolve_latest_plan


def get_workspace_panel(cwd: str, diff_summaries: list[dict] | None = None) -> dict:
    return build_workspace_view(cwd, diff_summaries or [])
