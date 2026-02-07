# Bank Beacon Reconciliation System v2

A Python-based reconciliation system for matching bank transactions with accounting entries from the Beacon system.

**v2** is a bank-centric redesign: you step through bank entries and see ranked beacon candidates, rather than stepping through pre-computed match suggestions.

## Quick Start

1. Ensure Python 3.7+ is installed (no external dependencies)
2. Place your CSV files in a data folder (e.g. `data/mydata/`)
3. Create a `config.json` in that folder (see below)
4. Launch from the data folder:

```bash
# Windows - double-click run.bat in the data folder, or:
python reconciliation_gui.py data/mydata/

# Or run directly from the code directory:
python reconciliation_gui.py
```

## Features

### Bank-Centric Navigation
- **Left panel**: Bank entry details, stepping through in date order
- **Right panel**: Beacon candidates for the current bank entry, ranked by confidence
- Default shows un-reconciled bank entries only (toggle "Show all" for everything)
- Each panel navigates independently with Prev/Next buttons

### Matching
- **1-to-1**: Single bank entry to single beacon entry (exact amount match)
- **1-to-2**: Single bank entry to a pair of beacon entries (amounts sum correctly, auto-detected for common amounts)
- **Manual match**: Enter trans_no(s) to match any combination
- **Auto-reconcile**: Automatically reconcile all high-confidence matches

### Confidence Scoring
- **Amount score**: Common amounts (configurable, e.g. £13, £9.50, £6.50) are weaker signals
- **Date score**: Proximity within configurable tolerance (default 7 days)
- **Name score**: Surname similarity matching between bank description and beacon payee
- **Member match**: member_1/member_2 fields checked against member numbers in bank description (best indicator, 0.95 confidence)

### Actions
- **Reconcile**: Confirm the current bank/beacon pairing
- **Un-reconcile**: Undo a reconciliation (frees both bank and beacon entries)
- **Reject pairing**: Mark a specific candidate as rejected (moves to bottom of list, greyed out but still visible)
- **Un-reject pairing**: Undo a rejection
- **Mark as resolved**: For bank entries with no beacon match, record a comment explaining the resolution
- **Auto-reconcile**: Batch-reconcile all entries above the confidence threshold

### Search
- **Bank search** (left panel): Search by description, amount, date, or bank ID
- **Beacon search** (right panel): Search by payee, trans_no, amount, date, or detail. "All beacons" checkbox bypasses the normal filter to find reconciled entries too

### Reports
Click "Reports" to generate five files in the data folder:
1. `report_reconciled.csv` - All reconciled bank/beacon pairings
2. `report_unreconciled_bank.csv` - Bank entries not yet reconciled
3. `report_unreconciled_beacon.csv` - Beacon entries not yet reconciled
4. `report_resolved.csv` - Manually resolved entries with comments
5. `report_stats.txt` - Summary statistics with date and version

### Stats Bar
Displayed at the top of the GUI:
- Reconciled: count and total amount
- Un-reconciled: count and total amount
- Resolved: count and total amount
- Version number

## Folder Structure

```
Bank-Beacon-Reconcile-v2/
├── reconciliation_system.py    # Core matching engine
├── reconciliation_gui.py       # Tkinter GUI
├── test_reconciliation.py      # Test suite (17 tests)
├── migrate_v1_to_v2.py         # One-off v1 -> v2 state migration
├── member_lookup.csv            # Shared member lookup (all datasets)
├── README.md
└── data/
    └── sample/                  # One data folder per dataset
        ├── config.json          # Per-dataset configuration
        ├── Bank_Transactions.csv
        ├── Beacon_Entries.csv
        ├── run.bat              # Windows launcher
        └── run.py               # Python launcher
```

Each dataset lives in its own subfolder under `data/`. The code and `member_lookup.csv` are shared at the top level.

## Configuration

Each data folder has a `config.json`:

```json
{
    "bank_file": "Bank_Transactions.csv",
    "beacon_file": "Beacon_Entries.csv",
    "common_amounts": ["13.00", "9.50", "6.50"],
    "date_tolerance_days": 7,
    "trans_no_limit": 5,
    "auto_reconcile_common_threshold": 0.90,
    "auto_reconcile_other_threshold": 0.80
}
```

- **bank_file / beacon_file**: CSV file names (can vary per dataset)
- **common_amounts**: Amounts treated as weak matching signals
- **date_tolerance_days**: Maximum days between bank and beacon dates
- **trans_no_limit**: Maximum gap between trans_no values for 1-to-2 detection
- **auto_reconcile thresholds**: Minimum confidence for auto-reconcile (separate for common and other amounts)

## File Format Requirements

### Bank_Transactions.csv
```
Date,Type,Description,Amount
15-Jan-25,DEB,SMITH J PAYMENT,26.00
```
- **Date**: Various formats supported (DD-MMM-YY, DD/MM/YYYY, etc.)
- **Type**: Transaction type
- **Description**: Usually contains name in SURNAME INITIAL format
- **Amount**: Decimal amount

### Beacon_Entries.csv
```
tkey,trans_no,date,account,amount,payee,detail,payment_method,cheque,notes,cleared,member_1,group,c_name
1,TRN001,15/01/2025,Sales,13.00,J Smith,First payment,Card,,,,SmithJ,,
```
- **date**: DD/MM/YYYY format
- **trans_no**: Transaction number (used for manual matching)
- **payee**: Payee name
- **amount**: Decimal amount
- **member_1**: Forename+Surname with no space (e.g. "SmithJ") - key matching field
- **member_2**: Second member field, same format

### member_lookup.csv
```
mem_no,status,forename,surname,known_as
123,Current,John,Smith,Johnny
```
Shared across all datasets. Maps member numbers to names for matching against bank descriptions.

## Matching Algorithm

### Scoring Components

1. **Amount Score** (0.0-1.0):
   - Common amounts: 0.3 (weak signal)
   - Other amounts: 1.0 (strong signal)

2. **Date Score** (0.0-1.0):
   - Same day: 1.0, 1 day: 0.95, 2 days: 0.90, 3 days: 0.80
   - 4-7 days: 0.60, 8-14 days: 0.40, 15-28 days: 0.25
   - Beacon before bank: 1 day = 0.50, 2 days = 0.25, 3+ days = excluded

3. **Name Score** (0.0-1.0):
   - Based on surname similarity matching
   - Member number match via member_1/member_2: 0.95 (overrides other scoring)

### Confidence Weights

For common amounts: Amount 10%, Date 45%, Name 45%

For other amounts: Amount 30%, Date 35%, Name 35%

1-to-2 matches receive a 10% confidence penalty.

### Candidate Ordering

Candidates are sorted: non-rejected first (highest confidence first), then rejected (highest confidence first).

## State

State is saved automatically to `reconciliation_state_v2.json` in the data folder. It stores:
- **reconciliations**: List of bank-to-beacon pairings (reconciled and resolved)
- **rejected_pairings**: Per-bank rejected beacon IDs (persists across sessions)

### Migrating from v1

If you have a v1 `reconciliation_state.json`, convert it:

```bash
python migrate_v1_to_v2.py path/to/reconciliation_state.json
```

This converts confirmed matches to reconciliations and carries over manually resolved entries. Rejected matches are ignored (not relevant in v2).

## Testing

```bash
python test_reconciliation.py
```

17 tests covering: loading, candidate generation, 1-to-1 matching, 1-to-2 matching, common amounts, reconcile/unreconcile, reject/unreject pairings, auto-reconcile, manual match, mark resolved, statistics, state persistence, search, exports, navigation helpers, candidate ordering.

## Classes

### reconciliation_system.py
- `BankTransaction`: Bank transaction data
- `BeaconEntry`: Beacon entry data (includes member_1, member_2)
- `BeaconCandidate`: A ranked candidate (single entry or pair) for a bank entry
- `Reconciliation`: A confirmed pairing between bank and beacon entries
- `ReconciliationSystem`: Main engine - candidate generation, reconciliation, search, exports

### reconciliation_gui.py
- `ReconciliationGUI`: Split-panel Tkinter GUI

## Troubleshooting

### CSV Encoding Issues
Files are read as UTF-8 with BOM handling. Save CSVs as UTF-8 if you encounter encoding errors.

### No Candidates Found
- Check amounts have potential exact matches in the beacon data
- Verify dates are within the configured tolerance
- Try increasing `date_tolerance_days` in config.json
- Use the beacon search with "All beacons" to find entries manually

### Date Parsing Errors
Bank dates support multiple formats (DD-MMM-YY, DD/MM/YYYY, etc.). Beacon dates must be DD/MM/YYYY.

## License

This project is provided for internal use.
