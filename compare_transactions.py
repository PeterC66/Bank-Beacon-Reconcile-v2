"""
Compare transactions between to_reconcile.csv and report_reconciled.csv.

Run from the directory containing the two CSV files:
    python ..\..\compare_transactions.py

Reads:
    to_reconcile.csv       - tab-separated, with columns including Transaction, In, Out
    report_reconciled.csv  - comma-separated, with columns including beacon_trans_no, beacon_amount

Writes:
    reconciliation_comparison.txt - results file in the current directory
"""

import csv
import os
import sys
from decimal import Decimal, InvalidOperation


def parse_currency(value):
    """Parse a currency string like '£1,234.56' into a Decimal. Returns Decimal('0') for blank."""
    if value is None:
        return Decimal("0")
    value = value.strip()
    if value == "":
        return Decimal("0")
    value = value.replace("£", "").replace(",", "").strip()
    return Decimal(value)


def read_to_reconcile(filepath):
    """Read the tab-separated to_reconcile.csv file.
    Returns a dict of {transaction_number: (amount, date)} where amount = In - Out.
    """
    transactions = {}
    duplicates = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row_num, row in enumerate(reader, start=2):
            trans_no = row["Transaction"].strip()
            if trans_no == "":
                continue
            in_val = parse_currency(row.get("In", ""))
            out_val = parse_currency(row.get("Out", ""))
            amount = in_val - out_val
            date = row.get("Date", "").strip()
            if trans_no in transactions:
                duplicates.append(trans_no)
            transactions[trans_no] = (amount, date)
    return transactions, duplicates


def read_report_reconciled(filepath):
    """Read the comma-separated report_reconciled.csv file.
    Returns a dict of {beacon_trans_no: (beacon_amount, bank_date, beacon_date)}.
    """
    transactions = {}
    duplicates = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=",")
        for row_num, row in enumerate(reader, start=2):
            trans_no = row["beacon_trans_no"].strip()
            if trans_no == "":
                continue
            amount = Decimal(row["beacon_amount"].strip())
            bank_date = row.get("bank_date", "").strip()
            beacon_date = row.get("beacon_date", "").strip()
            if trans_no in transactions:
                duplicates.append(trans_no)
            transactions[trans_no] = (amount, bank_date, beacon_date)
    return transactions, duplicates


def compare(to_reconcile, report_reconciled):
    """Compare the two sets of transactions.
    Returns:
        only_in_first  - set of transaction numbers only in to_reconcile
        only_in_second - set of transaction numbers only in report_reconciled
        mismatches     - list of (trans_no, amount_first, amount_second)
    """
    keys_first = set(to_reconcile.keys())
    keys_second = set(report_reconciled.keys())

    only_in_first = sorted(keys_first - keys_second)
    only_in_second = sorted(keys_second - keys_first)

    mismatches = []
    for trans_no in sorted(keys_first & keys_second):
        amt_first = to_reconcile[trans_no][0]
        amt_second = report_reconciled[trans_no][0]
        if amt_first != amt_second:
            mismatches.append((trans_no, amt_first, amt_second))

    return only_in_first, only_in_second, mismatches


def main():
    file_first = "to_reconcile.csv"
    file_second = "report_reconciled.csv"
    output_file = "reconciliation_comparison.txt"

    for f in [file_first, file_second]:
        if not os.path.exists(f):
            raise FileNotFoundError(
                f"'{f}' not found in the current directory: {os.getcwd()}"
            )

    to_reconcile, dups_first = read_to_reconcile(file_first)
    report_reconciled, dups_second = read_report_reconciled(file_second)

    only_in_first, only_in_second, mismatches = compare(to_reconcile, report_reconciled)

    total_first = sum(v[0] for v in to_reconcile.values())
    total_second = sum(v[0] for v in report_reconciled.values())
    matched_count = len(set(to_reconcile.keys()) & set(report_reconciled.keys())) - len(mismatches)

    lines = []
    lines.append("=" * 70)
    lines.append("RECONCILIATION COMPARISON REPORT")
    lines.append("=" * 70)
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append("-" * 70)
    lines.append(f"Transactions in to_reconcile.csv:       {len(to_reconcile)}")
    lines.append(f"Transactions in report_reconciled.csv:   {len(report_reconciled)}")
    lines.append(f"Matched (same transaction number):       {len(set(to_reconcile.keys()) & set(report_reconciled.keys()))}")
    lines.append(f"  - with matching amounts:               {matched_count}")
    lines.append(f"  - with different amounts:               {len(mismatches)}")
    lines.append(f"Only in to_reconcile.csv:                {len(only_in_first)}")
    lines.append(f"Only in report_reconciled.csv:           {len(only_in_second)}")
    lines.append("")

    # Duplicates
    if dups_first or dups_second:
        lines.append("DUPLICATE TRANSACTION NUMBERS (last occurrence used)")
        lines.append("-" * 70)
        if dups_first:
            lines.append(f"  In to_reconcile.csv:       {', '.join(dups_first)}")
        if dups_second:
            lines.append(f"  In report_reconciled.csv:  {', '.join(dups_second)}")
        lines.append("")

    # Totals
    lines.append("TOTALS COMPARISON")
    lines.append("-" * 70)
    lines.append(f"Total (to_reconcile.csv):        {total_first:>12}")
    lines.append(f"Total (report_reconciled.csv):   {total_second:>12}")
    lines.append(f"Difference:                      {total_first - total_second:>12}")
    lines.append("")

    # Only in first
    lines.append("TRANSACTIONS ONLY IN to_reconcile.csv")
    lines.append("-" * 70)
    if only_in_first:
        for trans_no in only_in_first:
            amount, date = to_reconcile[trans_no]
            lines.append(f"  {trans_no:>10}    date: {date:<12}  amount: {amount:>12}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Only in second
    lines.append("TRANSACTIONS ONLY IN report_reconciled.csv")
    lines.append("-" * 70)
    if only_in_second:
        for trans_no in only_in_second:
            amount, bank_date, beacon_date = report_reconciled[trans_no]
            lines.append(f"  {trans_no:>10}    bank_date: {bank_date:<12}  beacon_date: {beacon_date:<12}  amount: {amount:>12}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Mismatches
    lines.append("AMOUNT MISMATCHES (matched transaction numbers with different amounts)")
    lines.append("-" * 70)
    if mismatches:
        lines.append(f"  {'Trans No':>10}  {'to_reconcile':>14}  {'report_reconciled':>18}  {'Difference':>12}")
        for trans_no, amt_first, amt_second in mismatches:
            diff = amt_first - amt_second
            lines.append(f"  {trans_no:>10}  {amt_first:>14}  {amt_second:>18}  {diff:>12}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("=" * 70)

    report = "\n".join(lines)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\nReport written to: {os.path.abspath(output_file)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
    input("\nPress Enter to close...")
