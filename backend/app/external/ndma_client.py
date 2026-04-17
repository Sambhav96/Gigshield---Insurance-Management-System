"""external/ndma_client.py — NDMA Disaster Advisory API (fallback for flood trigger)."""
from __future__ import annotations
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import get_settings
from app.external.circuit_breaker import get_circuit_breaker

settings = get_settings()
_cb      = get_circuit_breaker("ndma")


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=6), reraise=True)
def _fetch_ndma(lat: float, lng: float) -> dict:
    url = f"{settings.ndma_api_url}/advisories"
    with httpx.Client(timeout=12) as client:
        resp = client.get(url, params={"lat": lat, "lon": lng, "radius_km": 25})
        resp.raise_for_status()
        return resp.json()


def fetch_flood_signal(lat: float, lng: float) -> dict:
    """
    Returns {flood_score, ndma_active, advisories, raw_data}.
    NDMA advisory present → ndma_active = 1 → contributes 0.40 to flood score.
    """
    def _call():
        return _fetch_ndma(lat, lng)

    try:
        data      = _cb.call(_call)
        advisories = data.get("advisories", [])
        ndma_active = 1 if advisories else 0
        # NDMA alone contributes 0.40 to flood score (spec §3.2)
        flood_score = 0.40 * ndma_active
        return {
            "flood_score": flood_score,
            "ndma_active": ndma_active,
            "advisories":  advisories,
            "raw_data":    data,
        }
    except Exception:
        return {"flood_score": 0.0, "ndma_active": 0, "advisories": [], "raw_data": {}}
