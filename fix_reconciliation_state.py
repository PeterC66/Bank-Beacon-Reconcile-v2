#!/usr/bin/env python3
"""
Fix script for reconciliation_state.json

This script cleans and rebuilds a corrupted reconciliation_state.json file by:
1. Filtering confirmed_matches to only keep valid statuses (confirmed, manual_match, manually_resolved)
2. Removing meaningful duplicates (same bank_transaction.id, same beacon IDs, same status)
3. Assigning new sequential MATCH_NNNN IDs starting from MATCH_0001
4. Setting matched=true for all beacon entries
5. Rebuilding matched_beacon_ids from the cleaned confirmed_matches
6. Clearing rejected_bank_ids and rejected_matches

Usage: python fix_reconciliation_state.py [path_to_json_file]
       If no path provided, looks for reconciliation_state.json in current directory

Output: reconciliation_state_fixed.json in the same directory as the input file
"""

import json
import sys
from pathlib import Path


VALID_STATUSES = {"confirmed", "manual_match", "manually_resolved"}


def load_json(file_path: Path) -> dict | None:
    """Load the JSON file. Returns None if failed."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: File not found: {file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON syntax at line {e.lineno}, column {e.colno}: {e.msg}")
        return None


def get_meaningful_key(match: dict) -> tuple:
    """
    Create a key for identifying meaningful duplicates.
    Two entries are duplicates if they have the same:
    - bank_transaction.id
    - beacon entry IDs (sorted)
    - status
    """
    bank_id = match.get("bank_transaction", {}).get("id", "")

    beacon_ids = tuple(sorted(
        beacon.get("id", "")
        for beacon in match.get("beacon_entries", [])
    ))

    status = match.get("status", "")

    return (bank_id, beacon_ids, status)


def fix_reconciliation_state(data: dict) -> dict:
    """
    Clean and rebuild the reconciliation state.

    Returns a new dict with:
    - Only valid confirmed_matches (filtered by status, deduplicated)
    - New sequential MATCH IDs
    - Fixed matched flags
    - Rebuilt matched_beacon_ids
    - Cleared rejected_bank_ids and rejected_matches
    """
    # Step 1: Filter confirmed_matches to valid statuses only
    valid_matches = []
    removed_invalid_status = 0

    for match in data.get("confirmed_matches", []):
        status = match.get("status", "")
        if status in VALID_STATUSES:
            valid_matches.append(match)
        else:
            removed_invalid_status += 1

    print(f"Filtered by status: kept {len(valid_matches)}, removed {removed_invalid_status} with invalid status")

    # Step 2: Remove meaningful duplicates (keep first occurrence)
    seen_keys = set()
    deduplicated_matches = []
    duplicate_count = 0

    for match in valid_matches:
        key = get_meaningful_key(match)
        if key not in seen_keys:
            seen_keys.add(key)
            deduplicated_matches.append(match)
        else:
            duplicate_count += 1

    print(f"Deduplicated: kept {len(deduplicated_matches)}, removed {duplicate_count} meaningful duplicates")

    # Step 3: Assign new sequential MATCH IDs and fix matched flags
    new_matches = []
    matched_beacon_ids = set()

    for i, match in enumerate(deduplicated_matches, start=1):
        new_match = match.copy()
        new_match["id"] = f"MATCH_{i:04d}"

        # Fix beacon entries - set matched=true and collect IDs
        new_beacon_entries = []
        for beacon in match.get("beacon_entries", []):
            new_beacon = beacon.copy()
            new_beacon["matched"] = True
            new_beacon_entries.append(new_beacon)

            beacon_id = beacon.get("id")
            if beacon_id:
                matched_beacon_ids.add(beacon_id)

        new_match["beacon_entries"] = new_beacon_entries
        new_matches.append(new_match)

    print(f"Assigned new IDs: MATCH_0001 to MATCH_{len(new_matches):04d}")
    print(f"Rebuilt matched_beacon_ids: {len(matched_beacon_ids)} beacon IDs")

    # Step 4: Build the new state
    new_state = {
        "matched_beacon_ids": sorted(list(matched_beacon_ids)),
        "confirmed_matches": new_matches,
        "rejected_bank_ids": [],
        "rejected_matches": []
    }

    return new_state


def main():
    # Determine file path
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
    else:
        file_path = Path("reconciliation_state.json")

    print(f"Loading: {file_path}")
    print("")

    # Load the file
    data = load_json(file_path)
    if data is None:
        sys.exit(1)

    # Show original stats
    original_confirmed = len(data.get("confirmed_matches", []))
    original_rejected = len(data.get("rejected_matches", []))
    original_beacon_ids = len(data.get("matched_beacon_ids", []))
    original_rejected_bank = len(data.get("rejected_bank_ids", []))

    print("Original file statistics:")
    print(f"  confirmed_matches: {original_confirmed}")
    print(f"  rejected_matches: {original_rejected}")
    print(f"  matched_beacon_ids: {original_beacon_ids}")
    print(f"  rejected_bank_ids: {original_rejected_bank}")
    print("")

    # Fix the state
    print("Processing...")
    new_state = fix_reconciliation_state(data)
    print("")

    # Show new stats
    print("New file statistics:")
    print(f"  confirmed_matches: {len(new_state['confirmed_matches'])}")
    print(f"  rejected_matches: {len(new_state['rejected_matches'])}")
    print(f"  matched_beacon_ids: {len(new_state['matched_beacon_ids'])}")
    print(f"  rejected_bank_ids: {len(new_state['rejected_bank_ids'])}")
    print("")

    # Write output file
    output_path = file_path.parent / "reconciliation_state_fixed.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(new_state, f, indent=2)

    print(f"Fixed file saved to: {output_path}")
    print("")
    print("IMPORTANT: Before using the fixed file:")
    print("  1. Back up your original reconciliation_state.json")
    print("  2. Run the validator on reconciliation_state_fixed.json to verify it's clean")
    print("  3. Rename reconciliation_state_fixed.json to reconciliation_state.json when ready")


if __name__ == "__main__":
    main()
