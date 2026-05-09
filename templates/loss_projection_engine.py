"""loss_projection_engine.py

Config-driven forensic loss projection.
Usage:
    python templates/loss_projection_engine.py --config clients/client_name_001/client_config.py
"""

import argparse
import importlib.util
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# -----------------------------------------------
# Date Validation
# -----------------------------------------------

def validate_review_date(review_date_str):
    try:
        review_date = datetime.strptime(review_date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f"REVIEW_DATE '{review_date_str}' is not in YYYY-MM-DD format. "
            f"Example: '2024-06-01'"
        )
    return review_date

# -----------------------------------------------
# Load Gold Layer
# -----------------------------------------------

def load_gold(path, review_date_str, date_col, revenue_col):
    df = pd.read_csv(path, parse_dates=[date_col])
    df = df[df[revenue_col].notna()]
    df = df[df[date_col].notna()]
    df = df.sort_values(date_col)

    # Check REVIEW_DATE falls within the data range
    data_min = df[date_col].min()
    data_max = df[date_col].max()
    review_dt = pd.Timestamp(review_date_str)

    print(f"  Data range     : {data_min.date()} -> {data_max.date()}")
    print(f"  Review date    : {review_date_str}")

    if review_dt < data_min:
        raise ValueError(
            f"REVIEW_DATE {review_date_str} is before the earliest data point "
            f"({data_min.date()}). No baseline can be established."
        )
    if review_dt > data_max:
        print(
            f"[WARN] REVIEW_DATE {review_date_str} is after the latest data point "
            f"({data_max.date()}). Post-review actuals will all be N/A."
        )

    return df

# -----------------------------------------------
# Monthly Aggregation
# -----------------------------------------------

def monthly_revenue(df, date_col, revenue_col):
    df = df.copy()
    df["month"] = df[date_col].dt.to_period("M")
    return df.groupby("month")[revenue_col].sum().reset_index()

# -----------------------------------------------
# Baseline Trend (pre-review)
# -----------------------------------------------

def check_seasonality(monthly_df, revenue_col):
    y = monthly_df[revenue_col].values
    if len(y) < 3:
        return
    cv = y.std() / y.mean() if y.mean() != 0 else 0
    if cv > 0.4:
        print(
            f"\n[WARN] High revenue variance detected (CV={cv:.2f}). "
            f"Seasonal spikes may cause the linear baseline to overstate losses. "
            f"Consider this a 'Silver Tier' caveat in your report."
        )
    else:
        print(f"  Seasonality check: CV={cv:.2f} - variance acceptable for linear fit.")

def fit_baseline(monthly_df, review_date, revenue_col):
    cutoff = pd.Period(review_date, freq="M")
    pre = monthly_df[monthly_df["month"] < cutoff].copy()

    if len(pre) < 2:
        raise ValueError(
            f"Not enough pre-review data to fit a baseline. "
            f"Found {len(pre)} months before {review_date}."
        )

    x = np.arange(len(pre))
    y = pre[revenue_col].values
    coeffs = np.polyfit(x, y, 1)
    slope, intercept = coeffs

    print(f"\n=== BASELINE TREND (pre {review_date}) ===")
    print(f"  Months of data : {len(pre)}")
    print(f"  Avg monthly rev: ${y.mean():,.2f}")
    print(f"  Monthly growth : ${slope:+,.2f}/month")
    check_seasonality(pre, revenue_col)

    return pre, slope, intercept, len(pre)

# -----------------------------------------------
# Post-Review Actual Revenue
# -----------------------------------------------

def actual_post_review(monthly_df, review_date, revenue_col):
    cutoff = pd.Period(review_date, freq="M")
    post = monthly_df[monthly_df["month"] >= cutoff].copy()

    print(f"\n=== ACTUAL POST-REVIEW ===")
    if post.empty:
        print("  No post-review data found.")
    else:
        print(f"  Months of data : {len(post)}")
        print(f"  Avg monthly rev: ${post[revenue_col].mean():,.2f}")
        print(f"  Total revenue  : ${post[revenue_col].sum():,.2f}")

    return post

# -----------------------------------------------
# Loss Projection
# -----------------------------------------------

def project_loss(slope, intercept, pre_length, post_df, projection_months, review_date, revenue_col):
    rows = []
    total_projected = 0.0
    total_actual = 0.0
    total_loss = 0.0

    post_revenue = post_df.set_index("month")[revenue_col].to_dict() if not post_df.empty else {}

    print(f"\n=== LOSS PROJECTION ({projection_months} months) ===")
    print(f"  {'Month':<12} {'Projected':>12} {'Actual':>12} {'Loss':>12}")
    print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*12}")

    review_period = pd.Period(review_date, freq="M")

    for i in range(projection_months):
        month = review_period + i
        x_val = pre_length + i
        projected = max(0.0, slope * x_val + intercept)
        actual = post_revenue.get(month, None)

        if actual is not None:
            loss = max(0.0, projected - actual)
            actual_str = f"${actual:,.2f}"
        else:
            loss = projected
            actual_str = "N/A"

        total_projected += projected
        if actual is not None:
            total_actual += actual
        total_loss += loss

        print(f"  {str(month):<12} ${projected:>11,.2f} {actual_str:>12} ${loss:>11,.2f}")

        rows.append({
            "month": str(month),
            "projected_revenue": round(projected, 2),
            "actual_revenue": round(actual, 2) if actual is not None else None,
            "estimated_loss": round(loss, 2)
        })

    print(f"\n  {'TOTAL':<12} ${total_projected:>11,.2f} ${total_actual:>11,.2f} ${total_loss:>11,.2f}")
    print(f"\n  Estimated total loss over {projection_months} months: ${total_loss:,.2f}")

    return pd.DataFrame(rows), total_loss

# -----------------------------------------------
# Main
# -----------------------------------------------

def load_config(config_path):
    spec = importlib.util.spec_from_file_location("client_config", config_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unable to load config: {config_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "config"):
        raise ValueError(f"Config file missing 'config' dict: {config_path}")
    return module.config


def run_projection(config_path):
    config = load_config(config_path)
    base_dir = Path(config.get("base_dir", Path(config_path).resolve().parent)).resolve()
    output_path = Path(config["output_path"])
    if not output_path.is_absolute():
        output_path = (base_dir / output_path).resolve()
    output_dir = output_path.parent

    gold_file = output_dir / config.get("gold_output_filename", "client_sales_GOLD.csv")
    projection_output = output_dir / config.get("projection_output_filename", "loss_projection_report.csv")

    review_date = config.get("review_date", "2026-01-15")
    projection_months = int(config.get("projection_months", 60))
    revenue_col = config.get("projection_revenue_col", "total_sale")
    date_col = config.get("projection_date_col", "sale_date")

    validate_review_date(review_date)
    print(f"Loading Gold Layer: {gold_file}")
    df = load_gold(gold_file, review_date, date_col, revenue_col)
    print(f"Loaded {len(df)} clean rows.")

    monthly = monthly_revenue(df, date_col, revenue_col)
    _, slope, intercept, pre_length = fit_baseline(monthly, review_date, revenue_col)
    post = actual_post_review(monthly, review_date, revenue_col)
    projection_df, total_loss = project_loss(
        slope,
        intercept,
        pre_length,
        post,
        projection_months,
        review_date,
        revenue_col,
    )

    projection_df.to_csv(projection_output, index=False)
    print(f"\nProjection report written to: {projection_output}")
    print(f"Review date used            : {review_date}")
    print(
        f"Projection window           : {projection_months} months "
        f"({projection_months // 12} years)"
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run forensic loss projection.")
    parser.add_argument("--config", required=True, help="Path to client_config.py")
    args = parser.parse_args()
    run_projection(args.config)
