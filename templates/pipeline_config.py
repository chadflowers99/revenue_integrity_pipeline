# pipeline_config.py

from pathlib import Path

CLIENT_BASE_DIR = Path(__file__).resolve().parent

config = {

    # Base directory for resolving relative paths
    "base_dir": str(CLIENT_BASE_DIR),

    # Input + Output
    "input_path": str(CLIENT_BASE_DIR / "raw_data.csv"),
    "output_path": str(CLIENT_BASE_DIR / "output" / "client_cleaned_data.csv"),

    # CSV format
    "delimiter": ",",

    # Use structural mode for messy datasets
    "mode": "structural",

    # Text columns (encoding + whitespace cleanup only)
    "text_columns": [
        "order_id",
        "item_name",
        "payment_method",
        "customer_zip"
    ],

    # Columns to apply title-case normalization
    "title_columns": [
        "item_name",
        "category",
        "payment_method"
    ],

    # Numeric columns (plain numbers only — no currency symbols)
    "numeric_columns": [
        "quantity"
    ],

    # Date columns
    "date_columns": [
        "sale_date"
    ],

    # Required columns — rows missing any of these are flagged as malformed
    "required_columns": [
        "order_id",
        "sale_date",
        "quantity",
        "unit_price",
        "category",
        "payment_method"
    ],

    # Optional recompute expressions
    # By default only basic arithmetic over known columns is allowed.
    # Set allow_unsafe_recompute=True only in trusted environments.
    "recompute": {
        # Example:
        # "total_spent": "quantity * price_per_unit"
    },
    "allow_unsafe_recompute": False,

    # Validation rules
    "validation_rules": [],

    # Value normalization maps (applied after text cleaning)
    "value_maps": {
        "item_name": {
            "Usb Cable": "USB Cable"
        },
        "category": {
            "Acc": "Accessories",
            "ACC": "Accessories",
            "Accessory": "Accessories",
            "Accessories": "Accessories",
            "Electronics": "Electronics"
        },
        "payment_method": {
            "Card": "Card",
            "Cash": "Cash",
            "Mobile": "Mobile",
            "Mobile Pay": "Mobile"
        }
    },

    # Conditional derivations from one column into another (e.g. backfill category)
    "conditional_maps": [
        {
            "target_column": "category",
            "source_column": "item_name",
            "lookup": {
                "Keyboard": "Accessories",
                "Laptop Stand": "Accessories",
                "Usb Cable": "Electronics",
                "Wireless Mouse": "Electronics"
            },
            "only_if_target_missing": True
        }
    ],

    # ZIP code columns to validate (must be 5 digits, else replaced with 'Unknown')
    "zip_columns": [
        "customer_zip"
    ],

    # Currency columns to apply forensic cleaning (diagnostic_currency_handler)
    "currency_columns": [
        "unit_price"
    ],

    # S5 threshold: flag as CRITICAL if this fraction of rows can't be coerced
    "s5_threshold": 0.05,

    # Row-level forensic status column for S5 routing.
    "row_flag_column": "_row_flag",

    # Export filenames for bifurcated outputs
    "gold_output_filename": "client_sales_GOLD.csv",
    "s5_output_filename": "client_S5_FORENSIC_BUFFER.csv",
    "projection_output_filename": "loss_projection_report.csv",

    # Projection settings
    "review_date": "2026-03-01",
    "projection_months": 60,
    "projection_revenue_col": "total_sale",
    "projection_date_col": "sale_date",
    "projection_mode": "moderate",
    "min_confident_baseline_months": 6,
    "low_confidence_max_horizon_months": 24,
    # Optional overrides (uncomment to force custom behavior):
    # "max_monthly_growth": 0.10,
    # "monthly_growth_damping": 0.98,

    # Columns to include in the data quality report (null counts per column)
    "quality_columns": [
        "sale_date",
        "quantity",
        "unit_price",
        "category",
        "payment_method",
        "customer_zip"
    ]
}
