# Bank Beacon Reconcile v2

## Project Overview
Bank-centric reconciliation system matching bank transactions to Beacon accounting entries.
Tkinter GUI with split-panel interface (left=bank, right=beacon candidates).

## Run Tests
```
python test_reconciliation.py
```

## Key Files
- `reconciliation_system.py` - Core engine (loading, matching, reconciliation, reports)
- `reconciliation_gui.py` - Tkinter GUI
- `test_reconciliation.py` - Test suite (30 tests, uses `data/sample/`)
- `member_lookup.csv` - Shared member directory (code level)
- `memno_aliases.csv` - Member number aliases (code level, optional)
- `confusable_members.csv` - Pairs of easily confused members (code level, optional)
- `data/<dataset>/config.json` - Per-dataset configuration
- `data/<dataset>/reconciliation_state_v2.json` - Saved state

## Conventions
- **Terminology**: "Reconciled" not "confirmed"
- **Version**: Ask before incrementing. Format: major.minor.patch
- **Current version**: 2.1.0
- **Data folders**: Each dataset in `data/<name>/` with own `config.json`, CSVs, `run.bat`
- **Member fields**: `member_1`/`member_2` on beacon = forename+surname, no space (e.g. "LLeonard")

## Architecture Notes
- Member resolution pipeline: exact name -> noise word strip -> surname+initial -> surname-only fallback
- `memno_aliases.csv` maps old_memno -> new_memno with chain resolution
- `confusable_members.csv` at code level (memno_1,memno_2 pairs) shows warnings in UI
- Bank CSV dates: multiple formats handled by `_parse_bank_date()`
- Beacon CSV dates: always `%d/%m/%Y`
- Decimal amounts: use `str(amount)` not format strings for display
