"""文件系统浏览 API：供前端「引用文件」选择器使用。

不限制工作区：可浏览任意目录（绝对路径）；返回一律为绝对路径。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api")


@router.get("/fs/list")
def fs_list(path: str = "") -> dict:
    """列出指定目录的内容（目录在前、文件在后，按名称排序）。

    - path：要浏览的绝对路径（"" = 根目录 /）。
    返回 entries（name/type/path 均为绝对路径），parent 为上级绝对路径（根目录为 None）。
    """
    cur = Path(path).resolve() if path else Path("/")
    if not cur.is_dir():
        raise HTTPException(status_code=400, detail="不是目录")

    def _key(p: Path) -> tuple[int, str]:
        return (0 if p.is_dir() else 1, p.name.lower())

    try:
        children = sorted(cur.iterdir(), key=_key)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"无法访问该目录: {exc}") from exc

    entries = [
        {
            "name": p.name,
            "type": "dir" if p.is_dir() else "file",
            "path": str(p.resolve()),
        }
        for p in children
    ]
    parent = str(cur.parent) if cur != cur.parent else None
    return {"path": str(cur), "parent": parent, "entries": entries}
