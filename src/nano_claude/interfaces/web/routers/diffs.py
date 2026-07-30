"""Diff API routes — list and retrieve checkpoints for the current session."""

from fastapi import APIRouter, HTTPException

from nano_claude.core.state import state
from nano_claude.core.diff_service import (
    get_checkpoint, list_checkpoint_files, list_checkpoints,
)

router = APIRouter()

@router.get("/api/diffs/{checkpoint_filename}")
async def api_get_diff(checkpoint_filename: str):
    """Get the full contents of a specific checkpoint file."""
    cp_data = get_checkpoint(state.cwd, checkpoint_filename)
    if cp_data is None:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    cp_data["files_list"] = list_checkpoint_files(cp_data)
    return cp_data
