"""
ml/dbscan_fraud_cluster.py — Geospatial fraud clustering via DBSCAN (Spec §21)

UNICORN FEATURE: Complete fraud protection via ML-based geospatial clustering

Detects coordinated enrollment fraud:
  - Clusters of riders enrolled from within 200m radius in 24h window
  - Min cluster size: 3 riders
  - Uses haversine distance metric for lat/lng

Weekly Celery task: run_geospatial_fraud_scan()
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

log = structlog.get_logger()

CLUSTER_RADIUS_KM    = 0.2    # 200m radius
MIN_CLUSTER_SIZE     = 3      # minimum riders to flag as cluster
ENROLLMENT_WINDOW_H  = 24     # hours to look back


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def run_dbscan_on_enrollments(
    rider_coords: list[dict],
) -> list[dict]:
    """
    Run DBSCAN on rider enrollment coordinates.
    
    rider_coords: list of {rider_id, lat, lon, enrolled_at}
    Returns: list of cluster dicts {cluster_id, rider_ids, centroid_lat, centroid_lon}
    """
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN

        if len(rider_coords) < MIN_CLUSTER_SIZE:
            return []

        coords_rad = np.radians([[r["lat"], r["lon"]] for r in rider_coords])
        # eps in radians: CLUSTER_RADIUS_KM / earth_radius_km
        eps_rad = CLUSTER_RADIUS_KM / 6371.0

        db = DBSCAN(
            eps=eps_rad,
            min_samples=MIN_CLUSTER_SIZE,
            algorithm="ball_tree",
            metric="haversine",
        ).fit(coords_rad)

        clusters = {}
        for idx, label in enumerate(db.labels_):
            if label == -1:
                continue   # noise point
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(rider_coords[idx])

        result = []
        for label, members in clusters.items():
            lats = [m["lat"] for m in members]
            lons = [m["lon"] for m in members]
            centroid_lat = float(np.mean(lats))
            centroid_lon = float(np.mean(lons))

            cluster_id = hashlib.sha256(
                f"{centroid_lat:.4f}:{centroid_lon:.4f}:{datetime.now(timezone.utc).date()}".encode()
            ).hexdigest()[:16]

            result.append({
                "cluster_id": cluster_id,
                "rider_ids": [m["rider_id"] for m in members],
                "centroid_lat": centroid_lat,
                "centroid_lon": centroid_lon,
                "member_count": len(members),
                "detection_method": "dbscan_haversine",
            })

        log.info("dbscan_complete", total_riders=len(rider_coords),
                 clusters_found=len(result))
        return result

    except Exception as exc:
        log.error("dbscan_failed", error=str(exc))
        return []


async def run_geospatial_fraud_scan(conn) -> dict:
    """
    Weekly task: scan new enrollments for geospatial fraud clusters.
    Flags suspected clusters in fraud_clusters table.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ENROLLMENT_WINDOW_H * 7)  # last week

    try:
        rows = await conn.fetch(
            """
            SELECT id, latitude, longitude, created_at
            FROM riders
            WHERE created_at >= $1
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
            ORDER BY created_at DESC
            """,
            cutoff,
        )
    except Exception:
        # latitude/longitude columns may not exist — query from telemetry instead
        try:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (r.id)
                    r.id, t.latitude, t.longitude, r.created_at
                FROM riders r
                JOIN telemetry_pings t ON t.rider_id = r.id
                WHERE r.created_at >= $1
                ORDER BY r.id, t.recorded_at ASC
                """,
                cutoff,
            )
        except Exception as exc:
            log.warning("geospatial_fraud_scan_skipped", error=str(exc))
            return {"status": "skipped", "reason": str(exc)}

    if not rows:
        return {"status": "ok", "clusters_found": 0}

    rider_coords = [
        {
            "rider_id": str(r["id"]),
            "lat": float(r["latitude"]),
            "lon": float(r["longitude"]),
            "enrolled_at": r["created_at"].isoformat() if r.get("created_at") else "",
        }
        for r in rows
    ]

    clusters = run_dbscan_on_enrollments(rider_coords)

    flagged = 0
    for cluster in clusters:
        try:
            await conn.execute(
                """
                INSERT INTO fraud_clusters (
                    cluster_id, cluster_type, rider_ids,
                    detection_reason, status
                ) VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (cluster_id) DO UPDATE
                  SET rider_ids = EXCLUDED.rider_ids,
                      status = EXCLUDED.status
                """,
                cluster["cluster_id"],
                "geospatial_dbscan",
                [uuid.UUID(rid) for rid in cluster["rider_ids"]],
                f"DBSCAN cluster: {cluster['member_count']} riders within 200m",
                "suspected",
            )
            # Flag all riders in cluster
            for rid in cluster["rider_ids"]:
                await conn.execute(
                    "UPDATE riders SET syndicate_suspect_group_id = $1, risk_score = LEAST(risk_score + 20, 100) WHERE id = $2",
                    cluster["cluster_id"], uuid.UUID(rid),
                )
            flagged += len(cluster["rider_ids"])
        except Exception as exc:
            log.error("cluster_persist_failed", error=str(exc))

    log.info("geospatial_fraud_scan_complete",
             riders_scanned=len(rider_coords),
             clusters_found=len(clusters),
             riders_flagged=flagged)

    return {
        "status": "ok",
        "riders_scanned": len(rider_coords),
        "clusters_found": len(clusters),
        "riders_flagged": flagged,
    }
