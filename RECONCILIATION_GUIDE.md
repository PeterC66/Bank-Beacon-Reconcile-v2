# Reconciliation Guide

**Bank Beacon Reconciliation System v2.2.0**

This guide explains how to carry out a reconciliation — matching your HSBC bank transactions to Beacon accounting entries. It assumes the system is already installed and configured. If not, see [README.md](README.md) first.

---

## Contents

- [Overview](#overview)
- [Launching the system](#launching-the-system)
- [Understanding the interface](#understanding-the-interface)
- [Recommended workflow](#recommended-workflow)
  - [Step 1: Auto-reconcile high-confidence matches](#step-1-auto-reconcile-high-confidence-matches)
  - [Step 2: Work through remaining entries manually](#step-2-work-through-remaining-entries-manually)
  - [Step 3: Handle entries with no match](#step-3-handle-entries-with-no-match)
  - [Step 4: Generate reports](#step-4-generate-reports)
- [Actions in detail](#actions-in-detail)
- [Searching](#searching)
- [Adjusting date tolerance](#adjusting-date-tolerance)
- [Checking consistency](#checking-consistency)
- [Tips and edge cases](#tips-and-edge-cases)

---

## Overview

Reconciliation means confirming that each bank transaction corresponds to one or more entries in the Beacon accounts, or recording why it does not. The system works bank-entry by bank-entry:

- The **left panel** shows one bank entry at a time
- The **right panel** shows ranked Beacon candidates for that entry
- You confirm, reject, or manually resolve each pairing
- Progress is saved automatically after every action

The recommended order is: **auto-reconcile first** (to handle clear-cut matches quickly), then **manually review the remainder**.

---

## Launching the system

Double-click `run.bat` in your data folder. The GUI will open and load your bank and Beacon data.

![BBR anonymised](https://github.com/user-attachments/assets/810b696a-1b32-40f0-80f1-d7c6a51e6c91)
*[Screenshot: application on startup showing both panels loaded]*

The stats bar at the top shows a summary:

```
Reconciled: 42 (£546.00) | Un-reconciled: 18 (£234.00) | Resolved: 2 (£26.00) | v2.2.0
```

By default, the bank panel shows **only un-reconciled entries**. Tick **Show all** (top-left) to see every bank entry including already-reconciled ones.

---

## Understanding the interface

*[Screenshot TBD: annotated overview of the full GUI window]*

### Stats bar (top)

Shows running totals: how many bank entries are reconciled, un-reconciled, and resolved, with their sum amounts.

### Left panel — bank entry

*[Screenshot TBD: left panel showing a single bank entry]*

Displays the current bank transaction:
- **Date**, **Type**, **Description**, **Amount**
- Any member numbers detected in the description, with their names from the Beacon member list
- A confusable-members warning if the bank entry could refer to more than one member with a similar name

Navigate with **< Prev Bank** and **Next Bank >**.

### Right panel — Beacon candidates

*[Screenshot TBD: right panel showing ranked candidates]*

Shows the Beacon candidates for the current bank entry, ranked by confidence (highest first). Each candidate shows:
- **Confidence score** (e.g. `0.87`) and match type (`1-to-1` or `1-to-2`)
- **Trans no**, **Date**, **Payee**, **Amount**, **Detail**, **Group**
- The scoring breakdown: amount score, date score, name score

For **1-to-2 candidates** (one bank entry matching a pair of Beacon entries), both entries are shown together with a combined score.

Rejected candidates appear below, greyed out.

Navigate with **< Prev Candidate** and **Next Candidate >**.

### Action buttons

| Button | What it does |
|--------|-------------|
| **Reconcile** | Confirms the current bank/candidate pairing |
| **Un-reconcile** | Undoes a reconciliation, freeing both entries |
| **Reject Pairing** | Marks the current candidate as wrong for this bank entry (moves to bottom, greyed out) |
| **Un-reject Pairing** | Undoes a rejection |
| **Auto-Reconcile** | Batch-reconciles all entries above the confidence thresholds |
| **Manual Match** | Enter one or two Beacon `trans_no` values to manually create a pairing |
| **Mark Resolved** | Records a comment explaining why a bank entry has no Beacon match |
| **Reports** | Generates report CSV files in the data folder |
| **Check Consistency** | Scans for issues such as duplicate matches or amount mismatches |

### Config spinboxes

- **Date tol** — date tolerance in days (default 7). Change and press Enter or click away to apply.
- **Trans limit** — maximum trans_no gap for 1-to-2 pair detection (default 5).

---

## Recommended workflow

### Step 1: Auto-reconcile high-confidence matches

Click **Auto-Reconcile**. The system will reconcile all candidates whose confidence exceeds the configured thresholds:
- Common amounts (e.g. subscription fees): threshold 0.90 by default
- All other amounts: threshold 0.80 by default

*[Screenshot TBD: after auto-reconcile — stats bar showing updated reconciled count]*

Auto-reconcile only acts on **unambiguous** high-confidence matches. It will not reconcile an entry if two candidates are both above the threshold. Review the stats bar to see how many were resolved.

> **Tip:** Run auto-reconcile at the start of every session. As you manually resolve more entries, running it again may catch additional matches that were previously blocked by ambiguous candidates.

---

### Step 2: Work through remaining entries manually

Use **Next Bank >** to step through un-reconciled entries (the left panel skips already-reconciled ones by default).

For each bank entry:

#### If the top candidate looks correct

Check the confidence score, date, payee name, and amount. If satisfied, click **Reconcile**. The system moves automatically to the next un-reconciled bank entry.

*[Screenshot TBD: a bank entry with a clear high-confidence candidate, about to be reconciled]*

#### If the top candidate is wrong

Click **Reject Pairing** to push it to the bottom of the candidate list. The next candidate becomes the focus. Continue rejecting until you find the right one, then click **Reconcile**.

#### If no candidate is correct but you know which Beacon entry to use

Click **Manual Match**. Enter the `trans_no` of the Beacon entry (e.g. `TRN1234`). For a 1-to-2 match, enter two trans_nos separated by a comma or space. Click **OK**.

*[Screenshot TBD: manual match dialog with a trans_no entered]*

> **Finding a trans_no:** Use the Beacon search panel (right side) to locate the entry. Tick **All beacons** to search across all entries including already-reconciled ones. Search by payee name, amount (e.g. `£26.00`), date (e.g. `17/03/2025`), or trans_no directly (e.g. `TRN1234`).

#### If the top candidate is a 1-to-2 match

A 1-to-2 candidate means the system detected that one bank payment corresponds to two Beacon entries (e.g. two people paying together). These are shown with match type `1-to-2` and carry a small confidence penalty. Verify both Beacon entries make sense before clicking **Reconcile**.

---

### Step 3: Handle entries with no match

Some bank entries may genuinely have no corresponding Beacon entry — for example, bank charges, transfers, or receipts outside the Beacon period. For these:

Click **Mark Resolved** and enter a brief comment explaining the situation (e.g. `Bank charge — not in Beacon`, `Transfer to savings — internal`).

*[Screenshot TBD: Mark Resolved dialog with a comment entered]*

Resolved entries appear in the `report_resolved.csv` report and are excluded from the un-reconciled count.

---

### Step 4: Generate reports

When you are satisfied that all bank entries are either reconciled or resolved, click **Reports**.

Five CSV/text files are written to your data folder:

| File | Contents |
|------|----------|
| `report_reconciled.csv` | All matched bank/Beacon pairings |
| `report_unreconciled_bank.csv` | Bank entries still without a match |
| `report_unreconciled_beacon.csv` | Beacon entries still without a match |
| `report_resolved.csv` | Manually resolved entries with your comments |
| `report_stats.txt` | Summary counts and totals, dated and versioned |

*[Screenshot TBD: data folder in Windows Explorer showing the five report files]*

Open the files in Excel to review. The `report_stats.txt` file is a quick sanity check — it should show zero (or explained) un-reconciled entries when you are done.

---

## Actions in detail

### Reconcile

Confirms the current bank entry is matched to the currently displayed Beacon candidate. Both entries are marked as reconciled and will no longer appear in un-reconciled views.

A 1-to-2 reconciliation links one bank entry to two Beacon entries; all three are marked reconciled together.

### Un-reconcile

Reverses a reconciliation. The bank entry and all associated Beacon entries return to un-reconciled status. Use this to correct a mistake.

To reach an already-reconciled entry: tick **Show all** in the left panel to show all bank entries, navigate to the one you want, then click **Un-reconcile**.

### Reject Pairing

Marks a specific Beacon candidate as the wrong match for this bank entry. The candidate is not deleted — it moves to the bottom of the list and is shown greyed out. It remains available in case you change your mind.

Rejections persist across sessions (they are saved in the state file).

### Un-reject Pairing

Navigate to a rejected candidate (it will be greyed out at the bottom of the list) and click **Un-reject Pairing** to restore it to the active candidates list.

### Manual Match

Opens a dialog where you can enter one or two Beacon `trans_no` values. Use this when:
- The correct Beacon entry is not appearing as a candidate (e.g. date is outside tolerance)
- You know the exact trans_no from the Beacon system
- You need to create a 1-to-2 match that was not auto-detected

### Mark Resolved

Records that a bank entry has been investigated and there is a known reason it has no Beacon match. You must enter a comment. This is different from reconciling — no Beacon entry is linked.

---

## Searching

Both panels have search boxes.

### Bank search (left panel)

Search types are auto-detected:

| Input | Searches by |
|-------|-------------|
| `Smith` | Name/description substring |
| `"Smith John"` | Exact phrase |
| `£26.00` or `26` | Exact amount |
| `17/03/2025` | Date (various formats accepted) |
| `BANK_0042` | Bank entry ID |

Click **Find** or press Enter. Click **Clear** to reset.

### Beacon search (right panel)

Same syntax as above, plus:

| Input | Searches by |
|-------|-------------|
| `TRN1234` | Beacon trans_no |
| `BEACON_0123` | Beacon entry ID |

**All beacons** — when ticked, searches across *all* Beacon entries including those already reconciled. Use this when you know a Beacon entry exists but cannot find it in the normal candidate list.

**Cheque** — when ticked, restricts results to cheque payments.

---

## Adjusting date tolerance

The **Date tol** spinbox (bottom of the action panel) controls how many days either side of the bank date the system looks for Beacon candidates. The default is 7 days.

If a bank entry has no candidates, or the correct candidate is missing, try increasing the tolerance:

1. Change **Date tol** to a higher value (e.g. 14 or 21)
2. Click away or press Enter — candidates for the current bank entry refresh automatically
3. Check whether the correct Beacon entry now appears

> **Note:** Increasing the tolerance may also introduce more false candidates for common amounts. Use it as a diagnostic tool, not a permanent setting.

The **Trans limit** spinbox controls the maximum `trans_no` gap for 1-to-2 pair detection. Increase it if valid pairs are being missed; decrease it to reduce false pair suggestions.

---

## Checking consistency

Click **Check Consistency** to scan the current state for issues such as:
- A Beacon entry reconciled to more than one bank entry
- Amount mismatches between a bank entry and its reconciled Beacon entries

Use **< Issue** and **Issue >** to step through any issues found. Click **Ignore** to dismiss an issue you have reviewed and accepted.

Run this check before generating final reports as a last sanity check.

---

## Tips and edge cases

### Common amounts (e.g. subscription fees)

Amounts like £13.00 or £9.50 appear many times in the Beacon data, so they are treated as weak matching signals. The system relies more heavily on date and name for these. The confidence threshold for auto-reconcile is set higher for common amounts (0.90 vs 0.80) to reduce false matches.

If the correct Beacon entry for a common-amount payment is not the top candidate, check the date and name carefully, then reconcile manually.

### Member numbers in bank descriptions

HSBC descriptions sometimes include a member number (e.g. `SMITH J 1234 PAYMENT`). The system detects this and uses it as a strong matching signal — a Beacon candidate whose `member_1` or `member_2` matches the number gets a name score of 0.95 regardless of name similarity.

The member information panel (bottom-left) shows the detected member number and their name from the Beacon member list.

### Confusable members warning

If two members have similar names (configured in `confusable_members.csv`), a warning is displayed when a bank entry could refer to either of them. Check both candidates carefully before reconciling.

### Member number aliases

If a member has re-registered under a new number, the old number can be mapped to the new one in `memno_aliases.csv`. This allows bank descriptions containing the old number to match Beacon entries using the new number.

### Restarting mid-session

Progress is saved automatically after every action. Simply close the window and re-open `run.bat` to continue where you left off.

### Un-reconciling a batch

There is no bulk un-reconcile. To undo multiple reconciliations, tick **Show all**, navigate to each reconciled bank entry, and click **Un-reconcile** individually.

### Running auto-reconcile more than once

It is safe to run **Auto-Reconcile** multiple times. It will only act on entries that are not yet reconciled and skips anything already done.
