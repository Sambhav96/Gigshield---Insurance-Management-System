"""external/owm_client.py — OpenWeatherMap One Call 3.0 client."""
from __future__ import annotations

import math
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.external.circuit_breaker import get_circuit_breaker

settings = get_settings()
_cb = get_circuit_breaker("owm")


def _compute_wet_bulb_stull(temp_c: float, rh_percent: float) -> float:
    """
    Stull (2011) wet bulb approximation.
    Tw = T×arctan(0.151977×√(RH+8.313659))
       + arctan(T+RH) - arctan(RH-1.676331)
       + 0.00391838×RH^1.5×arctan(0.023101×RH) - 4.686035
    """
    T = temp_c
    RH = rh_percent
    Tw = (
        T * math.atan(0.151977 * math.sqrt(RH + 8.313659))
        + math.atan(T + RH)
        - math.atan(RH - 1.676331)
        + 0.00391838 * (RH ** 1.5) * math.atan(0.023101 * RH)
        - 4.686035
    )
    return Tw


def _score_rain(rainfall_mm_hr: float, hub_threshold: float = 35.0) -> float:
    if rainfall_mm_hr >= 50:
        return 1.00
    elif rainfall_mm_hr >= 35:
        return 0.70 + ((rainfall_mm_hr - 35) / 15) * 0.30
    elif rainfall_mm_hr >= 20:
        return 0.30 + ((rainfall_mm_hr - 20) / 15) * 0.40
    return 0.00


def _score_heat(temp_c: float, rh_percent: float) -> float:
    Tw = _compute_wet_bulb_stull(temp_c, rh_percent)
    if Tw >= 35:
        return 1.00
    elif Tw >= 32:
        return 0.50 + ((Tw - 32) / 3) * 0.50
    return 0.00


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4), reraise=True)
def _fetch_owm(lat: float, lng: float) -> dict:
    url = "https://api.openweathermap.org/data/3.0/onecall"
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, params={
            "lat": lat, "lon": lng,
            "exclude": "minutely,daily,alerts",
            "appid": settings.owm_api_key,
            "units": "metric",
        })
        resp.raise_for_status()
        return resp.json()


def fetch_owm_signals(lat: float, lng: float, hub_threshold: float = 35.0) -> dict:
    """
    Returns: {
        rain_score, heat_score, temp_c, rh_pct, rainfall_mm_hr, wet_bulb_c,
        raw_data
    }
    Raises on failure — caller handles via fetch_with_fallback.
    """
    def _call():
        return _fetch_owm(lat, lng)

    data = _cb.call(_call)

    current = data.get("current", {})
    rain_1h = current.get("rain", {}).get("1h", 0.0)
    temp = current.get("temp", 0.0)
    rh = current.get("humidity", 0.0)
    wet_bulb = _compute_wet_bulb_stull(temp, rh)

    return {
        "rain_score": _score_rain(rain_1h, hub_threshold),
        "heat_score": _score_heat(temp, rh),
        "temp_c": temp,
        "rh_pct": rh,
        "rainfall_mm_hr": rain_1h,
        "wet_bulb_c": wet_bulb,
        "raw_data": current,
    }
