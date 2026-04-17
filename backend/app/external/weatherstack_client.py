"""external/weatherstack_client.py — Weatherstack wet bulb temperature (primary for heat trigger)."""
from __future__ import annotations
import math, httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import get_settings
from app.external.circuit_breaker import get_circuit_breaker

settings = get_settings()
_cb      = get_circuit_breaker("weatherstack")


def _stull_wet_bulb(temp_c: float, rh_percent: float) -> float:
    T, RH = temp_c, rh_percent
    return (
        T * math.atan(0.151977 * math.sqrt(RH + 8.313659))
        + math.atan(T + RH)
        - math.atan(RH - 1.676331)
        + 0.00391838 * (RH ** 1.5) * math.atan(0.023101 * RH)
        - 4.686035
    )


def _score_heat(wet_bulb: float) -> float:
    if wet_bulb >= 35:   return 1.00
    elif wet_bulb >= 32: return 0.50 + ((wet_bulb - 32) / 3) * 0.50
    return 0.00


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4), reraise=True)
def _fetch_weatherstack(lat: float, lng: float) -> dict:
    with httpx.Client(timeout=10) as client:
        resp = client.get("http://api.weatherstack.com/current", params={
            "access_key": settings.weatherstack_api_key,
            "query": f"{lat},{lng}",
            "units": "m",
        })
        resp.raise_for_status()
        return resp.json()


def fetch_heat_signal(lat: float, lng: float) -> dict:
    """Returns {heat_score, wet_bulb_c, temp_c, rh_pct, raw_data}."""
    def _call():
        return _fetch_weatherstack(lat, lng)
    data    = _cb.call(_call)
    current = data.get("current", {})
    temp    = float(current.get("temperature", 0))
    rh      = float(current.get("humidity", 0))
    wet_bulb = _stull_wet_bulb(temp, rh)
    return {
        "heat_score":  _score_heat(wet_bulb),
        "wet_bulb_c":  round(wet_bulb, 2),
        "temp_c":      temp,
        "rh_pct":      rh,
        "raw_data":    current,
    }
