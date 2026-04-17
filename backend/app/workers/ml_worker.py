"""workers/ml_worker.py — Monthly ML retraining + income inference."""
from __future__ import annotations

import structlog
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="app.workers.ml_worker.retrain_vulnerability_model")
def retrain_vulnerability_model():
    """Monthly: retrain GBM vulnerability index model."""
    from app.ml.vulnerability_model import train_vulnerability_model
    try:
        metrics = train_vulnerability_model()
        log.info("vulnerability_model_retrained", metrics=metrics)
    except Exception as exc:
        log.error("vulnerability_model_retrain_failed", error=str(exc))


@celery_app.task(name="app.workers.ml_worker.update_income_inferences")
def update_income_inferences():
    """Weekly (Monday): update telemetry_inferred_income for all riders."""
    import psycopg2, psycopg2.extras, asyncio, asyncpg
    from app.config import get_settings
    from app.services.income_service import infer_income_from_telemetry, compute_effective_income

    async def _run():
        pool = await asyncpg.create_pool(get_settings().database_url, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            rider_ids = await conn.fetch("SELECT id FROM riders")
            for r in rider_ids:
                try:
                    inferred = await infer_income_from_telemetry(conn, str(r["id"]))
                    if inferred > 0:
                        await conn.execute(
                            "UPDATE riders SET telemetry_inferred_income = $1 WHERE id = $2",
                            inferred, r["id"],
                        )
                    effective = await compute_effective_income(conn, str(r["id"]))
                    await conn.execute(
                        "UPDATE riders SET effective_income = $1 WHERE id = $2",
                        effective, r["id"],
                    )
                except Exception as exc:
                    log.error("income_inference_failed", rider_id=str(r["id"]), error=str(exc))
        await pool.close()

    try:
        asyncio.get_event_loop().run_until_complete(_run())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_run())
        loop.close()
    log.info("income_inferences_updated")


@celery_app.task(name="app.workers.ml_worker.update_zone_vulnerability_cache")
def update_zone_vulnerability_cache():
    """
    Monthly: update zone_risk_cache.vulnerability_idx from ML model predictions.
    Aggregates rider features by H3 zone, runs GBM predictions, writes to cache.
    """
    import asyncio
    import asyncpg
    from app.config import get_settings
    from app.ml.vulnerability_model import predict_vulnerability

    async def _run():
        pool = await asyncpg.create_pool(get_settings().database_url, min_size=1, max_size=3)
        async with pool.acquire() as conn:
            # Aggregate rider features per H3 zone
            zone_rows = await conn.fetch(
                """
                SELECT
                    h.h3_index_res9                                         AS h3_index,
                    AVG(r.risk_score)                                       AS risk_score,
                    COUNT(*)                                                 AS rider_count,
                    AVG(COALESCE(r.effective_income, 500) / 1000.0)        AS effective_income_normalized,
                    AVG(
                      (SELECT COUNT(*) FROM claims c
                       WHERE c.rider_id = r.id
                         AND c.initiated_at >= NOW() - INTERVAL '90 days')::float / 13.0
                    )                                                        AS claims_per_week_90d,
                    AVG(
                      (SELECT COALESCE(AVG(c2.fraud_score), 0.3) FROM claims c2
                       WHERE c2.rider_id = r.id
                         AND c2.initiated_at >= NOW() - INTERVAL '90 days')
                    )                                                        AS avg_fraud_score_90d
                FROM riders r
                JOIN policies p  ON p.rider_id = r.id AND p.status = 'active'
                JOIN hubs h      ON h.id = p.hub_id
                GROUP BY h.h3_index_res9
                """
            )

            updated = 0
            for row in zone_rows:
                features = {
                    "risk_score":                  float(row["risk_score"] or 50),
                    "claims_per_week_90d":         float(row["claims_per_week_90d"] or 0),
                    "avg_fraud_score_90d":         float(row["avg_fraud_score_90d"] or 0.3),
                    "hard_flag_count_90d":         0,
                    "vov_submissions_90d":         0,
                    "avg_shift_hours_7d":          8.0,
                    "city_encoded":                0,
                    "plan_encoded":                0,
                    "effective_income_normalized": float(row["effective_income_normalized"] or 0.5),
                    "hub_drainage_index":          0.5,
                }
                vuln_idx = predict_vulnerability(features)
                await conn.execute(
                    """
                    INSERT INTO zone_risk_cache (h3_index, vulnerability_idx, last_updated)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (h3_index) DO UPDATE
                      SET vulnerability_idx = EXCLUDED.vulnerability_idx,
                          last_updated = NOW()
                    """,
                    row["h3_index"], vuln_idx,
                )
                updated += 1

        await pool.close()
        return updated

    try:
        try:
            count = asyncio.get_event_loop().run_until_complete(_run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            count = loop.run_until_complete(_run())
            loop.close()
        log.info("zone_vulnerability_cache_updated", zones_updated=count)
    except Exception as exc:
        log.error("zone_vulnerability_cache_update_failed", error=str(exc))


@celery_app.task(name="app.workers.ml_worker.run_geospatial_fraud_scan")
def run_geospatial_fraud_scan():
    """Weekly: run DBSCAN geospatial fraud clustering on recent enrollments."""
    import asyncio
    import asyncpg
    from app.config import get_settings
    from app.ml.dbscan_fraud_cluster import run_geospatial_fraud_scan as _scan

    async def _run():
        pool = await asyncpg.create_pool(get_settings().database_url, min_size=1, max_size=3)
        async with pool.acquire() as conn:
            result = await _scan(conn)
        await pool.close()
        return result

    try:
        try:
            result = asyncio.get_event_loop().run_until_complete(_run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_run())
            loop.close()
        log.info("geospatial_fraud_scan_done", **result)
    except Exception as exc:
        log.error("geospatial_fraud_scan_failed", error=str(exc))
