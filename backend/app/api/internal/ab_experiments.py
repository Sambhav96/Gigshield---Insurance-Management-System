"""
api/internal/ab_experiments.py — A/B Experiment Management API
Wires experiment table to the admin Lab tab.
"""
from __future__ import annotations
import json
import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies import get_db, get_current_admin

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentCreate(BaseModel):
    name: str
    parameter_name: str
    parameter_value: str   # JSON string
    group_id: str


@router.get("")
async def list_experiments(admin=Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch(
        "SELECT * FROM experiments ORDER BY activated_at DESC LIMIT 100"
    )
    return {"experiments": [dict(r) for r in rows], "total": len(rows)}


@router.post("")
async def create_experiment(
    body: ExperimentCreate,
    admin=Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    # Deactivate existing for same param+group
    await conn.execute(
        "UPDATE experiments SET active = false WHERE parameter_name = $1 AND group_id = $2",
        body.parameter_name, body.group_id,
    )
    exp_id = await conn.fetchval(
        """
        INSERT INTO experiments (name, parameter_name, parameter_value, group_id, active, set_by_admin_id)
        VALUES ($1, $2, $3, $4, true, $5) RETURNING id
        """,
        body.name, body.parameter_name, body.parameter_value, body.group_id, admin["id"],
    )
    return {"status": "created", "id": str(exp_id)}


@router.delete("/{exp_id}")
async def deactivate_experiment(
    exp_id: str,
    admin=Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    await conn.execute(
        "UPDATE experiments SET active = false, deactivated_at = NOW() WHERE id = $1::uuid",
        exp_id,
    )
    return {"status": "deactivated"}


@router.get("/defaults")
async def seed_experiments(
    admin=Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Seed default experiments for key parameters."""
    from app.services.ab_service import seed_default_experiments
    await seed_default_experiments(conn)
    return {"status": "seeded"}
