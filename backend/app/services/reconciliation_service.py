"""
services/reconciliation_service.py — AUDIT FIXED

BUG-06 FIX: Layer 2 reconciliation now actually calls Razorpay to fetch payout status.
BUG-07 FIX: reconciliation_reports schema aligned with spec §20.1 columns.

Three layers per spec §20.1:
  Layer 1: Real-time webhook matching (handled by webhooks.py — instant)
  Layer 2: Polling stuck payouts > 10 min (every 30 min)
  Layer 3: Full daily reconciliation vs Razorpay ledger (3 AM UTC)
"""
from __future__ import annotations

import asyncpg
import structlog

log = structlog.get_logger()


async def reconcile_stuck_payouts(conn: asyncpg.Connection) -> dict:
    """
    Layer 2: BUG-06 FIX — actually calls Razorpay.payout.fetch() for stuck payouts.
    """
    stuck = await conn.fetch(
        """
        SELECT id, razorpay_ref, idempotency_key, amount, rider_id
        FROM payouts
        WHERE razorpay_status = 'processing'
          AND released_at < NOW() - INTERVAL '10 minutes'
        LIMIT 100
        """
    )
    results = {"checked": len(stuck), "updated": 0, "errors": 0, "late_success": 0}

    for payout in stuck:
        if not payout["razorpay_ref"]:
            continue
        try:
            from app.external.razorpay_client import get_razorpay_client
            rz_client  = get_razorpay_client()
            rz_payout  = rz_client.payout.fetch(payout["razorpay_ref"])
            rz_status  = rz_payout.get("status", "")

            status_map = {
                "processed": "success",
                "failed":    "failed",
                "reversed":  "reversed",
                "queued":    "processing",
                "pending":   "processing",
            }
            new_db_status = status_map.get(rz_status, "processing")

            if new_db_status != "processing":
                await conn.execute(
                    "UPDATE payouts SET razorpay_status=$1, reconciled_at=NOW(), reconcile_status='layer2_matched' WHERE id=$2",
                    new_db_status, payout["id"],
                )
                results["updated"] += 1
                if new_db_status == "success":
                    results["late_success"] += 1
                    # Update annual_payout_total if late success
                    await conn.execute(
                        "UPDATE riders SET annual_payout_total=COALESCE(annual_payout_total,0)+$1 WHERE id=$2",
                        float(payout["amount"]), payout["rider_id"],
                    )
                log.info("layer2_reconcile_updated", ref=payout["razorpay_ref"], new_status=new_db_status)
        except Exception as exc:
            log.error("layer2_reconcile_failed", ref=payout["razorpay_ref"], error=str(exc))
            results["errors"] += 1

    return results


async def run_daily_reconciliation(conn: asyncpg.Connection) -> dict:
    """
    Layer 3: BUG-07 FIX — uses spec §20.1 schema columns and fetches Razorpay ledger.
    """
    import json
    from datetime import datetime, timezone, timedelta

    yesterday_start = await conn.fetchval(
        "SELECT (date_trunc('day', NOW()) - INTERVAL '1 day')::timestamptz"
    )
    yesterday_end = await conn.fetchval(
        "SELECT date_trunc('day', NOW())::timestamptz"
    )

    # Count DB records for yesterday
    db_stats = await conn.fetchrow(
        """
        SELECT
            COUNT(*)                                                   AS total_db_records,
            COUNT(*) FILTER (WHERE razorpay_status='success')         AS success_count,
            COUNT(*) FILTER (WHERE razorpay_status='failed')          AS failed_count,
            COUNT(*) FILTER (WHERE razorpay_status='processing')      AS stuck_count,
            COALESCE(SUM(amount) FILTER (WHERE razorpay_status='success'), 0) AS success_amount
        FROM payouts
        WHERE released_at >= $1 AND released_at < $2
          AND payout_type != 'premium_debit'
        """,
        yesterday_start, yesterday_end,
    )

    # Attempt Razorpay ledger fetch for comparison
    total_razorpay_records = 0
    mismatch_count         = 0
    missing_from_db        = 0
    missing_from_rz        = 0
    total_discrepancy_inr  = 0.0
    razorpay_fetch_error   = None

    try:
        from app.external.razorpay_client import get_razorpay_client
        rz_client = get_razorpay_client()
        # Fetch payouts from Razorpay for yesterday window
        rz_payouts = rz_client.payout.all({
            "from": int(yesterday_start.timestamp()),
            "to":   int(yesterday_end.timestamp()),
            "count": 100,
        })
        total_razorpay_records = len(rz_payouts.get("items", []))

        # Cross-reference by reference_id (our idempotency_key prefix)
        rz_refs = {
            p.get("reference_id", ""): p
            for p in rz_payouts.get("items", [])
        }

        db_payouts = await conn.fetch(
            """
            SELECT idempotency_key, amount, razorpay_status, razorpay_ref
            FROM payouts
            WHERE released_at >= $1 AND released_at < $2
              AND payout_type != 'premium_debit'
            """,
            yesterday_start, yesterday_end,
        )

        for p in db_payouts:
            ikey_prefix = (p["idempotency_key"] or "")[:40]
            rz_match    = rz_refs.get(ikey_prefix)
            if rz_match is None:
                if p["razorpay_status"] == "success":
                    missing_from_rz   += 1
                    total_discrepancy_inr += float(p["amount"])
            else:
                rz_amount = rz_match.get("amount", 0) / 100  # paise → INR
                db_amount = float(p["amount"])
                if abs(rz_amount - db_amount) > 0.01:
                    mismatch_count        += 1
                    total_discrepancy_inr += abs(rz_amount - db_amount)

    except Exception as exc:
        razorpay_fetch_error = str(exc)
        log.warning("layer3_razorpay_fetch_failed", error=razorpay_fetch_error)

    issues_found = (mismatch_count + missing_from_db + missing_from_rz) > 0 or int(db_stats["stuck_count"] or 0) > 0

    # BUG-07 FIX: Insert with spec-aligned columns
    await conn.execute(
        """
        INSERT INTO reconciliation_reports (
            period, report_date, total_db_records, total_razorpay_records,
            matched_count, late_success_count, mismatch_count,
            missing_from_db_count, missing_from_razorpay_count,
            total_discrepancy_inr, issues_found, report_data, run_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, NOW())
        """,
        "daily",
        yesterday_start.date(),
        int(db_stats["total_db_records"] or 0),
        total_razorpay_records,
        int(db_stats["success_count"] or 0),
        0,   # late_success populated by layer2
        mismatch_count,
        missing_from_db,
        missing_from_rz,
        total_discrepancy_inr,
        issues_found,
        json.dumps({
            "stuck_count": int(db_stats["stuck_count"] or 0),
            "razorpay_fetch_error": razorpay_fetch_error,
        }),
    )

    log.info("layer3_reconciliation_complete", issues_found=issues_found,
             mismatch_count=mismatch_count, discrepancy_inr=total_discrepancy_inr)
    return {
        "period": "daily", "issues_found": issues_found,
        "total_db_records": int(db_stats["total_db_records"] or 0),
        "total_razorpay_records": total_razorpay_records,
        "mismatch_count": mismatch_count, "discrepancy_inr": total_discrepancy_inr,
    }
