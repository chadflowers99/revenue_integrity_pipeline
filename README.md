# Forensic Revenue Pipeline

Modular, production-grade data pipeline with forensic data validation, S5 quarantine routing, and revenue-loss projection.

This project is organized for reusable client onboarding.

## Architecture Diagram

```mermaid
flowchart TD
  A[RAW CSV] --> B[Bronze]
  B --> C[Silver Normalization]
  C --> D[Validation and S5 Split]
  D --> E[Gold Layer]
  E --> F[Projection Engine]
```

## Structure

- `templates/pipeline_config.py`: Copy and customize for each client.
- `templates/loss_projection_engine.py`: Shared projection script driven by client config.
- `clients/client_name_001/raw_data.csv`: Client source data.
- `clients/client_name_001/client_config.py`: Client-specific schema and projection settings.
- `clients/client_name_001/output/`: Logs and generated outputs.
- `cleanup_engine.py`: Core cleanup engine.
- `run_pipeline.py`: Orchestrates cleanup + projection for one client.

## New Client Setup

1. Create a folder under `clients/` (example: `clients/acme_2026_05`).
2. Copy `templates/pipeline_config.py` to `clients/acme_2026_05/client_config.py`.
3. Put source data at `clients/acme_2026_05/raw_data.csv`.
4. Run with a specific client folder name (or omit to use the default pointer):

```powershell
python .\run_pipeline.py acme_2026_05
```

## Projection Controls

The projection engine now supports maturity controls to keep long-range projections financially plausible and operationally defensible.

- `projection_mode`: `conservative`, `moderate`, or `aggressive`
- `max_monthly_growth`: optional hard cap override for monthly growth
- `monthly_growth_damping`: optional monthly damping factor
- `min_confident_baseline_months`: minimum baseline months before confidence downgrade
- `low_confidence_max_horizon_months`: automatic horizon clamp when baseline history is limited

Default behavior:

- If baseline history is thin (for example, fewer than 6 months), the engine downgrades mode, reduces growth assumptions, shortens horizon, and prints warnings.
- If configured revenue column is missing, the engine derives revenue from `quantity * unit_price` when available.

## Notes

- `run_pipeline.py` writes a timestamped log to the selected client output folder.
- Projection uses settings from `client_config.py`:
  - `review_date`
  - `projection_months`
  - `projection_revenue_col`
  - `projection_date_col`
  - `projection_mode`
  - `min_confident_baseline_months`
  - `low_confidence_max_horizon_months`
- Output files use safe-write behavior: if a target CSV is locked/open, the pipeline writes a timestamped fallback file instead of hard-failing.
