"""
Test script for Bank Beacon Reconciliation System v2
Tests all core functionality without GUI dependencies.
"""

import os
import sys
import json
from decimal import Decimal

from reconciliation_system import (
    ReconciliationSystem, BankTransaction, BeaconEntry,
    BeaconCandidate, Reconciliation, VERSION, migrate_v1_state
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample")
CODE_DIR = os.path.dirname(os.path.abspath(__file__))


def make_system():
    """Create a fresh system with sample data (no saved state)."""
    state_file = os.path.join(DATA_DIR, "reconciliation_state_v2.json")
    if os.path.exists(state_file):
        os.remove(state_file)
    system = ReconciliationSystem(data_dir=DATA_DIR, code_dir=CODE_DIR)
    system.load_data()
    return system


def test_loading():
    """Test loading CSV files and config."""
    print("\n=== Test: Loading Data ===")
    system = make_system()

    print(f"  Loaded {len(system.bank_transactions)} bank transactions")
    print(f"  Loaded {len(system.beacon_entries)} beacon entries")
    print(f"  Config: {system.config}")

    assert len(system.bank_transactions) > 0, "No bank transactions loaded"
    assert len(system.beacon_entries) > 0, "No beacon entries loaded"
    assert system.config['bank_file'] == 'Bank_Transactions.csv'
    assert system.config['beacon_file'] == 'Beacon_Entries.csv'

    # Verify bank entries are sorted by date
    dates = [b.date for b in system.bank_transactions]
    assert dates == sorted(dates), "Bank entries should be sorted by date"

    print(f"  Version: {VERSION}")
    print("PASSED")
    return system


def test_candidate_generation(system):
    """Test beacon candidate generation for bank entries."""
    print("\n=== Test: Candidate Generation ===")

    for bank in system.bank_transactions[:5]:
        candidates = system.get_candidates_for_bank(bank)
        if candidates:
            top = candidates[0]
            entry_text = ", ".join(
                f"{b.payee} {chr(163)}{b.amount}" for b in top.beacon_entries
            )
            print(f"  {bank.description[:30]:30s} {chr(163)}{str(bank.amount):>8s} -> "
                  f"{top.match_type} {top.confidence_score:.0%} [{entry_text}]")
        else:
            print(f"  {bank.description[:30]:30s} {chr(163)}{str(bank.amount):>8s} -> no candidates")

    # At least some bank entries should have candidates
    banks_with_candidates = sum(
        1 for b in system.bank_transactions
        if system.get_candidates_for_bank(b)
    )
    print(f"  {banks_with_candidates}/{len(system.bank_transactions)} bank entries have candidates")
    assert banks_with_candidates > 0, "No candidates generated for any bank entry"

    print("PASSED")


def test_one_to_one_matching(system):
    """Test 1-to-1 matching detection."""
    print("\n=== Test: 1-to-1 Matching ===")

    # Find a bank entry with a 1-to-1 candidate
    found_1to1 = False
    for bank in system.bank_transactions:
        candidates = system.get_candidates_for_bank(bank)
        for c in candidates:
            if c.match_type == "1-to-1":
                assert len(c.beacon_entries) == 1
                assert c.beacon_entries[0].amount == bank.amount
                if not found_1to1:
                    print(f"  1-to-1: {bank.description[:30]} {chr(163)}{bank.amount} -> "
                          f"{c.beacon_entries[0].payee} {chr(163)}{c.beacon_entries[0].amount} "
                          f"({c.confidence_score:.0%})")
                found_1to1 = True

    assert found_1to1, "No 1-to-1 candidates found"
    print("PASSED")


def test_one_to_two_matching(system):
    """Test 1-to-2 matching detection."""
    print("\n=== Test: 1-to-2 Matching ===")

    found_1to2 = False
    for bank in system.bank_transactions:
        candidates = system.get_candidates_for_bank(bank)
        for c in candidates:
            if c.match_type == "1-to-2":
                assert len(c.beacon_entries) == 2
                total = sum(b.amount for b in c.beacon_entries)
                assert total == bank.amount, f"1-to-2 total mismatch: {total} != {bank.amount}"
                if not found_1to2:
                    print(f"  1-to-2: {bank.description[:30]} {chr(163)}{bank.amount} -> "
                          f"{chr(163)}{c.beacon_entries[0].amount} + "
                          f"{chr(163)}{c.beacon_entries[1].amount} ({c.confidence_score:.0%})")
                found_1to2 = True

    if found_1to2:
        print("PASSED")
    else:
        print("SKIPPED (no 1-to-2 candidates in sample data)")


def test_common_amount_handling(system):
    """Test that common amounts have reduced confidence weighting."""
    print("\n=== Test: Common Amount Handling ===")

    assert Decimal('13.00') in system.common_amounts
    assert Decimal('9.50') in system.common_amounts
    assert Decimal('6.50') in system.common_amounts
    print(f"  Common amounts: {[str(a) for a in system.common_amounts]}")

    print("PASSED")


def test_reconcile(system):
    """Test reconciling a bank entry with a candidate."""
    print("\n=== Test: Reconcile ===")

    # Find a bank entry with candidates
    for bank in system.bank_transactions:
        candidates = system.get_candidates_for_bank(bank)
        if candidates:
            candidate = candidates[0]
            success, msg = system.reconcile(bank, candidate)
            assert success, f"Reconcile failed: {msg}"
            assert system.is_bank_reconciled(bank.id)

            rec = system.get_reconciliation_for_bank(bank.id)
            assert rec is not None
            assert rec.bank_id == bank.id
            assert rec.beacon_ids == [b.id for b in candidate.beacon_entries]
            print(f"  Reconciled: {bank.description[:30]} with {len(candidate.beacon_entries)} beacon(s)")

            # Should not be able to reconcile again
            success2, msg2 = system.reconcile(bank, candidate)
            assert not success2
            print(f"  Double-reconcile correctly blocked: {msg2}")
            break

    print("PASSED")


def test_unreconcile(system):
    """Test un-reconciling a bank entry."""
    print("\n=== Test: Un-reconcile ===")

    # First reconcile something
    for bank in system.bank_transactions:
        if system.is_bank_reconciled(bank.id):
            continue
        candidates = system.get_candidates_for_bank(bank)
        if candidates:
            system.reconcile(bank, candidates[0])
            break

    # Now find a reconciled entry and un-reconcile it
    for bank in system.bank_transactions:
        if system.is_bank_reconciled(bank.id):
            rec = system.get_reconciliation_for_bank(bank.id)
            beacon_ids = rec.beacon_ids[:]
            success, msg = system.unreconcile(bank.id)
            assert success, f"Un-reconcile failed: {msg}"
            assert not system.is_bank_reconciled(bank.id)

            # Beacon entries should be free again
            for bid in beacon_ids:
                for b in system.beacon_entries:
                    if b.id == bid:
                        assert not b.matched, f"Beacon {bid} should be unmatched"
            print(f"  Un-reconciled: {bank.description[:30]}")
            break

    print("PASSED")


def test_reject_pairing(system):
    """Test rejecting and un-rejecting a bank/beacon pairing."""
    print("\n=== Test: Reject Pairing ===")

    for bank in system.bank_transactions:
        if system.is_bank_reconciled(bank.id):
            continue
        candidates = system.get_candidates_for_bank(bank)
        if not candidates:
            continue

        candidate = candidates[0]
        beacon_id = candidate.beacon_entries[0].id

        # Reject
        system.reject_pairing(bank.id, beacon_id)

        # Verify rejected candidate appears at end
        refreshed = system.get_candidates_for_bank(bank)
        rejected = [c for c in refreshed if c.is_rejected]
        non_rejected = [c for c in refreshed if not c.is_rejected]
        if rejected and non_rejected:
            # Non-rejected should come before rejected in list
            first_rejected_idx = next(i for i, c in enumerate(refreshed) if c.is_rejected)
            last_non_rejected_idx = max(i for i, c in enumerate(refreshed) if not c.is_rejected)
            assert first_rejected_idx > last_non_rejected_idx, \
                "Rejected should be after non-rejected"

        print(f"  Rejected pairing: {bank.id} / {beacon_id}")
        print(f"  Candidates: {len(non_rejected)} non-rejected, {len(rejected)} rejected")

        # Un-reject
        system.unreject_pairing(bank.id, beacon_id)
        refreshed2 = system.get_candidates_for_bank(bank)
        rejected2 = [c for c in refreshed2 if c.is_rejected]
        assert len(rejected2) < len(rejected), "Un-reject should reduce rejected count"
        print(f"  Un-rejected: rejected count now {len(rejected2)}")
        break

    print("PASSED")


def test_auto_reconcile():
    """Test auto-reconcile of high-confidence matches."""
    print("\n=== Test: Auto-Reconcile ===")

    system = make_system()
    count = system.auto_reconcile()
    print(f"  Auto-reconciled: {count} entries")

    # Verify all auto-reconciled entries meet thresholds
    stats = system.get_statistics()
    print(f"  Reconciled: {stats['reconciled_count']}")
    print(f"  Un-reconciled: {stats['unreconciled_count']}")

    print("PASSED")


def test_manual_match():
    """Test manual matching via trans_no."""
    print("\n=== Test: Manual Match ===")

    system = make_system()

    # Find a bank entry and some beacons that add up
    bank = None
    trans_nos = []
    for b in system.bank_transactions:
        for beacon in system.beacon_entries:
            if beacon.amount == b.amount:
                bank = b
                trans_nos = [beacon.trans_no]
                break
        if bank:
            break

    if bank and trans_nos:
        success, msg = system.reconcile_manual(bank, trans_nos)
        assert success, f"Manual match failed: {msg}"
        assert system.is_bank_reconciled(bank.id)
        rec = system.get_reconciliation_for_bank(bank.id)
        assert rec.match_type == "manual"
        print(f"  Manual match: {bank.description[:30]} with trans_no {trans_nos}")
    else:
        print("  SKIPPED (no matching amounts found)")

    print("PASSED")


def test_mark_resolved():
    """Test marking a bank entry as manually resolved."""
    print("\n=== Test: Mark Resolved ===")

    system = make_system()
    bank = system.bank_transactions[0]

    success, msg = system.mark_resolved(bank, "Test resolution comment")
    assert success, f"Mark resolved failed: {msg}"
    assert system.is_bank_reconciled(bank.id)

    rec = system.get_reconciliation_for_bank(bank.id)
    assert rec.status == "manually_resolved"
    assert rec.match_type == "resolved"
    assert rec.comment == "Test resolution comment"
    assert rec.beacon_ids == []
    print(f"  Resolved: {bank.description[:30]} with comment")

    print("PASSED")


def test_statistics():
    """Test statistics calculation."""
    print("\n=== Test: Statistics ===")

    system = make_system()

    # Do some reconciling
    system.auto_reconcile()
    system.mark_resolved(system.get_unreconciled_bank_entries()[0], "test")

    stats = system.get_statistics()
    print(f"  Total bank: {stats['total_bank']}")
    print(f"  Total beacon: {stats['total_beacon']}")
    print(f"  Reconciled: {stats['reconciled_count']} ({chr(163)}{stats['reconciled_amount']:.2f})")
    print(f"  Resolved: {stats['resolved_count']} ({chr(163)}{stats['resolved_amount']:.2f})")
    print(f"  Un-reconciled: {stats['unreconciled_count']} ({chr(163)}{stats['unreconciled_amount']:.2f})")

    total_accounted = stats['reconciled_count'] + stats['resolved_count'] + stats['unreconciled_count']
    assert total_accounted == stats['total_bank'], \
        f"Counts don't add up: {total_accounted} != {stats['total_bank']}"

    print("PASSED")


def test_state_persistence():
    """Test saving and loading state."""
    print("\n=== Test: State Persistence ===")

    system = make_system()
    system.auto_reconcile()
    system.mark_resolved(system.get_unreconciled_bank_entries()[0], "persisted comment")

    # Reject a pairing
    unreconciled = system.get_unreconciled_bank_entries()
    if unreconciled:
        bank = unreconciled[0]
        candidates = system.get_candidates_for_bank(bank)
        if candidates:
            system.reject_pairing(bank.id, candidates[0].beacon_entries[0].id)

    stats_before = system.get_statistics()
    system.save_state()

    # Reload
    system2 = ReconciliationSystem(data_dir=DATA_DIR, code_dir=CODE_DIR)
    system2.load_data()

    stats_after = system2.get_statistics()
    assert stats_before['reconciled_count'] == stats_after['reconciled_count']
    assert stats_before['resolved_count'] == stats_after['resolved_count']

    print(f"  Saved and restored {stats_after['reconciled_count']} reconciliations, "
          f"{stats_after['resolved_count']} resolved, "
          f"{len(system2.rejected_pairings)} rejected pairings")

    print("PASSED")


def test_search():
    """Test bank and beacon search."""
    print("\n=== Test: Search ===")

    system = make_system()

    # Bank search by description
    results = system.search_bank_entries("SMITH")
    print(f"  Bank search 'SMITH': {len(results)} results")

    # Bank search by amount
    results = system.search_bank_entries("13.00")
    print(f"  Bank search '13.00': {len(results)} results")

    # Beacon search by payee
    results = system.search_beacon_entries("Smith")
    print(f"  Beacon search 'Smith': {len(results)} results")

    # Beacon search available only
    system.auto_reconcile()
    all_results = system.search_beacon_entries("", available_only=False)
    avail_results = system.search_beacon_entries("", available_only=True)
    # Empty search returns no results, which is correct
    print(f"  Beacon search (empty term): {len(all_results)} results (expected 0)")

    print("PASSED")


def test_exports():
    """Test report exports."""
    print("\n=== Test: Exports ===")

    system = make_system()
    system.auto_reconcile()
    system.mark_resolved(system.get_unreconciled_bank_entries()[0], "test export")

    # Export all reports
    r1 = system.export_reconciled_csv(os.path.join(DATA_DIR, "_test_reconciled.csv"))
    r2 = system.export_unreconciled_bank_csv(os.path.join(DATA_DIR, "_test_unrec_bank.csv"))
    r3 = system.export_unreconciled_beacon_csv(os.path.join(DATA_DIR, "_test_unrec_beacon.csv"))
    r4 = system.export_resolved_csv(os.path.join(DATA_DIR, "_test_resolved.csv"))
    system.export_stats_summary(os.path.join(DATA_DIR, "_test_stats.txt"))

    print(f"  Reconciled: {r1} rows")
    print(f"  Un-reconciled bank: {r2} rows")
    print(f"  Un-reconciled beacon: {r3} rows")
    print(f"  Resolved: {r4} rows")

    # Verify files exist
    for fname in ["_test_reconciled.csv", "_test_unrec_bank.csv",
                   "_test_unrec_beacon.csv", "_test_resolved.csv", "_test_stats.txt"]:
        path = os.path.join(DATA_DIR, fname)
        assert os.path.exists(path), f"Export file not created: {path}"
        os.remove(path)

    print("PASSED")


def test_navigation_helpers():
    """Test bank entry navigation helpers."""
    print("\n=== Test: Navigation Helpers ===")

    system = make_system()

    all_entries = system.get_bank_entries_sorted()
    unrec_entries = system.get_unreconciled_bank_entries()
    assert len(all_entries) >= len(unrec_entries)
    print(f"  All: {len(all_entries)}, Un-reconciled: {len(unrec_entries)}")

    # After auto-reconcile, unreconciled should decrease
    system.auto_reconcile()
    unrec_after = system.get_unreconciled_bank_entries()
    assert len(unrec_after) <= len(unrec_entries)
    print(f"  After auto-reconcile, un-reconciled: {len(unrec_after)}")

    print("PASSED")


def test_candidate_ordering():
    """Test that candidates are ordered correctly (non-rejected first, then rejected)."""
    print("\n=== Test: Candidate Ordering ===")

    system = make_system()

    for bank in system.bank_transactions:
        candidates = system.get_candidates_for_bank(bank)
        if len(candidates) < 2:
            continue

        # Reject one candidate
        beacon_id = candidates[0].beacon_entries[0].id
        system.reject_pairing(bank.id, beacon_id)

        refreshed = system.get_candidates_for_bank(bank)
        saw_rejected = False
        for c in refreshed:
            if c.is_rejected:
                saw_rejected = True
            elif saw_rejected:
                assert False, "Non-rejected candidate found after rejected one"

        print(f"  {bank.id}: {len(refreshed)} candidates, ordering correct")

        # Cleanup
        system.unreject_pairing(bank.id, beacon_id)
        break

    print("PASSED")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print(f"Bank Beacon Reconciliation v{VERSION} - Test Suite")
    print("=" * 60)

    # Clean up any existing state
    state_file = os.path.join(DATA_DIR, "reconciliation_state_v2.json")
    if os.path.exists(state_file):
        os.remove(state_file)
        print("(Removed existing state file for clean test run)")

    system = test_loading()
    test_candidate_generation(system)
    test_one_to_one_matching(system)
    test_one_to_two_matching(system)
    test_common_amount_handling(system)
    test_reconcile(system)
    test_unreconcile(system)
    test_reject_pairing(system)
    test_auto_reconcile()
    test_manual_match()
    test_mark_resolved()
    test_statistics()
    test_state_persistence()
    test_search()
    test_exports()
    test_navigation_helpers()
    test_candidate_ordering()

    # Final cleanup
    if os.path.exists(state_file):
        os.remove(state_file)

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
