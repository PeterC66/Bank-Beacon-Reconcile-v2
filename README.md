# Bank Beacon Reconciliation System

A Python-based reconciliation system for matching bank transactions with accounting entries from the Beacon system.

## Features

### Core Matching Logic
- **1-to-1 Matching**: Match single bank transactions to single Beacon entries
- **1-to-2 Matching**: Match single bank transactions to pairs of Beacon entries when amounts sum correctly
- **Exact Amount Matching**: Amounts must match exactly (including 1-to-2 sums)
- **Date Proximity**: Transactions must be within 7 days of each other
- **Name Similarity**: Matches surname + initial patterns between bank descriptions and Beacon payees

### Common Amount Handling
- £13.00 and £9.50 are identified as common amounts
- These amounts are treated as weak matching signals
- When common amounts are involved, date and name matching become more important

### Beacon Exclusivity
- Each Beacon entry can only match one Bank transaction
- Once a Beacon entry is confirmed in a match, it becomes unavailable for other matches

### GUI Features
- **Navigation**: Previous/Next buttons to move between suggested matches
- **Status Indicators**: Visual indicators showing Confirmed (green), Rejected (red), Skipped (blue), or Pending (yellow)
- **Editable History**: Navigate back to previous matches and change decisions
- **Queued Changes**: Changes are queued and applied when saving or refreshing
- **Display Layout**: Bank transaction on left, Beacon entries (1 or 2) on right
- **Confidence Scores**: Shows overall match confidence and breakdown by amount/date/name

## File Format Requirements

### Bank_Transactions.csv
```
Date,Type,Description,Amount
15-Jan-25,DEB,SMITH J PAYMENT,26.00
```
- **Date**: DD-MMM-YY format (e.g., 15-Jan-25)
- **Type**: Transaction type
- **Description**: Transaction description (usually contains name in SURNAME INITIAL format)
- **Amount**: Decimal amount

### Beacon_Entries.csv
```
date,trans_no,payee,amount,detail,category,ref
15/01/2025,TRN001,J Smith,13.00,First payment,Sales,REF001
```
- **date**: DD/MM/YYYY format
- **trans_no**: Transaction number
- **payee**: Payee name (usually in Initial Surname format)
- **amount**: Decimal amount
- **detail**: Transaction detail
- Additional columns are preserved but not used for matching

## Installation

1. Ensure Python 3.7+ is installed
2. No external dependencies required (uses standard library only)

## Usage

### Command Line (Testing/Debugging)
```bash
python reconciliation_system.py
```
This will load the CSV files, generate match suggestions, and print them to the console.

### Graphical Interface
```bash
python reconciliation_gui.py
```
This launches the full reconciliation interface.

### GUI Workflow

1. **Review Matches**: The system presents suggested matches one at a time
2. **Make Decisions**:
   - Click **Confirm** to accept a match
   - Click **Reject** to mark as incorrect
   - Click **Skip** to review later
3. **Navigate**: Use Previous/Next buttons to move between matches
4. **Edit Decisions**: Navigate back to change previous decisions
5. **Save Progress**: Click "Save Progress" to persist decisions
6. **Refresh**: Click "Refresh Suggestions" to regenerate matches after confirming some
7. **Export**: Click "Export Results" to create a CSV report

## Matching Algorithm

### Scoring Components

1. **Amount Score** (0.0-1.0):
   - Common amounts (£13.00, £9.50): 0.3 (weak signal)
   - Other amounts: 1.0 (strong signal)

2. **Date Score** (0.0-1.0):
   - Same day: 1.0
   - 7 days apart: ~0.14
   - Beyond 7 days: 0.0 (excluded)

3. **Name Score** (0.0-1.0):
   - Based on similarity matching between normalized names
   - Extracts surname + initial from both sources

### Confidence Calculation

For common amounts:
- Amount weight: 10%
- Date weight: 45%
- Name weight: 45%

For other amounts:
- Amount weight: 30%
- Date weight: 35%
- Name weight: 35%

1-to-2 matches receive a 10% penalty to prefer simpler matches when confidence is similar.

## Output Files

### reconciliation_state.json
Stores:
- List of matched Beacon entry IDs
- Confirmed matches with full details

### reconciliation_results.csv
Export containing:
- Bank transaction details
- Match type and status
- Confidence score
- Beacon entry details (up to 2)

## Example Output

```
MATCH_0000: 1-to-2 (confidence: 0.85)
  Bank: 15-Jan-25 - SMITH J PAYMENT - £26.00
  Beacon 1: 15/01/2025 - J Smith - £13.00
  Beacon 2: 15/01/2025 - J Smith - £13.00

MATCH_0001: 1-to-1 (confidence: 0.92)
  Bank: 16-Jan-25 - JONES A TRANSFER - £13.00
  Beacon 1: 16/01/2025 - A Jones - £13.00
```

## Architecture

```
Bank-Beacon-Reconcile/
├── reconciliation_system.py    # Core matching logic
├── reconciliation_gui.py       # Tkinter GUI
├── Bank_Transactions.csv       # Input: Bank transactions
├── Beacon_Entries.csv          # Input: Beacon entries
├── reconciliation_state.json   # Persistent state (generated)
├── reconciliation_results.csv  # Export output (generated)
└── README.md                   # This file
```

## Classes

### reconciliation_system.py
- `BankTransaction`: Data class for bank transactions
- `BeaconEntry`: Data class for Beacon entries
- `MatchSuggestion`: Data class for match suggestions
- `MatchStatus`: Enum for match states (PENDING, CONFIRMED, REJECTED, SKIPPED)
- `ReconciliationSystem`: Main matching engine

### reconciliation_gui.py
- `ReconciliationGUI`: Main GUI application class

## Troubleshooting

### CSV Encoding Issues
If you encounter encoding errors, ensure your CSV files are saved as UTF-8. The system handles UTF-8 BOM markers automatically.

### Date Parsing Errors
Ensure dates match the expected formats:
- Bank: DD-MMM-YY (e.g., 15-Jan-25)
- Beacon: DD/MM/YYYY (e.g., 15/01/2025)

### No Matches Found
If no matches are suggested:
- Check that amounts have potential exact matches
- Verify dates are within 7 days
- Ensure CSV files are in the correct format

## License

This project is provided for internal use.
