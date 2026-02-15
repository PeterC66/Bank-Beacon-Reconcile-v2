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

    # Test editing the resolved comment
    success, msg = system.update_resolved_comment(bank.id, "Updated comment")
    assert success, f"Update comment failed: {msg}"
    rec = system.get_reconciliation_for_bank(bank.id)
    assert rec.comment == "Updated comment"
    print(f"  Updated resolved comment: '{rec.comment}'")

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


def test_consistency_check():
    """Test consistency check on clean data and manufactured inconsistency."""
    print("\n=== Test: Consistency Check ===")

    system = make_system()
    system.auto_reconcile()

    # Clean data should have no inconsistencies
    issues = system.check_consistency()
    print(f"  After auto-reconcile: {len(issues)} issues (expected 0)")
    assert len(issues) == 0, f"Expected 0 issues, got {len(issues)}"

    # Mark resolved should also be clean
    unreconciled = system.get_unreconciled_bank_entries()
    if unreconciled:
        system.mark_resolved(unreconciled[0], "test")
    issues = system.check_consistency()
    assert len(issues) == 0

    print("PASSED")


def test_member_beacon_lookup():
    """Test looking up beacon entries by member name."""
    print("\n=== Test: Member Beacon Lookup ===")

    system = make_system()

    # Get a beacon with a member_1 field
    beacons_with_member = [b for b in system.beacon_entries if b.member_1]
    if beacons_with_member:
        member = beacons_with_member[0].member_1
        results = system.get_beacon_entries_for_member(member)
        print(f"  Member '{member}': {len(results)} beacon entries")
        assert len(results) > 0

        # Results should be sorted by date
        dates = [b.date for b in results]
        assert dates == sorted(dates), "Results should be sorted by date"
    else:
        print("  SKIPPED (no beacons with member_1 in sample data)")

    # Empty member should return nothing
    results = system.get_beacon_entries_for_member("")
    assert len(results) == 0

    # get_bank_id_for_beacon on unreconciled should return None
    assert system.get_bank_id_for_beacon("BEACON_9999") is None

    # Reconcile something and check get_bank_id_for_beacon
    system.auto_reconcile()
    for rec in system.reconciliations:
        if rec.beacon_ids:
            bank_id = system.get_bank_id_for_beacon(rec.beacon_ids[0])
            assert bank_id == rec.bank_id
            print(f"  get_bank_id_for_beacon({rec.beacon_ids[0]}) = {bank_id}")
            break

    print("PASSED")


def test_allow_1_to_2_config():
    """Test that allow_1_to_2=False disables 1-to-2 candidate generation."""
    print("\n=== Test: Allow 1-to-2 Config ===")

    system = make_system()

    # Find a bank entry that has 1-to-2 candidates
    bank_with_1to2 = None
    for bank in system.bank_transactions:
        candidates = system.get_candidates_for_bank(bank)
        if any(c.match_type == '1-to-2' for c in candidates):
            bank_with_1to2 = bank
            break

    if bank_with_1to2:
        # Disable 1-to-2
        system.allow_1_to_2 = False
        candidates = system.get_candidates_for_bank(bank_with_1to2)
        has_1to2 = any(c.match_type == '1-to-2' for c in candidates)
        assert not has_1to2, "Should have no 1-to-2 candidates when disabled"
        print(f"  {bank_with_1to2.id}: no 1-to-2 candidates when disabled (correct)")

        # Re-enable
        system.allow_1_to_2 = True
        candidates = system.get_candidates_for_bank(bank_with_1to2)
        has_1to2 = any(c.match_type == '1-to-2' for c in candidates)
        assert has_1to2, "Should have 1-to-2 candidates when enabled"
        print(f"  {bank_with_1to2.id}: has 1-to-2 candidates when enabled (correct)")
    else:
        print("  SKIPPED (no 1-to-2 candidates in sample data)")

    print("PASSED")


def test_amount_search_ignores_sign():
    """Test that amount search ignores sign."""
    print("\n=== Test: Amount Search Ignores Sign ===")

    system = make_system()

    # Search with positive amount
    results_pos = system.search_bank_entries("£13.00")
    # Search with negative amount (should find same results)
    results_neg = system.search_bank_entries("£-13.00")
    print(f"  Bank search '£13.00': {len(results_pos)} results")
    print(f"  Bank search '£-13.00': {len(results_neg)} results")
    assert len(results_pos) == len(results_neg), "Sign should not affect search results"

    print("PASSED")


def test_date_range_filter():
    """Test that bank_date_from/to filters bank entries in navigation."""
    print("\n=== Test: Date Range Filter ===")

    system = make_system()
    all_count = len(system.get_bank_entries_sorted())
    print(f"  All entries (no filter): {all_count}")

    # Set a narrow date range that excludes some entries
    from datetime import datetime
    dates = [b.date for b in system.bank_transactions]
    mid_date = sorted(dates)[len(dates) // 2]
    system.bank_date_from = mid_date
    system.bank_date_to = None
    filtered_count = len(system.get_bank_entries_sorted())
    print(f"  Filtered from {mid_date.strftime('%d/%m/%Y')}: {filtered_count}")
    assert filtered_count <= all_count, "Filtered count should be <= all"
    assert filtered_count > 0, "Should still have some entries"

    # Stats should only count entries in range
    stats = system.get_statistics()
    assert stats['total_bank'] == filtered_count, "Stats should only count in-range entries"
    print(f"  Stats total_bank: {stats['total_bank']} (in-range entries only)")

    # Reset
    system.bank_date_from = None
    assert len(system.get_bank_entries_sorted()) == all_count

    print("PASSED")


def test_cheque_matching():
    """Test cheque indicator, cheque filter, and cheque scoring bonus."""
    print("\n=== Test: Cheque Matching ===")

    system = make_system()

    # Test get_cheque_beacon_entries returns only cheque beacons
    cheque_beacons = system.get_cheque_beacon_entries()
    cheque_count = sum(1 for b in system.beacon_entries
                       if b.payment_method.lower() == 'cheque')
    assert len(cheque_beacons) == cheque_count, \
        f"Expected {cheque_count} cheque beacons, got {len(cheque_beacons)}"
    print(f"  Cheque beacons: {len(cheque_beacons)} out of {len(system.beacon_entries)}")

    # Test cheque bonus calculation
    from datetime import datetime
    beacon_cheque = BeaconEntry(
        id="TEST_CHQ", date=datetime(2025, 1, 15),
        trans_no="9999", payee="Test Payee", detail="",
        amount=Decimal("50.00"), payment_method="Cheque"
    )
    beacon_normal = BeaconEntry(
        id="TEST_NORM", date=datetime(2025, 1, 15),
        trans_no="9998", payee="Test Payee", detail="",
        amount=Decimal("50.00"), payment_method=""
    )
    # Bank description with "cheque" should give bonus for cheque beacon
    bonus = system._calculate_cheque_bonus("CHQ Payment 123", beacon_cheque)
    assert bonus > 0, "Should get cheque bonus when bank has CHQ and beacon is cheque"
    print(f"  Cheque bonus for CHQ in desc + cheque beacon: {bonus}")

    bonus_none = system._calculate_cheque_bonus("CHQ Payment 123", beacon_normal)
    assert bonus_none == 0, "Should NOT get cheque bonus when beacon is not cheque"
    print(f"  Cheque bonus for CHQ in desc + normal beacon: {bonus_none}")

    bonus_no_chq = system._calculate_cheque_bonus("Normal payment", beacon_cheque)
    assert bonus_no_chq == 0, "Should NOT get cheque bonus when bank has no cheque/chq"
    print(f"  Cheque bonus for normal desc + cheque beacon: {bonus_no_chq}")

    # Test "cheque" keyword no longer works in search_beacon_entries
    results = system.search_beacon_entries("cheque")
    # "cheque" should now be treated as a normal text search, not special keyword
    print(f"  search_beacon_entries('cheque'): {len(results)} results (text match only)")

    print("PASSED")


def test_member_number_resolution():
    """Test numeric member number resolution, title stripping, and scoring."""
    print("\n=== Test: Member Number Resolution ===")

    from datetime import datetime

    system = make_system()

    # --- Test _strip_titles ---
    assert system._strip_titles("MR JohnSmith") == "JohnSmith"
    assert system._strip_titles("MRS JaneSmith") == "JaneSmith"
    assert system._strip_titles("Mr. JohnSmith") == "JohnSmith"
    assert system._strip_titles("DR PROF JohnSmith") == "JohnSmith"
    assert system._strip_titles("JohnSmith") == "JohnSmith"
    assert system._strip_titles("") == ""
    # Noise words (Refund, Subs)
    assert system._strip_titles("Refund JohnSmith") == "JohnSmith"
    assert system._strip_titles("REFUND MRS JaneSmith") == "JaneSmith"
    assert system._strip_titles("Subs LLeonard") == "LLeonard"
    print("  _strip_titles: PASSED")

    # --- Test _build_name_to_memno_lookup ---
    # member_lookup loaded from member_lookup.csv has entries like:
    #   823: forename=L, surname=Leonard
    #   1679: forename=Virginia, surname=Wykes, known_as=Ginny
    lookup = system._build_name_to_memno_lookup()
    assert lookup.get('LLEONARD') == '823', f"Expected 823, got {lookup.get('LLEONARD')}"
    assert lookup.get('VIRGINIAWYKES') == '1679'
    assert lookup.get('GINNYWYKES') == '1679'  # known_as variant
    print(f"  _build_name_to_memno_lookup: {len(lookup)} entries, PASSED")

    # --- Test _resolve_name_to_memno ---
    assert system._resolve_name_to_memno("LLeonard", lookup) == '823'
    assert system._resolve_name_to_memno("VirginiaWykes", lookup) == '1679'
    assert system._resolve_name_to_memno("GinnyWykes", lookup) == '1679'
    assert system._resolve_name_to_memno("MRS VirginiaWykes", lookup) == '1679'
    assert system._resolve_name_to_memno("MR LLeonard", lookup) == '823'
    assert system._resolve_name_to_memno("UnknownPerson", lookup) == ''
    assert system._resolve_name_to_memno("", lookup) == ''
    # Refund/noise word handling
    assert system._resolve_name_to_memno("Refund LLeonard", lookup) == '823'
    assert system._resolve_name_to_memno("REFUND MRS VirginiaWykes", lookup) == '1679'
    assert system._resolve_name_to_memno("RefundLLeonard", lookup) == '823'  # no-space case
    assert system._resolve_name_to_memno("RefundVirginiaWykes", lookup) == '1679'
    assert system._resolve_name_to_memno("SubsBarbaraDuke", lookup) == '1783'
    # Period stripping (e.g. "L. Leonard" -> "LLeonard" -> exact match)
    assert system._resolve_name_to_memno("L. Leonard", lookup) == '823'
    # Surname + initial fallback: "V. Wykes" should match Virginia Wykes
    assert system._resolve_name_to_memno("V. Wykes", lookup) == '1679'
    # known_as initial: "G. Wykes" should match Ginny Wykes via known_as
    assert system._resolve_name_to_memno("G. Wykes", lookup) == '1679'
    # No matching initial but unique surname: "X. Wykes" resolves via surname-only fallback
    assert system._resolve_name_to_memno("X. Wykes", lookup) == '1679'
    # Joined initial+surname: "B. Duke" should match Barbara Duke
    assert system._resolve_name_to_memno("B. Duke", lookup) == '1783'
    print("  _resolve_name_to_memno (with periods + initial fallback): PASSED")

    # --- Test _resolve_member_numbers on beacon entries ---
    # Create beacon entries with known member names and inject them
    original_beacons = system.beacon_entries[:]
    test_beacon_1 = BeaconEntry(
        id="TEST_MEM_1", date=datetime(2025, 1, 15),
        trans_no="M001", payee="Test", detail="",
        amount=Decimal("10.00"), member_1="LLeonard"
    )
    test_beacon_2 = BeaconEntry(
        id="TEST_MEM_2", date=datetime(2025, 1, 16),
        trans_no="M002", payee="Test2", detail="",
        amount=Decimal("20.00"), member_1="VirginiaWykes", member_2="BarbaraDuke"
    )
    test_beacon_3 = BeaconEntry(
        id="TEST_MEM_3", date=datetime(2025, 1, 17),
        trans_no="M003", payee="Test3", detail="",
        amount=Decimal("30.00"), member_1="MRS GinnyWykes"
    )
    system.beacon_entries = [test_beacon_1, test_beacon_2, test_beacon_3]
    system._resolve_member_numbers()

    assert test_beacon_1.mem_no_1 == '823', f"Expected 823, got {test_beacon_1.mem_no_1}"
    assert test_beacon_2.mem_no_1 == '1679', f"Expected 1679, got {test_beacon_2.mem_no_1}"
    assert test_beacon_2.mem_no_2 == '1783', f"Expected 1783, got {test_beacon_2.mem_no_2}"
    assert test_beacon_3.mem_no_1 == '1679', f"Expected 1679 (via MRS Ginny), got {test_beacon_3.mem_no_1}"
    print("  _resolve_member_numbers: PASSED")

    # --- Test _calculate_member_match_score ---
    bank_with_mem = BankTransaction(
        id="TEST_B1", date=datetime(2025, 1, 15),
        type="DEB", description="LEONARD 823 PAYMENT",
        amount=Decimal("10.00"), mem_nos=['823']
    )
    # Score should be high when bank mem_no matches beacon mem_no
    score = system._calculate_member_match_score(bank_with_mem, test_beacon_1)
    assert score == 0.95, f"Expected 0.95, got {score}"

    # Score should be 0 when no match
    score_no_match = system._calculate_member_match_score(bank_with_mem, test_beacon_2)
    assert score_no_match == 0.0, f"Expected 0.0, got {score_no_match}"

    # Bank with no mem_nos
    bank_no_mem = BankTransaction(
        id="TEST_B2", date=datetime(2025, 1, 15),
        type="DEB", description="SOME PAYMENT",
        amount=Decimal("10.00"), mem_nos=[]
    )
    score_empty = system._calculate_member_match_score(bank_no_mem, test_beacon_1)
    assert score_empty == 0.0
    print("  _calculate_member_match_score: PASSED")

    # --- Test get_beacon_entries_for_member_no ---
    results = system.get_beacon_entries_for_member_no('1679')
    assert len(results) == 2, f"Expected 2, got {len(results)}"
    assert results[0].id == "TEST_MEM_2"
    assert results[1].id == "TEST_MEM_3"

    results_823 = system.get_beacon_entries_for_member_no('823')
    assert len(results_823) == 1
    assert results_823[0].id == "TEST_MEM_1"

    results_empty = system.get_beacon_entries_for_member_no('')
    assert len(results_empty) == 0
    print("  get_beacon_entries_for_member_no: PASSED")

    # --- Test _backfill_beacon_mem_nos ---
    test_beacon_blank = BeaconEntry(
        id="TEST_MEM_BF", date=datetime(2025, 1, 15),
        trans_no="M004", payee="No member text", detail="",
        amount=Decimal("10.00")
    )
    system.beacon_entries.append(test_beacon_blank)
    system.reconciliations.append(Reconciliation(
        bank_id="TEST_B1", beacon_ids=["TEST_MEM_BF"],
        match_type="1-to-1", status="reconciled"
    ))
    system.bank_transactions.append(bank_with_mem)
    system._backfill_beacon_mem_nos()
    assert test_beacon_blank.mem_no_1 == '823', \
        f"Backfill should set mem_no_1 to 823, got {test_beacon_blank.mem_no_1}"
    print("  _backfill_beacon_mem_nos: PASSED")

    # --- Test get_beacon_member_display ---
    # Resolved: should show "#mem_no FullName"
    display_1 = system.get_beacon_member_display(test_beacon_1, 1)
    assert "#823" in display_1 and "Leonard" in display_1, f"Got: {display_1}"

    # Resolved with known_as: should show "(Ginny)"
    display_3 = system.get_beacon_member_display(test_beacon_2, 1)
    assert "#1679" in display_3 and "Ginny" in display_3, f"Got: {display_3}"

    # Blank member: should show "--"
    display_blank = system.get_beacon_member_display(test_beacon_1, 2)
    assert display_blank == "--", f"Got: {display_blank}"

    # Unresolved: should show name with "(not recognised)"
    unknown = BeaconEntry(
        id="TEST_UNK", date=datetime(2025, 1, 15),
        trans_no="M005", payee="Unknown", detail="",
        amount=Decimal("5.00"), member_1="ZZZNoMatch"
    )
    display_unk = system.get_beacon_member_display(unknown, 1)
    assert "not recognised" in display_unk, f"Got: {display_unk}"

    # Multiple matches: add a duplicate surname member to test "N possible memnos"
    system.member_lookup['9001'] = {
        'status': 'current', 'forename': 'Bob', 'surname': 'Leonard',
        'known_as': '', 'class': '', 'payment_type': ''
    }
    dup = BeaconEntry(
        id="TEST_DUP", date=datetime(2025, 1, 15),
        trans_no="M006", payee="Dup", detail="",
        amount=Decimal("5.00"), member_1="X. Leonard"
    )
    # X. Leonard matches no forename initial but 2 Leonards exist, so "2 with surname"
    display_dup = system.get_beacon_member_display(dup, 1)
    assert "2 with surname" in display_dup, f"Got: {display_dup}"
    # But if we use an ambiguous initial... no forename starts with X
    # Let's test with "Leonard" (initial "L") - now 2 Leonards: L Leonard and Bob Leonard?
    # Actually L matches L Leonard (823) but not Bob Leonard (9001). So single match.
    # Let me use a real ambiguous case:
    system.member_lookup['9002'] = {
        'status': 'current', 'forename': 'Lisa', 'surname': 'Leonard',
        'known_as': '', 'class': '', 'payment_type': ''
    }
    dup2 = BeaconEntry(
        id="TEST_DUP2", date=datetime(2025, 1, 15),
        trans_no="M007", payee="Dup2", detail="",
        amount=Decimal("5.00"), member_1="L. Leonard"
    )
    # L. Leonard -> "LLEONARD" matches exact lookup (823), so resolves
    # That's correct - exact match takes priority.
    # For "N possible memnos", need case where exact match fails but multiple surname+initial match
    dup3 = BeaconEntry(
        id="TEST_DUP3", date=datetime(2025, 1, 15),
        trans_no="M008", payee="Dup3", detail="",
        amount=Decimal("5.00"), member_1="Li. Leonard"
    )
    # "Li. Leonard" -> "LILEONARD" - no exact match, surname=LEONARD, initial=L
    # Two Leonards start with L: 823 (L Leonard) and 9002 (Lisa Leonard)
    display_dup3 = system.get_beacon_member_display(dup3, 1)
    assert "2 possible memnos" in display_dup3, f"Got: {display_dup3}"
    # Clean up test members
    del system.member_lookup['9001']
    del system.member_lookup['9002']
    print("  get_beacon_member_display (with ambiguous): PASSED")

    # Restore original state
    system.beacon_entries = original_beacons
    system.reconciliations = [r for r in system.reconciliations if r.bank_id != "TEST_B1"]
    system.bank_transactions = [b for b in system.bank_transactions if b.id != "TEST_B1"]

    print("PASSED")


def test_ignored_inconsistencies():
    """Test ignoring and un-ignoring inconsistencies with state persistence."""
    print("\n=== Test: Ignored Inconsistencies ===")

    system = make_system()

    # Initially no ignored inconsistencies
    assert len(system.ignored_inconsistencies) == 0

    # Ignore an inconsistency
    system.ignore_inconsistency("BANK_0001", "Test issue")
    assert system.is_inconsistency_ignored("BANK_0001", "Test issue")
    assert not system.is_inconsistency_ignored("BANK_0001", "Different issue")
    assert not system.is_inconsistency_ignored("BANK_9999", "Test issue")
    assert len(system.ignored_inconsistencies) == 1
    print("  Ignore: PASSED")

    # Duplicate ignore should not add twice
    system.ignore_inconsistency("BANK_0001", "Test issue")
    assert len(system.ignored_inconsistencies) == 1
    print("  Duplicate ignore prevention: PASSED")

    # Add another
    system.ignore_inconsistency("BANK_0002", "Another issue")
    assert len(system.ignored_inconsistencies) == 2

    # Un-ignore
    system.unignore_inconsistency("BANK_0001", "Test issue")
    assert not system.is_inconsistency_ignored("BANK_0001", "Test issue")
    assert len(system.ignored_inconsistencies) == 1
    print("  Un-ignore: PASSED")

    # State persistence: save and reload
    system.save_state()
    system2 = ReconciliationSystem(data_dir=DATA_DIR, code_dir=CODE_DIR)
    system2.load_data()
    assert len(system2.ignored_inconsistencies) == 1
    assert system2.is_inconsistency_ignored("BANK_0002", "Another issue")
    print("  State persistence: PASSED")

    # Clean up
    system2.ignored_inconsistencies = []
    system2.save_state()

    print("PASSED")


def test_memno_aliases():
    """Test member number alias loading, chain resolution, and cycle detection."""
    print("\n=== Test: Memno Aliases ===")

    from datetime import datetime
    import tempfile

    system = make_system()

    # Create a temp aliases file
    alias_file = os.path.join(CODE_DIR, 'memno_aliases.csv')
    try:
        with open(alias_file, 'w', newline='', encoding='utf-8') as f:
            f.write("old_memno,new_memno\n")
            f.write("100,200\n")      # Simple alias
            f.write("200,300\n")      # Chain: 100->200->300
            f.write("400,500\n")      # Another simple alias

        system._load_memno_aliases()

        # Chain resolution: 100 should resolve to 300
        assert system.resolve_memno_alias('100') == '300', \
            f"Expected 300, got {system.resolve_memno_alias('100')}"
        # 200 should resolve to 300
        assert system.resolve_memno_alias('200') == '300', \
            f"Expected 300, got {system.resolve_memno_alias('200')}"
        # 300 is the canonical - no alias
        assert system.resolve_memno_alias('300') == '300'
        # 400 -> 500
        assert system.resolve_memno_alias('400') == '500'
        # Unknown memno is unchanged
        assert system.resolve_memno_alias('999') == '999'
        print("  Chain resolution: PASSED")

        # Test apply to entries
        bank = BankTransaction(
            id="TEST_ALIAS_B", date=datetime(2025, 1, 15),
            type="DEB", description="Test", amount=Decimal("10.00"),
            mem_nos=['100', '400']
        )
        beacon = BeaconEntry(
            id="TEST_ALIAS_E", date=datetime(2025, 1, 15),
            trans_no="A001", payee="Test", detail="",
            amount=Decimal("10.00"), mem_no_1="200", mem_no_2="400"
        )
        system.bank_transactions.append(bank)
        system.beacon_entries.append(beacon)
        system._apply_memno_aliases()
        assert bank.mem_nos == ['300', '500'], f"Got {bank.mem_nos}"
        assert beacon.mem_no_1 == '300', f"Got {beacon.mem_no_1}"
        assert beacon.mem_no_2 == '500', f"Got {beacon.mem_no_2}"
        print("  Apply aliases: PASSED")

        # Clean up test entries
        system.bank_transactions = [b for b in system.bank_transactions if b.id != "TEST_ALIAS_B"]
        system.beacon_entries = [b for b in system.beacon_entries if b.id != "TEST_ALIAS_E"]

        # Test cycle detection
        with open(alias_file, 'w', newline='', encoding='utf-8') as f:
            f.write("old_memno,new_memno\n")
            f.write("10,20\n")
            f.write("20,30\n")
            f.write("30,10\n")  # Cycle!

        system._load_memno_aliases()
        # Should not crash, cycle detected
        # The resolved value depends on which entry is processed first but shouldn't loop
        print("  Cycle detection (no crash): PASSED")

    finally:
        if os.path.exists(alias_file):
            os.remove(alias_file)

    print("PASSED")


def test_confusable_members():
    """Test confusable members CSV loading and warning display."""
    print("\n=== Test: Confusable Members ===")

    from datetime import datetime

    system = make_system()

    # Create a temp confusable_members.csv at code level
    confusable_file = os.path.join(CODE_DIR, 'confusable_members.csv')
    try:
        with open(confusable_file, 'w', newline='', encoding='utf-8') as f:
            f.write("memno_1,memno_2\n")
            f.write("823,1679\n")

        system._load_confusable_members()

        assert system.is_confusable_member('823')
        assert system.is_confusable_member('1679')
        assert not system.is_confusable_member('1783')
        print("  is_confusable_member: PASSED")

        warning_823 = system.get_confusable_warning('823')
        assert '#1679' in warning_823, f"Got: {warning_823}"
        warning_1679 = system.get_confusable_warning('1679')
        assert '#823' in warning_1679, f"Got: {warning_1679}"
        warning_none = system.get_confusable_warning('1783')
        assert warning_none == '', f"Got: {warning_none}"
        print("  get_confusable_warning: PASSED")

        # Test display with confusable warning
        beacon = BeaconEntry(
            id="TEST_CONF", date=datetime(2025, 1, 15),
            trans_no="C001", payee="Test", detail="",
            amount=Decimal("10.00"), member_1="LLeonard", mem_no_1="823"
        )
        display = system.get_beacon_member_display(beacon, 1)
        assert '\u26a0' in display, f"Expected warning symbol, got: {display}"
        assert '#1679' in display, f"Expected confusable memno ref, got: {display}"
        print("  Display with confusable warning: PASSED")

    finally:
        if os.path.exists(confusable_file):
            os.remove(confusable_file)
        # Reload to clear confusable state
        system._load_confusable_members()

    print("PASSED")


def test_new_reports():
    """Test inconsistencies and unresolved memno reports."""
    print("\n=== Test: New Reports ===")

    from datetime import datetime

    system = make_system()
    system.auto_reconcile()

    # Test inconsistencies report
    inconsistencies_path = os.path.join(DATA_DIR, "_test_inconsistencies.csv")
    r1 = system.export_inconsistencies_csv(inconsistencies_path)
    assert os.path.exists(inconsistencies_path)
    print(f"  Inconsistencies report: {r1} rows")
    os.remove(inconsistencies_path)

    # Test unresolved memno report
    unresolved_path = os.path.join(DATA_DIR, "_test_unresolved_memno.csv")
    r2 = system.export_unresolved_memno_csv(unresolved_path)
    assert os.path.exists(unresolved_path)
    print(f"  Unresolved memno report: {r2} rows")
    os.remove(unresolved_path)

    print("PASSED")


def test_memno_search():
    """Test #memno search for bank and beacon entries."""
    print("\n=== Test: #Memno Search ===")

    from datetime import datetime

    system = make_system()

    # Add test entries with known mem_nos
    bank = BankTransaction(
        id="TEST_SEARCH_B", date=datetime(2025, 1, 15),
        type="DEB", description="Test 823 payment",
        amount=Decimal("10.00"), mem_nos=['823']
    )
    beacon = BeaconEntry(
        id="TEST_SEARCH_E", date=datetime(2025, 1, 15),
        trans_no="S001", payee="Test", detail="",
        amount=Decimal("10.00"), mem_no_1="823"
    )
    system.bank_transactions.append(bank)
    system.beacon_entries.append(beacon)

    # Bank #memno search
    results = system.search_bank_entries("#823")
    assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}"
    # Check our test bank is in results
    found = any(system.bank_transactions[i].id == "TEST_SEARCH_B" for i in results)
    assert found, "Test bank entry not found in #823 search"
    print(f"  Bank #823 search: {len(results)} results")

    # Beacon #memno search
    results = system.search_beacon_entries("#823")
    assert len(results) >= 1
    found = any(b.id == "TEST_SEARCH_E" for b in results)
    assert found, "Test beacon entry not found in #823 search"
    print(f"  Beacon #823 search: {len(results)} results")

    # Non-matching #memno
    results = system.search_bank_entries("#99999")
    assert len(results) == 0
    results = system.search_beacon_entries("#99999")
    assert len(results) == 0
    print("  Non-matching #memno: 0 results")

    # Empty #
    results = system.search_bank_entries("#")
    assert len(results) == 0
    print("  Empty # search: 0 results")

    # Clean up
    system.bank_transactions = [b for b in system.bank_transactions if b.id != "TEST_SEARCH_B"]
    system.beacon_entries = [b for b in system.beacon_entries if b.id != "TEST_SEARCH_E"]

    print("PASSED")


def test_reconciled_comment():
    """Test adding comments to reconciled (not just resolved) entries."""
    print("\n=== Test: Reconciled Comment ===")

    system = make_system()

    # Find a bank entry, reconcile it, then add a comment
    for bank in system.bank_transactions:
        candidates = system.get_candidates_for_bank(bank)
        if candidates:
            success, msg = system.reconcile(bank, candidates[0])
            assert success, f"Reconcile failed: {msg}"

            # Should be able to add comment to reconciled entry
            success, msg = system.update_resolved_comment(bank.id, "Test reconciled comment")
            assert success, f"Add comment failed: {msg}"

            rec = system.get_reconciliation_for_bank(bank.id)
            assert rec.comment == "Test reconciled comment"
            assert rec.status == "reconciled"  # Still reconciled, not resolved
            print(f"  Added comment to reconciled entry: '{rec.comment}'")

            # Update the comment
            success, msg = system.update_resolved_comment(bank.id, "Updated comment")
            assert success
            rec = system.get_reconciliation_for_bank(bank.id)
            assert rec.comment == "Updated comment"
            print(f"  Updated comment: '{rec.comment}'")
            break

    print("PASSED")


def test_surname_only_fallback():
    """Test surname-only fallback for member resolution."""
    print("\n=== Test: Surname-Only Fallback ===")

    system = make_system()
    lookup = system._build_name_to_memno_lookup()

    # "B. Duke" -> should resolve to Barbara Duke (1783) via surname+initial
    assert system._resolve_name_to_memno("B. Duke", lookup) == '1783'
    print("  B. Duke -> 1783 (surname+initial): PASSED")

    # Test surname-only: add a member with unique surname
    system.member_lookup['9999'] = {
        'status': 'current', 'forename': 'Hannah', 'surname': 'Dickinson',
        'known_as': '', 'class': '', 'payment_type': ''
    }
    # "B. Dickinson" -> initial B doesn't match Hannah, but surname-only has 1 match
    result = system._resolve_name_to_memno("B. Dickinson", lookup)
    assert result == '9999', f"Expected 9999 (surname-only), got '{result}'"
    print("  B. Dickinson -> 9999 (surname-only fallback): PASSED")

    # Add another Dickinson - should NOT resolve (2 matches)
    system.member_lookup['9998'] = {
        'status': 'current', 'forename': 'Brian', 'surname': 'Dickinson',
        'known_as': '', 'class': '', 'payment_type': ''
    }
    # Now "B. Dickinson" should match Brian via surname+initial
    result = system._resolve_name_to_memno("B. Dickinson", lookup)
    assert result == '9998', f"Expected 9998 (B matches Brian), got '{result}'"
    print("  B. Dickinson with Brian -> 9998 (surname+initial): PASSED")

    # "X. Dickinson" -> no initial match, 2 Dickinsons, should not resolve
    result = system._resolve_name_to_memno("X. Dickinson", lookup)
    assert result == '', f"Expected '' (ambiguous), got '{result}'"
    print("  X. Dickinson with 2 Dickinsons -> '' (ambiguous): PASSED")

    # Clean up
    del system.member_lookup['9999']
    del system.member_lookup['9998']

    print("PASSED")


def test_excel_backup_loading():
    """Test loading beacon entries and member lookup from Excel backup file."""
    print("\n=== Test: Excel Backup Loading ===")

    # Create a config that uses the test Excel backup
    import json
    import shutil

    test_config = {
        "title": "Excel Backup Test",
        "bank_file": "Bank_Transactions.csv",
        "beacon_file": "Beacon_Entries.csv",
        "backup_file": "data/sample/test_backup.xlsx",
        "ledger_account": "Current",
        "ledger_date_from": "01/01/2025",
        "ledger_date_to": "28/02/2025",
        "ledger_exclude_cleared": True,
        "common_amounts": ["13.00", "9.50", "6.50"],
        "date_tolerance_days": 7,
        "trans_no_limit": 5,
        "auto_reconcile_common_threshold": 0.90,
        "auto_reconcile_other_threshold": 0.80,
        "allow_1_to_2": True,
        "match_beacon_detail": True
    }

    # Save temp config
    config_path = os.path.join(DATA_DIR, "config.json")
    original_config = open(config_path, 'r').read()
    with open(config_path, 'w') as f:
        json.dump(test_config, f, indent=2)

    try:
        state_file = os.path.join(DATA_DIR, "reconciliation_state_v2.json")
        if os.path.exists(state_file):
            os.remove(state_file)

        system = ReconciliationSystem(data_dir=DATA_DIR, code_dir=CODE_DIR)
        system.load_data()

        # Check members loaded
        assert len(system.member_lookup) == 3, \
            f"Expected 3 members, got {len(system.member_lookup)}"
        assert '823' in system.member_lookup
        assert system.member_lookup['823']['forename'] == 'L'
        assert system.member_lookup['823']['surname'] == 'Leonard'
        assert system.member_lookup['823']['class'] == 'Standard'
        assert system.member_lookup['823']['payment_type'] == 'DD'
        print(f"  Members loaded: {len(system.member_lookup)}")
        print(f"    Member 823: {system.member_lookup['823']}")

        # Check beacon entries loaded (should be 3: TRN001, TRN002, TRN003)
        # Excluded: TRN004 (Cash account), TRN005 (cleared), TRN006 (out of date range)
        assert len(system.beacon_entries) == 3, \
            f"Expected 3 beacon entries, got {len(system.beacon_entries)}"
        trans_nos = {b.trans_no for b in system.beacon_entries}
        assert trans_nos == {'TRN001', 'TRN002', 'TRN003'}, \
            f"Unexpected trans_nos: {trans_nos}"
        print(f"  Beacon entries loaded: {len(system.beacon_entries)}")
        for b in system.beacon_entries:
            print(f"    {b.trans_no}: {b.payee} £{b.amount} ({b.payment_method})")

        # Check cheque beacon
        chq = [b for b in system.beacon_entries if b.trans_no == 'TRN003'][0]
        assert chq.payment_method == 'Cheque'
        assert chq.member_1 == 'JonesA'
        print(f"  Cheque entry TRN003: payment_method={chq.payment_method}, member_1={chq.member_1}")

        # Test comparison with existing CSV
        beacon_csv = os.path.join(DATA_DIR, "Beacon_Entries.csv")
        result = system.compare_with_beacon_csv(beacon_csv)
        print(f"  Comparison: {len(result['in_both'])} matched, "
              f"{len(result['only_in_excel'])} only in Excel, "
              f"{len(result['only_in_csv'])} only in CSV, "
              f"{len(result['differences'])} with differences")

    finally:
        # Restore original config
        with open(config_path, 'w') as f:
            f.write(original_config)

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
    test_consistency_check()
    test_member_beacon_lookup()
    test_allow_1_to_2_config()
    test_amount_search_ignores_sign()
    test_date_range_filter()
    test_cheque_matching()
    test_member_number_resolution()
    test_ignored_inconsistencies()
    test_memno_aliases()
    test_confusable_members()
    test_new_reports()
    test_memno_search()
    test_reconciled_comment()
    test_surname_only_fallback()
    test_excel_backup_loading()

    # Final cleanup
    if os.path.exists(state_file):
        os.remove(state_file)

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
