"""dependencies.py — FastAPI dependency injection (auth, db, redis)."""
from __future__ import annotations

import uuid
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_db_connection
from app.core.security import decode_access_token
from jose import JWTError

bearer = HTTPBearer(auto_error=True)


async def get_db(conn: asyncpg.Connection = Depends(get_db_connection)) -> asyncpg.Connection:
    return conn


async def get_current_rider(
    credentials: HTTPAuthorizationCredentials = Security(bearer),
    conn: asyncpg.Connection = Depends(get_db),
) -> dict:
    try:
        payload = decode_access_token(credentials.credentials)
        rider_id: str = payload.get("sub")
        if not rider_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    row = await conn.fetchrow("SELECT * FROM riders WHERE id = $1", UUID(rider_id))
    if not row:
        raise HTTPException(status_code=401, detail="Rider not found")
    return dict(row)


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Security(bearer),
    conn: asyncpg.Connection = Depends(get_db),
) -> dict:
    try:
        payload = decode_access_token(credentials.credentials)
        role: str = payload.get("role", "")
        if role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        admin_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    row = await conn.fetchrow("SELECT * FROM admin_users WHERE id = $1", UUID(admin_id))
    if not row:
        raise HTTPException(status_code=401, detail="Admin not found")
    return dict(row)


async def get_current_hub_manager(
    credentials: HTTPAuthorizationCredentials = Security(bearer),
    conn: asyncpg.Connection = Depends(get_db),
) -> dict:
    try:
        payload = decode_access_token(credentials.credentials)
        role: str = payload.get("role", "")
        if role not in ("hub", "admin"):
            raise HTTPException(status_code=403, detail="Hub access required")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    raw_hub_ids = payload.get("hub_ids") or []
    if not raw_hub_ids and payload.get("hub_id"):
        raw_hub_ids = [payload.get("hub_id")]

    hub_ids: list[UUID] = []
    for raw in raw_hub_ids:
        try:
            hub_ids.append(uuid.UUID(str(raw)))
        except Exception:
            continue

    if role == "admin" and not hub_ids:
        rows = await conn.fetch("SELECT id FROM hubs")
        hub_ids = [row["id"] for row in rows]

    if not hub_ids:
        raise HTTPException(status_code=403, detail="No hub scope found in token")

    return {
        "manager_id": payload.get("sub"),
        "role": role,
        "hub_id": hub_ids[0],
        "hub_ids": hub_ids,
    }
