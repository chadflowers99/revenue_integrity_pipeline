"""Reconcile Market Holdings trade-history exports with Robinhood activity CSVs."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MARKET_HOLDINGS_CSV = BASE_DIR / "clients" / "trade_history.csv"
DEFAULT_ROBINHOOD_CSV = BASE_DIR / "clients" / "june.csv"
DEFAULT_OUTPUT_DIR = BASE_DIR / "clients" / "reconciliation"
QUANTITY_TOLERANCE = Decimal("0.000001")
CENT = Decimal("0.01")
HALF_CENT = Decimal("0.005")

SOURCE_COLUMNS = {
    "market_holdings": {
        "trade_date": ("TRADE DATE",),
        "action": ("ACTION",),
        "symbol": ("SYMBOL",),
        "quantity": ("QTY", "QUANTITY"),
        "price": ("PRICE",),
    },
    "robinhood": {
        "trade_date": ("Activity Date",),
        "action": ("Trans Code",),
        "symbol": ("Instrument",),
        "quantity": ("Quantity",),
        "price": ("Price",),
        "amount": ("Amount",),
    },
}

RECONCILIATION_FIELDS = [
    "trade_date",
    "symbol",
    "action",
    "market_holdings_rows",
    "robinhood_rows",
    "market_holdings_quantity",
    "robinhood_quantity",
    "quantity_difference",
    "market_holdings_notional",
    "robinhood_notional",
    "notional_difference",
    "market_holdings_expected_amount",
    "robinhood_amount",
    "amount_difference",
    "possible_duplicate",
    "possible_duplicate_sources",
    "status",
]


def _parse_trade_date(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("missing trade date")

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(iso_text).date().isoformat()
    except ValueError:
        pass

    for date_format in ("%m/%d/%Y", "%m/%d/%y", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError("invalid trade date")


def _parse_decimal(value, field_name):
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text:
        raise ValueError("missing " + field_name)
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("invalid " + field_name) from error
    if not number.is_finite():
        raise ValueError("invalid " + field_name)
    return number


def _canonical_trade(row):
    trade_date = _parse_trade_date(row.get("trade_date"))
    symbol = str(row.get("symbol") or "").strip().upper()
    action = str(row.get("action") or "").strip().upper()
    if not symbol:
        raise ValueError("missing symbol")
    if action not in ("BUY", "SELL"):
        raise ValueError("unsupported trade action")

    quantity = abs(_parse_decimal(row.get("quantity"), "quantity"))
    price = _parse_decimal(row.get("price"), "price")
    if quantity == 0:
        raise ValueError("quantity must be nonzero")
    if price < 0:
        raise ValueError("price cannot be negative")
    signed_amount = row.get("amount")
    if signed_amount is None or not str(signed_amount).strip():
        cashflow = quantity * price * (Decimal("1") if action == "SELL" else Decimal("-1"))
    else:
        cashflow = _parse_decimal(signed_amount, "amount")

    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
        "cashflow": cashflow,
    }


def _format_decimal(value):
    formatted = format(value.normalize(), "f")
    return "0" if formatted in ("-0", "") else formatted


def _trade_key(trade):
    return trade["trade_date"], trade["symbol"], trade["action"]


def _aggregate(rows):
    quantity = sum((row["quantity"] for row in rows), Decimal("0"))
    notional = sum(
        (row["quantity"] * row["price"] for row in rows), Decimal("0")
    )
    cashflow = sum((row["cashflow"] for row in rows), Decimal("0"))
    return quantity, notional, cashflow


def reconcile_rows(market_rows, broker_rows):
    """Compare canonical trade rows, aggregating fills by date, symbol, and side."""
    grouped = {
        "market_holdings": defaultdict(list),
        "robinhood": defaultdict(list),
    }
    duplicate_sources = defaultdict(set)

    for source, source_rows in (
        ("market_holdings", market_rows),
        ("robinhood", broker_rows),
    ):
        signatures = Counter()
        for source_row in source_rows:
            row = _canonical_trade(source_row)
            key = _trade_key(row)
            grouped[source][key].append(row)
            signature = key + (row["quantity"], row["price"])
            signatures[signature] += 1
        for signature, count in signatures.items():
            if count > 1:
                duplicate_sources[signature[:3]].add(source)

    results = []
    all_keys = set(grouped["market_holdings"]) | set(grouped["robinhood"])
    for trade_date, symbol, action in sorted(all_keys):
        key = (trade_date, symbol, action)
        market_trades = grouped["market_holdings"].get(key, [])
        broker_trades = grouped["robinhood"].get(key, [])
        market_quantity, market_notional, market_cashflow = _aggregate(market_trades)
        broker_quantity, broker_notional, broker_cashflow = _aggregate(broker_trades)
        quantity_difference = market_quantity - broker_quantity
        notional_difference = market_notional - broker_notional
        amount_difference = market_cashflow - broker_cashflow

        if not market_trades:
            status = "missing_market_holdings"
        elif not broker_trades:
            status = "missing_robinhood"
        elif abs(quantity_difference) > QUANTITY_TOLERANCE:
            status = "quantity_mismatch"
        else:
            # Market Holdings exports prices rounded to cents; allow for that precision.
            amount_tolerance = CENT + HALF_CENT * max(
                market_quantity, broker_quantity
            )
            status = (
                "amount_mismatch"
                if abs(amount_difference) > amount_tolerance
                else "matched"
            )

        possible_duplicate_sources = sorted(duplicate_sources.get(key, set()))
        results.append(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "action": action,
                "market_holdings_rows": str(len(market_trades)),
                "robinhood_rows": str(len(broker_trades)),
                "market_holdings_quantity": _format_decimal(market_quantity),
                "robinhood_quantity": _format_decimal(broker_quantity),
                "quantity_difference": _format_decimal(quantity_difference),
                "market_holdings_notional": _format_decimal(market_notional),
                "robinhood_notional": _format_decimal(broker_notional),
                "notional_difference": _format_decimal(notional_difference),
                "market_holdings_expected_amount": _format_decimal(market_cashflow),
                "robinhood_amount": _format_decimal(broker_cashflow),
                "amount_difference": _format_decimal(amount_difference),
                "possible_duplicate": str(bool(possible_duplicate_sources)).lower(),
                "possible_duplicate_sources": ";".join(possible_duplicate_sources),
                "status": status,
            }
        )
    return results


def _resolve_columns(fieldnames, source):
    available = {
        str(name).strip().casefold(): name for name in (fieldnames or []) if name
    }
    resolved = {}
    for canonical_name, aliases in SOURCE_COLUMNS[source].items():
        actual_name = next(
            (available.get(alias.casefold()) for alias in aliases if alias.casefold() in available),
            None,
        )
        if actual_name is None:
            raise ValueError(
                "CSV is missing a required " + source + " column for " + canonical_name
            )
        resolved[canonical_name] = actual_name
    return resolved


def _load_csv(path, source):
    trades = []
    invalid_rows = []
    excluded_rows = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = _resolve_columns(reader.fieldnames, source)
        for row_number, raw_row in enumerate(reader, start=2):
            action_value = str(raw_row.get(columns["action"]) or "").strip().upper()
            if source == "robinhood" and action_value not in ("BUY", "SELL"):
                excluded_rows.append(
                    {
                        "source": source,
                        "row_number": row_number,
                        "reason": "non_trade_activity",
                        "raw_data": json.dumps(raw_row, sort_keys=True),
                    }
                )
                continue

            canonical_row = {
                name: raw_row.get(column) for name, column in columns.items()
            }
            try:
                trades.append(_canonical_trade(canonical_row))
            except ValueError as error:
                invalid_rows.append(
                    {
                        "source": source,
                        "row_number": row_number,
                        "reason": str(error),
                        "raw_data": json.dumps(raw_row, sort_keys=True),
                    }
                )
    return trades, invalid_rows, excluded_rows


def _write_csv(path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def reconcile_csvs(market_path, robinhood_path, output_dir):
    market_trades, market_invalid, market_excluded = _load_csv(
        market_path, "market_holdings"
    )
    robinhood_trades, robinhood_invalid, robinhood_excluded = _load_csv(
        robinhood_path, "robinhood"
    )
    results = reconcile_rows(market_trades, robinhood_trades)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "trade_reconciliation.csv", results, RECONCILIATION_FIELDS
    )

    invalid_rows = market_invalid + robinhood_invalid
    invalid_fields = ["source", "row_number", "reason", "raw_data"]
    _write_csv(output_dir / "invalid_rows.csv", invalid_rows, invalid_fields)

    excluded_rows = market_excluded + robinhood_excluded
    excluded_fields = ["source", "row_number", "reason", "raw_data"]
    _write_csv(
        output_dir / "excluded_activity.csv", excluded_rows, excluded_fields
    )

    status_counts = Counter(row["status"] for row in results)
    summary = {
        "market_holdings": {
            "trade_rows": len(market_trades),
            "invalid_rows": len(market_invalid),
            "excluded_activity_rows": len(market_excluded),
        },
        "robinhood": {
            "trade_rows": len(robinhood_trades),
            "invalid_rows": len(robinhood_invalid),
            "excluded_activity_rows": len(robinhood_excluded),
        },
        "comparison_groups": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "possible_duplicate_groups": sum(
            row["possible_duplicate"] == "true" for row in results
        ),
    }
    with (output_dir / "reconciliation_summary.json").open(
        "w", encoding="utf-8"
    ) as summary_file:
        json.dump(summary, summary_file, indent=2)
        summary_file.write("\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Compare Market Holdings trade-history CSVs with Robinhood activity CSVs. "
            "Non-trade Robinhood activity is written separately."
        )
    )
    parser.add_argument(
        "--market-holdings-csv",
        type=Path,
        default=DEFAULT_MARKET_HOLDINGS_CSV,
        help="Market Holdings export (default: clients/trade_history.csv).",
    )
    parser.add_argument(
        "--robinhood-csv",
        type=Path,
        default=DEFAULT_ROBINHOOD_CSV,
        help="Robinhood activity export (default: clients/june.csv).",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    summary = reconcile_csvs(
        args.market_holdings_csv, args.robinhood_csv, args.output_dir
    )
    print(json.dumps(summary, indent=2))
    print("Reports written to: " + str(args.output_dir.resolve()))


if __name__ == "__main__":
    main()