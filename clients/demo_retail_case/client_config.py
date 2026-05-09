from pathlib import Path

CLIENT_BASE_DIR = Path(__file__).resolve().parent

config = {
    "base_dir": str(CLIENT_BASE_DIR),
    "input_path": str(CLIENT_BASE_DIR / "raw_data.csv"),
    "output_path": str(CLIENT_BASE_DIR / "output" / "client_cleaned_data.csv"),
    "delimiter": ",",
    "mode": "structural",
    "text_columns": [
        "order_id",
        "item_name",
        "payment_method",
        "customer_zip"
    ],
    "title_columns": [
        "item_name",
        "category",
        "payment_method"
    ],
    "numeric_columns": [
        "quantity"
    ],
    "date_columns": [
        "sale_date"
    ],
    "required_columns": [
        "order_id",
        "sale_date",
        "quantity",
        "unit_price",
        "category",
        "payment_method"
    ],
    "recompute": {
        "total_sale": "quantity * unit_price"
    },
    "allow_unsafe_recompute": False,
    "validation_rules": [],
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
    "zip_columns": [
        "customer_zip"
    ],
    "currency_columns": [
        "unit_price"
    ],
    "s5_threshold": 0.05,
    "row_flag_column": "_row_flag",
    "gold_output_filename": "client_sales_GOLD.csv",
    "s5_output_filename": "client_S5_FORENSIC_BUFFER.csv",
    "projection_output_filename": "loss_projection_report.csv",
    "review_date": "2026-01-15",
    "projection_months": 24,
    "projection_revenue_col": "total_sale",
    "projection_date_col": "sale_date",
    "quality_columns": [
        "sale_date",
        "quantity",
        "unit_price",
        "category",
        "payment_method",
        "customer_zip"
    ]
}
