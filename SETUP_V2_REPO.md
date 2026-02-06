# Setting up Bank-Beacon-Reconcile-v2

## Steps to create the new repository

### 1. Create the repo on GitHub
Go to https://github.com/new and create a new repository:
- **Name:** `Bank-Beacon-Reconcile-v2`
- **Description:** Bank Beacon Reconciliation System v2
- **Visibility:** Private (or Public, your choice)
- **Do NOT** initialize with README, .gitignore, or license (we'll push our own files)

### 2. Push the prepared files
The v2 files have been prepared at `/home/user/Bank-Beacon-Reconcile-v2/`.
Once the GitHub repo exists, run these commands:

```bash
cd /home/user/Bank-Beacon-Reconcile-v2
git init
git branch -m main
git add -A
git commit -m "Initial import from Bank-Beacon-Reconcile v1"
git remote add origin https://github.com/PeterC66/Bank-Beacon-Reconcile-v2.git
git push -u origin main
```

### Files included
All source files from v1 are included as a starting baseline:
- `reconciliation_system.py` - Core reconciliation engine
- `reconciliation_gui.py` - Tkinter GUI
- `test_reconciliation.py` - Test suite
- `fix_reconciliation_state.py` - State repair utility
- `validate_reconciliation_state.py` - State validator
- `Bank_Transactions.csv` - Sample bank data
- `Beacon_Entries.csv` - Sample beacon data
- `member_lookup.csv` - Member lookup table
- `README.md` - Documentation
- `SESSION_NOTES.md` - Development notes
- `reconciliation_state_format.md` - State format docs
- `.gitignore` - Git ignore rules
