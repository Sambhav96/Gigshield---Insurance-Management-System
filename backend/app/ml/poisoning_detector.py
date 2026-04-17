"""
ml/poisoning_detector.py — Training data quality filter (spec Section 22).

Detects poisoned training samples before model retraining:
  1. Anomalous claim rates (riders with > 3× city median claim frequency)
  2. Cluster contamination (riders in fraud_clusters table)
  3. Feature outliers (income anomalies, impossible GPS patterns)
  4. Label manipulation (claims with manual_override=True skew the model)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger()

# Thresholds
MAX_CLAIM_RATE_MULTIPLIER   = 3.0   # > 3× median = suspicious
MAX_INCOME_PERCENTILE       = 99.5  # cap extreme income values
MIN_SHIFT_HOURS             = 0.5   # less than 30 min/day = invalid


def filter_poisoned_samples(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Filter training DataFrame before retraining.
    Returns (clean_df, quality_report).

    Expected columns: rider_id, risk_score, claims_per_week_90d,
                      avg_fraud_score_90d, hard_flag_count_90d,
                      avg_shift_hours_7d, effective_income_normalized,
                      hub_drainage_index, will_claim,
                      is_fraud_cluster (bool), has_manual_override (bool)
    """
    original_size = len(df)
    quality_report = {"original_count": original_size, "filters_applied": []}

    # 1. Remove fraud cluster riders (contaminated labels)
    if "is_fraud_cluster" in df.columns:
        before = len(df)
        df = df[~df["is_fraud_cluster"].fillna(False)]
        removed = before - len(df)
        quality_report["filters_applied"].append({
            "filter": "fraud_cluster_riders", "removed": removed
        })

    # 2. Remove manual-override claims (not organic signals)
    if "has_manual_override" in df.columns:
        before = len(df)
        df = df[~df["has_manual_override"].fillna(False)]
        removed = before - len(df)
        quality_report["filters_applied"].append({
            "filter": "manual_override_claims", "removed": removed
        })

    # 3. Remove anomalous claim rates
    if "claims_per_week_90d" in df.columns:
        city_median = df["claims_per_week_90d"].median()
        threshold   = city_median * MAX_CLAIM_RATE_MULTIPLIER
        before      = len(df)
        df          = df[df["claims_per_week_90d"] <= max(threshold, 3.0)]
        removed     = before - len(df)
        quality_report["filters_applied"].append({
            "filter": "anomalous_claim_rate",
            "threshold": float(threshold), "removed": removed
        })

    # 4. Remove zero/near-zero shift hours (likely phantom riders)
    if "avg_shift_hours_7d" in df.columns:
        before = len(df)
        df     = df[df["avg_shift_hours_7d"] >= MIN_SHIFT_HOURS]
        removed = before - len(df)
        quality_report["filters_applied"].append({
            "filter": "phantom_riders_low_shift", "removed": removed
        })

    # 5. Cap income outliers (Winsorize at 99.5th percentile)
    if "effective_income_normalized" in df.columns:
        cap = np.percentile(df["effective_income_normalized"], MAX_INCOME_PERCENTILE)
        df["effective_income_normalized"] = df["effective_income_normalized"].clip(upper=cap)
        quality_report["filters_applied"].append({
            "filter": "income_outlier_winsorize", "cap": float(cap), "removed": 0
        })

    # 6. Remove rows with NaN in critical columns
    critical_cols = [c for c in ["risk_score", "will_claim"] if c in df.columns]
    before = len(df)
    df     = df.dropna(subset=critical_cols)
    removed = before - len(df)
    quality_report["filters_applied"].append({
        "filter": "null_critical_fields", "removed": removed
    })

    quality_report["final_count"]  = len(df)
    quality_report["removed_total"] = original_size - len(df)
    quality_report["retention_pct"] = round(len(df) / original_size * 100, 1) if original_size > 0 else 0

    log.info(
        "poisoning_filter_complete",
        original=original_size, final=len(df),
        removed=quality_report["removed_total"],
        retention_pct=quality_report["retention_pct"],
    )

    return df, quality_report
