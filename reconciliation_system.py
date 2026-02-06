"""
Bank Beacon Reconciliation System
Core matching logic for reconciling bank transactions with accounting entries.

Features:
- 1-to-1 and 1-to-2 matching
- Common amount weighting (£13, £9.50, £6.50)
- Date proximity matching (within 7 days)
- Name similarity matching (surname + initial)
- Beacon exclusivity (each Beacon matches only one Bank transaction)
- Auto-confirmation of high-confidence matches
- Optimized for large datasets with progress reporting
"""

import csv
import json
import os
import inspect
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple, Dict, Callable
from difflib import SequenceMatcher
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum


def debug_log(message: str):
    """Print debug message with line number."""
    frame = inspect.currentframe().f_back
    print(f"[DEBUG L{frame.f_lineno}] {message}")


class MatchStatus(Enum):
    """Status of a match decision."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    MANUAL_MATCH = "manual_match"
    MANUALLY_RESOLVED = "manually_resolved"


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
            raw_data=data.get('raw_data', {}),
            matched=data.get('matched', False)
        )


@dataclass
class MatchSuggestion:
    """Represents a suggested match between bank and beacon transactions."""
    id: str
    bank_transaction: BankTransaction
    beacon_entries: List[BeaconEntry]  # 1 or more entries (can be empty for manually_resolved)
    confidence_score: float
    match_type: str  # "1-to-1", "1-to-2", "manual", or "resolved"
    status: MatchStatus = MatchStatus.PENDING
    amount_score: float = 0.0
    date_score: float = 0.0
    name_score: float = 0.0
    comment: str = ""  # Optional comment for manually resolved items

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'bank_transaction': self.bank_transaction.to_dict(),
            'beacon_entries': [e.to_dict() for e in self.beacon_entries],
            'confidence_score': self.confidence_score,
            'match_type': self.match_type,
            'status': self.status.value,
            'amount_score': self.amount_score,
            'date_score': self.date_score,
            'name_score': self.name_score,
            'comment': self.comment
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'MatchSuggestion':
        return cls(
            id=data['id'],
            bank_transaction=BankTransaction.from_dict(data['bank_transaction']),
            beacon_entries=[BeaconEntry.from_dict(e) for e in data['beacon_entries']],
            confidence_score=data['confidence_score'],
            match_type=data['match_type'],
            status=MatchStatus(data['status']),
            amount_score=data.get('amount_score', 0.0),
            date_score=data.get('date_score', 0.0),
            name_score=data.get('name_score', 0.0),
            comment=data.get('comment', '')
        )


class ReconciliationSystem:
    """Main reconciliation system for matching bank and beacon transactions."""

    # Common amounts that are weak matching signals
    COMMON_AMOUNTS = [Decimal('13.00'), Decimal('9.50'), Decimal('6.50')]

    # Auto-confirm thresholds
    AUTO_CONFIRM_COMMON_THRESHOLD = 0.90  # >90% for common amounts
    AUTO_CONFIRM_OTHER_THRESHOLD = 0.80   # >80% for other amounts

    # Default date tolerance in days (can be overridden per-call)
    DEFAULT_DATE_TOLERANCE_DAYS = 7

    def __init__(self,
                 bank_file: str = "Bank_Transactions.csv",
                 beacon_file: str = "Beacon_Entries.csv",
                 state_file: str = "reconciliation_state.json",
                 member_lookup_file: str = "member_lookup.csv",
                 base_dir: str = None):
        # Use script directory as base if not specified
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = base_dir

        # Resolve file paths relative to base directory
        self.bank_file = os.path.join(base_dir, bank_file) if not os.path.isabs(bank_file) else bank_file
        self.beacon_file = os.path.join(base_dir, beacon_file) if not os.path.isabs(beacon_file) else beacon_file
        self.state_file = os.path.join(base_dir, state_file) if not os.path.isabs(state_file) else state_file
        self.member_lookup_file = os.path.join(base_dir, member_lookup_file) if not os.path.isabs(member_lookup_file) else member_lookup_file

        self.bank_transactions: List[BankTransaction] = []
        self.beacon_entries: List[BeaconEntry] = []
        self.match_suggestions: List[MatchSuggestion] = []
        self.confirmed_matches: List[MatchSuggestion] = []
        self.rejected_matches: List[MatchSuggestion] = []

        # Member lookup dictionary: mem_no -> {status, forename, surname}
        self.member_lookup: Dict[str, Dict] = {}

        # Track which beacon entries are already matched
        self.matched_beacon_ids: set = set()
        # Track which bank transactions have been rejected (to restore status on reload)
        self.rejected_bank_ids: set = set()

        # Index for fast lookups (built during generate_suggestions)
        self._beacon_by_amount: Dict[Decimal, List[BeaconEntry]] = {}
        self._beacon_amounts: set = set()

        # Progress callback
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None

        # Date tolerance for matching (can be changed at runtime)
        self.date_tolerance_days = self.DEFAULT_DATE_TOLERANCE_DAYS

    def load_data(self):
        """Load transactions from CSV files."""
        self.bank_transactions = self._load_bank_transactions()
        self.beacon_entries = self._load_beacon_entries()
        self._load_member_lookup()
        self._load_state()

    def _parse_bank_date(self, date_str: str) -> datetime:
        """Parse bank date string, trying multiple formats.

        Raises ValueError if no format matches.
        """
        formats = [
            '%d-%b-%y',      # 17-Mar-25 (original format)
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
        """Load bank transactions from CSV."""
        transactions = []

        if not os.path.exists(self.bank_file):
            return transactions

        with open(self.bank_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                try:
                    # Parse date using multi-format parser
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

        return transactions

    def _load_beacon_entries(self) -> List[BeaconEntry]:
        """Load beacon entries from CSV."""
        entries = []

        if not os.path.exists(self.beacon_file):
            return entries

        with open(self.beacon_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                try:
                    # Parse date in format DD/MM/YYYY
                    date = datetime.strptime(row['date'].strip(), '%d/%m/%Y')
                    amount = Decimal(row['amount'].strip().replace(',', ''))

                    entry = BeaconEntry(
                        id=f"BEACON_{idx:04d}",
                        date=date,
                        trans_no=row['trans_no'].strip(),
                        payee=row['payee'].strip(),
                        amount=amount,
                        detail=row.get('detail', '').strip(),
                        raw_data=dict(row)
                    )
                    entries.append(entry)
                except (ValueError, KeyError) as e:
                    print(f"Warning: Could not parse beacon row {idx}: {e}")

        return entries

    def _load_member_lookup(self):
        """Load member lookup from CSV file."""
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

    def extract_member_numbers(self, description: str) -> List[str]:
        """Extract all member numbers from a bank description.

        Extracts:
        - Standalone numbers (e.g., "823", "1783")
        - Numbers from U3A references (e.g., "U3A1679" -> "1679")
        - Numbers in patterns like "1786/1785"
        - Numbers concatenated with text (e.g., "1607HALL" -> "1607", "WHITTINGTON551" -> "551")
        - Numbers separated by AND (e.g., "U3A1076AND1077" -> "1076", "1077")

        Filters out:
        - Numbers > 10000 as they are not member numbers
        - Numbers that are part of dates (e.g., "2/12/25", "12/01/2025")
        - Numbers immediately following "Invoice" or "inv"
        """
        import re

        numbers = []

        # Extract numbers from U3A references, including AND-separated (e.g., U3A1076AND1077)
        # First handle U3A followed by numbers with possible AND separators
        u3a_pattern = r'u3a(\d+(?:and\d+)*)'
        u3a_matches = re.findall(u3a_pattern, description, flags=re.IGNORECASE)
        for match in u3a_matches:
            # Split on AND to get individual numbers
            for num in re.split(r'and', match, flags=re.IGNORECASE):
                if num:
                    numbers.append(num)

        # Remove ALL U3A references (with or without attached numbers) to avoid extracting "3" from "U3A"
        clean_desc = re.sub(r'u3a\d*(?:and\d+)*', '', description, flags=re.IGNORECASE)

        # Remove British dates (e.g., "2/12/25", "12/01/2025", "2-12-25", "12-01-2025")
        # Pattern matches: d/m/yy, dd/mm/yy, d/m/yyyy, dd/mm/yyyy (with / or - separator)
        date_pattern = r'\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b'
        clean_desc = re.sub(date_pattern, '', clean_desc)

        # Remove invoice numbers (numbers immediately following "Invoice" or "inv")
        # e.g., "Invoice 12345", "inv12345", "INV 12345"
        invoice_pattern = r'\b(?:invoice|inv)\s*\d+'
        clean_desc = re.sub(invoice_pattern, '', clean_desc, flags=re.IGNORECASE)

        # Extract all digit sequences (handles concatenated like "1607HALL", "WHITTINGTON551", "1552REA")
        # This finds any sequence of digits, regardless of word boundaries
        number_matches = re.findall(r'(\d+)', clean_desc)
        numbers.extend(number_matches)

        # Remove duplicates while preserving order, and filter out numbers > 10000
        seen = set()
        unique_numbers = []
        for num in numbers:
            if num not in seen:
                seen.add(num)
                # Filter out large numbers (not member numbers)
                if int(num) <= 10000:
                    unique_numbers.append(num)

        return unique_numbers

    def lookup_member(self, mem_no: str) -> Optional[Dict]:
        """Look up a member by their member number.

        Returns dict with 'status', 'forename', 'surname' if found, else None.
        """
        return self.member_lookup.get(mem_no)

    def get_member_lookup_text(self, description: str) -> str:
        """Get member lookup text for display in GUI.

        Returns formatted text showing member info for all numbers in description.
        Format: "Member NNN: Forename (known_as) Surname (status)"
        - known_as only shown if non-empty
        - status only shown if not "current"
        """
        numbers = self.extract_member_numbers(description)

        if not numbers:
            return "No mem_no given"

        lines = []
        for num in numbers:
            member = self.lookup_member(num)
            if member:
                # Build name: Forename (known_as) Surname
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

    def _load_state(self):
        """Load saved state from JSON file."""
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)

            # Load matched beacon IDs
            self.matched_beacon_ids = set(state.get('matched_beacon_ids', []))

            # Load confirmed matches
            self.confirmed_matches = [
                MatchSuggestion.from_dict(m)
                for m in state.get('confirmed_matches', [])
            ]

            # Load rejected bank IDs
            self.rejected_bank_ids = set(state.get('rejected_bank_ids', []))

            # Load rejected matches
            self.rejected_matches = [
                MatchSuggestion.from_dict(m)
                for m in state.get('rejected_matches', [])
            ]

            # Mark beacon entries as matched
            for entry in self.beacon_entries:
                if entry.id in self.matched_beacon_ids:
                    entry.matched = True

        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not load state: {e}")

    def save_state(self):
        """Save current state to JSON file."""
        state = {
            'matched_beacon_ids': list(self.matched_beacon_ids),
            'confirmed_matches': [m.to_dict() for m in self.confirmed_matches],
            'rejected_bank_ids': list(self.rejected_bank_ids),
            'rejected_matches': [m.to_dict() for m in self.rejected_matches]
        }

        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def _build_beacon_index(self, available_beacon: List[BeaconEntry]):
        """Build index of beacon entries by amount for fast lookup."""
        self._beacon_by_amount = defaultdict(list)
        self._beacon_amounts = set()

        for beacon in available_beacon:
            self._beacon_by_amount[beacon.amount].append(beacon)
            self._beacon_amounts.add(beacon.amount)

    def _report_progress(self, current: int, total: int, message: str):
        """Report progress if callback is set."""
        if self.progress_callback:
            self.progress_callback(current, total, message)

    def _find_beacon_by_member_name(self, member_name: str, available_beacon: List[BeaconEntry]) -> List[BeaconEntry]:
        """Find beacon entries where member_1 matches the given member name.

        Args:
            member_name: The name to match (forename+surname concatenated, no space)
            available_beacon: List of available beacon entries

        Returns:
            List of matching beacon entries (up to 10)
        """
        matches = []
        member_name_upper = member_name.upper()

        for beacon in available_beacon:
            # Check member_1 field in raw_data
            member_1 = beacon.raw_data.get('member_1', '').strip()
            if member_1:
                # Remove spaces for comparison
                member_1_clean = member_1.replace(' ', '').upper()
                if member_1_clean == member_name_upper:
                    matches.append(beacon)
                    if len(matches) >= 10:
                        break

        return matches

    def _generate_member_number_matches(self, bank_to_process: List[BankTransaction],
                                         available_beacon: List[BeaconEntry],
                                         suggestion_id: int) -> tuple:
        """Generate matches based on member numbers in bank descriptions.

        This is the first matching step that:
        a) If bank has 1 valid member number: generate 1-to-1 matches
        b) If bank has 2 valid member numbers: generate 1-to-2 matches

        Returns:
            Tuple of (matched_bank_ids, new_suggestion_id)
        """
        matched_bank_ids = set()

        for bank_txn in bank_to_process:
            # Extract member numbers from description
            member_numbers = self.extract_member_numbers(bank_txn.description)

            # Filter to valid member numbers (ones that exist in lookup)
            valid_numbers = [n for n in member_numbers if self.lookup_member(n) is not None]

            if not valid_numbers:
                continue

            # Get member names for each valid number
            member_names = []
            for num in valid_numbers[:2]:  # Only use first 2 valid numbers
                member = self.lookup_member(num)
                if member:
                    # Concatenate forename+surname without space
                    full_name = member['forename'] + member['surname']
                    member_names.append((num, full_name))

            if len(member_names) == 1:
                # 1-to-1 match: find beacon entries for this member
                num, name = member_names[0]
                matching_beacons = self._find_beacon_by_member_name(name, available_beacon)

                # Generate a suggestion for each matching beacon
                for beacon in matching_beacons:
                    if beacon.amount == bank_txn.amount:
                        match = MatchSuggestion(
                            id=f"MATCH_{suggestion_id:04d}",
                            bank_transaction=bank_txn,
                            beacon_entries=[beacon],
                            confidence_score=0.95,  # High confidence for member number match
                            match_type="1-to-1",
                            amount_score=1.0,
                            date_score=0.5,  # Date not checked here
                            name_score=1.0
                        )
                        self.match_suggestions.append(match)
                        suggestion_id += 1
                        matched_bank_ids.add(bank_txn.id)

            elif len(member_names) >= 2:
                # 1-to-2 match: find beacon entries for both members
                num1, name1 = member_names[0]
                num2, name2 = member_names[1]

                beacons1 = self._find_beacon_by_member_name(name1, available_beacon)
                beacons2 = self._find_beacon_by_member_name(name2, available_beacon)

                # Try to find a pair that sums to the bank amount
                for b1 in beacons1:
                    for b2 in beacons2:
                        if b1.id != b2.id and b1.amount + b2.amount == bank_txn.amount:
                            match = MatchSuggestion(
                                id=f"MATCH_{suggestion_id:04d}",
                                bank_transaction=bank_txn,
                                beacon_entries=[b1, b2],
                                confidence_score=0.95,  # High confidence for member number match
                                match_type="1-to-2",
                                amount_score=1.0,
                                date_score=0.5,
                                name_score=1.0
                            )
                            self.match_suggestions.append(match)
                            suggestion_id += 1
                            matched_bank_ids.add(bank_txn.id)
                            break
                    else:
                        continue
                    break

        return matched_bank_ids, suggestion_id

    def generate_suggestions(self, progress_callback: Callable[[int, int, str], None] = None,
                             include_confirmed: bool = False,
                             trans_no_limit: int = 5,
                             auto_confirm: bool = False,
                             date_tolerance_days: int = None) -> List[MatchSuggestion]:
        """Generate match suggestions for bank transactions.

        Args:
            progress_callback: Optional callback for progress updates
            include_confirmed: If True, include bank transactions that already have confirmed matches
            trans_no_limit: Maximum difference between trans_no values for 1-to-2 matches
            auto_confirm: If True, automatically confirm high-confidence matches
            date_tolerance_days: Maximum days difference for date matching (None = use current setting)
        """
        self.progress_callback = progress_callback
        self.trans_no_limit = trans_no_limit
        if date_tolerance_days is not None:
            self.date_tolerance_days = date_tolerance_days
        self.match_suggestions = []

        # Clean up confirmed_matches: remove entries that are no longer confirmed
        self.confirmed_matches = [m for m in self.confirmed_matches
                                  if m.status in (MatchStatus.CONFIRMED,
                                                  MatchStatus.MANUAL_MATCH,
                                                  MatchStatus.MANUALLY_RESOLVED)]

        # Start suggestion IDs from a number higher than any existing match
        # to avoid ID collisions
        max_existing_id = 0
        for match in self.confirmed_matches:
            if match.id.startswith('MATCH_'):
                try:
                    num = int(match.id.split('_')[1])
                    max_existing_id = max(max_existing_id, num)
                except (ValueError, IndexError):
                    pass
        suggestion_id = max_existing_id + 1
        debug_log(f"Starting suggestion_id from {suggestion_id}, confirmed_matches has {len(self.confirmed_matches)} entries")

        # Get bank transactions to process
        confirmed_bank_ids = {m.bank_transaction.id for m in self.confirmed_matches}

        if include_confirmed:
            # Include all bank transactions
            bank_to_process = list(self.bank_transactions)
        else:
            # Only unmatched bank transactions
            bank_to_process = [t for t in self.bank_transactions
                              if t.id not in confirmed_bank_ids]

        # Get available beacon entries (not matched)
        available_beacon = [e for e in self.beacon_entries
                          if e.id not in self.matched_beacon_ids]

        total_bank = len(bank_to_process)

        if total_bank == 0:
            # If include_confirmed, still add the confirmed matches
            if include_confirmed:
                for match in self.confirmed_matches:
                    self.match_suggestions.append(match)
            return self._sort_suggestions()

        # Step 1: Generate member number matches first
        self._report_progress(0, total_bank, "Matching by member numbers...")
        memno_matched_bank_ids, suggestion_id = self._generate_member_number_matches(
            bank_to_process, available_beacon, suggestion_id
        )

        # Build index for fast lookups
        self._report_progress(0, total_bank, "Building index...")
        self._build_beacon_index(available_beacon)

        # Step 2: Process remaining bank transactions (excluding those matched by member number)
        for idx, bank_txn in enumerate(bank_to_process):
            self._report_progress(idx + 1, total_bank, f"Processing {bank_txn.description[:20]}...")

            # Skip if already matched by member number
            if bank_txn.id in memno_matched_bank_ids:
                continue

            # Check if this bank transaction already has a confirmed match
            if bank_txn.id in confirmed_bank_ids:
                # Find and add the existing confirmed match
                for match in self.confirmed_matches:
                    if match.bank_transaction.id == bank_txn.id:
                        if match not in self.match_suggestions:
                            self.match_suggestions.append(match)
                        break
                continue

            # Find 1-to-1 matches (optimized)
            one_to_one = self._find_one_to_one_matches_fast(bank_txn)

            # Find 1-to-2 matches (optimized)
            one_to_two = self._find_one_to_two_matches_fast(bank_txn)

            # Combine and sort by confidence
            all_matches = one_to_one + one_to_two
            all_matches.sort(key=lambda m: m.confidence_score, reverse=True)

            # Add all matches above minimum confidence threshold
            MIN_CONFIDENCE_THRESHOLD = 0.1
            matches_added = 0
            for match in all_matches:
                if match.confidence_score >= MIN_CONFIDENCE_THRESHOLD:
                    match.id = f"MATCH_{suggestion_id:04d}"
                    self.match_suggestions.append(match)
                    suggestion_id += 1
                    matches_added += 1

            if matches_added == 0:
                # Create a suggestion with no beacon matches for unmatched bank txn
                suggestion = MatchSuggestion(
                    id=f"MATCH_{suggestion_id:04d}",
                    bank_transaction=bank_txn,
                    beacon_entries=[],
                    confidence_score=0.0,
                    match_type="no-match"
                )
                self.match_suggestions.append(suggestion)
                suggestion_id += 1

        # Auto-confirm high-confidence matches (only if requested)
        if auto_confirm:
            self._report_progress(total_bank, total_bank, "Auto-confirming high-confidence matches...")
            self._auto_confirm_matches()

        # Restore rejected status for previously rejected bank transactions
        self._restore_rejected_status()

        return self._sort_suggestions()

    def _sort_suggestions(self) -> List[MatchSuggestion]:
        """Sort suggestions by bank transaction, then status, then confidence."""
        # Status priority: confirmed=0, pending=1, skipped=2, rejected=3
        status_priority = {
            MatchStatus.CONFIRMED: 0,
            MatchStatus.PENDING: 1,
            MatchStatus.SKIPPED: 2,
            MatchStatus.REJECTED: 3,
        }

        self.match_suggestions.sort(key=lambda m: (
            m.bank_transaction.id,  # Group by bank transaction
            status_priority.get(m.status, 1),  # Then by status priority
            -m.confidence_score  # Then by confidence (highest first, hence negative)
        ))

        return self.match_suggestions

    def _restore_rejected_status(self):
        """Restore REJECTED status for previously rejected bank transactions."""
        for match in self.match_suggestions:
            if match.bank_transaction.id in self.rejected_bank_ids:
                if match.status == MatchStatus.PENDING:
                    match.status = MatchStatus.REJECTED
                    if match not in self.rejected_matches:
                        self.rejected_matches.append(match)

    def _find_one_to_one_matches_fast(self, bank_txn: BankTransaction) -> List[MatchSuggestion]:
        """Find 1-to-1 matches using indexed lookup."""
        matches = []

        # Only look at beacon entries with matching amount
        if bank_txn.amount not in self._beacon_by_amount:
            return matches

        for beacon in self._beacon_by_amount[bank_txn.amount]:
            # Calculate date score first (fast rejection)
            date_score = self._calculate_date_score(bank_txn.date, beacon.date)
            if date_score == 0:
                continue  # Outside date tolerance

            name_score = self._calculate_name_score(bank_txn.description, beacon.payee)
            amount_score = self._calculate_amount_score(bank_txn.amount)

            # Skip if name is 0% and amount is common - not a real match
            if name_score == 0 and bank_txn.amount in self.COMMON_AMOUNTS:
                continue

            # Calculate overall confidence
            confidence = self._calculate_confidence(
                amount_score, date_score, name_score, bank_txn.amount
            )

            match = MatchSuggestion(
                id="",  # Will be assigned later
                bank_transaction=bank_txn,
                beacon_entries=[beacon],
                confidence_score=confidence,
                match_type="1-to-1",
                amount_score=amount_score,
                date_score=date_score,
                name_score=name_score
            )
            matches.append(match)

        return matches

    def _trans_no_within_range(self, trans_no1: str, trans_no2: str, max_diff: int) -> bool:
        """Check if two transaction numbers are within max_diff of each other.

        Returns True if both trans_no values can be converted to integers and
        their absolute difference is <= max_diff. Returns False otherwise.
        """
        try:
            # Try direct integer conversion (works for pure numbers)
            num1 = int(trans_no1)
            num2 = int(trans_no2)
            return abs(num1 - num2) <= max_diff
        except (ValueError, TypeError):
            # Fall back to extracting numeric part for prefixed formats like "TRN001"
            import re
            match1 = re.search(r'(\d+)', str(trans_no1))
            match2 = re.search(r'(\d+)', str(trans_no2))
            if match1 and match2:
                return abs(int(match1.group(1)) - int(match2.group(1))) <= max_diff
            return False

    def _find_one_to_two_matches_fast(self, bank_txn: BankTransaction) -> List[MatchSuggestion]:
        """Find 1-to-2 matches using indexed lookup (optimized)."""
        matches = []
        bank_amount = bank_txn.amount
        bank_date = bank_txn.date

        # For each unique amount in beacon entries
        checked_pairs = set()

        for amount1 in self._beacon_amounts:
            amount2 = bank_amount - amount1

            # Skip if amount2 doesn't exist or if we've already checked this pair
            if amount2 not in self._beacon_amounts:
                continue

            pair_key = tuple(sorted([amount1, amount2]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            # Get beacons with these amounts
            beacons1 = self._beacon_by_amount[amount1]
            beacons2 = self._beacon_by_amount[amount2]

            # If same amount, need to handle differently
            if amount1 == amount2:
                # Pairs from same list
                for i, b1 in enumerate(beacons1):
                    # Check date early for b1
                    date_score1 = self._calculate_date_score(bank_date, b1.date)
                    if date_score1 == 0:
                        continue

                    for b2 in beacons1[i+1:]:
                        # Check if trans_no values are within 3 of each other
                        if not self._trans_no_within_range(b1.trans_no, b2.trans_no, self.trans_no_limit):
                            continue

                        # Check date early for b2
                        date_score2 = self._calculate_date_score(bank_date, b2.date)
                        if date_score2 == 0:
                            continue

                        match = self._create_two_match(bank_txn, b1, b2, date_score1, date_score2)
                        if match:
                            matches.append(match)
            else:
                # Pairs from different lists
                for b1 in beacons1:
                    date_score1 = self._calculate_date_score(bank_date, b1.date)
                    if date_score1 == 0:
                        continue

                    for b2 in beacons2:
                        # Check if trans_no values are within 3 of each other
                        if not self._trans_no_within_range(b1.trans_no, b2.trans_no, self.trans_no_limit):
                            continue

                        # Check date early for b2
                        date_score2 = self._calculate_date_score(bank_date, b2.date)
                        if date_score2 == 0:
                            continue

                        match = self._create_two_match(bank_txn, b1, b2, date_score1, date_score2)
                        if match:
                            matches.append(match)

        return matches

    def _create_two_match(self, bank_txn: BankTransaction,
                          beacon1: BeaconEntry, beacon2: BeaconEntry,
                          date_score1: float, date_score2: float) -> Optional[MatchSuggestion]:
        """Create a 1-to-2 match suggestion."""
        date_score = (date_score1 + date_score2) / 2

        # Calculate name scores
        name_score1 = self._calculate_name_score(bank_txn.description, beacon1.payee)
        name_score2 = self._calculate_name_score(bank_txn.description, beacon2.payee)
        name_score = (name_score1 + name_score2) / 2

        # Check if individual amounts are common
        is_common1 = beacon1.amount in self.COMMON_AMOUNTS
        is_common2 = beacon2.amount in self.COMMON_AMOUNTS

        # Skip if name is 0% and amounts are common - not a real match
        if name_score == 0 and (is_common1 and is_common2):
            return None

        # Calculate amount score based on whether amounts are common
        if is_common1 and is_common2:
            amount_score = 0.3  # Both common, weak signal
        elif is_common1 or is_common2:
            amount_score = 0.6  # One common
        else:
            amount_score = 1.0  # Neither common

        # Calculate overall confidence
        # 1-to-2 matches get a slight penalty since they're more complex
        base_confidence = self._calculate_confidence(
            amount_score, date_score, name_score, bank_txn.amount
        )
        confidence = base_confidence * 0.9  # 10% penalty for complexity

        return MatchSuggestion(
            id="",
            bank_transaction=bank_txn,
            beacon_entries=[beacon1, beacon2],
            confidence_score=confidence,
            match_type="1-to-2",
            amount_score=amount_score,
            date_score=date_score,
            name_score=name_score
        )

    def run_auto_confirm(self) -> int:
        """Run auto-confirmation on pending matches.

        Returns:
            Number of matches that were auto-confirmed.
        """
        return self._auto_confirm_matches()

    def _auto_confirm_matches(self) -> int:
        """Auto-confirm matches that exceed confidence thresholds.

        Returns:
            Number of matches that were auto-confirmed.
        """
        auto_confirmed = 0

        for match in self.match_suggestions:
            if match.status != MatchStatus.PENDING:
                continue
            if not match.beacon_entries:
                continue

            # Check if amount is common
            is_common = match.bank_transaction.amount in self.COMMON_AMOUNTS

            # Determine threshold
            if is_common:
                threshold = self.AUTO_CONFIRM_COMMON_THRESHOLD
            else:
                threshold = self.AUTO_CONFIRM_OTHER_THRESHOLD

            # Auto-confirm if above threshold
            if match.confidence_score > threshold:
                self.confirm_match(match)
                auto_confirmed += 1

        if auto_confirmed > 0:
            print(f"Auto-confirmed {auto_confirmed} high-confidence matches")

        return auto_confirmed

    def _calculate_date_score(self, bank_date: datetime,
                               beacon_date: datetime) -> float:
        """Calculate date proximity score (0-1).

        Beacon is typically entered AFTER bank transaction clears.
        - Beacon after bank: normal, allow up to self.date_tolerance_days
        - Beacon before bank: unusual, only allow 1-2 days

        The date_tolerance_days setting controls the maximum allowed date difference.
        """
        # Positive = beacon after bank (normal), negative = beacon before bank (unusual)
        days_diff = (beacon_date - bank_date).days
        tolerance = self.date_tolerance_days

        if days_diff >= 0:
            # Beacon AFTER bank (normal case)
            # Check against configurable tolerance
            if days_diff > tolerance:
                return 0.0    # Beyond tolerance, reject

            # Score based on how close the dates are
            if days_diff == 0:
                return 1.0    # Same day
            elif days_diff == 1:
                return 0.95   # Next day
            elif days_diff == 2:
                return 0.90
            elif days_diff == 3:
                return 0.80
            elif days_diff <= 7:
                return 0.60   # Within 1 week
            elif days_diff <= 14:
                return 0.40   # Within 2 weeks
            elif days_diff <= 28:
                return 0.25   # Within 4 weeks
            elif days_diff <= 42:
                return 0.15   # Within 6 weeks
            else:
                return 0.10   # Within tolerance but > 6 weeks
        else:
            # Beacon BEFORE bank (unusual case)
            abs_diff = abs(days_diff)
            if abs_diff == 1:
                return 0.50   # 1 day before - might be timing issue
            elif abs_diff == 2:
                return 0.25   # 2 days before
            else:
                return 0.0    # 3+ days before - reject

    def _calculate_name_score(self, bank_description: str,
                               beacon_payee: str) -> float:
        """Calculate name similarity score (0-1) based on surname matching.

        Compares ALL potential surnames from bank description against ALL
        potential surnames from beacon payee. Returns a match if ANY surname
        matches, supporting:
        - Different name orderings (FIRSTNAME SURNAME vs SURNAME FIRSTNAME)
        - Family member matching (account holder vs member being paid for)
        - Truncated bank names (ABERCROMB matching ABERCROMBIE)
        """
        # Extract potential surnames from both
        bank_surnames = self._extract_potential_surnames(bank_description)
        beacon_surnames = self._extract_potential_surnames(beacon_payee)

        if not bank_surnames or not beacon_surnames:
            return 0.3  # No names available, neutral score

        # Check each bank surname against each beacon surname
        best_score = 0.0

        for bank_name in bank_surnames:
            for beacon_name in beacon_surnames:
                score = self._compare_surnames(bank_name.lower(), beacon_name.lower())
                if score > best_score:
                    best_score = score
                    if best_score >= 0.9:
                        return best_score  # Early exit on strong match

        return best_score

    def _compare_surnames(self, bank_surname: str, beacon_surname: str) -> float:
        """Compare two surnames and return a similarity score (0-1).

        Handles:
        - Exact matches
        - Truncated names (bank names can be truncated, e.g., ABERCROMB vs ABERCROMBIE)
        - Typo tolerance for longer surnames
        """
        if not bank_surname or not beacon_surname:
            return 0.0

        # Exact match
        if bank_surname == beacon_surname:
            return 0.9  # Surname matches

        # Prefix matching for truncated bank names (at least 5 chars to avoid false positives)
        # Bank names are often truncated, so check if either is a prefix of the other
        if len(bank_surname) >= 5 and len(beacon_surname) >= 5:
            if beacon_surname.startswith(bank_surname) or bank_surname.startswith(beacon_surname):
                # Truncation detected - good match
                return 0.85

        # Substring matching for substantial names (at least 5 chars)
        if len(bank_surname) >= 5 and len(beacon_surname) >= 5:
            if bank_surname in beacon_surname or beacon_surname in bank_surname:
                return 0.7

        # Typo tolerance for longer surnames (6+ chars)
        # Short surnames (5 chars or less) need exact match - one letter difference
        # in "BARRY" vs "PARRY" is a completely different person
        if len(bank_surname) >= 6 and len(beacon_surname) >= 6:
            similarity = SequenceMatcher(None, bank_surname, beacon_surname).ratio()
            # Require very high similarity (90%+) for fuzzy match
            if similarity >= 0.9:
                return similarity * 0.7  # Cap at ~0.7 for fuzzy matches

        # No meaningful match
        return 0.0

    def _extract_potential_surnames(self, text: str) -> List[str]:
        """Extract all potential surnames from a text string.

        Returns a list of uppercase words that could be surnames (length > 2,
        not noise words). This approach handles both "FIRSTNAME SURNAME" and
        "SURNAME FIRSTNAME" orderings, as well as family member matching
        (e.g., account holder Margaret Kinnear paying for member Ruth Kinnear).
        """
        import re

        # Clean the text: remove U3A references, SUBS, REFUND, and numbers
        clean_text = re.sub(r'\bu3a\d*\b', '', text, flags=re.IGNORECASE)
        clean_text = re.sub(r'\bsubs?\b', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'\brefunds?\b', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'\b\d+(/\d+)?\b', '', clean_text)
        clean_text = re.sub(r'[-]', ' ', clean_text)
        clean_text = ' '.join(clean_text.split())

        parts = clean_text.split()

        # Noise words that should not be considered as names
        noise_words = {
            'PAYMENT', 'TRANSFER', 'CREDIT', 'DEBIT', 'REF', 'FT', 'TFR',
            'MISS', 'MR', 'MRS', 'MS', 'DR', 'PROF',
            'THE', 'AND', 'FOR', 'WITH'
        }

        # Accept words with letters and apostrophes (for O'Carroll, etc.)
        potential_surnames = []
        for p in parts:
            # Allow apostrophes in names
            clean_p = re.sub(r"'", '', p)  # Remove apostrophe for validation
            if re.match(r'^[A-Za-z]+$', clean_p) and len(p) > 2 and p.upper() not in noise_words:
                potential_surnames.append(p.upper())

        return potential_surnames

    def _extract_name(self, description: str) -> str:
        """Extract name from bank description.

        Returns a string with all potential surnames for matching.
        Bank names can be truncated by the bank (e.g., ABERCROMBIE -> ABERCROMB).
        """
        surnames = self._extract_potential_surnames(description)
        return ' '.join(surnames) if surnames else description.upper()

    def _normalize_name(self, payee: str) -> str:
        """Normalize beacon payee name - extract potential surnames.

        Uses the same approach as bank name extraction for consistent matching.
        """
        surnames = self._extract_potential_surnames(payee)
        return ' '.join(surnames) if surnames else payee.upper()

    def _calculate_amount_score(self, amount: Decimal) -> float:
        """Calculate amount score based on whether it's a common amount."""
        if amount in self.COMMON_AMOUNTS:
            return 0.3  # Common amount, weak signal
        return 1.0  # Uncommon amount, strong signal

    def _calculate_confidence(self, amount_score: float, date_score: float,
                              name_score: float, amount: Decimal) -> float:
        """Calculate overall confidence score."""
        # Weights for different factors
        # If amount is common, rely more heavily on date and name
        if amount in self.COMMON_AMOUNTS:
            # For common amounts, name and date are critical
            weights = {'amount': 0.1, 'date': 0.45, 'name': 0.45}
        else:
            # For uncommon amounts, amount match is more significant
            weights = {'amount': 0.3, 'date': 0.35, 'name': 0.35}

        confidence = (
            weights['amount'] * amount_score +
            weights['date'] * date_score +
            weights['name'] * name_score
        )

        return min(1.0, max(0.0, confidence))

    def confirm_match(self, match: MatchSuggestion):
        """Confirm a match and mark beacon entries as matched."""
        match.status = MatchStatus.CONFIRMED
        print(f"[DEBUG] confirm_match: set {match.id} status to CONFIRMED")
        self.confirmed_matches.append(match)

        # Mark beacon entries as matched
        confirmed_beacon_ids = set()
        for beacon in match.beacon_entries:
            self.matched_beacon_ids.add(beacon.id)
            confirmed_beacon_ids.add(beacon.id)
            beacon.matched = True

        # Auto-reject any other pending matches that involve these beacon entries
        print(f"[DEBUG] confirm_match: calling _reject_matches_with_beacons, match status={match.status}")
        self._reject_matches_with_beacons(confirmed_beacon_ids, exclude_match=match)
        print(f"[DEBUG] confirm_match: after _reject_matches_with_beacons, match status={match.status}")

        # Auto-reject any other pending matches for this bank transaction
        print(f"[DEBUG] confirm_match: calling _reject_matches_for_bank, match status={match.status}")
        self._reject_matches_for_bank(match.bank_transaction.id, exclude_match=match)
        print(f"[DEBUG] confirm_match: after _reject_matches_for_bank, match status={match.status}")

    def _reject_matches_for_bank(self, bank_id: str, exclude_match: MatchSuggestion = None):
        """Reject all pending matches for the specified bank transaction."""
        for suggestion in self.match_suggestions:
            # Use identity comparison (is) not value comparison (==)
            # because dataclass == compares all fields including status
            if suggestion is exclude_match:
                print(f"[DEBUG] _reject_matches_for_bank: skipping {suggestion.id} (is exclude_match)")
                continue
            if suggestion.status != MatchStatus.PENDING:
                continue

            if suggestion.bank_transaction.id == bank_id:
                print(f"[DEBUG] _reject_matches_for_bank: rejecting {suggestion.id} for bank {bank_id}")
                suggestion.status = MatchStatus.REJECTED
                self.rejected_bank_ids.add(bank_id)
                if suggestion not in self.rejected_matches:
                    self.rejected_matches.append(suggestion)

    def _reject_matches_with_beacons(self, beacon_ids: set, exclude_match: MatchSuggestion = None):
        """Reject all pending matches that involve any of the specified beacon entries."""
        for suggestion in self.match_suggestions:
            # Use identity comparison (is) not value comparison (==)
            # because dataclass == compares all fields including status
            if suggestion is exclude_match:
                continue
            if suggestion.status != MatchStatus.PENDING:
                continue

            # Check if this match involves any of the beacon entries
            for beacon in suggestion.beacon_entries:
                if beacon.id in beacon_ids:
                    suggestion.status = MatchStatus.REJECTED
                    self.rejected_bank_ids.add(suggestion.bank_transaction.id)
                    if suggestion not in self.rejected_matches:
                        self.rejected_matches.append(suggestion)
                    break

    def reject_match(self, match: MatchSuggestion):
        """Reject a match suggestion."""
        match.status = MatchStatus.REJECTED
        self.rejected_bank_ids.add(match.bank_transaction.id)
        if match not in self.rejected_matches:
            self.rejected_matches.append(match)

    def skip_match(self, match: MatchSuggestion):
        """Skip a match for later review."""
        match.status = MatchStatus.SKIPPED

    def undo_confirmation(self, match: MatchSuggestion):
        """Undo a confirmed match."""
        if match in self.confirmed_matches:
            self.confirmed_matches.remove(match)

        # Unmark beacon entries
        for beacon in match.beacon_entries:
            self.matched_beacon_ids.discard(beacon.id)
            beacon.matched = False

        match.status = MatchStatus.PENDING

    def undo_rejection(self, match: MatchSuggestion):
        """Undo a rejected match."""
        print(f"[DEBUG] undo_rejection: {match.id}, in rejected_matches={match in self.rejected_matches}")
        if match in self.rejected_matches:
            self.rejected_matches.remove(match)
            print(f"[DEBUG] undo_rejection: removed from rejected_matches")
        else:
            print(f"[DEBUG] undo_rejection: NOT in rejected_matches! len={len(self.rejected_matches)}")
            # Check if there's a match with same ID
            for rm in self.rejected_matches:
                if rm.id == match.id:
                    print(f"[DEBUG] undo_rejection: found match by ID, same object={rm is match}")
                    break

        self.rejected_bank_ids.discard(match.bank_transaction.id)
        match.status = MatchStatus.PENDING
        print(f"[DEBUG] undo_rejection: set status to PENDING")

    def update_match_status(self, match: MatchSuggestion, new_status: MatchStatus):
        """Update match status with proper handling."""
        old_status = match.status
        print(f"[DEBUG] update_match_status: {match.id} from {old_status} to {new_status}")

        # If changing from confirmed, undo the confirmation first
        if old_status == MatchStatus.CONFIRMED and new_status != MatchStatus.CONFIRMED:
            print(f"[DEBUG]   -> undo_confirmation")
            self.undo_confirmation(match)

        # If changing from manual match, undo similarly (unmark beacons)
        if old_status == MatchStatus.MANUAL_MATCH and new_status != MatchStatus.MANUAL_MATCH:
            print(f"[DEBUG]   -> undo manual match")
            self.undo_confirmation(match)  # Same logic as confirmed

        # If changing from manually resolved, remove from confirmed
        if old_status == MatchStatus.MANUALLY_RESOLVED and new_status != MatchStatus.MANUALLY_RESOLVED:
            print(f"[DEBUG]   -> undo manually resolved")
            if match in self.confirmed_matches:
                self.confirmed_matches.remove(match)
            match.status = MatchStatus.PENDING

        # If changing from rejected, undo the rejection first
        if old_status == MatchStatus.REJECTED and new_status != MatchStatus.REJECTED:
            print(f"[DEBUG]   -> undo_rejection")
            self.undo_rejection(match)
            print(f"[DEBUG]   -> after undo_rejection: status={match.status}")

        # If changing to confirmed, confirm the match
        if new_status == MatchStatus.CONFIRMED and old_status != MatchStatus.CONFIRMED:
            print(f"[DEBUG]   -> confirm_match")
            self.confirm_match(match)
            print(f"[DEBUG]   -> after confirm_match: status={match.status}")
        # If changing to rejected, reject the match
        elif new_status == MatchStatus.REJECTED and old_status != MatchStatus.REJECTED:
            print(f"[DEBUG]   -> reject_match")
            self.reject_match(match)
        else:
            match.status = new_status

        print(f"[DEBUG]   -> final status: {match.status}")

    def get_statistics(self) -> Dict:
        """Get reconciliation statistics including amount totals."""
        from decimal import Decimal

        total_bank = len(self.bank_transactions)
        total_beacon = len(self.beacon_entries)

        # Count different types of confirmed matches and their amounts
        confirmed_auto = [m for m in self.confirmed_matches
                         if m.status == MatchStatus.CONFIRMED]
        manual_matches = [m for m in self.confirmed_matches
                         if m.status == MatchStatus.MANUAL_MATCH]
        manually_resolved = [m for m in self.confirmed_matches
                            if m.status == MatchStatus.MANUALLY_RESOLVED]

        confirmed_count = len(confirmed_auto) + len(manual_matches) + len(manually_resolved)
        confirmed_amount = sum(m.bank_transaction.amount for m in confirmed_auto)
        manual_amount = sum(m.bank_transaction.amount for m in manual_matches)
        resolved_amount = sum(m.bank_transaction.amount for m in manually_resolved)
        total_confirmed_amount = confirmed_amount + manual_amount + resolved_amount

        matched_beacon = len(self.matched_beacon_ids)

        # Pending suggestions and their amounts
        pending = [m for m in self.match_suggestions
                  if m.status == MatchStatus.PENDING]
        pending_amount = sum(m.bank_transaction.amount for m in pending)

        rejected = [m for m in self.match_suggestions
                   if m.status == MatchStatus.REJECTED]
        rejected_amount = sum(m.bank_transaction.amount for m in rejected)

        skipped = [m for m in self.match_suggestions
                  if m.status == MatchStatus.SKIPPED]
        skipped_amount = sum(m.bank_transaction.amount for m in skipped)

        # Unmatched amounts
        unmatched_bank_count = total_bank - confirmed_count
        # Calculate unmatched bank amount from actual unmatched transactions
        confirmed_bank_ids = {m.bank_transaction.id for m in self.confirmed_matches}
        unmatched_bank_amount = sum(b.amount for b in self.bank_transactions
                                    if b.id not in confirmed_bank_ids)

        return {
            'total_bank_transactions': total_bank,
            'total_beacon_entries': total_beacon,
            'confirmed_matches': confirmed_count,
            'confirmed_amount': total_confirmed_amount,
            'auto_confirmed': len(confirmed_auto),
            'manual_matches': len(manual_matches),
            'manually_resolved': len(manually_resolved),
            'matched_beacon_entries': matched_beacon,
            'pending_suggestions': len(pending),
            'pending_amount': pending_amount,
            'rejected_suggestions': len(rejected),
            'rejected_amount': rejected_amount,
            'skipped_suggestions': len(skipped),
            'skipped_amount': skipped_amount,
            'unmatched_bank': unmatched_bank_count,
            'unmatched_bank_amount': unmatched_bank_amount,
            'unmatched_beacon': total_beacon - matched_beacon
        }

    def export_results(self, output_file: str = None):
        """Export reconciliation results to CSV."""
        if output_file is None:
            output_file = os.path.join(self.base_dir, "reconciliation_results.csv")

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'Bank_ID', 'Bank_Date', 'Bank_Description', 'Bank_Amount',
                'Match_Type', 'Status', 'Confidence',
                'Beacon_1_ID', 'Beacon_1_Date', 'Beacon_1_Payee', 'Beacon_1_Amount',
                'Beacon_2_ID', 'Beacon_2_Date', 'Beacon_2_Payee', 'Beacon_2_Amount'
            ])

            # Write matches
            for match in self.match_suggestions:
                bank = match.bank_transaction
                b1 = match.beacon_entries[0] if match.beacon_entries else None
                b2 = match.beacon_entries[1] if len(match.beacon_entries) > 1 else None

                writer.writerow([
                    bank.id, bank.date.strftime('%d-%b-%y'),
                    bank.description, str(bank.amount),
                    match.match_type, match.status.value,
                    f"{match.confidence_score:.2f}",
                    b1.id if b1 else '',
                    b1.date.strftime('%d/%m/%Y') if b1 else '',
                    b1.payee if b1 else '',
                    str(b1.amount) if b1 else '',
                    b2.id if b2 else '',
                    b2.date.strftime('%d/%m/%Y') if b2 else '',
                    b2.payee if b2 else '',
                    str(b2.amount) if b2 else ''
                ])

    def check_consistency(self, progress_callback: Callable[[int, int, str], None] = None) -> List[Tuple['MatchSuggestion', str, List['MatchSuggestion']]]:
        """Check for inconsistencies in confirmed matches.

        Returns a list of (match, reason, related_matches) tuples for any inconsistent matches.
        - match: The primary match for this inconsistency
        - reason: Description of the inconsistency
        - related_matches: All matches involved in this inconsistency (for navigation)

        Checks:
        1. Each beacon transaction is confirmed in at most one match
        2. Each confirmed match has bank amount = sum of beacon amounts
        """
        inconsistencies = []

        # Filter to only actually confirmed matches (confirmed_matches list may contain
        # stale entries due to object identity issues when matches are un-confirmed)
        actually_confirmed = [m for m in self.confirmed_matches if m.status == MatchStatus.CONFIRMED]

        total_checks = len(actually_confirmed) * 2  # Two checks per match
        current_check = 0

        debug_log(f"check_consistency: {len(self.confirmed_matches)} in confirmed_matches list, {len(actually_confirmed)} actually CONFIRMED")

        # Build a map of beacon_id -> list of confirmed matches that include it
        beacon_to_matches: Dict[str, List[MatchSuggestion]] = {}
        for match in actually_confirmed:
            for beacon in match.beacon_entries:
                if beacon.id not in beacon_to_matches:
                    beacon_to_matches[beacon.id] = []
                beacon_to_matches[beacon.id].append(match)

        # Check 1: Each beacon should be in at most one confirmed match
        checked_beacons = set()
        for match in actually_confirmed:
            current_check += 1
            if progress_callback:
                progress_callback(current_check, total_checks, "Checking beacon uniqueness...")

            for beacon in match.beacon_entries:
                if beacon.id in checked_beacons:
                    continue
                checked_beacons.add(beacon.id)

                matches_with_beacon = beacon_to_matches.get(beacon.id, [])
                if len(matches_with_beacon) > 1:
                    # This beacon is in multiple confirmed matches
                    match_ids = [m.id for m in matches_with_beacon]
                    debug_log(f"Beacon {beacon.id} found in {len(matches_with_beacon)} confirmed matches: {match_ids}")
                    for m in matches_with_beacon:
                        debug_log(f"  - {m.id}: bank={m.bank_transaction.id}, status={m.status}")
                    reason = f"Beacon {beacon.id} ({beacon.payee}, £{beacon.amount}) is confirmed in multiple matches: {', '.join(match_ids)}"
                    # Add ONE entry per beacon issue (use first match as primary)
                    # Include all related matches for navigation
                    entry = (matches_with_beacon[0], reason, matches_with_beacon)
                    # Check if this exact entry is already in inconsistencies
                    if not any(existing[0].id == entry[0].id and existing[1] == reason for existing in inconsistencies):
                        inconsistencies.append(entry)

        # Check 2: Bank amount should equal sum of beacon amounts
        for match in actually_confirmed:
            current_check += 1
            if progress_callback:
                progress_callback(current_check, total_checks, "Checking amount consistency...")

            if not match.beacon_entries:
                continue

            bank_amount = match.bank_transaction.amount
            beacon_total = sum(b.amount for b in match.beacon_entries)

            if bank_amount != beacon_total:
                print(f"[DEBUG] Amount mismatch for {match.id}: bank £{bank_amount} != beacon total £{beacon_total}")
                reason = f"Amount mismatch: Bank £{bank_amount} != Beacon total £{beacon_total}"
                # Only one match involved in amount mismatch
                entry = (match, reason, [match])
                if not any(existing[0].id == match.id and existing[1] == reason for existing in inconsistencies):
                    inconsistencies.append(entry)

        debug_log(f"check_consistency: found {len(inconsistencies)} inconsistencies")
        return inconsistencies

    def find_match_in_suggestions(self, match: 'MatchSuggestion') -> int:
        """Find the index of a match in the current suggestions list.

        Returns -1 if not found.

        Note: Matches by both match ID and bank transaction ID to handle cases
        where multiple matches have the same ID (can happen when suggestions
        are regenerated).
        """
        beacon_ids = [b.id for b in match.beacon_entries]
        debug_log(f"find_match_in_suggestions: looking for {match.id}, bank={match.bank_transaction.id}, beacons={beacon_ids}")

        # First try to find by both match ID and bank transaction ID (most reliable)
        for i, suggestion in enumerate(self.match_suggestions):
            if (suggestion.id == match.id and
                suggestion.bank_transaction.id == match.bank_transaction.id):
                debug_log(f"  Found by ID+bank at index {i}")
                return i

        # Fallback: try to find by bank transaction ID only
        for i, suggestion in enumerate(self.match_suggestions):
            if suggestion.bank_transaction.id == match.bank_transaction.id:
                # Check if beacon entries also match
                if len(suggestion.beacon_entries) == len(match.beacon_entries):
                    beacon_ids_match = all(
                        s.id == m.id
                        for s, m in zip(suggestion.beacon_entries, match.beacon_entries)
                    )
                    if beacon_ids_match:
                        debug_log(f"  Found by bank+beacons at index {i}")
                        return i

        debug_log(f"  NOT FOUND!")
        return -1

    def find_beacon_by_trans_no(self, trans_no: str) -> Optional[BeaconEntry]:
        """Find a beacon entry by its trans_no.

        Returns the BeaconEntry if found, None otherwise.
        """
        for entry in self.beacon_entries:
            if entry.trans_no == trans_no:
                return entry
        return None

    def is_beacon_already_matched(self, trans_no: str) -> bool:
        """Check if a beacon entry with the given trans_no is already matched."""
        entry = self.find_beacon_by_trans_no(trans_no)
        if entry is None:
            return False
        return entry.id in self.matched_beacon_ids

    def create_manual_match(self, bank_transaction: BankTransaction,
                            trans_nos: List[str]) -> tuple:
        """Create a manual match between a bank transaction and beacon entries.

        Args:
            bank_transaction: The bank transaction to match
            trans_nos: List of beacon trans_no values to match

        Returns:
            Tuple of (success: bool, message: str, match: Optional[MatchSuggestion])
        """
        # Validate all trans_nos first
        beacon_entries = []
        for trans_no in trans_nos:
            entry = self.find_beacon_by_trans_no(trans_no)
            if entry is None:
                return (False, f"Trans_no '{trans_no}' not found in beacon data", None)
            if entry.id in self.matched_beacon_ids:
                return (False, f"Trans_no '{trans_no}' is already matched to another bank transaction", None)
            beacon_entries.append(entry)

        # Check amount consistency
        beacon_total = sum(e.amount for e in beacon_entries)
        if bank_transaction.amount != beacon_total:
            return (False,
                    f"Amount mismatch: Bank £{bank_transaction.amount} != Beacon total £{beacon_total}",
                    None)

        # Create the manual match
        match_id = f"MANUAL_{bank_transaction.id}"
        match = MatchSuggestion(
            id=match_id,
            bank_transaction=bank_transaction,
            beacon_entries=beacon_entries,
            confidence_score=1.0,  # Manual matches are fully confident
            match_type="manual",
            status=MatchStatus.MANUAL_MATCH,
            amount_score=1.0,
            date_score=1.0,
            name_score=1.0
        )

        # Mark beacon entries as matched
        for entry in beacon_entries:
            entry.matched = True
            self.matched_beacon_ids.add(entry.id)

        # Add to confirmed matches
        self.confirmed_matches.append(match)

        # Save state
        self.save_state()

        return (True, f"Manual match created with {len(beacon_entries)} beacon entries", match)

    def create_manually_resolved(self, bank_transaction: BankTransaction,
                                  comment: str) -> tuple:
        """Mark a bank transaction as manually resolved.

        Args:
            bank_transaction: The bank transaction to mark as resolved
            comment: Explanation of how it was resolved

        Returns:
            Tuple of (success: bool, message: str, match: Optional[MatchSuggestion])
        """
        # Create the manually resolved entry
        match_id = f"RESOLVED_{bank_transaction.id}"
        match = MatchSuggestion(
            id=match_id,
            bank_transaction=bank_transaction,
            beacon_entries=[],  # No beacon entries for manually resolved
            confidence_score=1.0,
            match_type="resolved",
            status=MatchStatus.MANUALLY_RESOLVED,
            comment=comment
        )

        # Add to confirmed matches
        self.confirmed_matches.append(match)

        # Save state
        self.save_state()

        return (True, "Bank transaction marked as manually resolved", match)

    def get_all_bank_transactions_with_status(self) -> List[tuple]:
        """Get all bank transactions with their match status.

        Returns a list of (bank_transaction, status, match) tuples where:
        - status is 'matched', 'manual_match', 'resolved', or 'unmatched'
        - match is the MatchSuggestion if matched, else None
        """
        result = []

        # Build lookup of bank transactions that have matches
        matched_bank_ids = {}
        for match in self.confirmed_matches:
            if match.status in (MatchStatus.CONFIRMED, MatchStatus.MANUAL_MATCH,
                               MatchStatus.MANUALLY_RESOLVED):
                matched_bank_ids[match.bank_transaction.id] = match

        for bank_txn in self.bank_transactions:
            if bank_txn.id in matched_bank_ids:
                match = matched_bank_ids[bank_txn.id]
                if match.status == MatchStatus.MANUAL_MATCH:
                    result.append((bank_txn, 'manual_match', match))
                elif match.status == MatchStatus.MANUALLY_RESOLVED:
                    result.append((bank_txn, 'resolved', match))
                else:
                    result.append((bank_txn, 'matched', match))
            else:
                result.append((bank_txn, 'unmatched', None))

        return result

    def get_unmatched_beacon_entries(self) -> List[BeaconEntry]:
        """Get all beacon entries that are not matched to any bank transaction."""
        return [e for e in self.beacon_entries if e.id not in self.matched_beacon_ids]

    def export_matched_csv(self, filepath: str) -> int:
        """Export matched bank transactions to CSV.

        Format: Bank fields + Beacon fields (one row per beacon entry).
        Manually resolved entries have empty beacon fields but include comment.

        Returns the number of rows written.
        """
        import csv

        rows_written = 0
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Header
            writer.writerow([
                'bank_id', 'bank_date', 'bank_description', 'bank_amount',
                'beacon_trans_no', 'beacon_date', 'beacon_payee', 'beacon_amount',
                'beacon_mem_no', 'match_type', 'comment'
            ])

            # Get all matched bank transactions in bank transaction order
            for bank_txn, status, match in self.get_all_bank_transactions_with_status():
                if status == 'unmatched':
                    continue

                if match.beacon_entries:
                    # One row per beacon entry
                    for beacon in match.beacon_entries:
                        # Extract mem_no from beacon detail or payee if available
                        mem_no = self._extract_mem_no_from_beacon(beacon)
                        writer.writerow([
                            bank_txn.id,
                            bank_txn.date.strftime('%d/%m/%Y'),
                            bank_txn.description,
                            str(bank_txn.amount),
                            beacon.trans_no,
                            beacon.date.strftime('%d/%m/%Y'),
                            beacon.payee,
                            str(beacon.amount),
                            mem_no,
                            match.match_type,
                            match.comment
                        ])
                        rows_written += 1
                else:
                    # Manually resolved - no beacon entries
                    writer.writerow([
                        bank_txn.id,
                        bank_txn.date.strftime('%d/%m/%Y'),
                        bank_txn.description,
                        str(bank_txn.amount),
                        '', '', '', '', '',  # Empty beacon fields
                        match.match_type,
                        match.comment
                    ])
                    rows_written += 1

        return rows_written

    def _extract_mem_no_from_beacon(self, beacon: BeaconEntry) -> str:
        """Extract member number from beacon entry if available."""
        # Try to extract from detail field
        import re
        # Look for patterns like "member_1: 1234" or just numbers in detail
        match = re.search(r'member_1[:\s]+(\d+)', beacon.detail, re.IGNORECASE)
        if match:
            return match.group(1)

        # Try raw_data if available
        if beacon.raw_data:
            mem_no = beacon.raw_data.get('member_1', '')
            if mem_no:
                return str(mem_no)

        return ''

    def export_unmatched_beacon_csv(self, filepath: str) -> int:
        """Export unmatched beacon entries to CSV.

        Returns the number of rows written.
        """
        import csv

        unmatched = self.get_unmatched_beacon_entries()

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Header
            writer.writerow(['trans_no', 'date', 'payee', 'amount', 'mem_no', 'detail'])

            for beacon in unmatched:
                mem_no = self._extract_mem_no_from_beacon(beacon)
                writer.writerow([
                    beacon.trans_no,
                    beacon.date.strftime('%d/%m/%Y'),
                    beacon.payee,
                    str(beacon.amount),
                    mem_no,
                    beacon.detail
                ])

        return len(unmatched)

    def get_unmatched_bank_transactions(self) -> List[BankTransaction]:
        """Get all bank transactions that are not matched to any beacon entries."""
        # Build set of matched bank transaction IDs
        matched_bank_ids = set()
        for match in self.confirmed_matches:
            if match.status in (MatchStatus.CONFIRMED, MatchStatus.MANUAL_MATCH,
                               MatchStatus.MANUALLY_RESOLVED):
                matched_bank_ids.add(match.bank_transaction.id)

        return [b for b in self.bank_transactions if b.id not in matched_bank_ids]

    def export_unmatched_bank_csv(self, filepath: str) -> int:
        """Export unmatched bank transactions to CSV.

        Returns the number of rows written.
        """
        import csv

        unmatched = self.get_unmatched_bank_transactions()

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Header
            writer.writerow(['bank_id', 'date', 'type', 'description', 'amount'])

            for bank in unmatched:
                writer.writerow([
                    bank.id,
                    bank.date.strftime('%d/%m/%Y'),
                    bank.type,
                    bank.description,
                    str(bank.amount)
                ])

        return len(unmatched)


def main():
    """Main function for command-line usage."""
    system = ReconciliationSystem()
    system.load_data()

    print(f"Loaded {len(system.bank_transactions)} bank transactions")
    print(f"Loaded {len(system.beacon_entries)} beacon entries")

    def progress(current, total, message):
        print(f"\r[{current}/{total}] {message}".ljust(60), end='', flush=True)

    suggestions = system.generate_suggestions(progress_callback=progress)
    print()  # New line after progress
    print(f"Generated {len(suggestions)} match suggestions")

    # Count by status
    confirmed = len([m for m in suggestions if m.status == MatchStatus.CONFIRMED])
    pending = len([m for m in suggestions if m.status == MatchStatus.PENDING])

    print(f"  Auto-confirmed: {confirmed}")
    print(f"  Pending review: {pending}")

    # Print first few pending suggestions
    pending_suggestions = [m for m in suggestions if m.status == MatchStatus.PENDING][:5]
    if pending_suggestions:
        print("\nFirst pending matches:")
        for match in pending_suggestions:
            bank = match.bank_transaction
            print(f"\n{match.id}: {match.match_type} (confidence: {match.confidence_score:.2f})")
            print(f"  Bank: {bank.date.strftime('%d-%b-%y')} - {bank.description} - £{bank.amount}")

            for i, beacon in enumerate(match.beacon_entries, 1):
                print(f"  Beacon {i}: {beacon.date.strftime('%d/%m/%Y')} - {beacon.payee} - £{beacon.amount}")

    # Print statistics
    stats = system.get_statistics()
    print("\n--- Statistics ---")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
