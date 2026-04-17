"""utils/haversine.py — GPS distance calculation."""
from haversine import haversine as _haversine, Unit


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in kilometres between two GPS coordinates."""
    return _haversine((lat1, lng1), (lat2, lng2), unit=Unit.KILOMETERS)


def implied_speed_kmh(
    lat1: float, lng1: float, lat2: float, lng2: float, delta_seconds: float
) -> float:
    """Return implied speed between two pings in km/h. Catches GPS spoofing."""
    if delta_seconds <= 0:
        return 0.0
    dist = distance_km(lat1, lng1, lat2, lng2)
    hours = delta_seconds / 3600
    return dist / hours if hours > 0 else 0.0
