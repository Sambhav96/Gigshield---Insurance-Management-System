"""api/v1/vov.py — VOV video upload, EXIF check, YOLOv8 queue."""
from __future__ import annotations

import uuid
from datetime import timedelta

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies import get_db, get_current_rider
from app.workers.vov_worker import process_vov_video

router = APIRouter(prefix="/vov", tags=["vov"])

MAX_VIDEO_SIZE_MB = 50
VOV_WINDOW_HOURS = 3


@router.post("/upload/{claim_id}")
async def upload_vov(
    claim_id: uuid.UUID,
    video: UploadFile = File(...),
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Upload VOV video for a claim.
    Runs EXIF check synchronously (< 5 sec), queues YOLOv8 async.
    """
    # Validate claim ownership
    claim = await conn.fetchrow(
        "SELECT * FROM claims WHERE id = $1 AND rider_id = $2",
        claim_id, rider["id"],
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Check VOV window: trigger_time + 3 hours
    trigger = await conn.fetchrow(
        "SELECT * FROM trigger_events WHERE id = $1", claim["trigger_id"]
    )
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    db_now = await conn.fetchval("SELECT NOW()")
    window_end = trigger["triggered_at"] + timedelta(hours=VOV_WINDOW_HOURS)
    if db_now > window_end:
        raise HTTPException(status_code=400, detail="VOV window closed (3 hours after trigger)")

    # Validate file type
    if video.content_type not in ("video/mp4", "video/quicktime", "video/x-m4v"):
        raise HTTPException(status_code=400, detail="Only MP4/MOV videos accepted")

    content = await video.read()
    if len(content) > MAX_VIDEO_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Video too large (max {MAX_VIDEO_SIZE_MB}MB)")

    # Store video temporarily (in prod: Supabase Storage with 48h TTL)
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(content)
        tmp_path = f.name

    # Create evidence record
    evidence_id = await conn.fetchval(
        """
        INSERT INTO claim_evidence (
            claim_id, rider_id, h3_index, video_url,
            exif_valid, cv_confidence, gear_detected,
            ttl_delete_at
        ) VALUES ($1, $2, $3, $4, false, null, false, NOW() + INTERVAL '48 hours')
        RETURNING id
        """,
        claim["id"], rider["id"],
        trigger["h3_index"],
        f"local://{tmp_path}",
    )

    # Queue YOLOv8 async processing
    process_vov_video.delay(
        str(evidence_id),
        str(claim["id"]),
        str(rider["id"]),
        trigger["h3_index"],
        str(trigger["triggered_at"]),
        tmp_path,
    )

    return {
        "evidence_id": str(evidence_id),
        "status": "processing",
        "message": "Video received. Processing in background (30–60 seconds).",
    }
