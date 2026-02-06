#!/usr/bin/env python3
"""
Validator for reconciliation_state.json

Checks for:
1. Duplicate Match IDs (and reports if duplicates have identical or different data)
2. Orphaned Beacon IDs (IDs in matched_beacon_ids with no corresponding confirmed match)
3. Wrong Status in confirmed_matches (should only be confirmed, manual_match, or manually_resolved)
4. Inconsistent matched flag (beacon entries in confirmed_matches should have matched=true)

Usage: python validate_reconciliation_state.py [path_to_json_file]
       If no path provided, looks for reconciliation_state.json in current directory

Output: Console output + validation_report.txt in current directory
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict


class ValidationError:
    """Represents a single validation error with suggested fix."""

    def __init__(self, error_type: str, message: str, location: str, suggestion: str, details: dict = None):
        self.error_type = error_type
        self.message = message
        self.location = location
        self.suggestion = suggestion
        self.details = details or {}

    def __str__(self):
        return f"[{self.error_type}] {self.message}\n  Location: {self.location}\n  Suggestion: {self.suggestion}"


class ReconciliationStateValidator:
    """Validates reconciliation_state.json files."""

    VALID_CONFIRMED_STATUSES = {"confirmed", "manual_match", "manually_resolved"}

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.data = None
        self.errors: list[ValidationError] = []

    def load(self) -> bool:
        """Load the JSON file. Returns True if successful."""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            return True
        except FileNotFoundError:
            print(f"ERROR: File not found: {self.file_path}")
            return False
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON syntax at line {e.lineno}, column {e.colno}: {e.msg}")
            return False

    def validate(self) -> list[ValidationError]:
        """Run all validation checks. Returns list of errors."""
        self.errors = []

        if self.data is None:
            return self.errors

        self._check_duplicate_match_ids()
        self._check_orphaned_beacon_ids()
        self._check_wrong_status_in_confirmed()
        self._check_inconsistent_matched_flag()

        return self.errors

    def _check_duplicate_match_ids(self):
        """Check for duplicate Match IDs across confirmed_matches and rejected_matches."""
        id_occurrences = defaultdict(list)

        # Collect all match IDs with their source and full data
        for idx, match in enumerate(self.data.get("confirmed_matches", [])):
            match_id = match.get("id", f"<missing_id_at_index_{idx}>")
            id_occurrences[match_id].append({
                "source": "confirmed_matches",
                "index": idx,
                "data": match
            })

        for idx, match in enumerate(self.data.get("rejected_matches", [])):
            match_id = match.get("id", f"<missing_id_at_index_{idx}>")
            id_occurrences[match_id].append({
                "source": "rejected_matches",
                "index": idx,
                "data": match
            })

        # Find duplicates
        for match_id, occurrences in id_occurrences.items():
            if len(occurrences) > 1:
                # Check if data is identical or different
                first_data = occurrences[0]["data"]
                all_identical = all(
                    self._compare_matches(first_data, occ["data"])
                    for occ in occurrences[1:]
                )

                locations = [f"{occ['source']}[{occ['index']}]" for occ in occurrences]

                if all_identical:
                    self.errors.append(ValidationError(
                        error_type="DUPLICATE_ID_IDENTICAL",
                        message=f"Match ID '{match_id}' appears {len(occurrences)} times with IDENTICAL data",
                        location=", ".join(locations),
                        suggestion=f"Remove all but one occurrence of '{match_id}'. Since data is identical, keep any one and delete the others.",
                        details={
                            "match_id": match_id,
                            "count": len(occurrences),
                            "occurrences": locations,
                            "data_identical": True
                        }
                    ))
                else:
                    # Find differences between occurrences
                    differences = self._describe_differences(occurrences)
                    self.errors.append(ValidationError(
                        error_type="DUPLICATE_ID_DIFFERENT",
                        message=f"Match ID '{match_id}' appears {len(occurrences)} times with DIFFERENT data",
                        location=", ".join(locations),
                        suggestion=f"Renumber duplicate IDs to make them unique. Assign new sequential IDs (e.g., MATCH_NNNN where NNNN is max existing + 1, +2, etc.)",
                        details={
                            "match_id": match_id,
                            "count": len(occurrences),
                            "occurrences": locations,
                            "data_identical": False,
                            "differences": differences
                        }
                    ))

    def _compare_matches(self, match1: dict, match2: dict) -> bool:
        """Compare two match objects for equality (ignoring id field)."""
        # Create copies without the id field for comparison
        m1 = {k: v for k, v in match1.items() if k != "id"}
        m2 = {k: v for k, v in match2.items() if k != "id"}
        return json.dumps(m1, sort_keys=True) == json.dumps(m2, sort_keys=True)

    def _describe_differences(self, occurrences: list[dict]) -> list[str]:
        """Describe the differences between duplicate occurrences."""
        differences = []
        first = occurrences[0]["data"]

        for i, occ in enumerate(occurrences[1:], start=1):
            other = occ["data"]
            diff_fields = []

            all_keys = set(first.keys()) | set(other.keys())
            for key in all_keys:
                if key == "id":
                    continue
                val1 = first.get(key)
                val2 = other.get(key)
                if json.dumps(val1, sort_keys=True) != json.dumps(val2, sort_keys=True):
                    diff_fields.append(key)

            if diff_fields:
                differences.append(f"Occurrence 0 vs {i}: differ in fields: {', '.join(diff_fields)}")

        return differences

    def _check_orphaned_beacon_ids(self):
        """Check that every ID in matched_beacon_ids has a corresponding beacon entry in confirmed_matches."""
        matched_beacon_ids = set(self.data.get("matched_beacon_ids", []))

        # Collect all beacon IDs actually present in confirmed_matches
        confirmed_beacon_ids = set()
        for match in self.data.get("confirmed_matches", []):
            for beacon in match.get("beacon_entries", []):
                beacon_id = beacon.get("id")
                if beacon_id:
                    confirmed_beacon_ids.add(beacon_id)

        # Find orphans
        orphaned = matched_beacon_ids - confirmed_beacon_ids

        for orphan_id in sorted(orphaned):
            self.errors.append(ValidationError(
                error_type="ORPHANED_BEACON_ID",
                message=f"Beacon ID '{orphan_id}' is in matched_beacon_ids but has no corresponding entry in confirmed_matches",
                location=f"matched_beacon_ids (contains '{orphan_id}')",
                suggestion=f"Remove '{orphan_id}' from matched_beacon_ids array, OR add the corresponding confirmed match that should reference this beacon.",
                details={
                    "beacon_id": orphan_id
                }
            ))

    def _check_wrong_status_in_confirmed(self):
        """Check that confirmed_matches only contains entries with valid statuses."""
        for idx, match in enumerate(self.data.get("confirmed_matches", [])):
            status = match.get("status", "<missing>")
            match_id = match.get("id", f"<no_id_at_index_{idx}>")

            if status not in self.VALID_CONFIRMED_STATUSES:
                self.errors.append(ValidationError(
                    error_type="WRONG_STATUS",
                    message=f"Match '{match_id}' has invalid status '{status}' in confirmed_matches",
                    location=f"confirmed_matches[{idx}] (id: {match_id})",
                    suggestion=f"Move this entry to rejected_matches if status is 'rejected', or remove it if status is 'pending' or 'skipped'. Valid statuses for confirmed_matches are: {', '.join(sorted(self.VALID_CONFIRMED_STATUSES))}",
                    details={
                        "match_id": match_id,
                        "index": idx,
                        "current_status": status,
                        "valid_statuses": list(self.VALID_CONFIRMED_STATUSES)
                    }
                ))

    def _check_inconsistent_matched_flag(self):
        """Check that all beacon entries in confirmed_matches have matched=true."""
        for match_idx, match in enumerate(self.data.get("confirmed_matches", [])):
            match_id = match.get("id", f"<no_id_at_index_{match_idx}>")

            for beacon_idx, beacon in enumerate(match.get("beacon_entries", [])):
                beacon_id = beacon.get("id", f"<no_id>")
                matched_flag = beacon.get("matched")

                if matched_flag is not True:
                    self.errors.append(ValidationError(
                        error_type="INCONSISTENT_MATCHED_FLAG",
                        message=f"Beacon entry '{beacon_id}' in confirmed match '{match_id}' has matched={matched_flag} (should be true)",
                        location=f"confirmed_matches[{match_idx}].beacon_entries[{beacon_idx}] (beacon_id: {beacon_id})",
                        suggestion=f"Change 'matched' to true for beacon entry '{beacon_id}' in match '{match_id}'",
                        details={
                            "match_id": match_id,
                            "match_index": match_idx,
                            "beacon_id": beacon_id,
                            "beacon_index": beacon_idx,
                            "current_value": matched_flag
                        }
                    ))

    def generate_report(self) -> str:
        """Generate a formatted report of all validation errors."""
        lines = []
        lines.append("=" * 80)
        lines.append("RECONCILIATION STATE VALIDATION REPORT")
        lines.append(f"File: {self.file_path}")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 80)
        lines.append("")

        if not self.errors:
            lines.append("No validation errors found. The file appears to be valid.")
            lines.append("")
            return "\n".join(lines)

        # Summary
        lines.append(f"SUMMARY: Found {len(self.errors)} error(s)")
        lines.append("")

        # Group errors by type
        errors_by_type = defaultdict(list)
        for error in self.errors:
            errors_by_type[error.error_type].append(error)

        lines.append("Errors by type:")
        for error_type, type_errors in sorted(errors_by_type.items()):
            lines.append(f"  - {error_type}: {len(type_errors)}")
        lines.append("")

        # Detailed errors
        lines.append("-" * 80)
        lines.append("DETAILED ERRORS")
        lines.append("-" * 80)
        lines.append("")

        for i, error in enumerate(self.errors, start=1):
            lines.append(f"Error #{i}: [{error.error_type}]")
            lines.append(f"  Message: {error.message}")
            lines.append(f"  Location: {error.location}")
            lines.append(f"  Suggestion: {error.suggestion}")

            # Add extra details for duplicate ID errors
            if error.error_type in ("DUPLICATE_ID_IDENTICAL", "DUPLICATE_ID_DIFFERENT"):
                if "differences" in error.details and error.details["differences"]:
                    lines.append("  Differences:")
                    for diff in error.details["differences"]:
                        lines.append(f"    - {diff}")

            lines.append("")

        # Fix instructions
        lines.append("-" * 80)
        lines.append("HOW TO FIX THESE ERRORS")
        lines.append("-" * 80)
        lines.append("")

        if "DUPLICATE_ID_IDENTICAL" in errors_by_type:
            lines.append("DUPLICATE_ID_IDENTICAL:")
            lines.append("  These are exact duplicate entries. Simply delete all but one copy.")
            lines.append("  Search for the match ID in your JSON file and remove duplicate objects.")
            lines.append("")

        if "DUPLICATE_ID_DIFFERENT" in errors_by_type:
            lines.append("DUPLICATE_ID_DIFFERENT:")
            lines.append("  These entries have the same ID but different data.")
            lines.append("  1. Find the highest MATCH_NNNN ID in your file")
            lines.append("  2. Renumber the duplicate entries with new sequential IDs")
            lines.append("  3. Example: if max ID is MATCH_0150, rename duplicates to MATCH_0151, MATCH_0152, etc.")
            lines.append("")

        if "ORPHANED_BEACON_ID" in errors_by_type:
            lines.append("ORPHANED_BEACON_ID:")
            lines.append("  These beacon IDs are marked as matched but have no confirmed match.")
            lines.append("  Option A: Remove the orphaned ID from the 'matched_beacon_ids' array")
            lines.append("  Option B: Restore/add the missing confirmed match that references this beacon")
            lines.append("")

        if "WRONG_STATUS" in errors_by_type:
            lines.append("WRONG_STATUS:")
            lines.append("  These entries in confirmed_matches have invalid status values.")
            lines.append("  - If status is 'rejected': move the entire object to 'rejected_matches' array")
            lines.append("  - If status is 'pending' or 'skipped': remove from confirmed_matches entirely")
            lines.append("  Valid statuses for confirmed_matches: confirmed, manual_match, manually_resolved")
            lines.append("")

        if "INCONSISTENT_MATCHED_FLAG" in errors_by_type:
            lines.append("INCONSISTENT_MATCHED_FLAG:")
            lines.append("  These beacon entries should have 'matched': true")
            lines.append("  Find each beacon entry and change '\"matched\": false' to '\"matched\": true'")
            lines.append("")

        return "\n".join(lines)


def main():
    # Determine file path
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = "reconciliation_state.json"

    print(f"Validating: {file_path}")
    print("")

    # Create validator and load file
    validator = ReconciliationStateValidator(file_path)

    if not validator.load():
        sys.exit(1)

    # Run validation
    errors = validator.validate()

    # Generate and display report
    report = validator.generate_report()
    print(report)

    # Save report to file
    report_path = Path("validation_report.txt")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"Report saved to: {report_path.absolute()}")

    # Exit with appropriate code
    if errors:
        print(f"\nValidation FAILED with {len(errors)} error(s)")
        sys.exit(1)
    else:
        print("\nValidation PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
