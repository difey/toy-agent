"""Diff API routes — list and retrieve diffs for the current session."""

from fastapi import APIRouter, HTTPException

from nano_claude.interfaces.web.state import state
from nano_claude.interfaces.web.services.diff_service import get_diff, list_diffs

router = APIRouter()


@router.get("/api/diffs/list")
async def api_list_diffs():
    """List all diffs for the current session, most recent first."""
    return list_diffs(state.cwd)


@router.get("/api/diffs/{diff_filename}")
async def api_get_diff(diff_filename: str):
    """Get the full contents of a specific diff file."""
    diff_data = get_diff(state.cwd, diff_filename)
    if diff_data is None:
        raise HTTPException(status_code=404, detail="Diff not found")
    return diff_data
