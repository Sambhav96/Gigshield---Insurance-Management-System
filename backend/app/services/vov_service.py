"""
services/vov_service.py — GAP-01 FIX

Spec §26.1: vov-service owns claim_evidence, zone_vov_certs, YOLOv8 inference.
This is the service layer — Celery workers call into these functions.

GAP-11 FIX: VOV zone cert enforces BOTH conditions:
  confirmed >= 5 (absolute minimum — prevents 2-person collusion)
  confirmed / submitted >= 0.80

Cert check with 2 confirmed / 2 submitted = 100% ratio BUT < 5 confirmed → REJECT.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import structlog

log = structlog.get_logger()

VOV_WINDOW_HOURS        = 3
VOV_MIN_CONFIRMED       = 5       # GAP-11: absolute minimum, prevents 2-person collusion
VOV_CERT_RATIO          = 0.80    # 80% of submitted must be confirmed
VOV_CONFIDENCE_FLOOR    = 0.70    # cv_confidence >= 0.70 = confirmed
VOV_REWARD_INDIVIDUAL   = 15.0    # ₹ per confirmed video
VOV_REWARD_ZONE_CERT    = 20.0    # ₹ additional for zone cert contribution


async def check_vov_zone_certification(
    conn: asyncpg.Connection,
    h3_index: str,
    trigger_id: str,
) -> dict:
    """
    GAP-11 FIX: Enforce BOTH conditions:
      1. confirmed >= 5  (absolute minimum)
      2. confirmed / submitted >= 0.80

    Returns {certified, confirmed, submitted, avg_conf, certified_oracle}
    """
    trigger_uid = uuid.UUID(trigger_id)

    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE cv_confidence >= $1) AS confirmed,
            COUNT(*)                                    AS submitted,
            AVG(cv_confidence) FILTER (WHERE cv_confidence >= $1) AS avg_conf
        FROM claim_evidence
        WHERE h3_index = $2
          AND created_at >= (SELECT triggered_at FROM trigger_events WHERE id = $3)
          AND created_at <= (SELECT triggered_at FROM trigger_events WHERE id = $3) + INTERVAL '3 hours'
        """,
        VOV_CONFIDENCE_FLOOR, h3_index, trigger_uid,
    )

    confirmed  = int(row["confirmed"] or 0)
    submitted  = int(row["submitted"] or 0)
    avg_conf   = float(row["avg_conf"] or 0.0)

    # GAP-11: BOTH conditions must be true
    cert_ratio_ok  = submitted > 0 and (confirmed / submitted) >= VOV_CERT_RATIO
    cert_count_ok  = confirmed >= VOV_MIN_CONFIRMED

    if not (cert_count_ok and cert_ratio_ok):
        return {
            "certified": False, "confirmed": confirmed, "submitted": submitted,
            "avg_conf": avg_conf, "reason": f"need_min_{VOV_MIN_CONFIRMED}_confirmed_and_{VOV_CERT_RATIO*100:.0f}pct_ratio",
        }

    # Certify zone
    await conn.execute(
        """
        INSERT INTO zone_vov_certs (
            h3_index, trigger_id, submitted_count, confirmed_count,
            avg_cv_confidence, certified, certified_at, expires_at
        ) VALUES ($1,$2,$3,$4,$5,true,NOW(),NOW()+INTERVAL '2 hours')
        ON CONFLICT (h3_index, trigger_id) DO UPDATE
          SET certified=true, certified_at=NOW(), confirmed_count=$4, avg_cv_confidence=$5
        """,
        h3_index, trigger_uid, submitted, confirmed, avg_conf,
    )
    await conn.execute(
        "UPDATE trigger_events SET vov_zone_certified=true, vov_cert_score=$1 WHERE id=$2",
        avg_conf, trigger_uid,
    )

    # New certified oracle score
    trigger = await conn.fetchrow("SELECT * FROM trigger_events WHERE id=$1", trigger_uid)
    sat     = float(trigger.get("satellite_score") or 0)
    wth     = float(trigger.get("weather_score") or 0)
    certified_oracle = 0.40 * sat + 0.30 * wth + 0.30 * avg_conf

    log.info("zone_certified", h3_index=h3_index, trigger_id=trigger_id,
             confirmed=confirmed, submitted=submitted, oracle=certified_oracle)

    return {
        "certified": True, "confirmed": confirmed, "submitted": submitted,
        "avg_conf": avg_conf, "certified_oracle": certified_oracle,
    }


async def record_vov_submission(
    conn: asyncpg.Connection,
    rider_id: str,
    claim_id: str,
    trigger_id: str,
    h3_index: str,
    video_url: str,
    exif_valid: bool,
    cv_confidence: float,
    gear_detected: bool,
) -> dict:
    """Record a VOV evidence submission. Used by vov_worker after YOLOv8 inference."""
    # Boost confidence if gear detected
    if gear_detected and cv_confidence >= 0.50:
        cv_confidence = max(cv_confidence, 0.95)

    evidence_id = await conn.fetchval(
        """
        UPDATE claim_evidence
        SET exif_valid=$1, cv_confidence=$2, gear_detected=$3
        WHERE claim_id=$4 AND rider_id=$5
        RETURNING id
        """,
        exif_valid, cv_confidence, gear_detected,
        uuid.UUID(claim_id), uuid.UUID(rider_id),
    )

    # Issue individual reward if confirmed
    reward_issued = False
    if cv_confidence >= VOV_CONFIDENCE_FLOOR and exif_valid:
        from app.workers.vov_worker import _issue_vov_reward
        _issue_vov_reward.delay(rider_id, claim_id, "individual", VOV_REWARD_INDIVIDUAL)
        reward_issued = True

    # Check zone certification
    cert_result = await check_vov_zone_certification(conn, h3_index, trigger_id)

    return {
        "evidence_id":    str(evidence_id),
        "cv_confidence":  cv_confidence,
        "gear_detected":  gear_detected,
        "exif_valid":     exif_valid,
        "confirmed":      cv_confidence >= VOV_CONFIDENCE_FLOOR,
        "reward_issued":  reward_issued,
        "zone_cert":      cert_result,
    }


async def validate_vov_window(
    conn: asyncpg.Connection,
    trigger_id: str,
) -> tuple[bool, str]:
    """Check if VOV submission window is still open (3 hours after trigger)."""
    trigger = await conn.fetchrow("SELECT triggered_at FROM trigger_events WHERE id=$1", uuid.UUID(trigger_id))
    if not trigger:
        return False, "trigger_not_found"

    db_now     = await conn.fetchval("SELECT NOW()")
    window_end = trigger["triggered_at"] + timedelta(hours=VOV_WINDOW_HOURS)

    if db_now > window_end:
        return False, "window_closed"
    return True, "open"


async def validate_bundle_integrity(
    rider_id: str,
    pings: list[dict],
    submitted_hash: str,
) -> tuple[bool, str]:
    """
    GAP-10 FIX: Bundle fraud checks per spec §10.5:
    1. Hash integrity: recompute SHA-256 on server
    2. Interval uniformity: std_dev of gaps < 0.5s = fabricated
    3. H3 consistency: all pings <= 1 H3 ring apart
    """
    import hashlib, statistics
    from datetime import datetime, timezone
    from app.utils.h3_utils import latlng_to_h3, get_adjacent_cells

    # 1. Hash integrity
    timestamps = sorted([p["recorded_at"] for p in pings])
    computed_hash = hashlib.sha256(str(timestamps).encode()).hexdigest()
    if computed_hash != submitted_hash:
        return False, "hash_integrity_failed"

    # 2. Interval uniformity — gaps < 0.5s std-dev = fabricated
    if len(pings) >= 3:
        times = []
        for p in pings:
            t = p["recorded_at"]
            if isinstance(t, str):
                t = datetime.fromisoformat(t.replace("Z", "+00:00"))
            times.append(t.timestamp())
        times.sort()
        gaps = [times[i+1] - times[i] for i in range(len(times)-1)]
        if gaps:
            std = statistics.stdev(gaps) if len(gaps) > 1 else 0
            if std < 0.5 and len(gaps) > 5:
                return False, "interval_uniformity_failed_fabricated_timestamps"

    # 3. H3 consistency — all pings within 1 ring of first ping
    if len(pings) >= 2:
        first      = pings[0]
        base_h3    = latlng_to_h3(float(first["latitude"]), float(first["longitude"]), 9)
        adjacent   = get_adjacent_cells(base_h3)
        allowed    = {base_h3} | set(adjacent)
        for p in pings[1:]:
            ping_h3 = latlng_to_h3(float(p["latitude"]), float(p["longitude"]), 9)
            if ping_h3 not in allowed:
                return False, "h3_consistency_failed_impossible_movement"

    return True, "ok"
