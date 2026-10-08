# Revenue Integrity Pipeline

This repository currently provides a local trade reconciliation utility for comparing a Market Holdings trade-history export with a Robinhood activity export.

## Reconcile Trade Exports

From the repository root, run:

```powershell
python .\reconcile_trades.py
```

By default, the command reads `clients/trade_history.csv` and `clients/june.csv`. To compare different files, pass `--market-holdings-csv` and `--robinhood-csv`. Use `--output-dir` to select another report folder.

The input files need these columns:

- Market Holdings: `TRADE DATE`, `ACTION`, `SYMBOL`, `QTY` (or `QUANTITY`), `PRICE`
- Robinhood: `Activity Date`, `Instrument`, `Trans Code`, `Quantity`, `Price`, `Amount`

The reconciler normalizes the trade fields and groups records by trade date, symbol, and buy/sell action, allowing multiple broker fills to match one Market Holdings trade. It compares grouped quantities and expected signed cash flow against Robinhood's `Amount`. Non-trade Robinhood activity and invalid rows are written to separate reports. Exact repeated rows are marked as possible duplicates; they are not automatically removed.

Reports are written to `clients/reconciliation/` by default:

- `trade_reconciliation.csv`: one row per date/symbol/action group and its match status
- `invalid_rows.csv`: rows that could not be normalized for comparison
- `excluded_activity.csv`: non-trade Robinhood activity
- `reconciliation_summary.json`: counts by source and match status

Matching is group-level, so distinct orders for the same symbol, date, and side may be combined. Fees and settlement cash are not separately reconciled.

Run the tests with:

```powershell
python -m unittest discover -s .\tests -v
```

Each run overwrites the reports in `clients/reconciliation/` and leaves the input CSVs unchanged.

