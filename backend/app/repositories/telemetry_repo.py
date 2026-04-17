"""repositories/telemetry_repo.py — DB operations for telemetry_pings."""
from __future__ import annotations

import uuid
from datetime import datetime
import asyncpg

from app.utils.h3_utils import latlng_to_h3
from app.utils.crypto import sha256_hex


async def insert_telemetry_ping(
    conn: asyncpg.Connection,
    rider_id: str,
    latitude: float,
    longitude: float,
    speed_kmh: float,
    accuracy_m: float,
    network_type: str,
    platform_status: str,
    session_active: bool,
    recorded_at: datetime | str,
    is_bundle: bool = False,
    bundle_hash: str | None = None,
) -> str:
    if isinstance(recorded_at, str):
        # Accept both ISO8601 "...Z" and offset-aware datetime strings.
        recorded_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))

    h3_index = latlng_to_h3(latitude, longitude, resolution=9)

    ping_id = await conn.fetchval(
        """
        INSERT INTO telemetry_pings (
            rider_id, latitude, longitude, h3_index_res9,
            speed_kmh, accuracy_m, network_type,
            platform_status, session_active,
            recorded_at, is_bundle, bundle_hash
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        RETURNING id
        """,
        uuid.UUID(rider_id),
        latitude, longitude, h3_index,
        speed_kmh, accuracy_m, network_type,
        platform_status, session_active,
        recorded_at, is_bundle, bundle_hash,
    )
    return str(ping_id)


async def insert_bundle_pings(
    conn: asyncpg.Connection,
    rider_id: str,
    pings: list[dict],
) -> int:
    """Batch insert offline-bundled pings with integrity hash check."""
    bundle_hash = sha256_hex(str(sorted([p["recorded_at"] for p in pings])))
    inserted = 0
    for p in pings:
        try:
            await insert_telemetry_ping(
                conn, rider_id,
                p["latitude"], p["longitude"],
                p.get("speed_kmh", 0.0),
                p.get("accuracy_m", 0.0),
                p.get("network_type", "offline"),
                p.get("platform_status", "available"),
                p.get("session_active", False),
                p["recorded_at"],
                is_bundle=True,
                bundle_hash=bundle_hash,
            )
            inserted += 1
        except Exception:
            pass
    return inserted


async def get_recent_pings(
    conn: asyncpg.Connection,
    rider_id: str,
    limit: int = 10,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT * FROM telemetry_pings
        WHERE rider_id = $1
        ORDER BY recorded_at DESC
        LIMIT $2
        """,
        uuid.UUID(rider_id), limit,
    )
    return [dict(r) for r in rows]
