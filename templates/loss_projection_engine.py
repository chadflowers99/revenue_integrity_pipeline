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


MODE_ORDER = ["conservative", "moderate", "aggressive"]
MODE_SETTINGS = {
    "conservative": {
        "max_monthly_growth": 0.03,
        "monthly_growth_damping": 0.96,
    },
    "moderate": {
        "max_monthly_growth": 0.08,
        "monthly_growth_damping": 0.98,
    },
    "aggressive": {
        "max_monthly_growth": 0.15,
        "monthly_growth_damping": 0.99,
    },
}


def _sanitize_mode(mode):
    mode_normalized = str(mode or "moderate").strip().lower()
    if mode_normalized not in MODE_SETTINGS:
        print(f"[WARN] Unknown projection_mode '{mode}'. Falling back to 'moderate'.")
        return "moderate"
    return mode_normalized


def _downgrade_mode(mode):
    idx = MODE_ORDER.index(mode)
    return MODE_ORDER[max(0, idx - 1)]


def resolve_projection_controls(config, baseline_months):
    """Resolves capped-growth controls with baseline-confidence safeguards."""
    selected_mode = _sanitize_mode(config.get("projection_mode", "moderate"))
    base_controls = MODE_SETTINGS[selected_mode].copy()

    min_confident_months = int(config.get("min_confident_baseline_months", 6))
    low_confidence_horizon = int(config.get("low_confidence_max_horizon_months", 24))

    requested_horizon = int(config.get("projection_months", 60))
    max_horizon = requested_horizon
    applied_mode = selected_mode

    if baseline_months < min_confident_months:
        downgraded_mode = _downgrade_mode(selected_mode)
        if downgraded_mode != selected_mode:
            print(
                f"[WARN] Baseline months ({baseline_months}) < {min_confident_months}. "
                f"Downgrading projection mode from '{selected_mode}' to '{downgraded_mode}'."
            )
            applied_mode = downgraded_mode
            base_controls = MODE_SETTINGS[applied_mode].copy()

        if requested_horizon > low_confidence_horizon:
            max_horizon = low_confidence_horizon
            print(
                f"[WARN] Baseline months ({baseline_months}) are limited. "
                f"Shortening projection horizon from {requested_horizon} to {max_horizon} months."
            )

        # Apply extra caution under low confidence.
        base_controls["max_monthly_growth"] *= 0.75

    # Explicit config overrides take precedence over mode defaults.
    max_monthly_growth = float(
        config.get("max_monthly_growth", base_controls["max_monthly_growth"])
    )
    monthly_growth_damping = float(
        config.get("monthly_growth_damping", base_controls["monthly_growth_damping"])
    )

    print("\n=== PROJECTION CONTROLS ===")
    print(f"  Requested mode      : {selected_mode}")
    print(f"  Applied mode        : {applied_mode}")
    print(f"  Baseline months     : {baseline_months}")
    print(f"  Horizon (months)    : {max_horizon}")
    print(f"  Max monthly growth  : {max_monthly_growth:.2%}")
    print(f"  Growth damping/mo   : {monthly_growth_damping:.4f}")

    return {
        "projection_months": max_horizon,
        "max_monthly_growth": max_monthly_growth,
        "monthly_growth_damping": monthly_growth_damping,
    }


def safe_write_projection(df, projection_output):
    """Writes projection CSV and falls back to a timestamped filename if target is locked."""
    try:
        df.to_csv(projection_output, index=False)
        print(f"\nProjection report written to: {projection_output}")
        return projection_output
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_output = projection_output.with_name(
            f"{projection_output.stem}_{stamp}{projection_output.suffix or '.csv'}"
        )
        df.to_csv(fallback_output, index=False)
        print(
            f"\n[WARN] Projection output is locked/open. "
            f"Report written to fallback: {fallback_output}"
        )
        return fallback_output


def resolve_revenue_column(df, configured_revenue_col):
    """Resolves an existing revenue column or derives one from quantity * unit_price."""
    if configured_revenue_col in df.columns:
        return configured_revenue_col

    if {"quantity", "unit_price"}.issubset(df.columns):
        # Best-effort derive line-level revenue when canonical total_sale is absent.
        qty = pd.to_numeric(df["quantity"], errors="coerce")
        price = pd.to_numeric(df["unit_price"], errors="coerce")
        df["_derived_total_sale"] = qty * price
        print(
            f"[WARN] Revenue column '{configured_revenue_col}' not found. "
            "Using derived revenue from quantity * unit_price."
        )
        return "_derived_total_sale"

    fallback_candidates = ["total_sale", "total_revenue", "revenue", "amount", "unit_price"]
    for candidate in fallback_candidates:
        if candidate in df.columns:
            print(
                f"[WARN] Revenue column '{configured_revenue_col}' not found. "
                f"Falling back to '{candidate}'."
            )
            return candidate

    raise KeyError(
        f"Revenue column '{configured_revenue_col}' not found and no fallback is available. "
        f"Available columns: {list(df.columns)}"
    )

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
    revenue_col = resolve_revenue_column(df, revenue_col)
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

    return df, revenue_col

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

def project_loss(
    slope,
    intercept,
    pre_length,
    post_df,
    projection_months,
    review_date,
    revenue_col,
    max_monthly_growth,
    monthly_growth_damping,
):
    rows = []
    total_projected = 0.0
    total_actual = 0.0
    total_loss = 0.0

    post_revenue = post_df.set_index("month")[revenue_col].to_dict() if not post_df.empty else {}

    print(f"\n=== LOSS PROJECTION ({projection_months} months) ===")
    print(f"  {'Month':<12} {'Projected':>12} {'Actual':>12} {'Loss':>12}")
    print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*12}")

    review_period = pd.Period(review_date, freq="M")
    baseline_anchor = max(0.0, slope * max(pre_length - 1, 0) + intercept)
    if baseline_anchor <= 0:
        raw_growth_rate = 0.0
    else:
        raw_growth_rate = slope / baseline_anchor

    projected_prev = baseline_anchor

    for i in range(projection_months):
        month = review_period + i
        damped_growth = raw_growth_rate * (monthly_growth_damping ** i)
        if damped_growth > 0:
            damped_growth = min(damped_growth, max_monthly_growth)
        projected = max(0.0, projected_prev * (1 + damped_growth))
        projected_prev = projected
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
    df, revenue_col = load_gold(gold_file, review_date, date_col, revenue_col)
    print(f"Loaded {len(df)} clean rows.")

    monthly = monthly_revenue(df, date_col, revenue_col)
    _, slope, intercept, pre_length = fit_baseline(monthly, review_date, revenue_col)
    controls = resolve_projection_controls(config, pre_length)
    projection_months = controls["projection_months"]
    post = actual_post_review(monthly, review_date, revenue_col)
    projection_df, total_loss = project_loss(
        slope,
        intercept,
        pre_length,
        post,
        projection_months,
        review_date,
        revenue_col,
        controls["max_monthly_growth"],
        controls["monthly_growth_damping"],
    )

    written_projection_path = safe_write_projection(projection_df, projection_output)
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
