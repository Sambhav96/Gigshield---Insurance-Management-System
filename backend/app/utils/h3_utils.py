"""utils/h3_utils.py — H3 hexagonal grid operations."""
import h3


def latlng_to_h3(lat: float, lng: float, resolution: int = 9) -> str:
    if hasattr(h3, "latlng_to_cell"):
        return h3.latlng_to_cell(lat, lng, resolution)
    return h3.geo_to_h3(lat, lng, resolution)


def get_adjacent_cells(h3_index: str) -> list[str]:
    """Returns the 6 immediate neighbours of an H3 cell (k=1 ring, excluding center)."""
    try:
        if hasattr(h3, "grid_disk"):
            return list(h3.grid_disk(h3_index, 1) - {h3_index})
        return list(set(h3.k_ring(h3_index, 1)) - {h3_index})
    except Exception:
        return []


def is_in_zone(lat: float, lng: float, h3_index: str, resolution: int = 9) -> bool:
    """Check if a lat/lng falls in the given H3 cell."""
    cell = latlng_to_h3(lat, lng, resolution)
    return cell == h3_index


def is_in_zone_or_adjacent(lat: float, lng: float, h3_index: str) -> bool:
    try:
        cell = latlng_to_h3(lat, lng, 9)
        adjacent = get_adjacent_cells(h3_index)
        return cell == h3_index or cell in adjacent
    except Exception:
        return False


def h3_to_latlng(h3_index: str) -> tuple[float, float]:
    if hasattr(h3, "cell_to_latlng"):
        return h3.cell_to_latlng(h3_index)
    return h3.h3_to_geo(h3_index)
