# Bank Beacon Reconciliation System v2

**Version 2.2.0** | Windows | Python 3.8+

A bank-centric reconciliation tool for u3a groups using the [Beacon](https://www.u3a.org.uk/beacon) membership system. It matches HSBC bank transactions to Beacon accounting entries through a split-panel GUI, stepping through bank entries and showing ranked Beacon candidates for each.

---

## Contents

- [How it works](#how-it-works)
- [Installation](#installation)
- [Folder structure](#folder-structure)
- [Configuration reference](#configuration-reference)
- [File format reference](#file-format-reference)
- [Optional code-level files](#optional-code-level-files)
- [Matching algorithm](#matching-algorithm)
- [State and persistence](#state-and-persistence)
- [Reports](#reports)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## How it works

The system loads your bank transactions (HSBC CSV export) and your Beacon accounting entries (from a Beacon Excel backup). For each bank entry it generates ranked candidates from the Beacon data, scored by amount, date proximity, and payee name. You work through entries confirming, rejecting, or manually resolving each one. Progress is saved automatically.

See [RECONCILIATION_GUIDE.md](RECONCILIATION_GUIDE.md) for a step-by-step guide to actually doing a reconciliation.

---

## Installation

### Prerequisites

Before installing this system you will need:

- **Python 3.8 or later** — [python.org/downloads](https://www.python.org/downloads/). During installation, tick "Add Python to PATH".
- **openpyxl** — install after Python by running in a command prompt:
  ```
  pip install openpyxl
  ```
- **Git** (optional, for cloning) — [git-scm.com](https://git-scm.com/). Alternatively, download the repository as a ZIP from GitHub.

### Step 1 — Get the code

Clone or download this repository from GitHub into a folder on your computer, for example:

```
C:\Users\YourName\Bank-Beacon-Reconcile-v2\
```

This folder is called the **code folder** throughout this guide.

### Step 2 — Get your Beacon backup file

Export a full backup from Beacon using the **"Back up all data"** option:

> Beacon menu → Administration → Data Export and Backup → Back up all data

This produces an Excel file (`.xlsx`) containing all Beacon data including a `Members` worksheet and a `Ledger` worksheet. Save this file in the **code folder** (alongside `reconciliation_gui.py`).

Full details of the Beacon backup process are at:
[u3abeacon.zendesk.com — 9.5 Data Export and Backup](https://u3abeacon.zendesk.com/hc/en-gb/articles/360007304557-9-5-Data-Export-and-Backup)

### Step 3 — Get your bank CSV

*[To be done — instructions for downloading a transaction CSV from HSBC online banking.]*

> **Note:** The system currently supports HSBC's CSV export format. Support for other banks can be added by extending `_parse_bank_date()` and adjusting the column mapping in `reconciliation_system.py`.

Save the bank CSV file in your **data folder** (see Step 4).

### Step 4 — Create a data folder

Create a subfolder inside `data\` for your reconciliation period, for example:

```
data\2025-current\
```

Each reconciliation period (or separate bank account) gets its own data folder. The code folder is shared across all of them.

Copy the `run.bat` and `run.py` files from `data\sample\` into your new data folder, then copy your bank CSV into it.

Your data folder should look like:

```
data\2025-current\
├── config.json              ← you create this (see Step 5)
├── Bank_Transactions.csv    ← your HSBC export
├── run.bat                  ← copied from data\sample\
└── run.py                   ← copied from data\sample\
```

### Step 5 — Create config.json

Create a `config.json` file in your data folder. Here is a template for Excel backup mode:

```json
{
    "title": "Current Account Reconciliation — Jan to Mar 2025",
    "bank_file": "Bank_Transactions.csv",
    "backup_file": "beacon_backup_2025_03.xlsx",
    "ledger_account": "Current",
    "ledger_date_from": "01/01/2025",
    "ledger_date_to": "31/03/2025",
    "common_amounts": ["13.00", "9.50", "6.50"],
    "date_tolerance_days": 7,
    "trans_no_limit": 5,
    "auto_reconcile_common_threshold": 0.90,
    "auto_reconcile_other_threshold": 0.80
}
```

**Key fields:**

| Field | Description |
|-------|-------------|
| `title` | Displayed in the window title bar |
| `bank_file` | Name of your bank CSV (in the data folder) |
| `backup_file` | Name of your Beacon Excel backup (in the **code folder**) |
| `ledger_account` | The Beacon account to reconcile — typically `"Current"`. Some u3as have additional accounts (e.g. `"Social Account"`); check your Beacon ledger for the exact name |
| `ledger_date_from` | Start of the date range to load from the Beacon ledger (DD/MM/YYYY, inclusive) |
| `ledger_date_to` | End of the date range (DD/MM/YYYY, inclusive) |
| `common_amounts` | Amounts that appear frequently and are therefore weak matching signals — typically your standard subscription and session fees. Candidates with these amounts are scored differently (see [Matching algorithm](#matching-algorithm)) |
| `date_tolerance_days` | Maximum days between bank and Beacon dates for a candidate to be considered (default 7) |
| `trans_no_limit` | Maximum gap between two Beacon `trans_no` values for a 1-to-2 pair to be detected (default 5) |
| `auto_reconcile_common_threshold` | Minimum confidence for auto-reconcile when the amount is a common amount (default 0.90) |
| `auto_reconcile_other_threshold` | Minimum confidence for auto-reconcile when the amount is not common (default 0.80) |

### Step 6 — Launch the system

Double-click `run.bat` in your data folder. The GUI will open.

Alternatively, from a command prompt:

```
python C:\Users\YourName\Bank-Beacon-Reconcile-v2\reconciliation_gui.py data\2025-current\
```

### Step 7 — Optional: create alias and confusable-member files

See [Optional code-level files](#optional-code-level-files) below.

---

## Folder structure

```
Bank-Beacon-Reconcile-v2\          ← code folder
├── reconciliation_system.py        # Core matching engine
├── reconciliation_gui.py           # Tkinter GUI
├── test_reconciliation.py          # Test suite (38 tests)
├── beacon_backup_2025_03.xlsx      # Your Beacon Excel backup (you add this)
├── memno_aliases.csv               # Optional: member number aliases
├── confusable_members.csv          # Optional: easily confused member pairs
├── README.md
├── RECONCILIATION_GUIDE.md
└── data\
    ├── sample\                     # Example dataset
    │   ├── config.json
    │   ├── Bank_Transactions.csv
    │   ├── Beacon_Entries.csv
    │   ├── run.bat
    │   └── run.py
    └── 2025-current\               # Your dataset (you create this)
        ├── config.json
        ├── Bank_Transactions.csv
        ├── run.bat
        ├── run.py
        └── reconciliation_state_v2.json   # Auto-saved progress
```

---

## Configuration reference

All config fields and their defaults:

| Field | Default | Description |
|-------|---------|-------------|
| `title` | derived from account + date | Window title |
| `bank_file` | `"Bank_Transactions.csv"` | Bank CSV filename (in data folder) |
| `beacon_file` | `"Beacon_Entries.csv"` | Beacon CSV filename — not used in Excel backup mode |
| `backup_file` | `null` | Beacon Excel backup filename (in code folder). When set, replaces `beacon_file` and loads members from the `Members` worksheet |
| `ledger_account` | `null` | Required when `backup_file` is set |
| `ledger_date_from` | `null` | Required when `backup_file` is set (DD/MM/YYYY) |
| `ledger_date_to` | `null` | Required when `backup_file` is set (DD/MM/YYYY) |
| `ledger_exclude_cleared` | `true` | Exclude Beacon ledger entries that already have a Cleared date |
| `common_amounts` | `["13.00","9.50","6.50"]` | Amounts treated as weak matching signals |
| `date_tolerance_days` | `7` | Max days between bank and Beacon dates |
| `trans_no_limit` | `5` | Max trans_no gap for 1-to-2 pair detection |
| `auto_reconcile_common_threshold` | `0.90` | Auto-reconcile threshold for common amounts |
| `auto_reconcile_other_threshold` | `0.80` | Auto-reconcile threshold for other amounts |
| `allow_1_to_2` | `true` | Enable detection of 1-bank-to-2-beacon pairs |
| `match_beacon_detail` | `true` | Include beacon `detail` field in name matching |
| `bank_date_from` | `null` | Only load bank entries on or after this date (DD/MM/YYYY) |
| `bank_date_to` | `null` | Only load bank entries on or before this date (DD/MM/YYYY) |

---

## File format reference

### Bank_Transactions.csv (HSBC format)

```
Date,Type,Description,Amount
15-Jan-25,DEB,SMITH J PAYMENT,26.00
```

| Column | Description |
|--------|-------------|
| `Date` | Transaction date — multiple formats supported: `DD-MMM-YY`, `DD MMM YYYY`, `DD-MMM-YYYY`, `DD/MM/YYYY`, `DD/MM/YY`, `YYYY-MM-DD` |
| `Type` | Transaction type (e.g. DEB, CR) |
| `Description` | Free text — usually contains payee name in `SURNAME INITIAL` format, and may contain a member number |
| `Amount` | Decimal amount |

### Beacon_Entries.csv (CSV mode only)

Not used in Excel backup mode. If using CSV mode:

```
tkey,trans_no,date,account,amount,payee,detail,payment_method,cheque,notes,cleared,member_1,group,c_name
```

| Column | Description |
|--------|-------------|
| `date` | `DD/MM/YYYY` format |
| `trans_no` | Transaction reference |
| `payee` | Payee name |
| `amount` | Decimal amount |
| `member_1` | Forename+Surname, no space (e.g. `SmithJ`) |
| `member_2` | Second member, same format |

### Beacon Excel backup (Excel backup mode)

The backup file must contain:

- **`Members` worksheet** — columns: `mem_no`, `status`, `forename`, `surname` (plus optional `known_as`, `class`, `payment_type`)
- **`Ledger` worksheet** — same columns as `Beacon_Entries.csv` above

---

## Optional code-level files

These files live in the code folder alongside `reconciliation_gui.py`. They are shared across all datasets.

### memno_aliases.csv

Maps old member numbers to current member numbers. Useful when a member has been re-registered and their old number appears in bank descriptions.

```
old_memno,new_memno
1234,5678
```

Chains are resolved automatically (if 1234→5678 and 5678→9012, then 1234 resolves to 9012).

### confusable_members.csv

Pairs of members whose names are easily confused (e.g. two members with the same surname). When a bank entry could match either member, a warning is shown in the GUI.

```
memno_1,memno_2
1234,5678
```

Both files are optional. If absent, no aliases or warnings are applied.

---

## Matching algorithm

### Scoring components

**Amount score:**
- Common amount (in `common_amounts`): **0.3** — weak signal, many Beacon entries share this amount
- Any other amount: **1.0** — strong signal

**Date score:**

| Gap (bank after beacon) | Score |
|------------------------|-------|
| Same day | 1.00 |
| 1 day | 0.95 |
| 2 days | 0.90 |
| 3 days | 0.80 |
| 4–7 days | 0.60 |
| 8–14 days | 0.40 |
| 15–28 days | 0.25 |

Beacon entries dated *after* the bank date score lower (0.50 at 1 day, 0.25 at 2 days, excluded at 3+).

**Name score:**
- Surname similarity between bank description and Beacon payee/detail fields
- Member number found in bank description matching `member_1` or `member_2`: overrides to **0.95**

### Confidence weights

| Amount type | Amount | Date | Name |
|-------------|--------|------|------|
| Common | 10% | 45% | 45% |
| Other | 30% | 35% | 35% |

1-to-2 matches (one bank entry to two Beacon entries) receive a **10% confidence penalty**.

### Candidate ordering

Candidates are listed: non-rejected first (highest confidence first), then rejected entries (highest confidence first, greyed out).

---

## State and persistence

Progress is saved automatically to `reconciliation_state_v2.json` in the data folder after every action. It stores:

- **reconciliations** — all bank-to-beacon pairings (reconciled and resolved)
- **rejected_pairings** — per-bank rejected beacon IDs

The state file is human-readable JSON. Its format is documented in `reconciliation_state_format.md`.

---

## Reports

Click **Reports** in the GUI to generate five files in the data folder:

| File | Contents |
|------|----------|
| `report_reconciled.csv` | All reconciled bank/beacon pairings |
| `report_unreconciled_bank.csv` | Bank entries not yet reconciled |
| `report_unreconciled_beacon.csv` | Beacon entries not yet reconciled |
| `report_resolved.csv` | Manually resolved entries with comments |
| `report_stats.txt` | Summary statistics with date and version |

---

## Testing

```
python test_reconciliation.py
```

38 tests covering: loading, candidate generation, 1-to-1 and 1-to-2 matching, common amounts, reconcile/un-reconcile, reject/un-reject, auto-reconcile, manual match, mark resolved, statistics, state persistence, search, exports, navigation, candidate ordering, member resolution, aliases, and confusable members.

---

## Troubleshooting

### No candidates found for a bank entry
- Check that the amount has a potential match in the Beacon data
- Verify dates are within `date_tolerance_days` — try increasing it temporarily
- Use the Beacon search panel with **All beacons** ticked to find entries manually

### Wrong match selected by amount alone
Common amounts (e.g. £13.00) have many Beacon candidates. The correct match may be outside the date tolerance. Increase `date_tolerance_days` in config and click **Refresh**, then manually select the correct candidate.

### CSV encoding errors
Files are read as UTF-8 with BOM handling. If you see encoding errors, re-save your CSV as UTF-8 from Excel (File → Save As → CSV UTF-8).

### openpyxl not found
Run `pip install openpyxl` in a command prompt, then restart the application.

### Date parsing errors
Bank dates support multiple formats automatically. Beacon dates in the Excel backup must be `DD/MM/YYYY`. If a date fails to parse, check the raw value in Excel.

---

## Migrating from v1

If you have a v1 `reconciliation_state.json`, convert it with:

```
python migrate_v1_to_v2.py path\to\reconciliation_state.json
```

This converts confirmed matches to reconciliations and carries over manually resolved entries.

---

*This project is provided for internal u3a use.*
