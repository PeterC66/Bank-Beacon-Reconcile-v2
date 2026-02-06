# Reconciliation State File Format

This document describes the structure and usage of the `reconciliation_state.json` file used by the Bank-Beacon Reconciliation System.

## Overview

The state file persists reconciliation progress between sessions. It tracks:
- Which beacon entries have been matched
- Confirmed matches (including manual matches and manually resolved items)
- Rejected bank transactions
- Rejected matches (for potential reconsideration)

The file is automatically created and updated in the same directory as the data files when the system runs.

## Top-Level Structure

```json
{
  "matched_beacon_ids": [...],
  "confirmed_matches": [...],
  "rejected_bank_ids": [...],
  "rejected_matches": [...]
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `matched_beacon_ids` | Array of strings | IDs of beacon entries that have been matched to bank transactions |
| `confirmed_matches` | Array of MatchSuggestion | All confirmed/finalized matches |
| `rejected_bank_ids` | Array of strings | IDs of bank transactions marked as rejected (no match expected) |
| `rejected_matches` | Array of MatchSuggestion | Matches that were rejected (preserved for potential reconsideration) |

## MatchSuggestion Object

Each match suggestion contains:

```json
{
  "id": "MATCH_0001",
  "bank_transaction": { ... },
  "beacon_entries": [ ... ],
  "confidence_score": 0.85,
  "match_type": "1-to-1",
  "status": "confirmed",
  "amount_score": 1.0,
  "date_score": 0.9,
  "name_score": 0.75,
  "comment": ""
}
```

### MatchSuggestion Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | String | Unique identifier (format: `MATCH_NNNN`) |
| `bank_transaction` | BankTransaction | The bank transaction being matched |
| `beacon_entries` | Array of BeaconEntry | One or more beacon entries (empty for `manually_resolved`) |
| `confidence_score` | Float (0-1) | Overall match confidence |
| `match_type` | String | Type of match: `"1-to-1"`, `"1-to-2"`, `"manual"`, or `"resolved"` |
| `status` | String | Current status (see Status Values below) |
| `amount_score` | Float (0-1) | How well amounts match |
| `date_score` | Float (0-1) | How well dates match |
| `name_score` | Float (0-1) | How well names match |
| `comment` | String | User comment (used primarily for `manually_resolved` items) |

### Status Values

| Status | Description |
|--------|-------------|
| `pending` | Awaiting user decision |
| `confirmed` | User confirmed this match is correct |
| `rejected` | User rejected this match as incorrect |
| `skipped` | User skipped (will see again later) |
| `manual_match` | User manually created this match by entering trans_no(s) |
| `manually_resolved` | User marked as resolved without beacon match (e.g., bank fee) |

### Match Type Values

| Type | Description |
|------|-------------|
| `1-to-1` | One bank transaction matched to one beacon entry |
| `1-to-2` | One bank transaction matched to two beacon entries (amounts sum) |
| `manual` | User manually specified the beacon transaction(s) |
| `resolved` | User marked as resolved without matching to beacon entries |

## BankTransaction Object

```json
{
  "id": "BANK_001",
  "date": "15-Jan-24",
  "type": "BGC",
  "description": "SMITH JOHN U3A1234",
  "amount": "13.00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | String | Unique identifier (format: `BANK_NNN`) |
| `date` | String | Transaction date (format: `DD-Mon-YY`, e.g., `15-Jan-24`) |
| `type` | String | Transaction type (e.g., `BGC`, `FPI`, `BBP`) |
| `description` | String | Bank description (often contains member name and number) |
| `amount` | String | Transaction amount as decimal string (e.g., `"13.00"`) |

## BeaconEntry Object

```json
{
  "id": "BEACON_001",
  "date": "15/01/2024",
  "trans_no": "12345",
  "payee": "John Smith",
  "amount": "13.00",
  "detail": "Membership renewal",
  "matched": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | String | Unique identifier (format: `BEACON_NNN`) |
| `date` | String | Entry date (format: `DD/MM/YYYY`) |
| `trans_no` | String | Beacon transaction number |
| `payee` | String | Payee/member name |
| `amount` | String | Amount as decimal string |
| `detail` | String | Transaction detail/description |
| `matched` | Boolean | Whether this entry has been matched |

## How the System Uses the State File

### On Startup (Loading)

1. Reads `matched_beacon_ids` and marks corresponding beacon entries as matched
2. Restores `confirmed_matches` list (these won't be suggested again)
3. Restores `rejected_bank_ids` (these bank transactions won't be suggested for matching)
4. Restores `rejected_matches` (preserved for potential reconsideration)

### During Operation (Saving)

The state is saved after each user action:
- Confirming a match
- Rejecting a match
- Creating a manual match
- Marking a transaction as manually resolved

### When Generating Suggestions

1. Excludes bank transactions in `rejected_bank_ids`
2. Excludes beacon entries in `matched_beacon_ids`
3. Cleans up `confirmed_matches` to remove any non-confirmed entries
4. Assigns new match IDs starting from max existing ID + 1 (prevents ID collisions)

## Common Issues and Repairs

### Duplicate Match IDs

**Symptom**: Multiple matches with same ID, inconsistency warnings on startup.

**Cause**: Older versions could generate IDs starting from 0, conflicting with existing matches.

**Repair**: Find and renumber duplicate IDs:
```python
# In the state file, ensure all MATCH_NNNN IDs are unique
# Renumber any duplicates to use sequential IDs
```

### Orphaned Beacon IDs

**Symptom**: Beacon entries marked as matched but no corresponding confirmed match exists.

**Cause**: State corruption or interrupted save.

**Repair**: Remove orphaned IDs from `matched_beacon_ids`:
```json
// Ensure every ID in matched_beacon_ids has a corresponding
// beacon entry in some confirmed_matches[].beacon_entries[]
```

### Wrong Status in confirmed_matches

**Symptom**: `confirmed_matches` contains entries with status other than `confirmed`, `manual_match`, or `manually_resolved`.

**Cause**: Bug in older versions didn't filter properly.

**Repair**: Remove entries with invalid status:
```json
// Keep only entries where status is one of:
// "confirmed", "manual_match", "manually_resolved"
```

### Inconsistent matched Flag

**Symptom**: BeaconEntry in confirmed match has `"matched": false`.

**Cause**: State saved before flag was set.

**Repair**: Set `"matched": true` for all beacon entries in confirmed matches:
```json
// For each entry in confirmed_matches[].beacon_entries[]
// ensure "matched": true
```

## Manual Editing Guidelines

When manually editing the state file:

1. **Always backup first**: Copy `reconciliation_state.json` before editing
2. **Maintain JSON validity**: Use a JSON validator after editing
3. **Keep IDs unique**: Match IDs must be unique across all arrays
4. **Update matched_beacon_ids**: If adding/removing matches, update this array accordingly
5. **Use correct date formats**: Bank dates are `DD-Mon-YY`, Beacon dates are `DD/MM/YYYY`
6. **Amounts as strings**: Always quote decimal amounts (e.g., `"13.00"` not `13.00`)

## Example Snippets

### Minimal Confirmed Match (1-to-1)

```json
{
  "id": "MATCH_0001",
  "bank_transaction": {
    "id": "BANK_001",
    "date": "15-Jan-24",
    "type": "BGC",
    "description": "SMITH JOHN U3A1234",
    "amount": "13.00"
  },
  "beacon_entries": [{
    "id": "BEACON_001",
    "date": "15/01/2024",
    "trans_no": "12345",
    "payee": "John Smith",
    "amount": "13.00",
    "detail": "Membership",
    "matched": true
  }],
  "confidence_score": 0.95,
  "match_type": "1-to-1",
  "status": "confirmed",
  "amount_score": 1.0,
  "date_score": 1.0,
  "name_score": 0.85,
  "comment": ""
}
```

### Manually Resolved Entry

```json
{
  "id": "MATCH_0002",
  "bank_transaction": {
    "id": "BANK_002",
    "date": "20-Jan-24",
    "type": "CHG",
    "description": "SERVICE CHARGE",
    "amount": "5.00"
  },
  "beacon_entries": [],
  "confidence_score": 1.0,
  "match_type": "resolved",
  "status": "manually_resolved",
  "amount_score": 0.0,
  "date_score": 0.0,
  "name_score": 0.0,
  "comment": "Bank service charge - no beacon entry expected"
}
```
