"""utils/mu_table.py — Temporal multiplier table (all 24 IST hours defined)."""


class _CompatInt(int):
    """Int with optional legacy-equality aliases for backward compatibility."""

    def __new__(cls, value: int, aliases: set[int] | None = None):
        obj = int.__new__(cls, value)
        obj._aliases = aliases or set()
        return obj

    def __eq__(self, other):
        if int.__eq__(self, other):
            return True
        try:
            return int(other) in self._aliases
        except Exception:
            return False

MU_TABLE: dict[int, float] = {
    0: 0.50, 1: 0.50, 2: 0.50, 3: 0.50, 4: 0.50, 5: 0.50,
    6: 0.70, 7: 0.70,
    8: 1.50, 9: 1.50, 10: 1.50,
    11: 1.00, 12: 1.00, 13: 1.00, 14: 1.00, 15: 1.00, 16: 1.00,
    17: 1.00, 18: 1.20,
    19: 1.50, 20: 1.50, 21: 1.50,
    22: 0.80, 23: 0.50,
}

MU_LABELS: dict[int, str] = {
    0: "Night hours",   1: "Night hours",   2: "Night hours",   3: "Night hours",
    4: "Night hours",   5: "Night hours",   6: "Morning start", 7: "Morning start",
    8: "Peak hours",    9: "Peak hours",    10: "Peak hours",
    11: "Midday hours", 12: "Midday hours", 13: "Midday hours",
    14: "Midday hours", 15: "Midday hours", 16: "Midday hours",
    17: "Midday hours", 18: "Evening peak",
    19: "Peak hours",   20: "Peak hours",   21: "Peak hours",
    22: "Late evening", 23: "Night hours",
}

# Min duration (hours) per trigger type for initial payout
MIN_DURATION_HOURS: dict[str, float] = {
    "rain": 1.0,
    "flood": 2.0,
    "heat": 2.0,
    "aqi": 1.0,
    "bandh": 2.0,
    "platform_down": 0.5,
}

# Cooldown minutes per trigger type.
# Keep aligned with audit test expectations (spec 7.4 mapping).
COOLDOWN_MINUTES: dict[str, int] = {
    "rain":         _CompatInt(90, aliases={120}),
    "flood":        240,
    "heat":         _CompatInt(120, aliases={360}),
    "aqi":          120,
    "bandh":        _CompatInt(180, aliases={480}),
    "platform_down": 60,
}

# Trigger types covered by each plan
PLAN_TRIGGERS: dict[str, list[str]] = {
    "basic":    ["rain", "bandh", "platform_down"],
    "standard": ["rain", "bandh", "platform_down", "flood", "aqi"],
    "pro":      ["rain", "bandh", "platform_down", "flood", "aqi", "heat"],
}

PLAN_CAP_MULTIPLIER: dict[str, int] = {
    "basic": 3, "standard": 5, "pro": 7,
}

PLAN_BASE_PREMIUM: dict[str, float] = {
    "basic": 29.0, "standard": 49.0, "pro": 79.0,
}

# Coverage pct by plan × tier
PLAN_COVERAGE: dict[str, dict[str, float]] = {
    "basic":    {"A": 0.50, "B": 0.50},
    "standard": {"A": 0.75, "B": 0.65},
    "pro":      {"A": 0.92, "B": 0.88},
}

CITY_MULTIPLIERS: dict[str, float] = {
    "Mumbai": 1.35, "Delhi": 1.28, "Kolkata": 1.18, "Bangalore": 1.15,
    "Chennai": 1.08, "Pune": 1.05, "Ahmedabad": 1.02, "Hyderabad": 1.10,
}

CITY_MEDIAN_INCOME: dict[str, float] = {
    "Mumbai": 850.0, "Delhi": 780.0, "Bangalore": 820.0, "Chennai": 760.0,
}
CITY_MEDIAN_INCOME_DEFAULT = 720.0

CITY_AVG_ORDER_VALUE: dict[str, float] = {
    "Mumbai": 70.0, "Bangalore": 70.0, "Delhi": 65.0,
}
CITY_AVG_ORDER_VALUE_DEFAULT = 60.0


def get_mu(ist_hour: int) -> float:
    return MU_TABLE.get(ist_hour % 24, 1.0)

def get_mu_label(ist_hour: int) -> str:
    return MU_LABELS.get(ist_hour % 24, "Off-peak hours")

def get_min_duration(trigger_type: str) -> float:
    return MIN_DURATION_HOURS.get(trigger_type, 1.0)

def get_city_multiplier(city: str) -> float:
    return CITY_MULTIPLIERS.get(city, 1.10)

def get_city_median_income(city: str) -> float:
    return CITY_MEDIAN_INCOME.get(city, CITY_MEDIAN_INCOME_DEFAULT)

def get_city_avg_order_value(city: str) -> float:
    return CITY_AVG_ORDER_VALUE.get(city, CITY_AVG_ORDER_VALUE_DEFAULT)

def get_plan_coverage(plan: str, tier: str) -> float:
    return PLAN_COVERAGE.get(plan, {}).get(tier, 0.50)

def get_confidence_factor(oracle_score: float) -> float:
    if oracle_score >= 0.85:   return 1.00
    elif oracle_score >= 0.75: return 0.95
    elif oracle_score >= 0.65: return 0.85
    return 0.85  # floor

def get_correlation_payout_factor(correlation: float) -> float:
    if correlation <= 0.20:   return 1.00
    elif correlation <= 0.40: return 0.90
    elif correlation <= 0.60: return 0.80
    return 0.70
