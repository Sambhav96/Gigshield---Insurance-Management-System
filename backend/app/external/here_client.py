"""external/here_client.py — HERE Maps traffic API client for bandh detection."""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.external.circuit_breaker import get_circuit_breaker

settings = get_settings()
_cb = get_circuit_breaker("here")


def _score_bandh_traffic(speed_ratio: float, nlp_score: float = 0.0) -> float:
    """
    speed_ratio = current_avg_speed / 30-day baseline
    nlp_score = TF-IDF bandh keyword score (capped at 0.50, cannot auto-trigger alone)
    """
    if speed_ratio <= 0.05:
        traffic_score = 1.00
    elif speed_ratio <= 0.15:
        traffic_score = 0.60 + ((0.15 - speed_ratio) / 0.10) * 0.40
    else:
        traffic_score = 0.00

    # NLP alone cannot auto-trigger
    combined = max(traffic_score, nlp_score * 0.80)
    return combined


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4), reraise=True)
def _fetch_here_flow(lat: float, lng: float, radius_m: int = 3000) -> dict:
    url = "https://data.traffic.hereapi.com/v7/flow"
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, params={
            "in": f"circle:{lat},{lng};r={radius_m}",
            "locationReferencing": "none",
            "apiKey": settings.here_api_key,
        })
        resp.raise_for_status()
        return resp.json()


def fetch_traffic_signal(lat: float, lng: float, baseline_kmh: float = 30.0) -> dict:
    """Returns: {bandh_score, traffic_score, speed_ratio, avg_speed_kmh, raw_data}"""
    def _call():
        return _fetch_here_flow(lat, lng)

    data = _cb.call(_call)

    # Extract average speed from HERE flow data
    results = data.get("results", [])
    speeds = []
    for r in results:
        current_flow = r.get("currentFlow", {})
        speed = current_flow.get("speed", None)
        if speed is not None:
            speeds.append(speed)

    avg_speed = sum(speeds) / len(speeds) if speeds else baseline_kmh
    speed_ratio = avg_speed / baseline_kmh if baseline_kmh > 0 else 1.0

    traffic_score = _score_bandh_traffic(speed_ratio)

    return {
        "bandh_score": traffic_score,
        "traffic_score": traffic_score,
        "speed_ratio": speed_ratio,
        "avg_speed_kmh": avg_speed,
        "raw_data": {"results_count": len(results)},
    }
