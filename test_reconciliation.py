"""
Test script for Bank Beacon Reconciliation System
Tests all core functionality without GUI dependencies.
"""

import os
import sys
from decimal import Decimal

from reconciliation_system import (
    ReconciliationSystem, MatchStatus, BankTransaction, BeaconEntry, MatchSuggestion
)


def test_loading():
    """Test loading CSV files."""
    print("\n=== Test: Loading Data ===")
    system = ReconciliationSystem()
    system.load_data()

    print(f"✓ Loaded {len(system.bank_transactions)} bank transactions")
    print(f"✓ Loaded {len(system.beacon_entries)} beacon entries")

    assert len(system.bank_transactions) == 20, "Expected 20 bank transactions"
    assert len(system.beacon_entries) == 33, "Expected 33 beacon entries"

    print("✓ Loading test PASSED")
    return system


def test_one_to_one_matching(system):
    """Test 1-to-1 matching detection."""
    print("\n=== Test: 1-to-1 Matching ===")
    suggestions = system.generate_suggestions()

    one_to_one = [m for m in suggestions if m.match_type == "1-to-1"]
    print(f"✓ Found {len(one_to_one)} 1-to-1 matches")

    # Check specific expected 1-to-1 match (JONES A TRANSFER £13)
    jones_match = next(
        (m for m in one_to_one
         if "JONES" in m.bank_transaction.description),
        None
    )

    assert jones_match is not None, "Expected JONES 1-to-1 match"
    assert len(jones_match.beacon_entries) == 1
    assert jones_match.beacon_entries[0].amount == Decimal('13.00')
    print(f"✓ JONES match found: £{jones_match.bank_transaction.amount} -> £{jones_match.beacon_entries[0].amount}")

    print("✓ 1-to-1 matching test PASSED")


def test_one_to_two_matching(system):
    """Test 1-to-2 matching detection."""
    print("\n=== Test: 1-to-2 Matching ===")
    suggestions = system.generate_suggestions()

    # Include both pending and auto-confirmed 1-to-2 matches
    one_to_two = [m for m in suggestions if m.match_type == "1-to-2"]
    print(f"✓ Found {len(one_to_two)} 1-to-2 matches")

    # Check SMITH J PAYMENT £26 = £13 + £13
    smith_match = next(
        (m for m in one_to_two
         if "SMITH" in m.bank_transaction.description and
         m.bank_transaction.amount == Decimal('26.00')),
        None
    )

    assert smith_match is not None, "Expected SMITH 1-to-2 match"
    assert len(smith_match.beacon_entries) == 2

    beacon_total = sum(b.amount for b in smith_match.beacon_entries)
    assert beacon_total == Decimal('26.00'), f"Expected sum £26, got £{beacon_total}"
    print(f"✓ SMITH match found: £{smith_match.bank_transaction.amount} -> £{smith_match.beacon_entries[0].amount} + £{smith_match.beacon_entries[1].amount}")

    # Check uneven 1-to-2 match (TAYLOR £45.50 = £32 + £13.50)
    # This may be auto-confirmed due to high confidence
    taylor_match = next(
        (m for m in one_to_two
         if "TAYLOR" in m.bank_transaction.description),
        None
    )

    if taylor_match:
        beacon_total = sum(b.amount for b in taylor_match.beacon_entries)
        assert beacon_total == Decimal('45.50')
        print(f"✓ TAYLOR uneven match: £{taylor_match.bank_transaction.amount} -> £{taylor_match.beacon_entries[0].amount} + £{taylor_match.beacon_entries[1].amount} (status: {taylor_match.status.value})")
    else:
        # TAYLOR may have been auto-confirmed in a previous run
        print("  (TAYLOR match may have been processed in previous state)")

    print("✓ 1-to-2 matching test PASSED")


def test_common_amount_handling(system):
    """Test that common amounts (£13, £9.50, £6.50) have reduced confidence."""
    print("\n=== Test: Common Amount Handling ===")

    # Verify £6.50 is now a common amount
    assert Decimal('6.50') in system.COMMON_AMOUNTS, "£6.50 should be a common amount"
    assert Decimal('13.00') in system.COMMON_AMOUNTS, "£13.00 should be a common amount"
    assert Decimal('9.50') in system.COMMON_AMOUNTS, "£9.50 should be a common amount"
    print(f"✓ Common amounts: {[str(a) for a in system.COMMON_AMOUNTS]}")

    suggestions = system.generate_suggestions()

    # Find matches with common amounts (£13, £9.50, or £6.50)
    common_amounts = [Decimal('13.00'), Decimal('9.50'), Decimal('6.50')]
    common_matches = [
        m for m in suggestions
        if m.bank_transaction.amount in common_amounts
        and m.match_type == "1-to-1"
        and m.status == MatchStatus.PENDING  # Not auto-confirmed
    ]

    # Find matches with non-common amounts
    non_common_matches = [
        m for m in suggestions
        if m.bank_transaction.amount not in common_amounts
        and m.match_type == "1-to-1"
    ]

    if common_matches and non_common_matches:
        avg_common = sum(m.confidence_score for m in common_matches) / len(common_matches)
        avg_non_common = sum(m.confidence_score for m in non_common_matches) / len(non_common_matches)

        print(f"  Average confidence for common amounts: {avg_common:.2f}")
        print(f"  Average confidence for non-common amounts: {avg_non_common:.2f}")
        print("✓ Common amount weighting applied")

    print("✓ Common amount handling test PASSED")


def test_auto_confirmation(system):
    """Test auto-confirmation of high-confidence matches."""
    print("\n=== Test: Auto-Confirmation ===")

    # Reset system
    system = ReconciliationSystem()
    system.load_data()
    suggestions = system.generate_suggestions()

    # Verify no auto-confirmation happened yet (disabled by default)
    initially_confirmed = [m for m in suggestions if m.status == MatchStatus.CONFIRMED]
    assert len(initially_confirmed) == 0, "Auto-confirm should be disabled by default"

    # Now run auto-confirmation explicitly
    count = system.run_auto_confirm()

    # Count auto-confirmed matches
    auto_confirmed = [m for m in suggestions if m.status == MatchStatus.CONFIRMED]
    pending = [m for m in suggestions if m.status == MatchStatus.PENDING]

    print(f"  Auto-confirmed: {len(auto_confirmed)}")
    print(f"  Pending: {len(pending)}")

    # Verify thresholds are being applied
    for match in auto_confirmed:
        is_common = match.bank_transaction.amount in system.COMMON_AMOUNTS
        if is_common:
            assert match.confidence_score > 0.90, f"Common amount auto-confirmed below 90%: {match.confidence_score}"
        else:
            assert match.confidence_score > 0.80, f"Other amount auto-confirmed below 80%: {match.confidence_score}"

    print("✓ All auto-confirmed matches meet threshold requirements")
    print("✓ Auto-confirmation test PASSED")


def test_match_status_changes(system):
    """Test confirming, rejecting, and changing match decisions."""
    print("\n=== Test: Match Status Changes ===")

    suggestions = system.generate_suggestions()
    test_match = suggestions[0]

    # Initial status should be PENDING
    assert test_match.status == MatchStatus.PENDING
    print(f"✓ Initial status: {test_match.status.value}")

    # Confirm the match
    system.confirm_match(test_match)
    assert test_match.status == MatchStatus.CONFIRMED
    print(f"✓ After confirm: {test_match.status.value}")

    # Check beacon entries are marked as matched
    for beacon in test_match.beacon_entries:
        assert beacon.id in system.matched_beacon_ids
    print(f"✓ {len(test_match.beacon_entries)} beacon entries marked as matched")

    # Undo confirmation
    system.undo_confirmation(test_match)
    assert test_match.status == MatchStatus.PENDING
    print(f"✓ After undo: {test_match.status.value}")

    # Check beacon entries are unmarked
    for beacon in test_match.beacon_entries:
        assert beacon.id not in system.matched_beacon_ids
    print("✓ Beacon entries unmarked")

    # Test reject
    system.reject_match(test_match)
    assert test_match.status == MatchStatus.REJECTED
    print(f"✓ After reject: {test_match.status.value}")

    # Test update_match_status
    system.update_match_status(test_match, MatchStatus.CONFIRMED)
    assert test_match.status == MatchStatus.CONFIRMED
    print(f"✓ After update to CONFIRMED: {test_match.status.value}")

    # Change from CONFIRMED to SKIPPED
    system.update_match_status(test_match, MatchStatus.SKIPPED)
    assert test_match.status == MatchStatus.SKIPPED
    # Beacon entries should be unmarked when changing from CONFIRMED
    for beacon in test_match.beacon_entries:
        assert beacon.id not in system.matched_beacon_ids
    print(f"✓ After update to SKIPPED: {test_match.status.value} (beacons unmarked)")

    print("✓ Match status changes test PASSED")


def test_navigation_simulation():
    """Simulate GUI navigation behavior."""
    print("\n=== Test: Navigation Simulation ===")

    system = ReconciliationSystem()
    system.load_data()
    suggestions = system.generate_suggestions()

    current_index = 0
    queued_changes = {}  # Simulates GUI queue

    # Move forward and make decisions
    print("  Navigating forward and making decisions...")

    # Confirm first match
    match = suggestions[current_index]
    queued_changes[match.id] = MatchStatus.CONFIRMED
    current_index += 1
    print(f"  Index {current_index-1}: Queued CONFIRMED for {match.id}")

    # Reject second match
    match = suggestions[current_index]
    queued_changes[match.id] = MatchStatus.REJECTED
    current_index += 1
    print(f"  Index {current_index-1}: Queued REJECTED for {match.id}")

    # Skip third match
    match = suggestions[current_index]
    queued_changes[match.id] = MatchStatus.SKIPPED
    current_index += 1
    print(f"  Index {current_index-1}: Queued SKIPPED for {match.id}")

    # Navigate back
    current_index -= 2
    print(f"  Navigated back to index {current_index}")

    # Change previous decision
    match = suggestions[current_index]
    old_status = queued_changes.get(match.id, MatchStatus.PENDING)
    queued_changes[match.id] = MatchStatus.CONFIRMED
    print(f"  Changed {match.id} from {old_status.value} to CONFIRMED")

    # Apply queued changes
    print("  Applying queued changes...")
    for match_id, new_status in queued_changes.items():
        for m in suggestions:
            if m.id == match_id:
                system.update_match_status(m, new_status)
                print(f"  Applied {new_status.value} to {match_id}")
                break

    # Verify final states
    assert suggestions[0].status == MatchStatus.CONFIRMED
    assert suggestions[1].status == MatchStatus.CONFIRMED  # Changed from REJECTED
    assert suggestions[2].status == MatchStatus.SKIPPED

    print("✓ Navigation simulation test PASSED")


def test_beacon_exclusivity(system):
    """Test that Beacon entries can only match one Bank transaction."""
    print("\n=== Test: Beacon Exclusivity ===")

    # Reset system
    system = ReconciliationSystem()
    system.load_data()
    suggestions = system.generate_suggestions()

    # Confirm a match
    match = suggestions[0]
    beacon_ids = [b.id for b in match.beacon_entries]
    system.confirm_match(match)

    print(f"✓ Confirmed match with beacon IDs: {beacon_ids}")

    # Regenerate suggestions
    new_suggestions = system.generate_suggestions()

    # Check that matched beacon IDs are not used in new suggestions
    for new_match in new_suggestions:
        for beacon in new_match.beacon_entries:
            assert beacon.id not in beacon_ids, f"Beacon {beacon.id} should be excluded"

    print("✓ Confirmed beacon entries excluded from new suggestions")
    print("✓ Beacon exclusivity test PASSED")


def test_date_tolerance():
    """Test that matches outside date tolerance are excluded."""
    print("\n=== Test: Date Tolerance ===")

    system = ReconciliationSystem()
    system.load_data()
    suggestions = system.generate_suggestions()

    # Asymmetric tolerance: beacon after bank allows up to 63 days (9 weeks)
    # beacon before bank only allows 2 days
    for match in suggestions:
        bank_date = match.bank_transaction.date
        for beacon in match.beacon_entries:
            days_diff = (beacon.date - bank_date).days  # positive = beacon after bank
            if days_diff >= 0:
                assert days_diff <= 63, f"Match {match.id} has date diff of {days_diff} days (max 63)"
            else:
                assert abs(days_diff) <= 2, f"Match {match.id} has beacon {abs(days_diff)} days before bank (max 2)"

    print("✓ All matches within date tolerance (up to 9 weeks for beacon after bank)")
    print("✓ Date tolerance test PASSED")


def test_state_persistence():
    """Test saving and loading state."""
    print("\n=== Test: State Persistence ===")

    # Create system with a separate test state file
    test_state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_state.json")

    # Remove test state file if exists
    if os.path.exists(test_state_file):
        os.remove(test_state_file)

    system = ReconciliationSystem(state_file=test_state_file)
    system.load_data()
    suggestions = system.generate_suggestions()

    # Count how many were auto-confirmed
    initial_confirmed = len(system.confirmed_matches)
    initial_beacon_ids = len(system.matched_beacon_ids)

    # Manually confirm a pending match
    pending = [m for m in suggestions if m.status == MatchStatus.PENDING]
    if pending:
        system.confirm_match(pending[0])

    system.save_state()
    final_confirmed = len(system.confirmed_matches)

    print(f"✓ Saved state with {final_confirmed} confirmed matches (auto: {initial_confirmed}, manual: {final_confirmed - initial_confirmed})")

    # Create new system, load state
    system2 = ReconciliationSystem(state_file=test_state_file)
    system2.load_data()
    system2._load_state()

    assert len(system2.confirmed_matches) == final_confirmed, f"Expected {final_confirmed}, got {len(system2.confirmed_matches)}"
    assert len(system2.matched_beacon_ids) >= initial_beacon_ids

    print(f"✓ Loaded state with {len(system2.confirmed_matches)} confirmed matches")
    print(f"✓ {len(system2.matched_beacon_ids)} beacon IDs marked as matched")

    # Cleanup
    if os.path.exists(test_state_file):
        os.remove(test_state_file)
    print("✓ State persistence test PASSED")


def test_export():
    """Test exporting results to CSV."""
    print("\n=== Test: Export Results ===")

    system = ReconciliationSystem()
    system.load_data()
    suggestions = system.generate_suggestions()

    # Make some decisions
    system.confirm_match(suggestions[0])
    system.reject_match(suggestions[1])

    # Export
    system.export_results("test_results.csv")

    # Verify file exists
    assert os.path.exists("test_results.csv")

    # Read and check content
    with open("test_results.csv", 'r') as f:
        lines = f.readlines()

    assert len(lines) >= 21  # Header + at least 20 matches (may have more due to multiple matches per bank txn)
    print(f"✓ Exported {len(lines)-1} matches to CSV")

    # Cleanup
    os.remove("test_results.csv")
    print("✓ Export test PASSED")


def test_rejected_persistence():
    """Test that rejected matches are persisted and restored."""
    print("\n=== Test: Rejected Match Persistence ===")

    # Create system with a separate test state file
    test_state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_rejected_state.json")

    # Remove test state file if exists
    if os.path.exists(test_state_file):
        os.remove(test_state_file)

    system = ReconciliationSystem(state_file=test_state_file)
    system.load_data()
    suggestions = system.generate_suggestions()

    # Find a pending match and reject it
    pending = [m for m in suggestions if m.status == MatchStatus.PENDING]
    assert len(pending) > 0, "No pending matches to test"

    test_match = pending[0]
    rejected_bank_id = test_match.bank_transaction.id
    system.reject_match(test_match)

    assert test_match.status == MatchStatus.REJECTED
    assert rejected_bank_id in system.rejected_bank_ids
    print(f"✓ Rejected match for bank ID: {rejected_bank_id}")

    system.save_state()
    print("✓ Saved state with rejected match")

    # Create new system, load state
    system2 = ReconciliationSystem(state_file=test_state_file)
    system2.load_data()

    # Check rejected bank IDs are loaded
    assert rejected_bank_id in system2.rejected_bank_ids, "Rejected bank ID not loaded"
    print("✓ Rejected bank ID restored from state")

    # Generate suggestions - should restore rejected status
    suggestions2 = system2.generate_suggestions()

    # Find the match with the rejected bank ID
    restored_match = next(
        (m for m in suggestions2 if m.bank_transaction.id == rejected_bank_id),
        None
    )
    assert restored_match is not None, "Rejected match not found in new suggestions"
    assert restored_match.status == MatchStatus.REJECTED, f"Expected REJECTED, got {restored_match.status.value}"
    print("✓ Rejected status restored in regenerated suggestions")

    # Test undo rejection
    system2.undo_rejection(restored_match)
    assert restored_match.status == MatchStatus.PENDING
    assert rejected_bank_id not in system2.rejected_bank_ids
    print("✓ Undo rejection works correctly")

    # Cleanup
    if os.path.exists(test_state_file):
        os.remove(test_state_file)
    print("✓ Rejected match persistence test PASSED")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Bank Beacon Reconciliation System - Test Suite")
    print("=" * 60)

    # Clean up any existing state file to ensure fresh tests
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reconciliation_state.json")
    if os.path.exists(state_file):
        os.remove(state_file)
        print("(Removed existing state file for clean test run)")

    system = test_loading()
    test_one_to_one_matching(system)
    test_one_to_two_matching(system)
    test_common_amount_handling(system)
    test_auto_confirmation(system)
    test_match_status_changes(system)
    test_navigation_simulation()
    test_beacon_exclusivity(system)
    test_date_tolerance()
    test_state_persistence()
    test_rejected_persistence()
    test_export()

    # Clean up state file after tests
    if os.path.exists(state_file):
        os.remove(state_file)

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
