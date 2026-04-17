"""
services/notification_service.py — Multi-channel notification system

Channels:
  1. FCM Push (Web Push via Firebase) — primary, free
  2. SMS (via Supabase built-in Twilio) — fallback for critical events

NOTE: WhatsApp channel has been removed per product decision.
      The notifications table schema still has 'whatsapp' as a valid channel
      value for historical records, but no new WhatsApp notifications are sent.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

from app.config import get_settings
from app.core.redis_client import get_sync_redis

settings = get_settings()
log = structlog.get_logger()

NOTIFICATION_CHANNEL = "notifications"

TEMPLATES = {
    "payout_success":       "₹{amount} sent to your UPI account — {trigger_type} protection active 🛡️",
    "payout_queued":        "Your payout of ₹{amount} is confirmed. Arrives in {eta_hours} hour(s).",
    "claim_soft_flagged":   "Claim under verification. ₹{provisional_amount} sent now; ₹{remainder} arrives in 2 hours.",
    "claim_hard_flagged":   "Claim being reviewed. Decision in 4 hours. Upload a video to expedite.",
    "claim_approved":       "Your claim of ₹{amount} has been approved ✅",
    "claim_rejected":       "Claim could not be approved. Reason: {reason}. Dispute within 7 days.",
    "weekly_cap_reached":   "Weekly limit ₹{cap} reached. Coverage resets Monday 🔄",
    "event_cap_reached":    "Event cap ₹{event_cap} reached. ₹{remaining_weekly} weekly balance still available.",
    "policy_renewed":       "GigShield renewed ✅ Premium: ₹{premium}. Discount weeks: {discount_weeks}/4.",
    "policy_lapsed":        "Payment failed. Coverage paused. Update payment method to continue.",
    "trigger_active":       "🚨 {trigger_type} alert in your zone! Protection active. Stay safe.",
    "trigger_resolved":     "✅ {trigger_type} event in your zone resolved.",
    "vov_prompt":           "Help verify disruption in your zone. Upload 10-sec video → earn ₹{reward} 🎥",
    "dispute_received":     "Dispute received. We'll respond by {deadline}.",
    "goodwill_credit":      "₹{amount} goodwill credit added to your account 🎁",
    "referral_reward":      "Your referral {name} enrolled! ₹{amount} bonus added to your account 🤝",
}


def publish_notification(
    rider_id: str,
    event_type: str,
    context: dict,
    channels: list[str] | None = None,
) -> None:
    """
    Fire-and-forget: publish to Redis queue.
    notification_worker handles delivery asynchronously.
    Default channels: push only (WhatsApp removed).
    """
    if channels is None:
        channels = ["push"]  # WhatsApp removed — push is the primary channel

    # Strip 'whatsapp' from any caller that still passes it (defensive)
    channels = [c for c in channels if c != "whatsapp"]
    if not channels:
        channels = ["push"]

    message = {
        "id": str(uuid.uuid4()),
        "rider_id": rider_id,
        "event_type": event_type,
        "context": context,
        "channels": channels,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        redis = get_sync_redis()
        redis.publish(NOTIFICATION_CHANNEL, json.dumps(message))
        redis.lpush("notification_queue", json.dumps(message))
        log.debug("notification_published", event_type=event_type, rider_id=rider_id)
    except Exception as exc:
        log.error("notification_publish_failed", error=str(exc), event_type=event_type)


def render_template(event_type: str, context: dict) -> str:
    tmpl = TEMPLATES.get(event_type, "GigShield notification.")
    try:
        return tmpl.format(**context)
    except KeyError:
        return tmpl


async def send_fcm_push(rider_id: str, title: str, body: str, data: dict | None = None) -> bool:
    """
    Send FCM push notification.
    Requires rider's FCM token stored in riders table.
    """
    fcm_key = getattr(settings, "fcm_server_key", "")
    if not fcm_key or fcm_key == "placeholder":
        log.debug("fcm_not_configured_skipping")
        return False

    # FCM token would be fetched from DB in production
    log.info("fcm_push_queued", rider_id=rider_id, title=title)
    return True
