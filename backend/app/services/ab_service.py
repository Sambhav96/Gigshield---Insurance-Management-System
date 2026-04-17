"""
services/ab_service.py — A/B Experiment Framework

UNICORN FEATURE: Product optimization via A/B testing

Tables already exist: experiments, message_experiments
This service wires them into the pricing, messaging, and feature flag systems.

Usage:
    from app.services.ab_service import get_experiment_value, assign_rider_to_group
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import structlog

log = structlog.get_logger()

# Default parameter values (fallback when no experiment active)
DEFAULTS = {
    "auto_clear_fs_threshold": 0.40,
    "vov_reward_amount":       10.0,
    "soft_flag_provisional":   0.70,
    "rain_threshold_mm":       35.0,
    "weekly_premium_discount": 0.0,
    "payout_speed_mode":       "standard",  # "standard" | "instant"
    "onboarding_variant":      "default",   # "default" | "streamlined" | "gamified"
    "trigger_sensitivity":     1.0,
}


def assign_rider_to_group(rider_id: str, experiment_name: str, num_groups: int = 2) -> str:
    """
    Deterministically assign a rider to an experiment group.
    Same rider always gets same group for same experiment (consistent UX).
    """
    hash_val = int(hashlib.sha256(f"{rider_id}:{experiment_name}".encode()).hexdigest(), 16)
    group_idx = hash_val % num_groups
    return f"group_{group_idx}"


async def get_experiment_value(
    conn,
    rider_id: str,
    parameter_name: str,
    fallback: Any = None,
) -> Any:
    """
    Get the experiment parameter value for a rider.
    Returns rider's assigned group value, or default if no active experiment.
    """
    if fallback is None:
        fallback = DEFAULTS.get(parameter_name)

    try:
        # Get rider's experiment group
        rider = await conn.fetchrow(
            "SELECT experiment_group_id FROM riders WHERE id = $1::uuid", rider_id
        )
        if not rider:
            return fallback

        group_id = rider["experiment_group_id"] or "control"

        # Look up active experiment for this parameter + group
        row = await conn.fetchrow(
            """
            SELECT parameter_value FROM experiments
            WHERE parameter_name = $1
              AND group_id = $2
              AND active = true
            ORDER BY activated_at DESC
            LIMIT 1
            """,
            parameter_name, group_id,
        )

        if row:
            val = row["parameter_value"]
            # Parse JSON value
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    return val
            return val

        # Check control group as fallback
        control_row = await conn.fetchrow(
            """
            SELECT parameter_value FROM experiments
            WHERE parameter_name = $1
              AND group_id = 'control'
              AND active = true
            ORDER BY activated_at DESC
            LIMIT 1
            """,
            parameter_name,
        )

        if control_row:
            val = control_row["parameter_value"]
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    return val
            return val

    except Exception as exc:
        log.debug("experiment_lookup_failed", parameter=parameter_name, error=str(exc))

    return fallback


async def get_message_template(conn, event_type: str, group_id: str) -> Optional[str]:
    """Get A/B-tested message template for a notification event."""
    try:
        row = await conn.fetchrow(
            """
            SELECT message_template FROM message_experiments
            WHERE message_key = $1
              AND group_id = $2
              AND active = true
            ORDER BY created_at DESC
            LIMIT 1
            """,
            event_type, group_id,
        )
        return row["message_template"] if row else None
    except Exception:
        return None


async def seed_default_experiments(conn) -> None:
    """Seed default A/B experiments for key parameters."""
    experiments = [
        ("auto_clear_threshold", "auto_clear_fs_threshold", "0.40", "control"),
        ("auto_clear_threshold", "auto_clear_fs_threshold", "0.35", "group_1"),  # more conservative
        ("vov_reward", "vov_reward_amount", "10.0", "control"),
        ("vov_reward", "vov_reward_amount", "15.0", "group_1"),                  # higher reward
        ("payout_speed", "payout_speed_mode", '"standard"', "control"),
        ("payout_speed", "payout_speed_mode", '"instant"', "group_1"),          # test instant payout
    ]

    for name, param, value, group in experiments:
        try:
            await conn.execute(
                """
                INSERT INTO experiments (name, parameter_name, parameter_value, group_id, active)
                VALUES ($1, $2, $3, $4, true)
                ON CONFLICT DO NOTHING
                """,
                name, param, value, group,
            )
        except Exception:
            pass  # Table may not exist yet
