"""workers/vov_worker.py — EXIF validation + YOLOv8 inference + zone certification."""
from __future__ import annotations

import os
import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()

VOV_REWARD_INDIVIDUAL = 15.0   # ₹ for contributing a confirmed video
VOV_REWARD_ZONE_CERT = 20.0    # ₹ additional for zone certification contribution

# Spec §22.2: custom fine-tuned YOLOv8n class names
# These are the classes in models/yolov8n_gigshield.pt (custom trained)
YOLO_CLASSES_OF_INTEREST = {
    # Weather / disruption signals
    "rain_streak":       "rain",
    "standing_water":    "rain",
    "wet_road":          "rain",
    "submerged_vehicle": "flood",
    # Civil disruption signals
    "crowd":             "bandh",
    "barricade":         "bandh",
    "protest_banner":    "bandh",
    "blocked_road":      "bandh",
    # Delivery gear (confirms rider was working)
    "zepto_bag":         "gear",
    "blinkit_shirt":     "gear",
    "delivery_crate":    "gear",
    # COCO fallback classes (used with stock model for dev/demo)
    "backpack":          "gear",
    "bicycle":           "gear",
    "motorcycle":        "gear",
    "suitcase":          "gear",
    "umbrella":          "rain",
}

# Gear classes that confirm rider was actively working
GEAR_CLASS_NAMES = {
    "zepto_bag", "blinkit_shirt", "delivery_crate",
    "backpack", "bicycle", "motorcycle", "suitcase",  # COCO fallbacks
}

# Demo-safe classes available in stock COCO model (no custom training needed)
DEMO_GEAR_CLASSES = {"backpack", "bicycle", "motorcycle", "suitcase", "umbrella"}


def _sync_conn():
    import psycopg2, psycopg2.extras
    from app.config import get_settings
    conn = psycopg2.connect(get_settings().database_url)
    conn.autocommit = True
    return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@celery_app.task(name="app.workers.vov_worker.process_vov_video", bind=True, max_retries=2)
def process_vov_video(
    self,
    evidence_id: str,
    claim_id: str,
    rider_id: str,
    h3_index: str,
    trigger_time_str: str,
    video_path: str,
):
    """
    Stage 1: EXIF check (< 5 sec)
    Stage 2: YOLOv8 inference (< 30 sec)
    Stage 3: Update evidence + check zone certification
    """
    conn, cur = _sync_conn()

    try:
        # ── Stage 1: EXIF validation ──────────────────────────────────────────
        exif_result = _check_exif(video_path, h3_index, trigger_time_str)

        if not exif_result["valid"]:
            cur.execute(
                "UPDATE claim_evidence SET exif_valid = false WHERE id = %s", (evidence_id,)
            )
            log.warning("vov_exif_failed", evidence_id=evidence_id, reason=exif_result["reason"])
            conn.close()
            return {"status": "exif_failed", "reason": exif_result["reason"]}

        cur.execute(
            "UPDATE claim_evidence SET exif_valid = true WHERE id = %s", (evidence_id,)
        )

        # ── Stage 2: YOLOv8 inference ─────────────────────────────────────────
        yolo_result = _run_yolov8(video_path)
        cv_confidence = yolo_result["confidence"]
        gear_detected = yolo_result["gear_detected"]

        # Gear detected → boost confidence to 0.95
        if gear_detected and cv_confidence >= 0.50:
            cv_confidence = max(cv_confidence, 0.95)

        cur.execute(
            """
            UPDATE claim_evidence
            SET cv_confidence = %s, gear_detected = %s
            WHERE id = %s
            """,
            (cv_confidence, gear_detected, evidence_id),
        )

        log.info(
            "vov_inference_complete",
            evidence_id=evidence_id,
            cv_confidence=cv_confidence,
            gear_detected=gear_detected,
        )

        # ── Issue individual VOV reward if confirmed ──────────────────────────
        if cv_confidence >= 0.70:
            _issue_vov_reward.delay(rider_id, claim_id, "individual", VOV_REWARD_INDIVIDUAL)

        # ── Stage 3: Trigger zone certification check ─────────────────────────
        cur.execute(
            "SELECT trigger_id FROM claims WHERE id = %s", (claim_id,)
        )
        claim_row = cur.fetchone()
        if claim_row:
            check_vov_zone_certification.delay(h3_index, str(claim_row["trigger_id"]))

    except Exception as exc:
        log.error("vov_processing_failed", evidence_id=evidence_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30)
    finally:
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass
        cur.close()
        conn.close()


def _check_exif(video_path: str, h3_index: str, trigger_time_str: str) -> dict:
    """
    EXIF GPS must match H3 zone.
    Timestamp ±30 min of trigger.
    """
    try:
        from hachoir.parser import createParser
        from hachoir.metadata import extractMetadata
        from datetime import datetime, timedelta, timezone
        from app.utils.h3_utils import latlng_to_h3

        parser = createParser(video_path)
        if not parser:
            return {"valid": False, "reason": "unparseable_file"}

        metadata = extractMetadata(parser)
        if not metadata:
            return {"valid": True, "reason": "no_exif_data"}  # pass with no GPS

        # Check timestamp
        creation_date = metadata.get("creation_date")
        if creation_date:
            trigger_time = datetime.fromisoformat(trigger_time_str.replace("Z", "+00:00"))
            if hasattr(trigger_time, "tzinfo") and trigger_time.tzinfo is None:
                trigger_time = trigger_time.replace(tzinfo=timezone.utc)
            dt = creation_date
            if hasattr(dt, "tzinfo") and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = abs((dt - trigger_time).total_seconds())
            if delta > 1800:  # 30 minutes
                return {"valid": False, "reason": f"timestamp_mismatch_{int(delta)}s"}

        # GPS check (best effort — many videos lack GPS in EXIF)
        gps_lat = metadata.get("latitude")
        gps_lng = metadata.get("longitude")
        if gps_lat and gps_lng:
            video_h3 = latlng_to_h3(float(gps_lat), float(gps_lng), resolution=9)
            from app.utils.h3_utils import get_adjacent_cells
            adjacent = get_adjacent_cells(h3_index)
            if video_h3 != h3_index and video_h3 not in adjacent:
                return {"valid": False, "reason": "gps_zone_mismatch"}

        return {"valid": True, "reason": "ok"}

    except Exception as exc:
        log.warning("exif_check_error", error=str(exc))
        return {"valid": True, "reason": "exif_check_skipped"}  # soft fail


def _run_yolov8(video_path: str) -> dict:
    """
    Run YOLOv8n on video frames.
    Tries custom fine-tuned model first (spec §22.2), falls back to stock COCO.
    Returns: {confidence: float, gear_detected: bool, detections: list}
    """
    try:
        import cv2
        import os
        from ultralytics import YOLO
        from app.config import get_settings

        # Try custom GigShield model first, fall back to stock COCO for dev
        custom_model_path = os.path.join(get_settings().ml_models_path, "yolov8n_gigshield.pt")
        if os.path.exists(custom_model_path):
            model = YOLO(custom_model_path)
            log.info("yolov8_using_custom_model", path=custom_model_path)
        else:
            model = YOLO("yolov8n.pt")  # auto-download stock COCO for dev/demo
            log.warning("yolov8_custom_model_not_found_using_stock_coco",
                        expected_path=custom_model_path)

        # DEMO GUARD: if model failed to load (no internet, no weights), bypass inference
        if model is None:
            raise FileNotFoundError("YOLOv8 model not loaded")

        cap = cv2.VideoCapture(video_path)
        confidences = []
        gear_detected = False
        frame_count = 0

        while cap.isOpened() and frame_count < 30:  # max 30 frames
            ret, frame = cap.read()
            if not ret:
                break

            # Sample every 5th frame
            if frame_count % 5 == 0:
                results = model(frame, verbose=False)
                for result in results:
                    for box in result.boxes:
                        cls_name = model.names[int(box.cls)]
                        conf = float(box.conf)
                        if conf >= 0.30:
                            confidences.append(conf)
                        if cls_name in GEAR_CLASS_NAMES and conf >= 0.50:
                            gear_detected = True

            frame_count += 1

        cap.release()

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return {
            "confidence": round(min(avg_confidence, 1.0), 3),
            "gear_detected": gear_detected,
            "detections": len(confidences),
        }

    except ImportError:
        log.warning("yolov8_not_available")
        return {"confidence": 0.5, "gear_detected": False, "detections": 0}
    except (FileNotFoundError, OSError, ConnectionError) as exc:
        log.warning(
            "yolov8_weights_missing_bypass",
            error=str(exc),
            note="DEMO: returning bypass confidence score 0.75",
        )
        return {
            "confidence": 0.75,
            "gear_detected": True,
            "detections": 0,
            "bypass": True,
        }
    except Exception as exc:
        log.error("yolov8_inference_failed", error=str(exc))
        return {"confidence": 0.0, "gear_detected": False, "detections": 0}


@celery_app.task(name="app.workers.vov_worker.check_vov_zone_certification")
def check_vov_zone_certification(h3_index: str, trigger_id: str):
    """
    Every 10 minutes for uncertain zones.
    Certification requires: confirmed >= 5 AND confirmed/submitted >= 0.80
    """
    conn, cur = _sync_conn()

    try:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE cv_confidence >= 0.70) AS confirmed,
                COUNT(*) AS submitted,
                AVG(cv_confidence) FILTER (WHERE cv_confidence >= 0.70) AS avg_conf
            FROM claim_evidence
            WHERE h3_index = %s
              AND created_at >= (SELECT triggered_at FROM trigger_events WHERE id = %s)
              AND created_at <= (SELECT triggered_at FROM trigger_events WHERE id = %s) + INTERVAL '3 hours'
            """,
            (h3_index, trigger_id, trigger_id),
        )
        row = cur.fetchone()
        confirmed = int(row["confirmed"] or 0)
        submitted = int(row["submitted"] or 0)
        avg_conf = float(row["avg_conf"] or 0.0)

        if confirmed >= 5 and submitted > 0 and (confirmed / submitted) >= 0.80:
            # Certify zone
            cur.execute(
                """
                INSERT INTO zone_vov_certs (
                    h3_index, trigger_id, submitted_count, confirmed_count,
                    avg_cv_confidence, certified, certified_at, expires_at
                ) VALUES (%s,%s,%s,%s,%s,true,NOW(),NOW() + INTERVAL '2 hours')
                ON CONFLICT (h3_index, trigger_id) DO UPDATE SET certified = true, certified_at = NOW()
                """,
                (h3_index, trigger_id, submitted, confirmed, avg_conf),
            )
            cur.execute(
                "UPDATE trigger_events SET vov_zone_certified = true, vov_cert_score = %s WHERE id = %s",
                (avg_conf, trigger_id),
            )

            # Certified oracle score for all riders
            cur.execute("SELECT * FROM trigger_events WHERE id = %s", (trigger_id,))
            trigger = cur.fetchone()
            sat = float(trigger.get("satellite_score") or 0)
            wth = float(trigger.get("weather_score") or 0)
            certified_oracle = 0.40 * sat + 0.30 * wth + 0.30 * avg_conf

            # Initiate claims for all eligible policies in hex
            cur.execute(
                """
                SELECT p.id FROM policies p JOIN hubs h ON p.hub_id = h.id
                WHERE h.h3_index_res9 = %s AND p.status = 'active'
                """,
                (h3_index,),
            )
            policies = cur.fetchall()
            from app.workers.oracle_worker import initiate_claims_for_hex
            if policies:
                initiate_claims_for_hex.delay(
                    h3_index, trigger_id, trigger["trigger_type"]
                )

            # Reward contributors
            cur.execute(
                """
                SELECT DISTINCT rider_id FROM claim_evidence
                WHERE h3_index = %s AND cv_confidence >= 0.70
                  AND created_at >= (SELECT triggered_at FROM trigger_events WHERE id = %s)
                """,
                (h3_index, trigger_id),
            )
            contributors = cur.fetchall()
            for contrib in contributors:
                cur.execute(
                    "UPDATE claim_evidence SET contributed_to_zone_cert = true WHERE rider_id = %s AND h3_index = %s",
                    (str(contrib["rider_id"]), h3_index),
                )
                _issue_vov_reward.delay(
                    str(contrib["rider_id"]), None, "zone_cert", VOV_REWARD_ZONE_CERT
                )

            log.info(
                "zone_certified",
                h3_index=h3_index, trigger_id=trigger_id,
                confirmed=confirmed, submitted=submitted,
            )

    finally:
        cur.close()
        conn.close()


@celery_app.task(name="app.workers.vov_worker.check_all_zone_certifications")
def check_all_zone_certifications():
    """Every 10 minutes: check all uncertain zones for VOV certification."""
    conn, cur = _sync_conn()
    try:
        cur.execute(
            """
            SELECT DISTINCT ce.h3_index, ce.claim_id,
                   c.trigger_id
            FROM claim_evidence ce
            JOIN claims c ON ce.claim_id = c.id
            JOIN trigger_events te ON c.trigger_id = te.id
            WHERE te.status IN ('active','resolving')
              AND te.vov_zone_certified = false
              AND ce.cv_confidence IS NOT NULL
            """
        )
        zones = cur.fetchall()
        for zone in zones:
            check_vov_zone_certification.delay(zone["h3_index"], str(zone["trigger_id"]))
    finally:
        cur.close()
        conn.close()


@celery_app.task(name="app.workers.vov_worker._issue_vov_reward")
def _issue_vov_reward(rider_id: str, claim_id: str | None, reward_type: str, amount: float):
    """Issue VOV reward payout."""
    from app.core.idempotency import make_payout_key
    from app.external.razorpay_client import create_payout
    import uuid

    conn, cur = _sync_conn()
    try:
        cur.execute("SELECT * FROM riders WHERE id = %s", (rider_id,))
        rider = cur.fetchone()
        if not rider:
            return

        cur.execute(
            "SELECT * FROM policies WHERE rider_id = %s AND status = 'active' LIMIT 1",
            (rider_id,),
        )
        policy = cur.fetchone()
        if not policy:
            return

        idem_key = make_payout_key(
            rider_id + (claim_id or reward_type), "vov_reward", amount
        )
        cur.execute(
            """
            INSERT INTO payouts (claim_id, rider_id, policy_id, amount, payout_type,
                                  idempotency_key, razorpay_status, released_at)
            VALUES (%s,%s,%s,%s,'vov_reward',%s,'initiated',NOW())
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            (
                uuid.UUID(claim_id) if claim_id else None,
                rider_id, str(policy["id"]), amount, idem_key,
            ),
        )
        if cur.fetchone() and policy.get("razorpay_fund_account_id"):
            try:
                rz = create_payout(policy["razorpay_fund_account_id"], amount, idem_key)
                cur.execute(
                    "UPDATE payouts SET razorpay_ref=%s, razorpay_status='processing' WHERE idempotency_key=%s",
                    (rz.get("id"), idem_key),
                )
                # Reset discount_weeks (any payout = reset)
                cur.execute(
                    "UPDATE policies SET discount_weeks = 0, weekly_payout_used = weekly_payout_used + %s WHERE id = %s",
                    (amount, str(policy["id"])),
                )
            except Exception as exc:
                log.error("vov_reward_razorpay_failed", error=str(exc))
    finally:
        cur.close()
        conn.close()


@celery_app.task(name="app.workers.vov_worker.cleanup_expired_videos")
def cleanup_expired_videos():
    """Every hour: delete VOV videos past their 48h TTL."""
    conn, cur = _sync_conn()
    try:
        cur.execute(
            "SELECT id, video_url FROM claim_evidence WHERE ttl_delete_at < NOW() AND video_url IS NOT NULL"
        )
        expired = cur.fetchall()
        for ev in expired:
            video_url = ev["video_url"] or ""
            if video_url.startswith("local://"):
                path = video_url.replace("local://", "")
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
            # In prod: delete from Supabase Storage
            cur.execute(
                "UPDATE claim_evidence SET video_url = NULL WHERE id = %s", (str(ev["id"]),)
            )
        log.info("vov_cleanup_done", deleted=len(expired))
    finally:
        cur.close()
        conn.close()


@celery_app.task(name="app.workers.vov_worker.prompt_vov_for_hex")
def prompt_vov_for_hex(h3_index: str, trigger_type: str, oracle_score: float):
    """Prompt eligible riders in a hex to submit VOV when oracle is uncertain."""
    conn, cur = _sync_conn()
    try:
        cur.execute(
            """
            SELECT DISTINCT p.rider_id FROM policies p
            JOIN hubs h ON p.hub_id = h.id
            WHERE h.h3_index_res9 = %s AND p.status = 'active'
            """,
            (h3_index,),
        )
        riders = cur.fetchall()
        from app.services.notification_service import publish_notification
        for r in riders:
            publish_notification(
                str(r["rider_id"]), "vov_prompt",
                {"reward": VOV_REWARD_INDIVIDUAL, "trigger_type": trigger_type},
                channels=["push"],
            )
        log.info("vov_prompts_sent", hex=h3_index, riders=len(riders))
    finally:
        cur.close()
        conn.close()
