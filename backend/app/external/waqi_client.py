"""external/waqi_client.py — WAQI Air Quality API client."""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.external.circuit_breaker import get_circuit_breaker

settings = get_settings()
_cb = get_circuit_breaker("waqi")


def _score_aqi(aqi: int) -> float:
    if aqi >= 450:
        return 1.00   # Hazardous — Pro plan threshold
    elif aqi >= 300:
        return 0.80
    elif aqi >= 200:
        return 0.60   # Standard plan threshold floor
    return 0.00


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4), reraise=True)
def _fetch_waqi(lat: float, lng: float) -> dict:
    url = f"https://api.waqi.info/feed/geo:{lat};{lng}/"
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, params={"token": settings.waqi_api_key})
        resp.raise_for_status()
        return resp.json()


def fetch_aqi_signal(lat: float, lng: float) -> dict:
    """Returns: {aqi_score, aqi_value, raw_data}"""
    def _call():
        return _fetch_waqi(lat, lng)

    data = _cb.call(_call)

    aqi_value = int(data.get("data", {}).get("aqi", 0))
    return {
        "aqi_score": _score_aqi(aqi_value),
        "aqi_value": aqi_value,
        "raw_data": data.get("data", {}),
    }
