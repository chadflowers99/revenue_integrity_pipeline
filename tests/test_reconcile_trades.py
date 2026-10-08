import csv
import tempfile
import unittest
from pathlib import Path

from reconcile_trades import reconcile_csvs, reconcile_rows


def trade(trade_date, symbol, action, quantity, price, amount=None):
    row = {
        "trade_date": trade_date,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
    }
    if amount is not None:
        row["amount"] = amount
    return row


class ReconcileRowsTests(unittest.TestCase):
    def test_aggregates_broker_partial_fills(self):
        market_rows = [trade("2026-01-02", "MSFT", "BUY", "10", "100.00")]
        broker_rows = [
            trade("2026-01-02", "MSFT", "Buy", "6", "99.99", "-599.94"),
            trade("2026-01-02", "MSFT", "Buy", "4", "100.015", "-400.06"),
        ]

        result = reconcile_rows(market_rows, broker_rows)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "matched")
        self.assertEqual(result[0]["market_holdings_quantity"], "10")
        self.assertEqual(result[0]["robinhood_quantity"], "10")
        self.assertEqual(result[0]["amount_difference"], "0")
        self.assertEqual(result[0]["possible_duplicate"], "false")

    def test_reports_missing_trade_and_exact_duplicate(self):
        market_rows = [trade("2026-01-02", "MSFT", "BUY", "10", "100.00")]
        broker_rows = [
            trade("2026-01-02", "AAPL", "Sell", "2", "50.00"),
            trade("2026-01-02", "AAPL", "Sell", "2", "50.00"),
        ]

        result = reconcile_rows(market_rows, broker_rows)
        by_symbol = {row["symbol"]: row for row in result}

        self.assertEqual(by_symbol["MSFT"]["status"], "missing_robinhood")
        self.assertEqual(by_symbol["AAPL"]["status"], "missing_market_holdings")
        self.assertEqual(by_symbol["AAPL"]["possible_duplicate"], "true")

    def test_reports_quantity_and_notional_mismatches(self):
        market_rows = [
            trade("2026-01-02", "MSFT", "BUY", "10", "100.00"),
            trade("2026-01-03", "AAPL", "SELL", "2", "50.00"),
        ]
        broker_rows = [
            trade("2026-01-02", "MSFT", "Buy", "9", "100.00"),
            trade("2026-01-03", "AAPL", "Sell", "2", "51.00"),
        ]

        result = reconcile_rows(market_rows, broker_rows)
        by_symbol = {row["symbol"]: row for row in result}

        self.assertEqual(by_symbol["MSFT"]["status"], "quantity_mismatch")
        self.assertEqual(by_symbol["AAPL"]["status"], "amount_mismatch")

    def test_uses_signed_robinhood_amount_for_buy_and_sell(self):
        market_rows = [
            trade("2026-06-17", "SVIX", "BUY", "1", "22.80"),
            trade("2026-06-17", "SVIX", "SELL", "1", "22.82"),
        ]
        broker_rows = [
            trade("2026-06-17", "SVIX", "Buy", "1", "$22.80", "($22.80)"),
            trade("2026-06-17", "SVIX", "Sell", "1", "22.82", "22.82"),
        ]

        result = reconcile_rows(market_rows, broker_rows)

        self.assertEqual([row["status"] for row in result], ["matched", "matched"])
        self.assertEqual(
            [row["robinhood_amount"] for row in result], ["-22.8", "22.82"]
        )

    def test_reads_export_headers_and_separates_non_trade_activity(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            market_path = root / "market_holdings.csv"
            robinhood_path = root / "robinhood.csv"
            output_dir = root / "reports"

            with market_path.open("w", newline="", encoding="utf-8") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["TRADE DATE", "ACTION", "SYMBOL", "QTY", "PRICE"])
                writer.writerow(["2026-01-02", "BUY", "MSFT", "10", "100.00"])

            with robinhood_path.open("w", newline="", encoding="utf-8") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(
                    [
                        "Activity Date",
                        "Process Date",
                        "Settle Date",
                        "Instrument",
                        "Description",
                        "Trans Code",
                        "Quantity",
                        "Price",
                        "Amount",
                    ]
                )
                writer.writerow(
                    ["2026-01-02", "", "", "MSFT", "Buy", "Buy", "10", "100.00", "-1000"]
                )
                writer.writerow(
                    ["2026-01-02", "", "", "", "Deposit", "ACH", "", "", "500"]
                )

            summary = reconcile_csvs(market_path, robinhood_path, output_dir)

            self.assertEqual(summary["status_counts"], {"matched": 1})
            self.assertEqual(summary["robinhood"]["excluded_activity_rows"], 1)
            self.assertTrue((output_dir / "trade_reconciliation.csv").exists())
            with (output_dir / "excluded_activity.csv").open(
                newline="", encoding="utf-8"
            ) as csv_file:
                excluded_rows = list(csv.DictReader(csv_file))
            self.assertEqual(excluded_rows[0]["reason"], "non_trade_activity")


if __name__ == "__main__":
    unittest.main()