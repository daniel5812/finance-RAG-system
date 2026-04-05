"""
documents/routes/folders.py — Folder CRUD for document organization.

POST   /folders/          create a folder
GET    /folders/          list all folders for the authenticated user
DELETE /folders/{id}      delete a folder (documents lose their folder_id via FK)
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
import asyncpg
from asyncpg.exceptions import UniqueViolationError

from core.dependencies import get_db_pool, get_current_user
from core.logger import get_logger
from documents.crud import create_folder, list_folders, get_folder, delete_folder

logger = get_logger(__name__)
router = APIRouter(prefix="/folders", tags=["folders"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class FolderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class FolderResponse(BaseModel):
    id: int
    name: str
    owner_id: str
    created_at: datetime


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=FolderResponse, status_code=201)
async def create_folder_route(
    body: FolderCreateRequest,
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> FolderResponse:
    """Create a new folder scoped to the authenticated user."""
    name = body.name.strip()
    try:
        row = await create_folder(pool, owner_id=user_id, name=name)
    except UniqueViolationError:
        raise HTTPException(status_code=409, detail=f"Folder '{name}' already exists.")
    logger.info(f"folder_created user={user_id} folder_id={row['id']} name={name!r}")
    return FolderResponse(**row)


@router.get("/", response_model=List[FolderResponse])
async def list_folders_route(
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
) -> List[FolderResponse]:
    """List all folders belonging to the authenticated user."""
    rows = await list_folders(pool, owner_id=user_id)
    return [FolderResponse(**r) for r in rows]


@router.delete("/{folder_id}", status_code=200)
async def delete_folder_route(
    folder_id: int,
    user_id: str = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Delete a folder (ownership enforced). Documents in the folder become unassigned."""
    folder = await get_folder(pool, folder_id=folder_id, owner_id=user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found.")
    await delete_folder(pool, folder_id=folder_id, owner_id=user_id)
    logger.info(f"folder_deleted user={user_id} folder_id={folder_id}")
    return {"status": "deleted", "folder_id": folder_id}
