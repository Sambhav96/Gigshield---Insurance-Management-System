"""external/imd_client.py — IMD Open Data API (fallback for rain trigger)."""
from __future__ import annotations
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.external.circuit_breaker import get_circuit_breaker

_cb = get_circuit_breaker("imd")

IMD_BASE_URL = "https://imdpune.gov.in/cmpg/Realtime/obs_rainfall.php"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=6), reraise=True)
def _fetch_imd(lat: float, lng: float) -> dict:
    """IMD Open Data — returns nearest station rainfall in mm/hr."""
    with httpx.Client(timeout=12) as client:
        resp = client.get(IMD_BASE_URL, params={"lat": lat, "lon": lng}, timeout=12)
        resp.raise_for_status()
        return resp.json()


def fetch_imd_rain_signal(lat: float, lng: float, hub_threshold: float = 35.0) -> dict:
    """Returns same format as owm_client.fetch_owm_signals for drop-in fallback use."""
    from app.external.owm_client import _score_rain

    def _call():
        return _fetch_imd(lat, lng)

    try:
        data         = _cb.call(_call)
        rainfall_mm  = float(data.get("rainfall_mm_hr", 0))
        return {
            "rain_score":      _score_rain(rainfall_mm, hub_threshold),
            "heat_score":      0.0,
            "temp_c":          0.0,
            "rh_pct":          0.0,
            "rainfall_mm_hr":  rainfall_mm,
            "wet_bulb_c":      0.0,
            "raw_data":        data,
        }
    except Exception:
        return {"rain_score": 0.0, "heat_score": 0.0, "temp_c": 0, "rh_pct": 0,
                "rainfall_mm_hr": 0, "wet_bulb_c": 0, "raw_data": {}}
