"""
services/oracle_service.py — AUDIT FIXED

CODE-05 FIX: platform_down uses health check score directly (not weather=0.0)
GAP-19 FIX:  Weatherstack (heat primary), IMD (rain fallback),
             Earth Engine (flood primary), NDMA (flood fallback) all wired
"""
from __future__ import annotations

import json, time
from typing import Optional
import structlog

from app.core.redis_client import get_sync_redis
from app.external.circuit_breaker import CircuitOpenError
from app.utils.mu_table import COOLDOWN_MINUTES, get_correlation_payout_factor

log = structlog.get_logger()

WEIGHT_CONFIGS = {
    "base":  {"satellite": 0.40, "weather": 0.30, "traffic": 0.30},
    "peer":  {"satellite": 0.35, "weather": 0.25, "traffic": 0.20, "peer": 0.20},
    "accel": {"satellite": 0.35, "weather": 0.25, "traffic": 0.20, "accel": 0.20},
    "both":  {"satellite": 0.30, "weather": 0.20, "traffic": 0.15, "peer": 0.20, "accel": 0.15},
}

CACHE_TTL = {"owm_weather": 900, "waqi_aqi": 1800, "here_traffic": 600, "earth_engine": 7200, "weatherstack": 7200}
DEFAULT_ORACLE_THRESHOLD = 0.65
COLD_START_THRESHOLD     = 0.75
VOV_UNCERTAIN_FLOOR      = 0.30
TRIGGER_PRIORITY         = ["flood", "platform_down", "bandh", "rain", "aqi", "heat"]


def _bucket(): return int(time.time()) // 900
def _ck(src, h3): return f"oracle:{src}:{h3}:{_bucket()}"


def _fetch_with_fallback(primary_fn, fallback_fn, ck, ttl, redis, *args, **kwargs):
    cached_raw = redis.get(ck)
    if cached_raw:
        try:
            c = json.loads(cached_raw)
            if time.time() - c.get("_ts", 0) < ttl:
                return c, "cache", 0.0
        except Exception: pass
    try:
        r = primary_fn(*args, **kwargs)
        if r:
            r["_ts"] = time.time()
            redis.set(ck, json.dumps(r, default=str), ex=ttl)
            return r, "primary", 0.0
    except Exception as e:
        log.warning("oracle_primary_failed", error=str(e))
    if fallback_fn:
        try:
            r = fallback_fn(*args, **kwargs)
            if r:
                r["_ts"] = time.time()
                redis.set(ck, json.dumps(r, default=str), ex=ttl)
                return r, "fallback", 0.10
        except Exception as e:
            log.warning("oracle_fallback_failed", error=str(e))
    if cached_raw:
        try: return json.loads(cached_raw), "stale_cache", 0.15
        except Exception: pass
    return None, "unavailable", None


def _apply_penalties(weights, penalties):
    return {k: w * max(0.0, 1.0 - (penalties.get(k, 0.0) or 0.0))
            for k, w in weights.items() if penalties.get(k) is not None}


def _renormalize(weights):
    total = sum(weights.values())
    if total <= 0: return {}
    return {k: v / total for k, v in weights.items()}


def compute_oracle_score(
    trigger_type: str, lat: float, lng: float, h3_index: str,
    hub_threshold_mm: float = 35.0, platform_down_score: float = 0.0,
    peer_active: bool = False, accel_active: bool = False,
    peer_score: float = 0.0, accel_score: float = 0.0,
) -> dict:
    from app.external.owm_client import fetch_owm_signals
    from app.external.waqi_client import fetch_aqi_signal
    from app.external.here_client import fetch_traffic_signal
    from app.external.imd_client import fetch_imd_rain_signal
    from app.external.weatherstack_client import fetch_heat_signal
    from app.external.earth_engine_client import fetch_ndwi_signal
    from app.external.ndma_client import fetch_flood_signal

    redis    = get_sync_redis()
    signals  = {}; sources = {}; penalties = {}; raw_data = {}

    if trigger_type == "rain":
        d, src, pen = _fetch_with_fallback(
            lambda: fetch_owm_signals(lat, lng, hub_threshold_mm),
            lambda: fetch_imd_rain_signal(lat, lng, hub_threshold_mm),
            _ck("owm_weather", h3_index), CACHE_TTL["owm_weather"], redis,
        )
        if d:
            signals["weather"] = d.get("rain_score", 0.0)
            sources["weather"] = src; penalties["weather"] = pen; raw_data["rain"] = d
        else:
            penalties["weather"] = None

    elif trigger_type == "heat":
        # GAP-19 FIX: Weatherstack is primary for heat (spec §3.3)
        d, src, pen = _fetch_with_fallback(
            lambda: fetch_heat_signal(lat, lng),
            lambda: fetch_owm_signals(lat, lng, hub_threshold_mm),  # OWM fallback with Stull
            _ck("weatherstack", h3_index), CACHE_TTL["weatherstack"], redis,
        )
        if d:
            signals["weather"] = d.get("heat_score", 0.0)
            sources["weather"] = src; penalties["weather"] = pen; raw_data["heat"] = d
        else:
            penalties["weather"] = None

    elif trigger_type == "aqi":
        d, src, pen = _fetch_with_fallback(
            lambda: fetch_aqi_signal(lat, lng),
            None,
            _ck("waqi_aqi", h3_index), CACHE_TTL["waqi_aqi"], redis,
        )
        if d:
            signals["weather"] = d.get("aqi_score", 0.0)
            sources["weather"] = src; penalties["weather"] = pen; raw_data["aqi"] = d
        else:
            penalties["weather"] = None

    elif trigger_type == "flood":
        # GAP-19 FIX: Earth Engine primary, NDMA fallback
        ndma_d = fetch_flood_signal(lat, lng)  # always try NDMA
        ndma_active = ndma_d.get("ndma_active", 0)

        d, src, pen = _fetch_with_fallback(
            lambda: fetch_ndwi_signal(lat, lng, ndma_active),
            lambda: {"satellite_score": 0.0, "flood_score": 0.40 * ndma_active,
                     "ndwi_value": 0.0, "source": "ndma_only", "_ts": time.time()},
            _ck("earth_engine", h3_index), CACHE_TTL["earth_engine"], redis,
        )
        if d:
            signals["satellite"] = d.get("satellite_score", 0.0)
            sources["satellite"] = src; penalties["satellite"] = pen
            raw_data["flood"] = d
        else:
            penalties["satellite"] = None
        # Weather signal still from OWM (rain intensity for flood)
        owm, src2, pen2 = _fetch_with_fallback(
            lambda: fetch_owm_signals(lat, lng, hub_threshold_mm),
            None, _ck("owm_weather", h3_index), CACHE_TTL["owm_weather"], redis,
        )
        if owm:
            signals["weather"] = owm.get("rain_score", 0.0)
            sources["weather"] = src2; penalties["weather"] = pen2

    elif trigger_type == "bandh":
        d, src, pen = _fetch_with_fallback(
            lambda: fetch_traffic_signal(lat, lng),
            None,
            _ck("here_traffic", h3_index), CACHE_TTL["here_traffic"], redis,
        )
        if d:
            signals["traffic"] = d.get("bandh_score", 0.0)
            sources["traffic"] = src; penalties["traffic"] = pen; raw_data["bandh"] = d
        else:
            penalties["traffic"] = None

    elif trigger_type == "platform_down":
        # CODE-05 FIX: use actual platform_down_score from health checks, not 0.0
        signals["weather"]  = platform_down_score
        sources["weather"]  = "health_check"
        penalties["weather"] = 0.0

    if peer_active and peer_score > 0:
        signals["peer"] = float(peer_score); sources["peer"] = "peer_consensus"; penalties["peer"] = 0.0
    if accel_active and accel_score > 0:
        signals["accel"] = float(accel_score); sources["accel"] = "accelerometer"; penalties["accel"] = 0.0

    if peer_active and accel_active:   cfg = "both"
    elif peer_active:                  cfg = "peer"
    elif accel_active:                 cfg = "accel"
    else:                              cfg = "base"

    weights    = dict(WEIGHT_CONFIGS[cfg])
    adjusted   = _apply_penalties(weights, penalties)
    normalized = _renormalize(adjusted)

    if not normalized:
        return {"oracle_score": 0.0, "weight_config_name": cfg, "weight_config": {},
                "signal_scores": {}, "signal_sources": {}, "raw_api_data": {}, "penalties": {}}

    oracle_score = round(max(0.0, min(1.0,
        sum(normalized.get(k, 0.0) * signals.get(k, 0.0) for k in normalized)
    )), 4)

    log.info("oracle_computed", trigger_type=trigger_type, h3=h3_index, score=oracle_score, cfg=cfg)
    return {"oracle_score": oracle_score, "weight_config_name": cfg, "weight_config": normalized,
            "signal_scores": signals, "signal_sources": sources, "raw_api_data": raw_data, "penalties": penalties}


def compute_correlation_factor(cur, city, trigger_type):
    if trigger_type == "platform_down": return 1.0, 0.70
    cur.execute("SELECT COUNT(DISTINCT h3_index_res9) AS t FROM hubs WHERE city=%s", (city,))
    total = int(cur.fetchone()["t"] or 1)
    cur.execute("""
        SELECT COUNT(DISTINCT te.h3_index) AS a FROM trigger_events te
        JOIN hubs h ON te.hub_id=h.id
        WHERE h.city=%s AND te.status IN ('active','resolving') AND te.triggered_at>=NOW()-INTERVAL '2 hours'
    """, (city,))
    active = int(cur.fetchone()["a"] or 0)
    C = active / total
    return round(C, 4), get_correlation_payout_factor(C)


def compute_cooldown_factor(cur, h3_index, trigger_type):
    cooldown_mins = COOLDOWN_MINUTES.get(trigger_type, 90)
    cur.execute("""
        SELECT id FROM trigger_events WHERE h3_index=%s AND trigger_type=%s AND status='resolved'
          AND resolved_at >= NOW() - (%s || ' minutes')::interval LIMIT 1
    """, (h3_index, trigger_type, str(cooldown_mins)))
    in_cd = cur.fetchone() is not None
    return in_cd, (0.50 if in_cd else 1.00)


def resolve_stacking(concurrent_triggers):
    if not concurrent_triggers: raise ValueError("No triggers")
    if len(concurrent_triggers) == 1: return concurrent_triggers[0], []
    pri = {t: i for i, t in enumerate(TRIGGER_PRIORITY)}
    s = sorted(concurrent_triggers, key=lambda t: (-t.get("event_payout_estimate", 0), pri.get(t["trigger_type"], 99)))
    return s[0], s[1:]


def get_oracle_threshold(cur, group_id, cold_start):
    if cold_start: return COLD_START_THRESHOLD
    try:
        cur.execute("""
            SELECT parameter_value::float FROM experiments
            WHERE parameter_name='oracle_threshold' AND group_id IN (%s,'all') AND active=true
            ORDER BY CASE WHEN group_id=%s THEN 0 ELSE 1 END, created_at DESC LIMIT 1
        """, (group_id, group_id))
        row = cur.fetchone()
        if row: return float(row["parameter_value"])
    except Exception as e:
        log.warning("experiment_threshold_read_failed", error=str(e))
    return DEFAULT_ORACLE_THRESHOLD
