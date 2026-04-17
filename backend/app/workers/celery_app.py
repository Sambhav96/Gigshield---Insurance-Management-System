"""workers/celery_app.py — Celery app factory + beat schedule."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "gigshield",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.oracle_worker",
        "app.workers.payout_worker",
        "app.workers.continuation_worker",
        "app.workers.vov_worker",
        "app.workers.monday_worker",
        "app.workers.reconciliation_worker",
        "app.workers.metrics_worker",
        "app.workers.ml_worker",
        "app.workers.notification_worker",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",  # IST — spec §28 requires IST for monday debit
    enable_utc=True,
    broker_use_ssl={"ssl_cert_reqs": None},
    redis_backend_use_ssl={"ssl_cert_reqs": None},
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.payout_worker.*": {"queue": "payout"},
        "app.workers.vov_worker.*": {"queue": "vov"},
        "app.workers.oracle_worker.*": {"queue": "oracle"},
        "app.workers.monday_worker.*": {"queue": "monday"},
    },
)

celery_app.conf.beat_schedule = {
    # ── Every 5 minutes ──────────────────────────────────────────────────────
    "platform-health-checks": {
        "task": "app.workers.oracle_worker.check_all_platform_health",
        "schedule": 300,  # 5 min
    },
    "liquidity-snapshot": {
        "task": "app.workers.metrics_worker.take_liquidity_snapshot",
        "schedule": 300,
    },
    # ── Every 10 minutes ─────────────────────────────────────────────────────
    "vov-zone-certification-check": {
        "task": "app.workers.vov_worker.check_all_zone_certifications",
        "schedule": 600,
    },
    # ── Every 15 minutes ─────────────────────────────────────────────────────
    "oracle-fetch-and-score": {
        "task": "app.workers.oracle_worker.run_oracle_cycle",
        "schedule": 900,
    },
    "metrics-snapshot": {
        "task": "app.workers.metrics_worker.take_metrics_snapshot",
        "schedule": 900,
    },
    # ── Every 30 minutes ─────────────────────────────────────────────────────
    "continuation-payouts": {
        "task": "app.workers.continuation_worker.run_continuation_loop",
        "schedule": 1800,
    },
    "reconciliation-polling": {
        "task": "app.workers.reconciliation_worker.poll_stuck_payouts",
        "schedule": 1800,
    },
    # ── Every hour ───────────────────────────────────────────────────────────
    "vov-ttl-cleanup": {
        "task": "app.workers.vov_worker.cleanup_expired_videos",
        "schedule": 3600,
    },
    "solvency-check": {
        "task": "app.workers.metrics_worker.check_solvency",
        "schedule": 3600,
    },
    "drain-payout-recovery-queue": {
        "task": "app.workers.payout_worker.drain_recovery_queue",
        "schedule": 3600,
    },
    "drain-notification-queue": {
        "task": "app.workers.notification_worker.send_pending_notifications",
        "schedule": 60,
    },
    # ── Monday 00:01 IST = Sunday 18:31 UTC ──────────────────────────────────
    "monday-cycle": {
        "task": "app.workers.monday_worker.run_monday_cycle",
        "schedule": crontab(hour=18, minute=31, day_of_week=0),
    },
    # ── Monday 00:05 IST — risk decay (after cap reset) ──────────────────────
    "monday-risk-decay": {
        "task": "app.workers.monday_worker.apply_risk_decay_all",
        "schedule": crontab(hour=18, minute=35, day_of_week=0),
    },
    # ── Daily 03:00 UTC ───────────────────────────────────────────────────────
    "daily-reconciliation": {
        "task": "app.workers.reconciliation_worker.run_daily_reconciliation",
        "schedule": crontab(hour=3, minute=0),
    },
    # ── Monthly 1st 02:00 UTC ─────────────────────────────────────────────────
    "monthly-ml-retrain": {
        "task": "app.workers.ml_worker.retrain_vulnerability_model",
        "schedule": crontab(hour=2, minute=0, day_of_month=1),
    },
    # Every hour — dead letter queue retry for stuck payouts
    "dead-letter-payout-retry": {
        "task": "app.workers.payout_worker.retry_dead_letter_payouts",
        "schedule": 3600,
    },
    # Weekly Sunday 01:00 UTC — geospatial fraud cluster scan
    "weekly-geospatial-fraud-scan": {
        "task": "app.workers.ml_worker.run_geospatial_fraud_scan",
        "schedule": crontab(hour=1, minute=0, day_of_week=0),
    },
    # Monthly 1st 02:30 UTC — update zone cache after model retrain
    "monthly-zone-vuln-cache": {
        "task": "app.workers.ml_worker.update_zone_vulnerability_cache",
        "schedule": crontab(hour=2, minute=30, day_of_month=1),
    },
}
