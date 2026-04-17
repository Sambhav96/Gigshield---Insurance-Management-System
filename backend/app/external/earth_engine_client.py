"""
external/earth_engine_client.py — Google Earth Engine NDWI for flood detection.
Primary signal for flood trigger (spec §3.2).
Requires GEE service account JSON configured in settings.
"""
from __future__ import annotations
import structlog
from app.config import get_settings
from app.external.circuit_breaker import get_circuit_breaker

settings = get_settings()
_cb      = get_circuit_breaker("earth_engine")
log      = structlog.get_logger()


def _score_flood_ndwi(satellite_ndwi: float, ndma_active: int) -> float:
    """
    Spec §3.2 flood score:
    score = (0.60 × CLAMP((ndwi − 0.3) / 0.5, 0, 1)) + (0.40 × ndma_active)
    """
    sat_component  = 0.60 * max(0.0, min(1.0, (satellite_ndwi - 0.3) / 0.5))
    ndma_component = 0.40 * ndma_active
    return round(sat_component + ndma_component, 4)


def fetch_ndwi_signal(lat: float, lng: float, ndma_active: int = 0) -> dict:
    """
    Fetch NDWI from Google Earth Engine for flood detection.
    Falls back gracefully if GEE not configured (returns 0.0 with unavailable source).
    """
    if not settings.earth_engine_service_account_json:
        log.warning("earth_engine_not_configured")
        return {
            "satellite_score": 0.0,
            "ndwi_value":      0.0,
            "flood_score":     _score_flood_ndwi(0.0, ndma_active),
            "source":          "unavailable",
            "raw_data":        {},
        }

    def _call():
        try:
            import ee
            credentials = ee.ServiceAccountCredentials(
                None, key_file=settings.earth_engine_service_account_json
            )
            ee.Initialize(credentials)
            point      = ee.Geometry.Point([lng, lat])
            sentinel2  = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(point)
                .filterDate(
                    ee.Date.now().advance(-7, "day"),
                    ee.Date.now(),
                )
                .sort("CLOUDY_PIXEL_PERCENTAGE")
                .first()
            )
            nir  = sentinel2.select("B8")
            swir = sentinel2.select("B11")
            ndwi = nir.subtract(swir).divide(nir.add(swir))
            val  = ndwi.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=point, scale=10
            ).getInfo()
            return {"ndwi": val.get("B8", 0.0) or 0.0}
        except ImportError:
            log.warning("earthengine_api_not_installed")
            return {"ndwi": 0.0}

    try:
        result     = _cb.call(_call)
        ndwi_value = float(result.get("ndwi", 0.0))
        return {
            "satellite_score": max(0.0, min(1.0, (ndwi_value - 0.3) / 0.5)),
            "ndwi_value":      ndwi_value,
            "flood_score":     _score_flood_ndwi(ndwi_value, ndma_active),
            "source":          "earth_engine",
            "raw_data":        result,
        }
    except Exception as exc:
        log.error("earth_engine_fetch_failed", error=str(exc))
        return {
            "satellite_score": 0.0, "ndwi_value": 0.0,
            "flood_score":     _score_flood_ndwi(0.0, ndma_active),
            "source":          "failed", "raw_data": {},
        }
