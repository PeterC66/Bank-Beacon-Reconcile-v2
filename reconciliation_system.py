"""
Bank Beacon Reconciliation System v2
Core matching logic for reconciling bank transactions with accounting entries.

v2 changes from v1:
- Bank-centric navigation: step through bank entries, see ranked beacon candidates
- "Reconciled" replaces "confirmed" terminology
- Per-bank rejected beacon pairings (persistent across sessions)
- Config file per data folder (common amounts, date tolerance, etc.)
- member_1 and member_2 fields from beacon entries for matching
- Simpler state format: just reconciliations + rejected pairings

Features:
- 1-to-1 and 1-to-2 matching (auto-detected)
- Manual matching via trans_no for 1-to-many
- Common amount weighting (configurable)
- Date proximity matching (configurable tolerance)
- Name similarity matching (surname + initial)
- Member number matching (best indicator)
- Auto-reconcile high-confidence matches
"""

VERSION = "2.0.0"

import csv
import json
import os
import re
import inspect
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Callable
from difflib import SequenceMatcher
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum


def debug_log(message: str):
    """Print debug message with line number."""
    frame = inspect.currentframe().f_back
    print(f"[DEBUG L{frame.f_lineno}] {message}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BankTransaction:
    """Represents a bank transaction."""
    id: str
    date: datetime
    type: str
    description: str
    amount: Decimal
    raw_data: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'date': self.date.strftime('%d-%b-%y'),
            'type': self.type,
            'description': self.description,
            'amount': str(self.amount)
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'BankTransaction':
        return cls(
            id=data['id'],
            date=datetime.strptime(data['date'], '%d-%b-%y'),
            type=data['type'],
            description=data['description'],
            amount=Decimal(data['amount']),
            raw_data=data.get('raw_data', {})
        )


@dataclass
class BeaconEntry:
    """Represents a Beacon accounting entry."""
    id: str
    date: datetime
    trans_no: str
    payee: str
    amount: Decimal
    detail: str
    member_1: str = ""
    member_2: str = ""
    payment_method: str = ""
    raw_data: Dict = field(default_factory=dict)
    matched: bool = False

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'date': self.date.strftime('%d/%m/%Y'),
            'trans_no': self.trans_no,
            'payee': self.payee,
            'amount': str(self.amount),
            'detail': self.detail,
            'member_1': self.member_1,
            'member_2': self.member_2,
            'matched': self.matched
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'BeaconEntry':
        return cls(
            id=data['id'],
            date=datetime.strptime(data['date'], '%d/%m/%Y'),
            trans_no=data['trans_no'],
            payee=data['payee'],
            amount=Decimal(data['amount']),
            detail=data['detail'],
            member_1=data.get('member_1', ''),
            member_2=data.get('member_2', ''),
            raw_data=data.get('raw_data', {}),
            matched=data.get('matched', False)
        )


@dataclass
class BeaconCandidate:
    """A ranked beacon candidate (single or pair) for a bank entry."""
    beacon_entries: List[BeaconEntry]
    confidence_score: float
    match_type: str  # "1-to-1" or "1-to-2"
    amount_score: float = 0.0
    date_score: float = 0.0
    name_score: float = 0.0
    is_rejected: bool = False  # True if this pairing was rejected by user


@dataclass
class Reconciliation:
    """A confirmed reconciliation between a bank entry and beacon entry/entries."""
    bank_id: str
    beacon_ids: List[str]
    match_type: str  # "1-to-1", "1-to-2", "manual", "resolved"
    status: str  # "reconciled" or "manually_resolved"
    comment: str = ""

    def to_dict(self) -> Dict:
        return {
            'bank_id': self.bank_id,
            'beacon_ids': self.beacon_ids,
            'match_type': self.match_type,
            'status': self.status,
            'comment': self.comment
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Reconciliation':
        return cls(
            bank_id=data['bank_id'],
            beacon_ids=data['beacon_ids'],
            match_type=data['match_type'],
            status=data['status'],
            comment=data.get('comment', '')
        )


# ---------------------------------------------------------------------------
# Main system
# ---------------------------------------------------------------------------

class ReconciliationSystem:
    """Main reconciliation system for matching bank and beacon transactions.

    v2 architecture: bank-centric. For each bank entry, generate ranked
    beacon candidates on demand. State stores reconciliations and per-bank
    rejected pairings.
    """

    DEFAULT_CONFIG = {
        'title': 'Bank Beacon Reconciliation',
        'bank_file': 'Bank_Transactions.csv',
        'beacon_file': 'Beacon_Entries.csv',
        'common_amounts': ['13.00', '9.50', '6.50'],
        'date_tolerance_days': 7,
        'trans_no_limit': 5,
        'auto_reconcile_common_threshold': 0.90,
        'auto_reconcile_other_threshold': 0.80,
        'allow_1_to_2': True,
        'match_beacon_detail': True,
        'bank_date_from': None,
        'bank_date_to': None,
    }

    def __init__(self, data_dir: str = None, code_dir: str = None):
        """Initialize the reconciliation system.

        Args:
            data_dir: Directory containing data files (CSVs, config, state).
                      Defaults to code_dir if not specified.
            code_dir: Directory containing the code and member_lookup.csv.
                      Defaults to the directory of this script.
        """
        if code_dir is None:
            code_dir = os.path.dirname(os.path.abspath(__file__))
        if data_dir is None:
            data_dir = code_dir
        self.code_dir = code_dir
        self.data_dir = data_dir

        # Load config from data directory
        self.config = dict(self.DEFAULT_CONFIG)
        self._load_config()

        # Resolve file paths
        self.bank_file = os.path.join(data_dir, self.config['bank_file'])
        self.beacon_file = os.path.join(data_dir, self.config['beacon_file'])
        self.state_file = os.path.join(data_dir, 'reconciliation_state_v2.json')
        self.member_lookup_file = os.path.join(code_dir, 'member_lookup.csv')

        # Data
        self.bank_transactions: List[BankTransaction] = []
        self.beacon_entries: List[BeaconEntry] = []

        # Member lookup dictionary: mem_no -> {status, forename, surname, known_as}
        self.member_lookup: Dict[str, Dict] = {}

        # State: reconciliations and rejected pairings
        self.reconciliations: List[Reconciliation] = []
        self.rejected_pairings: List[Dict] = []  # [{bank_id, beacon_id}, ...]

        # Derived lookups (rebuilt from state)
        self._reconciled_bank_ids: Dict[str, Reconciliation] = {}
        self._reconciled_beacon_ids: set = set()
        self._rejected_pairings_by_bank: Dict[str, set] = defaultdict(set)

        # Config-derived
        self.common_amounts: List[Decimal] = [
            Decimal(a) for a in self.config['common_amounts']
        ]
        self.date_tolerance_days: int = self.config['date_tolerance_days']
        self.trans_no_limit: int = self.config['trans_no_limit']
        self.auto_reconcile_common_threshold: float = self.config['auto_reconcile_common_threshold']
        self.auto_reconcile_other_threshold: float = self.config['auto_reconcile_other_threshold']
        self.allow_1_to_2: bool = self.config['allow_1_to_2']
        self.match_beacon_detail: bool = self.config['match_beacon_detail']

        # Date range filter for bank entries
        self.bank_date_from: Optional[datetime] = None
        self.bank_date_to: Optional[datetime] = None
        if self.config.get('bank_date_from'):
            try:
                self.bank_date_from = datetime.strptime(self.config['bank_date_from'], '%d/%m/%Y')
            except ValueError:
                print(f"Warning: Could not parse bank_date_from: {self.config['bank_date_from']}")
        if self.config.get('bank_date_to'):
            try:
                self.bank_date_to = datetime.strptime(self.config['bank_date_to'], '%d/%m/%Y')
            except ValueError:
                print(f"Warning: Could not parse bank_date_to: {self.config['bank_date_to']}")


        # Index for fast lookups
        self._beacon_by_amount: Dict[Decimal, List[BeaconEntry]] = {}
        self._beacon_amounts: set = set()

    def _load_config(self):
        """Load config.json from data directory if it exists."""
        config_path = os.path.join(self.data_dir, 'config.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                self.config.update(user_config)
                print(f"Loaded config from {config_path}")
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load config: {e}")

    # -------------------------------------------------------------------
    # Data loading
    # -------------------------------------------------------------------

    def load_data(self):
        """Load transactions from CSV files and restore state."""
        self.bank_transactions = self._load_bank_transactions()
        self.beacon_entries = self._load_beacon_entries()
        self._load_member_lookup()
        self._load_state()
        self._rebuild_indices()

    def _parse_bank_date(self, date_str: str) -> datetime:
        """Parse bank date string, trying multiple formats."""
        formats = [
            '%d-%b-%y',      # 17-Mar-25
            '%d %b %Y',      # 17 Mar 2025
            '%d %b %y',      # 17 Mar 25
            '%d-%b-%Y',      # 17-Mar-2025
            '%d/%m/%Y',      # 17/03/2025
            '%d/%m/%y',      # 17/03/25
            '%Y-%m-%d',      # 2025-03-17
        ]
        date_str = date_str.strip()
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"Could not parse date: {date_str}")

    def _load_bank_transactions(self) -> List[BankTransaction]:
        """Load bank transactions from CSV, sorted by date."""
        transactions = []

        if not os.path.exists(self.bank_file):
            print(f"Warning: Bank file not found: {self.bank_file}")
            return transactions

        with open(self.bank_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                try:
                    date = self._parse_bank_date(row['Date'])
                    amount = Decimal(row['Amount'].strip().replace(',', ''))

                    transaction = BankTransaction(
                        id=f"BANK_{idx:04d}",
                        date=date,
                        type=row['Type'].strip(),
                        description=row['Description'].strip(),
                        amount=amount,
                        raw_data=dict(row)
                    )
                    transactions.append(transaction)
                except (ValueError, KeyError) as e:
                    print(f"Warning: Could not parse bank row {idx}: {e}")

        # Sort by date (primary navigation order)
        transactions.sort(key=lambda t: (t.date, t.id))
        return transactions

    def _load_beacon_entries(self) -> List[BeaconEntry]:
        """Load beacon entries from CSV."""
        entries = []

        if not os.path.exists(self.beacon_file):
            print(f"Warning: Beacon file not found: {self.beacon_file}")
            return entries

        with open(self.beacon_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                try:
                    date = datetime.strptime(row['date'].strip(), '%d/%m/%Y')
                    amount = Decimal(row['amount'].strip().replace(',', ''))

                    entry = BeaconEntry(
                        id=f"BEACON_{idx:04d}",
                        date=date,
                        trans_no=row['trans_no'].strip(),
                        payee=row['payee'].strip(),
                        amount=amount,
                        detail=row.get('detail', '').strip(),
                        member_1=row.get('member_1', '').strip(),
                        member_2=row.get('member_2', '').strip(),
                        payment_method=row.get('payment_method', '').strip(),
                        raw_data=dict(row)
                    )
                    entries.append(entry)
                except (ValueError, KeyError) as e:
                    print(f"Warning: Could not parse beacon row {idx}: {e}")

        return entries

    def _load_member_lookup(self):
        """Load member lookup from CSV file (shared, in code directory)."""
        self.member_lookup = {}

        if not os.path.exists(self.member_lookup_file):
            print(f"Warning: Member lookup file not found: {self.member_lookup_file}")
            return

        with open(self.member_lookup_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    mem_no = row['mem_no'].strip()
                    self.member_lookup[mem_no] = {
                        'status': row['status'].strip(),
                        'forename': row['forename'].strip(),
                        'surname': row['surname'].strip(),
                        'known_as': row.get('known_as', '').strip()
                    }
                except KeyError as e:
                    print(f"Warning: Could not parse member lookup row: {e}")

        print(f"Loaded {len(self.member_lookup)} member lookup entries")

    # -------------------------------------------------------------------
    # State management (v2 format)
    # -------------------------------------------------------------------

    def _load_state(self):
        """Load saved state from v2 JSON file."""
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)

            self.reconciliations = [
                Reconciliation.from_dict(r)
                for r in state.get('reconciliations', [])
            ]
            self.rejected_pairings = state.get('rejected_pairings', [])

            self._rebuild_lookups()

            # Mark beacon entries as matched
            for entry in self.beacon_entries:
                if entry.id in self._reconciled_beacon_ids:
                    entry.matched = True

            print(f"Loaded state: {len(self.reconciliations)} reconciliations, "
                  f"{len(self.rejected_pairings)} rejected pairings")

        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not load state: {e}")

    def save_state(self):
        """Save current state to v2 JSON file."""
        state = {
            'version': VERSION,
            'reconciliations': [r.to_dict() for r in self.reconciliations],
            'rejected_pairings': self.rejected_pairings
        }

        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)

    def _rebuild_lookups(self):
        """Rebuild derived lookup structures from reconciliations and rejected pairings."""
        self._reconciled_bank_ids = {}
        self._reconciled_beacon_ids = set()
        self._rejected_pairings_by_bank = defaultdict(set)

        for rec in self.reconciliations:
            self._reconciled_bank_ids[rec.bank_id] = rec
            for beacon_id in rec.beacon_ids:
                self._reconciled_beacon_ids.add(beacon_id)

        for rp in self.rejected_pairings:
            self._rejected_pairings_by_bank[rp['bank_id']].add(rp['beacon_id'])

    def _rebuild_indices(self):
        """Build beacon amount index for fast candidate lookup."""
        self._beacon_by_amount = defaultdict(list)
        self._beacon_amounts = set()
        for beacon in self.beacon_entries:
            self._beacon_by_amount[beacon.amount].append(beacon)
            self._beacon_amounts.add(beacon.amount)

    # -------------------------------------------------------------------
    # Bank entry navigation
    # -------------------------------------------------------------------

    def is_bank_in_date_range(self, bank: BankTransaction) -> bool:
        """Check if a bank entry falls within the configured date range."""
        if self.bank_date_from and bank.date < self.bank_date_from:
            return False
        if self.bank_date_to and bank.date > self.bank_date_to:
            return False
        return True

    def get_bank_entries_sorted(self) -> List[BankTransaction]:
        """Get all bank entries sorted by date (filtered by date range if configured)."""
        return [b for b in self.bank_transactions if self.is_bank_in_date_range(b)]

    def get_unreconciled_bank_entries(self) -> List[BankTransaction]:
        """Get unreconciled bank entries sorted by date (filtered by date range)."""
        return [b for b in self.bank_transactions
                if b.id not in self._reconciled_bank_ids
                and self.is_bank_in_date_range(b)]

    def is_bank_reconciled(self, bank_id: str) -> bool:
        """Check if a bank entry is reconciled."""
        return bank_id in self._reconciled_bank_ids

    def get_reconciliation_for_bank(self, bank_id: str) -> Optional[Reconciliation]:
        """Get the reconciliation for a bank entry, if any."""
        return self._reconciled_bank_ids.get(bank_id)

    def get_beacon_entries_for_reconciliation(self, rec: Reconciliation) -> List[BeaconEntry]:
        """Get the actual BeaconEntry objects for a reconciliation."""
        beacon_map = {b.id: b for b in self.beacon_entries}
        return [beacon_map[bid] for bid in rec.beacon_ids if bid in beacon_map]

    # -------------------------------------------------------------------
    # Beacon candidate generation (the core of v2)
    # -------------------------------------------------------------------

    def get_candidates_for_bank(self, bank_txn: BankTransaction) -> List[BeaconCandidate]:
        """Get ranked beacon candidates for a bank entry.

        Returns candidates sorted by confidence (highest first), with
        rejected pairings at the end, marked as rejected.
        """
        rejected_beacon_ids = self._rejected_pairings_by_bank.get(bank_txn.id, set())

        # Get available beacon entries (not reconciled)
        available = [b for b in self.beacon_entries
                     if b.id not in self._reconciled_beacon_ids]

        # Generate 1-to-1 candidates
        candidates_1to1 = self._find_1to1_candidates(bank_txn, available)

        # Generate 1-to-2 candidates (if allowed)
        candidates_1to2 = []
        if self.allow_1_to_2:
            candidates_1to2 = self._find_1to2_candidates(bank_txn, available)

        # Combine all candidates
        all_candidates = candidates_1to1 + candidates_1to2

        # Mark rejected pairings
        for c in all_candidates:
            beacon_id_set = {b.id for b in c.beacon_entries}
            if beacon_id_set & rejected_beacon_ids:
                c.is_rejected = True

        # Sort: non-rejected first (by confidence desc), then rejected (by confidence desc)
        all_candidates.sort(key=lambda c: (c.is_rejected, -c.confidence_score))

        return all_candidates

    def _find_1to1_candidates(self, bank_txn: BankTransaction,
                               available: List[BeaconEntry]) -> List[BeaconCandidate]:
        """Find 1-to-1 beacon candidates for a bank entry."""
        candidates = []

        for beacon in available:
            if beacon.amount != bank_txn.amount:
                continue

            # Calculate scores
            date_score = self._calculate_date_score(bank_txn.date, beacon.date)
            if date_score == 0:
                continue

            # Check member number match first (best indicator)
            member_match_score = self._calculate_member_match_score(bank_txn, beacon)
            if member_match_score > 0:
                # Strong member match - use high confidence
                confidence = max(0.95, member_match_score)
                candidates.append(BeaconCandidate(
                    beacon_entries=[beacon],
                    confidence_score=confidence,
                    match_type="1-to-1",
                    amount_score=1.0,
                    date_score=date_score,
                    name_score=member_match_score
                ))
                continue

            name_score = self._calculate_name_score(bank_txn.description, beacon.payee)
            if self.match_beacon_detail and beacon.detail:
                detail_score = self._calculate_name_score(bank_txn.description, beacon.detail)
                name_score = max(name_score, detail_score)
            amount_score = self._calculate_amount_score(bank_txn.amount)

            # Skip if name is 0% and amount is common
            if name_score == 0 and bank_txn.amount in self.common_amounts:
                continue

            confidence = self._calculate_confidence(
                amount_score, date_score, name_score, bank_txn.amount
            )

            if confidence >= 0.1:
                candidates.append(BeaconCandidate(
                    beacon_entries=[beacon],
                    confidence_score=confidence,
                    match_type="1-to-1",
                    amount_score=amount_score,
                    date_score=date_score,
                    name_score=name_score
                ))

        return candidates

    def _find_1to2_candidates(self, bank_txn: BankTransaction,
                               available: List[BeaconEntry]) -> List[BeaconCandidate]:
        """Find 1-to-2 beacon pair candidates for a bank entry."""
        candidates = []
        bank_amount = bank_txn.amount
        bank_date = bank_txn.date

        # Build temporary index of available beacons by amount
        avail_by_amount: Dict[Decimal, List[BeaconEntry]] = defaultdict(list)
        avail_amounts: set = set()
        for b in available:
            avail_by_amount[b.amount].append(b)
            avail_amounts.add(b.amount)

        checked_pairs = set()

        for amount1 in avail_amounts:
            amount2 = bank_amount - amount1
            if amount2 not in avail_amounts:
                continue

            pair_key = tuple(sorted([amount1, amount2]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            beacons1 = avail_by_amount[amount1]
            beacons2 = avail_by_amount[amount2]

            if amount1 == amount2:
                for i, b1 in enumerate(beacons1):
                    date_score1 = self._calculate_date_score(bank_date, b1.date)
                    if date_score1 == 0:
                        continue
                    for b2 in beacons1[i+1:]:
                        if not self._trans_no_within_range(b1.trans_no, b2.trans_no, self.trans_no_limit):
                            continue
                        date_score2 = self._calculate_date_score(bank_date, b2.date)
                        if date_score2 == 0:
                            continue
                        candidate = self._create_1to2_candidate(bank_txn, b1, b2, date_score1, date_score2)
                        if candidate:
                            candidates.append(candidate)
            else:
                for b1 in beacons1:
                    date_score1 = self._calculate_date_score(bank_date, b1.date)
                    if date_score1 == 0:
                        continue
                    for b2 in beacons2:
                        if not self._trans_no_within_range(b1.trans_no, b2.trans_no, self.trans_no_limit):
                            continue
                        date_score2 = self._calculate_date_score(bank_date, b2.date)
                        if date_score2 == 0:
                            continue
                        candidate = self._create_1to2_candidate(bank_txn, b1, b2, date_score1, date_score2)
                        if candidate:
                            candidates.append(candidate)

        return candidates

    def _create_1to2_candidate(self, bank_txn: BankTransaction,
                                beacon1: BeaconEntry, beacon2: BeaconEntry,
                                date_score1: float, date_score2: float) -> Optional[BeaconCandidate]:
        """Create a 1-to-2 candidate from a beacon pair."""
        date_score = (date_score1 + date_score2) / 2

        # Check member match for both
        member_score1 = self._calculate_member_match_score(bank_txn, beacon1)
        member_score2 = self._calculate_member_match_score(bank_txn, beacon2)

        if member_score1 > 0 and member_score2 > 0:
            # Both beacons match members from bank description
            confidence = 0.95 * 0.9  # High confidence with 1-to-2 penalty
            return BeaconCandidate(
                beacon_entries=[beacon1, beacon2],
                confidence_score=confidence,
                match_type="1-to-2",
                amount_score=1.0,
                date_score=date_score,
                name_score=(member_score1 + member_score2) / 2
            )

        name_score1 = self._calculate_name_score(bank_txn.description, beacon1.payee)
        if self.match_beacon_detail and beacon1.detail:
            detail_score1 = self._calculate_name_score(bank_txn.description, beacon1.detail)
            name_score1 = max(name_score1, detail_score1)
        name_score2 = self._calculate_name_score(bank_txn.description, beacon2.payee)
        if self.match_beacon_detail and beacon2.detail:
            detail_score2 = self._calculate_name_score(bank_txn.description, beacon2.detail)
            name_score2 = max(name_score2, detail_score2)
        name_score = (name_score1 + name_score2) / 2

        is_common1 = beacon1.amount in self.common_amounts
        is_common2 = beacon2.amount in self.common_amounts

        if name_score == 0 and (is_common1 and is_common2):
            return None

        if is_common1 and is_common2:
            amount_score = 0.3
        elif is_common1 or is_common2:
            amount_score = 0.6
        else:
            amount_score = 1.0

        base_confidence = self._calculate_confidence(
            amount_score, date_score, name_score, bank_txn.amount
        )
        confidence = base_confidence * 0.9  # 10% penalty for 1-to-2

        if confidence < 0.1:
            return None

        return BeaconCandidate(
            beacon_entries=[beacon1, beacon2],
            confidence_score=confidence,
            match_type="1-to-2",
            amount_score=amount_score,
            date_score=date_score,
            name_score=name_score
        )

    # -------------------------------------------------------------------
    # Member number matching
    # -------------------------------------------------------------------

    def extract_member_numbers(self, description: str) -> List[str]:
        """Extract all member numbers from a bank description."""
        numbers = []

        u3a_pattern = r'u3a(\d+(?:and\d+)*)'
        u3a_matches = re.findall(u3a_pattern, description, flags=re.IGNORECASE)
        for match in u3a_matches:
            for num in re.split(r'and', match, flags=re.IGNORECASE):
                if num:
                    numbers.append(num)

        clean_desc = re.sub(r'u3a\d*(?:and\d+)*', '', description, flags=re.IGNORECASE)
        date_pattern = r'\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b'
        clean_desc = re.sub(date_pattern, '', clean_desc)
        invoice_pattern = r'\b(?:invoice|inv)\s*\d+'
        clean_desc = re.sub(invoice_pattern, '', clean_desc, flags=re.IGNORECASE)

        number_matches = re.findall(r'(\d+)', clean_desc)
        numbers.extend(number_matches)

        seen = set()
        unique_numbers = []
        for num in numbers:
            if num not in seen:
                seen.add(num)
                if int(num) <= 10000:
                    unique_numbers.append(num)

        return unique_numbers

    def lookup_member(self, mem_no: str) -> Optional[Dict]:
        """Look up a member by their member number."""
        return self.member_lookup.get(mem_no)

    def get_member_lookup_text(self, description: str) -> str:
        """Get member lookup text for display in GUI."""
        numbers = self.extract_member_numbers(description)

        if not numbers:
            return "No mem_no given"

        lines = []
        for num in numbers:
            member = self.lookup_member(num)
            if member:
                forename = member['forename']
                known_as = member['known_as']
                surname = member['surname']

                if known_as:
                    name = f"{forename} ({known_as}) {surname}"
                else:
                    name = f"{forename} {surname}"

                if member['status'].lower() != 'current':
                    name += f" ({member['status']})"
                lines.append(f"Member {num}: {name}")
            else:
                lines.append(f"{num} is an unknown mem_no")

        return "\n".join(lines)

    def _calculate_member_match_score(self, bank_txn: BankTransaction,
                                       beacon: BeaconEntry) -> float:
        """Check if a beacon matches via member number from bank description.

        Returns score > 0 if there's a member match, 0 otherwise.
        Checks both member_1 and member_2 fields on beacon.
        """
        member_numbers = self.extract_member_numbers(bank_txn.description)
        valid_numbers = [n for n in member_numbers if self.lookup_member(n) is not None]

        if not valid_numbers:
            return 0.0

        for num in valid_numbers:
            member = self.lookup_member(num)
            if not member:
                continue
            full_name = (member['forename'] + member['surname']).replace(' ', '').upper()

            # Check member_1
            m1 = beacon.member_1.replace(' ', '').upper()
            if m1 and m1 == full_name:
                return 0.95

            # Check member_2
            m2 = beacon.member_2.replace(' ', '').upper()
            if m2 and m2 == full_name:
                return 0.95

        return 0.0

    # -------------------------------------------------------------------
    # Scoring functions (preserved from v1)
    # -------------------------------------------------------------------

    def _calculate_date_score(self, bank_date: datetime,
                               beacon_date: datetime) -> float:
        """Calculate date proximity score (0-1)."""
        days_diff = (beacon_date - bank_date).days
        tolerance = self.date_tolerance_days

        if days_diff >= 0:
            if days_diff > tolerance:
                return 0.0
            if days_diff == 0:
                return 1.0
            elif days_diff == 1:
                return 0.95
            elif days_diff == 2:
                return 0.90
            elif days_diff == 3:
                return 0.80
            elif days_diff <= 7:
                return 0.60
            elif days_diff <= 14:
                return 0.40
            elif days_diff <= 28:
                return 0.25
            elif days_diff <= 42:
                return 0.15
            else:
                return 0.10
        else:
            abs_diff = abs(days_diff)
            if abs_diff == 1:
                return 0.50
            elif abs_diff == 2:
                return 0.25
            else:
                return 0.0

    def _calculate_name_score(self, bank_description: str,
                               beacon_payee: str) -> float:
        """Calculate name similarity score (0-1) based on surname matching."""
        bank_surnames = self._extract_potential_surnames(bank_description)
        beacon_surnames = self._extract_potential_surnames(beacon_payee)

        if not bank_surnames or not beacon_surnames:
            return 0.3

        best_score = 0.0
        for bank_name in bank_surnames:
            for beacon_name in beacon_surnames:
                score = self._compare_surnames(bank_name.lower(), beacon_name.lower())
                if score > best_score:
                    best_score = score
                    if best_score >= 0.9:
                        return best_score

        return best_score

    def _compare_surnames(self, bank_surname: str, beacon_surname: str) -> float:
        """Compare two surnames and return a similarity score (0-1)."""
        if not bank_surname or not beacon_surname:
            return 0.0

        if bank_surname == beacon_surname:
            return 0.9

        if len(bank_surname) >= 5 and len(beacon_surname) >= 5:
            if beacon_surname.startswith(bank_surname) or bank_surname.startswith(beacon_surname):
                return 0.85

        if len(bank_surname) >= 5 and len(beacon_surname) >= 5:
            if bank_surname in beacon_surname or beacon_surname in bank_surname:
                return 0.7

        if len(bank_surname) >= 6 and len(beacon_surname) >= 6:
            similarity = SequenceMatcher(None, bank_surname, beacon_surname).ratio()
            if similarity >= 0.9:
                return similarity * 0.7

        return 0.0

    def _extract_potential_surnames(self, text: str) -> List[str]:
        """Extract all potential surnames from a text string."""
        clean_text = re.sub(r'\bu3a\d*\b', '', text, flags=re.IGNORECASE)
        clean_text = re.sub(r'\bsubs?\b', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'\brefunds?\b', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'\b\d+(/\d+)?\b', '', clean_text)
        clean_text = re.sub(r'[-]', ' ', clean_text)
        clean_text = ' '.join(clean_text.split())

        parts = clean_text.split()

        noise_words = {
            'PAYMENT', 'TRANSFER', 'CREDIT', 'DEBIT', 'REF', 'FT', 'TFR',
            'MISS', 'MR', 'MRS', 'MS', 'DR', 'PROF',
            'THE', 'AND', 'FOR', 'WITH'
        }

        potential_surnames = []
        for p in parts:
            clean_p = re.sub(r"'", '', p)
            if re.match(r'^[A-Za-z]+$', clean_p) and len(p) > 2 and p.upper() not in noise_words:
                potential_surnames.append(p.upper())

        return potential_surnames

    def _calculate_amount_score(self, amount: Decimal) -> float:
        """Calculate amount score based on whether it's a common amount."""
        if amount in self.common_amounts:
            return 0.3
        return 1.0

    def _calculate_confidence(self, amount_score: float, date_score: float,
                              name_score: float, amount: Decimal) -> float:
        """Calculate overall confidence score."""
        if amount in self.common_amounts:
            weights = {'amount': 0.1, 'date': 0.45, 'name': 0.45}
        else:
            weights = {'amount': 0.3, 'date': 0.35, 'name': 0.35}

        confidence = (
            weights['amount'] * amount_score +
            weights['date'] * date_score +
            weights['name'] * name_score
        )

        return min(1.0, max(0.0, confidence))

    def _trans_no_within_range(self, trans_no1: str, trans_no2: str, max_diff: int) -> bool:
        """Check if two transaction numbers are within max_diff of each other."""
        try:
            num1 = int(trans_no1)
            num2 = int(trans_no2)
            return abs(num1 - num2) <= max_diff
        except (ValueError, TypeError):
            match1 = re.search(r'(\d+)', str(trans_no1))
            match2 = re.search(r'(\d+)', str(trans_no2))
            if match1 and match2:
                return abs(int(match1.group(1)) - int(match2.group(1))) <= max_diff
            return False

    # -------------------------------------------------------------------
    # Reconciliation actions
    # -------------------------------------------------------------------

    def reconcile(self, bank_txn: BankTransaction, candidate: BeaconCandidate) -> Tuple[bool, str]:
        """Reconcile a bank entry with a beacon candidate.

        Returns (success, message).
        """
        # Verify amount match
        beacon_total = sum(b.amount for b in candidate.beacon_entries)
        if bank_txn.amount != beacon_total:
            return False, f"Amount mismatch: Bank £{bank_txn.amount} != Beacon total £{beacon_total}"

        # Check bank isn't already reconciled
        if bank_txn.id in self._reconciled_bank_ids:
            return False, f"Bank entry {bank_txn.id} is already reconciled"

        # Check beacons aren't already reconciled
        for beacon in candidate.beacon_entries:
            if beacon.id in self._reconciled_beacon_ids:
                return False, f"Beacon {beacon.id} ({beacon.payee}) is already reconciled"

        # Create reconciliation
        rec = Reconciliation(
            bank_id=bank_txn.id,
            beacon_ids=[b.id for b in candidate.beacon_entries],
            match_type=candidate.match_type,
            status="reconciled"
        )
        self.reconciliations.append(rec)

        # Update lookups
        self._reconciled_bank_ids[bank_txn.id] = rec
        for beacon in candidate.beacon_entries:
            self._reconciled_beacon_ids.add(beacon.id)
            beacon.matched = True

        # Remove any rejected pairings for this bank entry (no longer relevant)
        self.rejected_pairings = [
            rp for rp in self.rejected_pairings
            if rp['bank_id'] != bank_txn.id
        ]
        self._rejected_pairings_by_bank.pop(bank_txn.id, None)

        self.save_state()
        return True, "Reconciled successfully"

    def reconcile_manual(self, bank_txn: BankTransaction,
                         trans_nos: List[str]) -> Tuple[bool, str]:
        """Manually reconcile a bank entry with specific beacon trans_nos.

        Returns (success, message).
        """
        beacon_entries = []
        for trans_no in trans_nos:
            beacon = self.find_beacon_by_trans_no(trans_no)
            if beacon is None:
                return False, f"Trans_no '{trans_no}' not found"
            if beacon.id in self._reconciled_beacon_ids:
                return False, f"Trans_no '{trans_no}' is already reconciled"
            beacon_entries.append(beacon)

        beacon_total = sum(b.amount for b in beacon_entries)
        if bank_txn.amount != beacon_total:
            return False, f"Amount mismatch: Bank £{bank_txn.amount} != Beacon total £{beacon_total}"

        if bank_txn.id in self._reconciled_bank_ids:
            return False, f"Bank entry {bank_txn.id} is already reconciled"

        match_type = "manual"
        rec = Reconciliation(
            bank_id=bank_txn.id,
            beacon_ids=[b.id for b in beacon_entries],
            match_type=match_type,
            status="reconciled"
        )
        self.reconciliations.append(rec)

        self._reconciled_bank_ids[bank_txn.id] = rec
        for beacon in beacon_entries:
            self._reconciled_beacon_ids.add(beacon.id)
            beacon.matched = True

        self.rejected_pairings = [
            rp for rp in self.rejected_pairings
            if rp['bank_id'] != bank_txn.id
        ]
        self._rejected_pairings_by_bank.pop(bank_txn.id, None)

        self.save_state()
        return True, f"Manually reconciled with {len(beacon_entries)} beacon entries"

    def mark_resolved(self, bank_txn: BankTransaction, comment: str) -> Tuple[bool, str]:
        """Mark a bank entry as manually resolved (no beacon match expected).

        Returns (success, message).
        """
        if bank_txn.id in self._reconciled_bank_ids:
            return False, f"Bank entry {bank_txn.id} is already reconciled"

        rec = Reconciliation(
            bank_id=bank_txn.id,
            beacon_ids=[],
            match_type="resolved",
            status="manually_resolved",
            comment=comment
        )
        self.reconciliations.append(rec)
        self._reconciled_bank_ids[bank_txn.id] = rec

        self.save_state()
        return True, "Marked as manually resolved"

    def unreconcile(self, bank_id: str) -> Tuple[bool, str]:
        """Undo a reconciliation.

        Returns (success, message).
        """
        rec = self._reconciled_bank_ids.get(bank_id)
        if rec is None:
            return False, f"Bank entry {bank_id} is not reconciled"

        # Remove reconciliation
        self.reconciliations.remove(rec)
        del self._reconciled_bank_ids[bank_id]

        # Unmark beacon entries
        for beacon_id in rec.beacon_ids:
            self._reconciled_beacon_ids.discard(beacon_id)
            for beacon in self.beacon_entries:
                if beacon.id == beacon_id:
                    beacon.matched = False

        self.save_state()
        return True, "Reconciliation undone"

    def reject_pairing(self, bank_id: str, beacon_id: str):
        """Reject a specific bank/beacon pairing (persists across sessions)."""
        pairing = {'bank_id': bank_id, 'beacon_id': beacon_id}
        if pairing not in self.rejected_pairings:
            self.rejected_pairings.append(pairing)
            self._rejected_pairings_by_bank[bank_id].add(beacon_id)
            self.save_state()

    def unreject_pairing(self, bank_id: str, beacon_id: str):
        """Undo a rejected pairing."""
        pairing = {'bank_id': bank_id, 'beacon_id': beacon_id}
        if pairing in self.rejected_pairings:
            self.rejected_pairings.remove(pairing)
            self._rejected_pairings_by_bank[bank_id].discard(beacon_id)
            self.save_state()

    # -------------------------------------------------------------------
    # Auto-reconcile
    # -------------------------------------------------------------------

    def auto_reconcile(self) -> int:
        """Auto-reconcile high-confidence matches for unreconciled bank entries.

        For each unreconciled bank entry, gets the top candidate and reconciles
        it if it exceeds the confidence threshold. Only reconciles if the
        candidate is the only strong match (no ambiguity).

        Returns the number of auto-reconciled entries.
        """
        count = 0
        unreconciled = self.get_unreconciled_bank_entries()

        for bank_txn in unreconciled:
            candidates = self.get_candidates_for_bank(bank_txn)
            non_rejected = [c for c in candidates if not c.is_rejected]

            if not non_rejected:
                continue

            top = non_rejected[0]
            if not top.beacon_entries:
                continue

            is_common = bank_txn.amount in self.common_amounts
            threshold = (self.auto_reconcile_common_threshold if is_common
                        else self.auto_reconcile_other_threshold)

            if top.confidence_score > threshold:
                success, _ = self.reconcile(bank_txn, top)
                if success:
                    count += 1

        if count > 0:
            print(f"Auto-reconciled {count} entries")
        return count

    # -------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------

    def get_statistics(self) -> Dict:
        """Get reconciliation statistics (respects date range filter)."""
        in_range = [b for b in self.bank_transactions if self.is_bank_in_date_range(b)]
        in_range_ids = {b.id for b in in_range}

        total_bank = len(in_range)
        total_beacon = len(self.beacon_entries)

        reconciled = [r for r in self.reconciliations
                      if r.status == 'reconciled' and r.bank_id in in_range_ids]
        resolved = [r for r in self.reconciliations
                    if r.status == 'manually_resolved' and r.bank_id in in_range_ids]

        # Build bank amount lookup
        bank_by_id = {b.id: b for b in in_range}

        reconciled_amount = sum(
            bank_by_id[r.bank_id].amount
            for r in reconciled if r.bank_id in bank_by_id
        )
        resolved_amount = sum(
            bank_by_id[r.bank_id].amount
            for r in resolved if r.bank_id in bank_by_id
        )

        unreconciled_bank = [b for b in in_range
                             if b.id not in self._reconciled_bank_ids]
        unreconciled_amount = sum(b.amount for b in unreconciled_bank)

        return {
            'total_bank': total_bank,
            'total_beacon': total_beacon,
            'reconciled_count': len(reconciled),
            'reconciled_amount': reconciled_amount,
            'resolved_count': len(resolved),
            'resolved_amount': resolved_amount,
            'unreconciled_count': len(unreconciled_bank),
            'unreconciled_amount': unreconciled_amount,
            'unreconciled_beacon': total_beacon - len(self._reconciled_beacon_ids),
            'rejected_pairings': len(self.rejected_pairings),
        }

    # -------------------------------------------------------------------
    # Search helpers
    # -------------------------------------------------------------------

    def find_beacon_by_trans_no(self, trans_no: str) -> Optional[BeaconEntry]:
        """Find a beacon entry by its trans_no."""
        for entry in self.beacon_entries:
            if entry.trans_no == trans_no:
                return entry
        return None

    def find_bank_by_id(self, bank_id: str) -> Optional[BankTransaction]:
        """Find a bank transaction by its ID."""
        for txn in self.bank_transactions:
            if txn.id == bank_id:
                return txn
        return None

    def search_bank_entries(self, search_term: str) -> List[int]:
        """Search bank entries and return matching indices.

        Returns indices into self.bank_transactions.
        """
        term = search_term.strip().lower()
        if not term:
            return []

        results = []
        for i, bank in enumerate(self.bank_transactions):
            if term in bank.description.lower():
                results.append(i)
            elif term in bank.id.lower():
                results.append(i)
            elif term.lstrip('£') and self._is_amount_match(term, bank.amount):
                results.append(i)
            elif self._is_date_match(term, bank.date):
                results.append(i)
        return results

    def search_beacon_entries(self, search_term: str,
                               available_only: bool = False) -> List[BeaconEntry]:
        """Search beacon entries by various criteria.

        Args:
            search_term: The search term
            available_only: If True, only search un-reconciled beacons

        Returns matching BeaconEntry objects.
        """
        term = search_term.strip().lower()
        if not term:
            return []

        entries = self.beacon_entries
        if available_only:
            entries = [b for b in entries if b.id not in self._reconciled_beacon_ids]

        # Special keyword: "cheque" filters by payment_method
        if term == 'cheque':
            return [b for b in entries
                    if b.payment_method.lower() == 'cheque']

        results = []
        for beacon in entries:
            if term in beacon.payee.lower():
                results.append(beacon)
            elif term in beacon.trans_no.lower():
                results.append(beacon)
            elif term in beacon.id.lower():
                results.append(beacon)
            elif term in beacon.detail.lower():
                results.append(beacon)
            elif term.lstrip('£') and self._is_amount_match(term, beacon.amount):
                results.append(beacon)
            elif self._is_date_match(term, beacon.date):
                results.append(beacon)
        return results

    def _is_amount_match(self, term: str, amount: Decimal) -> bool:
        """Check if search term matches an amount (ignores sign)."""
        try:
            search_amount = Decimal(term.lstrip('£').strip())
            return abs(amount) == abs(search_amount)
        except Exception:
            return False

    def _is_date_match(self, term: str, date: datetime) -> bool:
        """Check if search term matches a date."""
        formats = [
            '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y',
            '%d %b %Y', '%d %B %Y', '%d-%b-%Y', '%d-%b-%y', '%Y-%m-%d',
        ]
        for fmt in formats:
            try:
                search_date = datetime.strptime(term, fmt)
                return date.date() == search_date.date()
            except ValueError:
                continue
        return False

    # -------------------------------------------------------------------
    # Consistency check
    # -------------------------------------------------------------------

    def check_consistency(self) -> List[Tuple[Reconciliation, str]]:
        """Check for inconsistencies in reconciliations.

        Returns a list of (reconciliation, reason) tuples.

        Checks:
        1. Each beacon entry appears in at most one reconciliation
        2. Each bank entry appears in at most one reconciliation
        3. For each reconciliation, bank amount == sum of beacon amounts
        """
        inconsistencies = []
        bank_by_id = {b.id: b for b in self.bank_transactions}
        beacon_by_id = {b.id: b for b in self.beacon_entries}

        # Check 1: Beacon uniqueness
        beacon_to_recs: Dict[str, List[Reconciliation]] = defaultdict(list)
        for rec in self.reconciliations:
            for bid in rec.beacon_ids:
                beacon_to_recs[bid].append(rec)

        reported_beacon_groups = set()
        for bid, recs in beacon_to_recs.items():
            if len(recs) > 1:
                key = frozenset(r.bank_id for r in recs)
                if key in reported_beacon_groups:
                    continue
                reported_beacon_groups.add(key)
                beacon = beacon_by_id.get(bid)
                beacon_desc = f"{beacon.payee} {chr(163)}{beacon.amount}" if beacon else bid
                rec_ids = ", ".join(r.bank_id for r in recs)
                inconsistencies.append(
                    (recs[0], f"Beacon {bid} ({beacon_desc}) is in multiple reconciliations: {rec_ids}")
                )

        # Check 2: Bank uniqueness
        bank_to_recs: Dict[str, List[Reconciliation]] = defaultdict(list)
        for rec in self.reconciliations:
            bank_to_recs[rec.bank_id].append(rec)

        for bank_id, recs in bank_to_recs.items():
            if len(recs) > 1:
                inconsistencies.append(
                    (recs[0], f"Bank {bank_id} appears in {len(recs)} reconciliations")
                )

        # Check 3: Amount matching
        for rec in self.reconciliations:
            if rec.status == 'manually_resolved':
                continue  # No beacon entries to check
            bank = bank_by_id.get(rec.bank_id)
            if not bank:
                inconsistencies.append(
                    (rec, f"Bank {rec.bank_id} not found in loaded data")
                )
                continue
            beacon_total = Decimal('0')
            for bid in rec.beacon_ids:
                beacon = beacon_by_id.get(bid)
                if beacon:
                    beacon_total += beacon.amount
                else:
                    inconsistencies.append(
                        (rec, f"Beacon {bid} not found in loaded data (in reconciliation for {rec.bank_id})")
                    )
            if rec.beacon_ids and beacon_total != bank.amount:
                inconsistencies.append(
                    (rec, f"Amount mismatch: Bank {chr(163)}{bank.amount} != Beacon total {chr(163)}{beacon_total}")
                )

        return inconsistencies

    # -------------------------------------------------------------------
    # Member beacon lookup
    # -------------------------------------------------------------------

    def get_beacon_entries_for_member(self, member_name: str) -> List[BeaconEntry]:
        """Get all beacon entries where member_1 matches the given name.

        Args:
            member_name: The member name to match (forename+surname, case-insensitive)

        Returns list of BeaconEntry sorted by date.
        """
        if not member_name:
            return []
        name_upper = member_name.replace(' ', '').upper()
        results = []
        for beacon in self.beacon_entries:
            m1 = beacon.member_1.replace(' ', '').upper()
            if m1 and m1 == name_upper:
                results.append(beacon)
        results.sort(key=lambda b: b.date)
        return results

    def get_bank_id_for_beacon(self, beacon_id: str) -> Optional[str]:
        """Get the bank_id that a beacon is reconciled with, if any."""
        for rec in self.reconciliations:
            if beacon_id in rec.beacon_ids:
                return rec.bank_id
        return None

    # -------------------------------------------------------------------
    # Export / Reports
    # -------------------------------------------------------------------

    def _write_report_header(self, writer, report_name: str):
        """Write standard report header rows: title, report name, date/time."""
        title = self.config.get('title', 'Bank Beacon Reconciliation')
        writer.writerow([title])
        writer.writerow([report_name])
        writer.writerow([f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"])
        writer.writerow([])  # Blank separator row

    def export_reconciled_csv(self, filepath: str) -> int:
        """Export reconciled transactions to CSV. Returns rows written."""
        bank_by_id = {b.id: b for b in self.bank_transactions}
        beacon_by_id = {b.id: b for b in self.beacon_entries}

        rows = 0
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            self._write_report_header(writer, "Reconciled Transactions Report")
            writer.writerow([
                'bank_id', 'bank_date', 'bank_description', 'bank_amount',
                'beacon_trans_no', 'beacon_date', 'beacon_payee', 'beacon_amount',
                'beacon_member_1', 'match_type'
            ])
            for rec in self.reconciliations:
                if rec.status != 'reconciled':
                    continue
                bank = bank_by_id.get(rec.bank_id)
                if not bank:
                    continue
                for bid in rec.beacon_ids:
                    beacon = beacon_by_id.get(bid)
                    if not beacon:
                        continue
                    writer.writerow([
                        bank.id, bank.date.strftime('%d/%m/%Y'),
                        bank.description, str(bank.amount),
                        beacon.trans_no, beacon.date.strftime('%d/%m/%Y'),
                        beacon.payee, str(beacon.amount),
                        beacon.member_1, rec.match_type
                    ])
                    rows += 1
        return rows

    def export_unreconciled_bank_csv(self, filepath: str) -> int:
        """Export unreconciled bank transactions to CSV."""
        unreconciled = self.get_unreconciled_bank_entries()
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            self._write_report_header(writer, "Unreconciled Bank Transactions Report")
            writer.writerow(['bank_id', 'date', 'type', 'description', 'amount'])
            for bank in unreconciled:
                writer.writerow([
                    bank.id, bank.date.strftime('%d/%m/%Y'),
                    bank.type, bank.description, str(bank.amount)
                ])
        return len(unreconciled)

    def export_unreconciled_beacon_csv(self, filepath: str) -> int:
        """Export unreconciled beacon entries to CSV."""
        unreconciled = [b for b in self.beacon_entries
                        if b.id not in self._reconciled_beacon_ids]
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            self._write_report_header(writer, "Unreconciled Beacon Entries Report")
            writer.writerow(['trans_no', 'date', 'payee', 'amount', 'member_1', 'detail'])
            for beacon in unreconciled:
                writer.writerow([
                    beacon.trans_no, beacon.date.strftime('%d/%m/%Y'),
                    beacon.payee, str(beacon.amount),
                    beacon.member_1, beacon.detail
                ])
        return len(unreconciled)

    def export_resolved_csv(self, filepath: str) -> int:
        """Export manually resolved bank transactions to CSV."""
        bank_by_id = {b.id: b for b in self.bank_transactions}
        resolved = [r for r in self.reconciliations if r.status == 'manually_resolved']

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            self._write_report_header(writer, "Manually Resolved Transactions Report")
            writer.writerow(['bank_id', 'date', 'type', 'description', 'amount', 'comment'])
            for rec in resolved:
                bank = bank_by_id.get(rec.bank_id)
                if not bank:
                    continue
                writer.writerow([
                    bank.id, bank.date.strftime('%d/%m/%Y'),
                    bank.type, bank.description, str(bank.amount),
                    rec.comment
                ])
        return len(resolved)

    def export_stats_summary(self, filepath: str):
        """Export a stats summary report."""
        title = self.config.get('title', 'Bank Beacon Reconciliation')
        stats = self.get_statistics()
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"{title}\n")
            f.write(f"Summary Report\n")
            f.write(f"Version: {VERSION}\n")
            f.write(f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write(f"Data folder: {self.data_dir}\n")
            f.write(f"{'='*60}\n\n")
            f.write(f"Bank transactions:      {stats['total_bank']}\n")
            f.write(f"Beacon entries:         {stats['total_beacon']}\n\n")
            f.write(f"Reconciled:             {stats['reconciled_count']} "
                    f"(£{stats['reconciled_amount']:.2f})\n")
            f.write(f"Manually resolved:      {stats['resolved_count']} "
                    f"(£{stats['resolved_amount']:.2f})\n")
            f.write(f"Un-reconciled bank:     {stats['unreconciled_count']} "
                    f"(£{stats['unreconciled_amount']:.2f})\n")
            f.write(f"Un-reconciled beacon:   {stats['unreconciled_beacon']}\n")
            f.write(f"Rejected pairings:      {stats['rejected_pairings']}\n")


# ---------------------------------------------------------------------------
# State migration (v1 -> v2)
# ---------------------------------------------------------------------------

def migrate_v1_state(v1_state_path: str, v2_state_path: str):
    """Migrate a v1 reconciliation_state.json to v2 format.

    Converts confirmed_matches -> reconciliations.
    Ignores rejected_matches and rejected_bank_ids (not relevant in v2).
    """
    with open(v1_state_path, 'r', encoding='utf-8') as f:
        v1_state = json.load(f)

    reconciliations = []
    for match in v1_state.get('confirmed_matches', []):
        status_val = match.get('status', 'confirmed')

        if status_val == 'manually_resolved':
            rec = Reconciliation(
                bank_id=match['bank_transaction']['id'],
                beacon_ids=[],
                match_type='resolved',
                status='manually_resolved',
                comment=match.get('comment', '')
            )
        else:
            # confirmed or manual_match -> reconciled
            beacon_ids = [b['id'] for b in match.get('beacon_entries', [])]
            rec = Reconciliation(
                bank_id=match['bank_transaction']['id'],
                beacon_ids=beacon_ids,
                match_type=match.get('match_type', '1-to-1'),
                status='reconciled'
            )
        reconciliations.append(rec)

    v2_state = {
        'version': VERSION,
        'reconciliations': [r.to_dict() for r in reconciliations],
        'rejected_pairings': []
    }

    with open(v2_state_path, 'w', encoding='utf-8') as f:
        json.dump(v2_state, f, indent=2)

    print(f"Migrated {len(reconciliations)} reconciliations from v1 to v2")
    return len(reconciliations)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Main function for command-line usage."""
    import sys

    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    system = ReconciliationSystem(data_dir=data_dir)
    system.load_data()

    print(f"Bank Beacon Reconciliation v{VERSION}")
    print(f"Loaded {len(system.bank_transactions)} bank transactions")
    print(f"Loaded {len(system.beacon_entries)} beacon entries")

    stats = system.get_statistics()
    print(f"\n--- Statistics ---")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
