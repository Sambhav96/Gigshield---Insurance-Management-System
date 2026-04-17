"""core/idempotency.py — SHA-256 idempotency key generation for all money ops."""
import hashlib


def make_payout_key(claim_id: str, payout_type: str, amount: float) -> str:
    """SHA-256(claim_id:payout_type:amount) — canonical payout idempotency key."""
    raw = f"{claim_id}:{payout_type}:{amount:.2f}"
    return hashlib.sha256(raw.encode()).hexdigest()


def make_debit_key(policy_id: str, week_start: str) -> str:
    """SHA-256(policy_id:week_start:debit) — Monday debit idempotency key."""
    raw = f"{policy_id}:{week_start}:debit"
    return hashlib.sha256(raw.encode()).hexdigest()


def make_claim_key(rider_id: str, trigger_id: str, policy_id: str) -> str:
    """SHA-256(rider_id:trigger_id:policy_id) — claim creation idempotency key."""
    raw = f"{rider_id}:{trigger_id}:{policy_id}"
    return hashlib.sha256(raw.encode()).hexdigest()
