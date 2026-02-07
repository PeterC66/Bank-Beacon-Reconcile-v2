"""
Migrate v1 reconciliation state to v2 format.

Usage:
    python migrate_v1_to_v2.py <v1_state_file> [v2_state_file]

If v2_state_file is not specified, saves to reconciliation_state_v2.json
in the same directory as the v1 file.
"""

import sys
import os

# Add the code directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reconciliation_system import migrate_v1_state


def main():
    if len(sys.argv) < 2:
        print("Usage: python migrate_v1_to_v2.py <v1_state_file> [v2_state_file]")
        print()
        print("Converts a v1 reconciliation_state.json to v2 format.")
        print("Confirmed matches -> reconciled, manually resolved carried over.")
        print("Rejected matches are ignored (not relevant in v2).")
        sys.exit(1)

    v1_path = sys.argv[1]
    if not os.path.exists(v1_path):
        print(f"Error: v1 state file not found: {v1_path}")
        sys.exit(1)

    if len(sys.argv) > 2:
        v2_path = sys.argv[2]
    else:
        v2_path = os.path.join(os.path.dirname(v1_path), "reconciliation_state_v2.json")

    if os.path.exists(v2_path):
        response = input(f"v2 state file already exists: {v2_path}\nOverwrite? (y/n): ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    count = migrate_v1_state(v1_path, v2_path)
    print(f"Done. Output: {v2_path}")


if __name__ == "__main__":
    main()
