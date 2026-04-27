import json
import os

from nano_claude.tool import Tool, ToolContext, ToolExecResult


TODO_STORE_FILE = os.path.join(
    os.path.expanduser("~"), ".nano_claude", "todos.json"
)


def _load_todos() -> list[dict]:
    if not os.path.exists(TODO_STORE_FILE):
        return []
    try:
        with open(TODO_STORE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_todos(todos: list[dict]) -> None:
    os.makedirs(os.path.dirname(TODO_STORE_FILE), exist_ok=True)
    with open(TODO_STORE_FILE, "w") as f:
        json.dump(todos, f, indent=2)


class TodoWriteTool(Tool):
    @property
    def name(self) -> str:
        return "todowrite"

    @property
    def description(self) -> str:
        return (
            "Create and manage a structured task list (todos) for tracking "
            "multi-step task progress. Use this tool to plan, track, and update "
            "tasks when working on complex multi-step objectives. "
            "Each todo item has content, status (pending/in_progress/completed/cancelled), "
            "and priority (high/medium/low). "
            "The task list is persisted across sessions."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The full list of todo items (provide ALL items, this replaces the entire list)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Task description",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "Task status",
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": "Task priority",
                            },
                        },
                        "required": ["content", "status", "priority"],
                    },
                },
            },
            "required": ["todos"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        todos: list[dict] = args["todos"]

        _save_todos(todos)

        active = [t for t in todos if t["status"] not in ("completed", "cancelled")]
        completed = [t for t in todos if t["status"] == "completed"]
        cancelled = [t for t in todos if t["status"] == "cancelled"]

        summary_parts = []
        if active:
            summary_parts.append(f"{len(active)} active")
        if completed:
            summary_parts.append(f"{len(completed)} completed")
        if cancelled:
            summary_parts.append(f"{len(cancelled)} cancelled")

        summary = ", ".join(summary_parts) if summary_parts else "0 todos"

        return ToolExecResult(
            title=f"todowrite [{summary}]",
            output=json.dumps(todos, indent=2, ensure_ascii=False),
        )
