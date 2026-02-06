# Session Notes - Bank Beacon Reconciliation System

**Date:** 2026-02-06
**Purpose:** Continuity notes for next development session

---

## What Was Implemented This Session

### 1. Configurable Date Tolerance
- Added `date_tolerance_days` parameter (default 7 days)
- GUI spinbox before "Refresh Suggestions" button
- Click Refresh to apply new tolerance
- Fixes cases where bank/beacon dates are >7 days apart

### 2. Enhanced Search with Auto-Detection
Search box now supports multiple search types (auto-detected):
- `name` - substring search in description/payee (default)
- `"exact text"` - literal quoted string search
- `£13.00` or `13` - exact amount search
- `17/03/2025`, `17-Mar-2025`, etc. - date search (multiple formats)
- `TR_7130` - beacon trans_no search
- `MATCH_0001`, `BANK_0042`, `BEACON_0123` - exact ID search

Help text displayed next to search box. "No matches found" shows in red.

### 3. Multi-Format Bank Date Parsing
Bank CSV loading now accepts multiple date formats:
- `17-Mar-25` (original)
- `17 Mar 2025`, `17-Mar-2025`
- `17/03/2025`, `17/03/25`
- `2025-03-17`

### 4. Stats with Amount Totals
Stats bar now shows amounts:
```
Confirmed: 150 (£1,950.00) | Pending: 4 (£52.00) | Rejected: 2 | Unmatched Bank: 3 (£39.00)
```

### 5. Skip Confirmed Includes Manual Types
"Skip confirmed" checkbox now also skips:
- MANUAL_MATCH
- MANUALLY_RESOLVED

### 6. UI Improvements
- "NO MATCH FOUND" displays with bold 12pt font and warning symbols
- "Export CSVs" button renamed to "Reports"
- Search "No matches found" shows in red

### 7. Documentation
- Created `reconciliation_state_format.md` - technical docs for state file structure

---

## Known Issues / Pending Investigation

### Stats Discrepancy
- User reported: Pending shows 4 (correct) but Unmatched Bank shows 3 (should be 4)
- **Possible cause:** `unmatched_bank` is calculated as `total_bank - confirmed_count`
- If one bank transaction has multiple pending suggestions, counts diverge
- **Not fully resolved** - needs investigation

### Common Amount Matching Limitation
- £13.00 is a common amount with many beacon entries
- A bank transaction may match the WRONG £13.00 beacon if dates align
- The correct match (e.g., Madden) may be outside date tolerance
- **Workaround:** Increase date tolerance and manually select correct match

---

## Key Files

| File | Purpose |
|------|---------|
| `reconciliation_system.py` | Core matching logic, state management |
| `reconciliation_gui.py` | Tkinter GUI |
| `reconciliation_state.json` | Persisted state (matches, rejections) |
| `reconciliation_state_format.md` | State file documentation |

---

## Configuration Constants (reconciliation_system.py)

```python
COMMON_AMOUNTS = [Decimal('13.00'), Decimal('9.50'), Decimal('6.50')]
AUTO_CONFIRM_COMMON_THRESHOLD = 0.90   # >90% for common amounts
AUTO_CONFIRM_OTHER_THRESHOLD = 0.80    # >80% for other amounts
DEFAULT_DATE_TOLERANCE_DAYS = 7
```

---

## Match Status Types

| Status | Description |
|--------|-------------|
| PENDING | Awaiting user decision |
| CONFIRMED | User confirmed match |
| REJECTED | User rejected match |
| SKIPPED | User skipped (see again later) |
| MANUAL_MATCH | User manually entered trans_no(s) |
| MANUALLY_RESOLVED | User marked resolved without beacon match |

---

## Recent Git Commits (this session)

1. Add documentation for reconciliation_state.json format
2. Add configurable date tolerance and ensure all bank transactions displayed
3. Add enhanced search with auto-detection of search type
4. Add trans_no search, fix skip confirmed, and multi-format bank date parsing
5. Enhance stats with amounts, highlight no-match, rename button
6. Adjust highlight colors: gray for no-match panel, red for search

---

## Tips for Next Session

1. The codebase is well-documented - read the code for implementation details
2. State file format is documented in `reconciliation_state_format.md`
3. Debug output goes to console (print statements with `[DEBUG]` prefix)
4. `debug_log()` function in reconciliation_system.py includes line numbers
