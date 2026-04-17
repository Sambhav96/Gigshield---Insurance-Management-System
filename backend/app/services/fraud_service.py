"""
services/fraud_service.py — COMPLETE (audit fix)

3-layer fraud detection per spec Section 10:
  Layer 1 — Intent (GPS + session + platform, ALL required within 60 min)
  Layer 2 — Presence (Haversine + H3 adjacency, ≥2/3 pings)
  Layer 3 — Bayesian score: 1.0 − (0.60×oracle + 0.40×presence)

Hard gates (any fail → fraud_score=1.0, hard-flag, STOP):
  - GPS velocity > 150 km/h between consecutive pings
  - Intent check failed (any factor, platform N/A excepted)
  - Presence < 0.67 (< 2 of 3 pings in zone)
  - Bundle integrity hash mismatch

Geospatial fraud clustering (spec Section 21):
  - Same IP prefix + same enrollment day → suspect cluster
  - Same device fingerprint → blacklisted

Risk decay (spec Section 4.2):
  - Clean week (no payouts) → pull score 2pts toward neutral 50
  - Hard-flag confirmed → +30 immediately
  - Fraud investigation confirmed → score = 100
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from app.utils.haversine import distance_km, implied_speed_kmh
from app.utils.h3_utils import is_in_zone_or_adjacent
from app.external.platform_adapter import get_rider_platform_status

log = structlog.get_logger()

GPS_VELOCITY_LIMIT_KMH  = 150.0
MIN_PINGS_FOR_INTENT    = 3
STATIONARY_RADIUS_M     = 50.0
STATIONARY_MIN_DURATION = 45      # minutes
PRESENCE_MIN_RATIO      = 2 / 3   # 2 of 3 pings must be in zone


# ── Layer 1: Intent check ─────────────────────────────────────────────────────

def check_intent(
    pings: list[dict],
    trigger_time: datetime,
    rider_id: str,
    platform: str,
) -> tuple[bool, dict]:
    """
    F1: ≥3 pings in last 60 min, not stationary 45+ min at residential
    F2: at least 1 session_active ping in last 60 min
    F3: platform status = available | on_delivery (soft; N/A if API down)
    All three must pass. F3=N/A → soft-flag (not hard-flag).
    """
    factors = {
        "f1_gps": False,
        "f2_session": False,
        "f3_platform": False,
        "f3_platform_unavailable": False,
    }

    # F1 — GPS movement pattern
    if len(pings) >= MIN_PINGS_FOR_INTENT:
        is_stat = _is_stationary(pings)
        factors["f1_gps"] = not is_stat
    # else f1_gps stays False

    # F2 — App session heartbeat
    session_pings = [p for p in pings if p.get("session_active")]
    factors["f2_session"] = len(session_pings) >= 1

    # F3 — Platform status
    try:
        platform_result = get_rider_platform_status(rider_id, platform)
        if platform_result is None:
            factors["f3_platform"] = True          # N/A → treat as pass
            factors["f3_platform_unavailable"] = True
        else:
            status = platform_result.get("status", "")
            factors["f3_platform"] = status in ("available", "on_delivery")
    except Exception:
        factors["f3_platform"] = True              # API error → N/A
        factors["f3_platform_unavailable"] = True

    intent_passed = factors["f1_gps"] and factors["f2_session"] and factors["f3_platform"]
    log.info("intent_check", rider_id=rider_id, intent_passed=intent_passed, factors=factors)
    return intent_passed, factors


def _is_stationary(pings: list[dict]) -> bool:
    """True if all pings within 50m and duration ≥ 45 min."""
    if len(pings) < 2:
        return False
    first, last = pings[0], pings[-1]
    spread_km = distance_km(
        float(first["latitude"]), float(first["longitude"]),
        float(last["latitude"]),  float(last["longitude"]),
    )
    if spread_km * 1000 >= STATIONARY_RADIUS_M:
        return False
    t1 = _to_dt(first["recorded_at"])
    t2 = _to_dt(last["recorded_at"])
    return (t2 - t1).total_seconds() / 60 >= STATIONARY_MIN_DURATION


def _to_dt(v) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


# ── Layer 2: Presence check ───────────────────────────────────────────────────

def check_presence(
    pings: list[dict],
    hub_lat: float,
    hub_lng: float,
    hub_radius_km: float,
    hub_h3_index: str,
) -> tuple[float, bool]:
    """
    Returns (presence_confidence, velocity_hard_flag).
    Velocity > 150 km/h between any two pings → hard_flag = True.
    3/3 match → 1.00 | 2/3 → 0.67 | 1/3 → 0.33 (fail) | 0/3 → 0.00.
    """
    if not pings:
        return 0.0, False

    # Velocity spoofing check on ALL consecutive pairs
    for i in range(len(pings) - 1):
        p1, p2 = pings[i], pings[i + 1]
        t1, t2 = _to_dt(p1["recorded_at"]), _to_dt(p2["recorded_at"])
        delta   = (t2 - t1).total_seconds()
        if delta > 0:
            speed = implied_speed_kmh(
                float(p1["latitude"]), float(p1["longitude"]),
                float(p2["latitude"]), float(p2["longitude"]),
                delta,
            )
            if speed > GPS_VELOCITY_LIMIT_KMH:
                log.warning("velocity_spoofing", speed_kmh=speed, p1=str(p1), p2=str(p2))
                return 0.0, True

    # Presence match: last 3 pings
    last_3 = pings[-3:] if len(pings) >= 3 else pings
    match_count = 0
    for ping in last_3:
        dist = distance_km(
            float(ping["latitude"]), float(ping["longitude"]),
            hub_lat, hub_lng,
        )
        in_zone = (
            dist <= hub_radius_km
            or is_in_zone_or_adjacent(float(ping["latitude"]), float(ping["longitude"]), hub_h3_index)
        )
        if in_zone:
            match_count += 1

    n     = len(last_3)
    ratio = match_count / n if n > 0 else 0.0

    if ratio >= 1.0:       confidence = 1.00
    elif ratio >= 2/3:     confidence = 0.67
    elif ratio >= 1/3:     confidence = 0.33   # below minimum threshold
    else:                  confidence = 0.00

    return confidence, False


# ── Layer 3: Bayesian fraud score ─────────────────────────────────────────────

def compute_fraud_score(oracle_confidence: float, presence_confidence: float) -> float:
    """fraud_score = 1.0 − (0.60 × oracle + 0.40 × presence). Clamped [0, 1]."""
    score = 1.0 - (0.60 * oracle_confidence + 0.40 * presence_confidence)
    return round(max(0.0, min(1.0, score)), 4)


def classify_fraud(
    fraud_score: float,
    risk_profile: str = "medium",
    auto_clear_threshold: float = 0.40,
    hard_flag_threshold: float  = 0.70,
) -> str:
    """auto_cleared | soft_flagged | hard_flagged. High-risk tightens thresholds."""
    if risk_profile == "high":
        auto_clear_threshold = min(auto_clear_threshold, 0.30)
        hard_flag_threshold  = min(hard_flag_threshold, 0.60)
    if fraud_score < auto_clear_threshold:
        return "auto_cleared"
    elif fraud_score <= hard_flag_threshold:
        return "soft_flagged"
    return "hard_flagged"


def get_fraud_thresholds(cur, group_id: str, risk_profile: str) -> tuple[float, float]:
    """Read fraud thresholds from experiments table at runtime."""
    auto_clear = 0.40
    hard_flag  = 0.70
    try:
        for param, default in [("auto_clear_fs_threshold", auto_clear), ("hard_flag_fs_threshold", hard_flag)]:
            cur.execute("""
                SELECT parameter_value::float FROM experiments
                WHERE parameter_name = %s AND group_id IN (%s, 'all') AND active = true
                ORDER BY CASE WHEN group_id = %s THEN 0 ELSE 1 END, created_at DESC LIMIT 1
            """, (param, group_id, group_id))
            row = cur.fetchone()
            if row:
                if param == "auto_clear_fs_threshold": auto_clear = float(row["parameter_value"])
                else:                                  hard_flag  = float(row["parameter_value"])
    except Exception as e:
        log.warning("fraud_threshold_read_failed", error=str(e))

    if risk_profile == "high":
        auto_clear = min(auto_clear, 0.30)
        hard_flag  = min(hard_flag, 0.60)

    return auto_clear, hard_flag


# ── Full 3-layer evaluation (async, used by claim initiation) ─────────────────

async def evaluate_claim_fraud(
    conn,
    claim_id: str,
    rider_id: str,
    trigger_id: str,
    policy_id: str,
    oracle_score: float,
    platform: str,
    risk_profile: str = "medium",
) -> dict:
    """Async wrapper for use in FastAPI endpoints (not Celery workers)."""
    trigger_row = await conn.fetchrow(
        "SELECT * FROM trigger_events WHERE id = $1", uuid.UUID(trigger_id)
    )
    if not trigger_row:
        return {"error": "trigger_not_found", "fraud_score": 1.0, "disposition": "hard_flagged"}

    pings = await conn.fetch(
        """
        SELECT latitude, longitude, speed_kmh, recorded_at,
               session_active, platform_status, h3_index_res9
        FROM telemetry_pings
        WHERE rider_id = $1
          AND recorded_at BETWEEN $2 - INTERVAL '60 min' AND $2
        ORDER BY recorded_at ASC
        """,
        uuid.UUID(rider_id), trigger_row["triggered_at"],
    )
    pings_list = [dict(p) for p in pings]

    intent_passed, factors = check_intent(
        pings_list, trigger_row["triggered_at"], rider_id, platform
    )

    if not intent_passed:
        return {
            "fraud_score": 1.0, "disposition": "hard_flagged",
            "intent_passed": False, "intent_factors": factors,
            "presence_confidence": 0.0, "oracle_confidence": oracle_score,
            "hard_flag_reason": "intent_check_failed",
        }

    hub_row = await conn.fetchrow(
        "SELECT * FROM hubs WHERE id = (SELECT hub_id FROM policies WHERE id = $1)",
        uuid.UUID(policy_id),
    )
    if not hub_row:
        return {"fraud_score": 1.0, "disposition": "hard_flagged", "hard_flag_reason": "hub_not_found"}

    presence_conf, velocity_flag = check_presence(
        pings_list,
        float(hub_row["latitude"]), float(hub_row["longitude"]),
        float(hub_row["radius_km"]), hub_row["h3_index_res9"],
    )

    if velocity_flag:
        return {
            "fraud_score": 1.0, "disposition": "hard_flagged",
            "intent_passed": True, "intent_factors": factors,
            "presence_confidence": 0.0, "oracle_confidence": oracle_score,
            "hard_flag_reason": "gps_velocity_spoofing",
        }

    if presence_conf < 0.67:
        return {
            "fraud_score": 1.0, "disposition": "hard_flagged",
            "intent_passed": True, "intent_factors": factors,
            "presence_confidence": presence_conf, "oracle_confidence": oracle_score,
            "hard_flag_reason": "presence_check_failed",
        }

    fraud_score = compute_fraud_score(oracle_score, presence_conf)
    disposition = classify_fraud(fraud_score, risk_profile)

    return {
        "fraud_score": fraud_score, "disposition": disposition,
        "intent_passed": True, "intent_factors": factors,
        "presence_confidence": presence_conf, "oracle_confidence": oracle_score,
        "hard_flag_reason": None,
    }


# ── Geospatial fraud cluster detection (spec Section 21) ─────────────────────

def detect_fraud_cluster(cur, rider_id: str, enrollment_ip_prefix: str, device_fingerprint: str) -> Optional[str]:
    """
    Check if new rider is part of a fraud syndicate.
    Returns cluster_id if found, None otherwise.

    Detection triggers:
    1. Same IP /24 prefix + enrolled within same 24h window → suspect cluster
    2. Device fingerprint in blacklisted_devices → hard reject

    NOTE: Tables blacklisted_devices and fraud_clusters may not exist in all
    environments. All queries are wrapped in try/except for graceful degradation.
    """
    # Check blacklisted device (graceful fallback if table missing)
    if device_fingerprint:
        try:
            cur.execute(
                "SELECT id FROM blacklisted_devices WHERE device_fingerprint = %s LIMIT 1",
                (device_fingerprint,),
            )
            if cur.fetchone():
                log.warning("blacklisted_device_enrollment_attempt", device=device_fingerprint[:16])
                return "BLACKLISTED"
        except Exception as e:
            log.warning("blacklisted_devices_table_unavailable", error=str(e))
            # Degraded mode: skip blacklist check, continue enrollment

    if not enrollment_ip_prefix:
        return None

    # Check IP cluster: ≥3 riders from same /24 in last 24h
    try:
        cur.execute(
            """
            SELECT COUNT(*) AS cnt, ARRAY_AGG(id) AS rider_ids
            FROM riders
            WHERE enrollment_ip_prefix = %s
              AND created_at >= NOW() - INTERVAL '24 hours'
              AND id != %s
            """,
            (enrollment_ip_prefix, rider_id),
        )
        row = cur.fetchone()
    except Exception as e:
        log.warning("fraud_cluster_query_failed", error=str(e))
        return None

    if row and int(row["cnt"] or 0) >= 2:  # 2 others + this rider = 3 total
        cluster_id = hashlib.sha256(
            f"{enrollment_ip_prefix}:{datetime.now(timezone.utc).date()}".encode()
        ).hexdigest()[:16]

        # Upsert cluster record (graceful fallback if table missing)
        try:
            all_rider_ids = list(row["rider_ids"] or []) + [uuid.UUID(rider_id)]
            cur.execute(
                """
                INSERT INTO fraud_clusters (
                    cluster_id, cluster_type, rider_ids,
                    detection_reason, enrollment_ip_prefix, status
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (cluster_id) DO UPDATE
                  SET rider_ids = EXCLUDED.rider_ids,
                      status = EXCLUDED.status
                """,
                (cluster_id, "ip_prefix_cluster", all_rider_ids,
                 "ip_prefix_cluster_24h", enrollment_ip_prefix, "suspected"),
            )
            cur.execute(
                "UPDATE riders SET syndicate_suspect_group_id = %s WHERE id = ANY(%s)",
                (cluster_id, all_rider_ids),
            )
            log.warning("fraud_cluster_detected", cluster_id=cluster_id, rider_count=len(all_rider_ids))
        except Exception as e:
            log.error("fraud_cluster_insert_failed", error=str(e))
            # Still return cluster_id so caller knows a cluster was detected
            # even if we couldn't persist it
            return cluster_id

        return cluster_id

    return None


# ── Risk score decay (spec Section 4.2) ───────────────────────────────────────

def apply_risk_decay(current_score: int, week_had_payouts: bool) -> int:
    """
    Weekly reputation decay: if clean week, pull score 2pts toward neutral 50.
    Hard-flag/fraud events are handled separately (immediate +30 / =100).
    """
    if week_had_payouts:
        return current_score   # no decay on active claim weeks
    direction    = -1 if current_score > 50 else 1
    return max(0, min(100, current_score + (direction * 2)))


def apply_hard_flag_penalty(current_score: int, fraud_confirmed: bool = False) -> int:
    """Immediate risk score increase on hard-flag or confirmed fraud."""
    if fraud_confirmed:
        return 100
    return min(100, current_score + 30)
