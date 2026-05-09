# Demo Retail Case

This folder contains a demo client setup for the forensic revenue pipeline.

The demo shows how the pipeline ingests messy retail sales data, normalizes it, flags incomplete records, routes review-required rows into an S5 forensic buffer, and exports a clean Gold Layer for reporting and projection analysis.

## Files

- `client_config.py`: Client-specific cleanup, validation, conditional mapping, and projection configuration.
- `raw_data.csv`: Sample retail sales data with clean rows and intentionally messy records.
- `output/`: Generated cleaned files, S5 buffer files, malformed-row reports, logs, and projection outputs.

## What This Demo Shows

- Config-driven CSV cleanup
- Header normalization
- Currency parsing without contaminating numeric columns
- Conditional category backfill from item names
- Dedicated `row_flag` review-state tracking
- Gold/S5 split for clean vs review-required records
- Audit-safe output generation

## Expected Outputs

- `client_cleaned_data.csv`
- `client_cleaned_data_malformed_rows.csv`
- `client_sales_GOLD.csv`
- `client_S5_FORENSIC_BUFFER.csv`
- `loss_projection_report.csv`
- `forensic_audit_YYYYMMDD_HHMMSS.log`

## Usage

From the project root:

```bash
python run_pipeline.py demo_retail_case
```
