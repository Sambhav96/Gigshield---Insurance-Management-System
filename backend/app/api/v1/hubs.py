"""api/v1/hubs.py — Hub listing for rider registration."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query
from app.dependencies import get_db
from app.repositories.hub_repo import list_hubs

router = APIRouter(prefix="/hubs", tags=["hubs"])


@router.get("")
async def get_hubs(
    city: str | None = Query(None),
    conn: asyncpg.Connection = Depends(get_db),
):
    hubs = await list_hubs(conn, city=city)
    return {"hubs": hubs}
