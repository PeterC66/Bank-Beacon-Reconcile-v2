"""
Bank Beacon Reconciliation GUI
Graphical interface for reviewing and confirming match suggestions.

Features:
- Navigation with Previous/Next buttons
- Visual status indicators (Confirmed/Rejected/Skipped)
- Editable history (change previous decisions)
- Bank transaction on left, Beacon entries on right
- 1-to-2 match display support
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional
import sys

from reconciliation_system import (
    ReconciliationSystem, MatchSuggestion, MatchStatus, debug_log
)


class ReconciliationGUI:
    """Main GUI for bank reconciliation."""

    # Color scheme
    COLORS = {
        MatchStatus.PENDING: '#FFF3CD',      # Yellow/amber
        MatchStatus.CONFIRMED: '#D4EDDA',    # Green
        MatchStatus.REJECTED: '#F8D7DA',     # Red/pink
        MatchStatus.SKIPPED: '#D1ECF1',      # Blue/cyan
        MatchStatus.MANUAL_MATCH: '#C3E6CB', # Darker green for manual
        MatchStatus.MANUALLY_RESOLVED: '#B8DAFF', # Blue for resolved
        'no-match': '#E2E3E5',               # Gray
    }

    STATUS_LABELS = {
        MatchStatus.PENDING: 'PENDING',
        MatchStatus.CONFIRMED: '✓ CONFIRMED',
        MatchStatus.REJECTED: '✗ REJECTED',
        MatchStatus.SKIPPED: '⏭ SKIPPED',
        MatchStatus.MANUAL_MATCH: '⚡ MANUAL MATCH',
        MatchStatus.MANUALLY_RESOLVED: '📋 MANUALLY RESOLVED',
    }

    def __init__(self, master: tk.Tk):
        self.master = master
        self.master.title("Bank Beacon Reconciliation")
        self.master.geometry("1200x700")
        self.master.minsize(900, 600)

        # Initialize reconciliation system
        self.system = ReconciliationSystem()
        self.system.load_data()

        # Show loading summary
        bank_count = len(self.system.bank_transactions)
        beacon_count = len(self.system.beacon_entries)

        if bank_count == 0 or beacon_count == 0:
            messagebox.showwarning(
                "Loading Issue",
                f"Loaded {bank_count} bank transactions and {beacon_count} beacon entries.\n\n"
                f"Looking for files in:\n"
                f"{self.system.base_dir}\n\n"
                f"Expected files:\n"
                f"- {self.system.bank_file}\n"
                f"- {self.system.beacon_file}\n\n"
                f"Please ensure both files exist and have the correct format."
            )

        # Generate suggestions with progress dialog
        self.suggestions = self._generate_with_progress()

        # Current match index - start at first pending match
        self.current_index = self._find_first_pending()

        # Queued changes (for edits made when navigating back)
        self.queued_changes = {}  # match_id -> new_status

        # Setup GUI components
        self._setup_styles()
        self._create_widgets()
        self._update_display()

        # Show summary after GUI loads, then run consistency check
        if bank_count > 0 and beacon_count > 0:
            confirmed = len([m for m in self.suggestions if m.status == MatchStatus.CONFIRMED])
            pending = len([m for m in self.suggestions if m.status == MatchStatus.PENDING])
            self.master.after(100, lambda: self._show_startup_summary(
                bank_count, beacon_count, confirmed, pending
            ))

    def _show_startup_summary(self, bank_count, beacon_count, confirmed, pending):
        """Show startup summary and then run consistency check."""
        messagebox.showinfo(
            "Data Loaded",
            f"Loaded {bank_count} bank transactions\n"
            f"Loaded {beacon_count} beacon entries\n"
            f"Generated {len(self.suggestions)} match suggestions\n\n"
            f"Auto-confirmed: {confirmed}\n"
            f"Pending review: {pending}"
        )
        # Run consistency check after summary is closed (don't show message if clean)
        self.master.after(100, lambda: self._run_consistency_check(show_message_if_clean=False))

    def _generate_with_progress(self):
        """Generate suggestions with a progress dialog."""
        bank_count = len(self.system.bank_transactions)

        # For small datasets, skip progress dialog
        if bank_count < 50:
            return self.system.generate_suggestions()

        # Create progress dialog
        progress_window = tk.Toplevel(self.master)
        progress_window.title("Generating Matches")
        progress_window.geometry("400x120")
        progress_window.transient(self.master)
        progress_window.grab_set()

        # Center the dialog
        progress_window.update_idletasks()
        x = self.master.winfo_x() + (self.master.winfo_width() - 400) // 2
        y = self.master.winfo_y() + (self.master.winfo_height() - 120) // 2
        progress_window.geometry(f"+{x}+{y}")

        ttk.Label(progress_window, text="Processing transactions...",
                  font=('Segoe UI', 11)).pack(pady=(15, 5))

        progress_label = ttk.Label(progress_window, text="Initializing...")
        progress_label.pack(pady=5)

        progress_bar = ttk.Progressbar(progress_window, length=350, mode='determinate')
        progress_bar.pack(pady=10)

        def update_progress(current, total, message):
            progress_bar['maximum'] = total
            progress_bar['value'] = current
            progress_label.config(text=f"[{current}/{total}] {message[:40]}")
            progress_window.update()

        # Generate suggestions
        suggestions = self.system.generate_suggestions(progress_callback=update_progress)

        progress_window.destroy()
        return suggestions

    def _find_first_pending(self):
        """Find the index of the first pending match (skipping rejected)."""
        for i, match in enumerate(self.suggestions):
            if match.status == MatchStatus.PENDING:
                return i
        # If no pending, find first non-confirmed, non-rejected
        for i, match in enumerate(self.suggestions):
            if match.status not in (MatchStatus.CONFIRMED, MatchStatus.REJECTED):
                return i
        return 0

    def _setup_styles(self):
        """Configure ttk styles."""
        style = ttk.Style()
        style.configure('Title.TLabel', font=('Segoe UI', 14, 'bold'))
        style.configure('Header.TLabel', font=('Segoe UI', 11, 'bold'))
        style.configure('Amount.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('Status.TLabel', font=('Segoe UI', 10, 'bold'))
        style.configure('Nav.TButton', font=('Segoe UI', 10))
        style.configure('Action.TButton', font=('Segoe UI', 10, 'bold'), padding=10)
        # Larger text for values (description, payee, detail)
        style.configure('Value.TLabel', font=('Segoe UI', 12))

    def _create_widgets(self):
        """Create all GUI widgets."""
        # Create outer frame for canvas and scrollbar
        outer_frame = ttk.Frame(self.master)
        outer_frame.pack(fill=tk.BOTH, expand=True)

        # Create canvas with scrollbar
        self.canvas = tk.Canvas(outer_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Create main frame inside canvas
        main_frame = ttk.Frame(self.canvas, padding="10")
        self.canvas_window = self.canvas.create_window((0, 0), window=main_frame, anchor="nw")

        # Configure canvas scrolling
        def configure_scroll(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def configure_canvas_width(event):
            self.canvas.itemconfig(self.canvas_window, width=event.width)

        main_frame.bind("<Configure>", configure_scroll)
        self.canvas.bind("<Configure>", configure_canvas_width)

        # Enable mousewheel scrolling
        def on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def on_mousewheel_linux(event):
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")

        self.canvas.bind_all("<MouseWheel>", on_mousewheel)  # Windows/Mac
        self.canvas.bind_all("<Button-4>", on_mousewheel_linux)  # Linux scroll up
        self.canvas.bind_all("<Button-5>", on_mousewheel_linux)  # Linux scroll down

        # Top section: Statistics and progress
        self._create_stats_section(main_frame)

        # Middle section: Transaction display
        self._create_transaction_section(main_frame)

        # Bottom section: Actions and navigation
        self._create_action_section(main_frame)

    def _create_stats_section(self, parent):
        """Create statistics display section."""
        stats_frame = ttk.LabelFrame(parent, text="Reconciliation Progress", padding="10")
        stats_frame.pack(fill=tk.X, pady=(0, 10))

        # Top row: Progress info and stats
        top_row = ttk.Frame(stats_frame)
        top_row.pack(fill=tk.X)

        # Progress info
        self.progress_label = ttk.Label(top_row, text="Match 0 of 0")
        self.progress_label.pack(side=tk.LEFT)

        # Stats summary
        self.stats_label = ttk.Label(top_row, text="")
        self.stats_label.pack(side=tk.RIGHT)

        # Progress bar
        self.progress_bar = ttk.Progressbar(
            top_row, mode='determinate', length=300
        )
        self.progress_bar.pack(side=tk.LEFT, padx=20)

        # Bottom row: Search/filter
        search_row = ttk.Frame(stats_frame)
        search_row.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(search_row, text="Search:").pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(search_row, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind('<Return>', self._on_search)

        ttk.Button(search_row, text="Find", command=self._on_search).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_row, text="Find Prev", command=self._on_search_prev).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_row, text="Find Next", command=self._on_search_next).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_row, text="Clear", command=self._on_search_clear).pack(side=tk.LEFT, padx=2)

        self.search_result_label = ttk.Label(search_row, text="", foreground='gray')
        self.search_result_label.pack(side=tk.LEFT, padx=10)

        # Search help text
        search_help = ttk.Label(
            search_row,
            text='[name | "exact" | £amount | date | TR_transno | MATCH_/BANK_/BEACON_id]',
            foreground='#666666',
            font=('Segoe UI', 8)
        )
        search_help.pack(side=tk.LEFT, padx=5)

        # Track search state
        self.search_matches = []
        self.search_index = 0

    def _create_transaction_section(self, parent):
        """Create transaction display section with Bank on left, Beacon on right."""
        txn_frame = ttk.Frame(parent)
        txn_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # Configure grid weights for responsive layout
        txn_frame.columnconfigure(0, weight=1)
        txn_frame.columnconfigure(1, weight=1)
        txn_frame.rowconfigure(0, weight=1)

        # Left side: Bank Transaction
        self._create_bank_panel(txn_frame)

        # Right side: Beacon Entries
        self._create_beacon_panel(txn_frame)

    def _create_bank_panel(self, parent):
        """Create bank transaction panel (left side)."""
        bank_frame = ttk.LabelFrame(parent, text="Bank Transaction", padding="15")
        bank_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 5))

        # Status indicator
        self.bank_status_frame = tk.Frame(bank_frame)
        self.bank_status_frame.pack(fill=tk.X, pady=(0, 10))

        self.status_label = ttk.Label(
            self.bank_status_frame, text="PENDING",
            style='Status.TLabel'
        )
        self.status_label.pack(side=tk.LEFT)

        self.match_type_label = ttk.Label(
            self.bank_status_frame, text="1-to-1",
            style='Status.TLabel'
        )
        self.match_type_label.pack(side=tk.RIGHT)

        # Bank details
        details_frame = ttk.Frame(bank_frame)
        details_frame.pack(fill=tk.BOTH, expand=True)

        # Match ID
        ttk.Label(details_frame, text="Match ID:", style='Header.TLabel').grid(
            row=0, column=0, sticky='w', pady=5
        )
        self.match_id_label = ttk.Label(details_frame, text="", foreground='gray')
        self.match_id_label.grid(row=0, column=1, sticky='w', padx=10, pady=5)

        # Bank ID
        ttk.Label(details_frame, text="Bank ID:", style='Header.TLabel').grid(
            row=1, column=0, sticky='w', pady=5
        )
        self.bank_id_label = ttk.Label(details_frame, text="", foreground='gray')
        self.bank_id_label.grid(row=1, column=1, sticky='w', padx=10, pady=5)

        # Date
        ttk.Label(details_frame, text="Date:", style='Header.TLabel').grid(
            row=2, column=0, sticky='w', pady=5
        )
        self.bank_date_label = ttk.Label(details_frame, text="")
        self.bank_date_label.grid(row=2, column=1, sticky='w', padx=10, pady=5)

        # Type
        ttk.Label(details_frame, text="Type:", style='Header.TLabel').grid(
            row=3, column=0, sticky='w', pady=5
        )
        self.bank_type_label = ttk.Label(details_frame, text="")
        self.bank_type_label.grid(row=3, column=1, sticky='w', padx=10, pady=5)

        # Description
        ttk.Label(details_frame, text="Description:", style='Header.TLabel').grid(
            row=4, column=0, sticky='w', pady=5
        )
        self.bank_desc_label = ttk.Label(details_frame, text="", wraplength=350, style='Value.TLabel')
        self.bank_desc_label.grid(row=4, column=1, sticky='w', padx=10, pady=5)

        # Member lookup (based on numbers in description)
        ttk.Label(details_frame, text="Member:", style='Header.TLabel').grid(
            row=5, column=0, sticky='nw', pady=5
        )
        self.member_lookup_label = ttk.Label(
            details_frame, text="", wraplength=350,
            foreground='#006600', justify=tk.LEFT
        )
        self.member_lookup_label.grid(row=5, column=1, sticky='w', padx=10, pady=5)

        # Amount (prominent)
        amount_frame = ttk.Frame(bank_frame)
        amount_frame.pack(fill=tk.X, pady=(20, 0))

        ttk.Label(amount_frame, text="Amount:", style='Header.TLabel').pack(side=tk.LEFT)
        self.bank_amount_label = ttk.Label(
            amount_frame, text="£0.00", style='Amount.TLabel',
            foreground='#0066CC'
        )
        self.bank_amount_label.pack(side=tk.LEFT, padx=10)

        # Confidence score
        confidence_frame = ttk.Frame(bank_frame)
        confidence_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(confidence_frame, text="Confidence:", style='Header.TLabel').pack(side=tk.LEFT)
        self.confidence_label = ttk.Label(confidence_frame, text="0%")
        self.confidence_label.pack(side=tk.LEFT, padx=10)

        # Score breakdown
        self.score_breakdown_label = ttk.Label(bank_frame, text="", foreground='gray')
        self.score_breakdown_label.pack(fill=tk.X, pady=(5, 0))

    def _create_beacon_panel(self, parent):
        """Create beacon entries panel (right side) - supports 1-2 entries."""
        beacon_frame = ttk.LabelFrame(parent, text="Beacon Entries", padding="15")
        beacon_frame.grid(row=0, column=1, sticky='nsew', padx=(5, 0))

        # Container for beacon entries (will hold 1 or 2 entry frames)
        self.beacon_container = ttk.Frame(beacon_frame)
        self.beacon_container.pack(fill=tk.BOTH, expand=True)

        # Create two entry frames (second one may be hidden)
        self.beacon_frames = []
        self.beacon_widgets = []

        for i in range(2):
            frame = ttk.Frame(self.beacon_container)
            widgets = self._create_beacon_entry_widgets(frame, i + 1)
            self.beacon_frames.append(frame)
            self.beacon_widgets.append(widgets)

        # Total amount (for 1-to-2 matches)
        self.total_frame = ttk.Frame(beacon_frame)
        ttk.Label(self.total_frame, text="Total:", style='Header.TLabel').pack(side=tk.LEFT)
        self.beacon_total_label = ttk.Label(
            self.total_frame, text="£0.00", style='Amount.TLabel',
            foreground='#0066CC'
        )
        self.beacon_total_label.pack(side=tk.LEFT, padx=10)

        # Additional entries indicator (for manual matches with >2 entries)
        self.additional_entries_label = ttk.Label(
            beacon_frame,
            text="",
            font=('Segoe UI', 10, 'italic'),
            foreground='#666666'
        )

        # No match message
        self.no_match_label = ttk.Label(
            beacon_frame,
            text="No matching Beacon entries found",
            font=('Segoe UI', 10),
            foreground='gray',
            justify='center'
        )

    def _create_beacon_entry_widgets(self, frame, entry_num):
        """Create widgets for a single beacon entry display."""
        widgets = {}

        # Entry header
        header_frame = ttk.Frame(frame)
        header_frame.pack(fill=tk.X, pady=(0, 5))

        widgets['header'] = ttk.Label(
            header_frame, text=f"Entry {entry_num}", style='Header.TLabel'
        )
        widgets['header'].pack(side=tk.LEFT)

        # Separator
        sep = ttk.Separator(frame, orient='horizontal')
        sep.pack(fill=tk.X, pady=5)

        # Details grid
        details = ttk.Frame(frame)
        details.pack(fill=tk.X)

        # Beacon ID
        ttk.Label(details, text="ID:").grid(row=0, column=0, sticky='w', pady=3)
        widgets['id'] = ttk.Label(details, text="", foreground='gray')
        widgets['id'].grid(row=0, column=1, sticky='w', padx=10, pady=3)

        # Trans No
        ttk.Label(details, text="Trans No:").grid(row=1, column=0, sticky='w', pady=3)
        widgets['trans_no'] = ttk.Label(details, text="")
        widgets['trans_no'].grid(row=1, column=1, sticky='w', padx=10, pady=3)

        # Date
        ttk.Label(details, text="Date:").grid(row=2, column=0, sticky='w', pady=3)
        widgets['date'] = ttk.Label(details, text="")
        widgets['date'].grid(row=2, column=1, sticky='w', padx=10, pady=3)

        # Payee
        ttk.Label(details, text="Payee:").grid(row=3, column=0, sticky='w', pady=3)
        widgets['payee'] = ttk.Label(details, text="", wraplength=300, style='Value.TLabel')
        widgets['payee'].grid(row=3, column=1, sticky='w', padx=10, pady=3)

        # Detail
        ttk.Label(details, text="Detail:").grid(row=4, column=0, sticky='w', pady=3)
        widgets['detail'] = ttk.Label(details, text="", wraplength=300, style='Value.TLabel')
        widgets['detail'].grid(row=4, column=1, sticky='w', padx=10, pady=3)

        # Amount
        ttk.Label(details, text="Amount:").grid(row=5, column=0, sticky='w', pady=3)
        widgets['amount'] = ttk.Label(details, text="£0.00", foreground='#0066CC')
        widgets['amount'].grid(row=5, column=1, sticky='w', padx=10, pady=3)

        return widgets

    def _create_action_section(self, parent):
        """Create action buttons and navigation section in two rows."""
        action_frame = ttk.LabelFrame(parent, text="Navigation & Actions", padding="5")
        action_frame.pack(fill=tk.X, pady=(10, 0))

        # Row 1: Navigation controls
        nav_row = ttk.Frame(action_frame)
        nav_row.pack(fill=tk.X, pady=(0, 5))

        self.prev_button = ttk.Button(
            nav_row, text="◀ Previous", style='Nav.TButton',
            command=self._on_previous
        )
        self.prev_button.pack(side=tk.LEFT, padx=5)

        self.next_button = ttk.Button(
            nav_row, text="Next ▶", style='Nav.TButton',
            command=self._on_next
        )
        self.next_button.pack(side=tk.LEFT, padx=5)

        # Jump to input
        ttk.Label(nav_row, text="  Go to:").pack(side=tk.LEFT)
        self.jump_entry = ttk.Entry(nav_row, width=5)
        self.jump_entry.pack(side=tk.LEFT, padx=5)
        self.jump_entry.bind('<Return>', self._on_jump)
        ttk.Button(nav_row, text="Go", command=self._on_jump).pack(side=tk.LEFT)

        # Skip checkboxes
        ttk.Label(nav_row, text="    ").pack(side=tk.LEFT)
        self.skip_confirmed_var = tk.BooleanVar(value=True)
        self.skip_confirmed_check = ttk.Checkbutton(
            nav_row, text="Skip confirmed", variable=self.skip_confirmed_var
        )
        self.skip_confirmed_check.pack(side=tk.LEFT, padx=5)

        self.skip_rejected_var = tk.BooleanVar(value=True)
        self.skip_rejected_check = ttk.Checkbutton(
            nav_row, text="Skip rejected", variable=self.skip_rejected_var
        )
        self.skip_rejected_check.pack(side=tk.LEFT, padx=5)

        # Show all transactions checkbox
        self.show_all_var = tk.BooleanVar(value=False)
        self.show_all_check = ttk.Checkbutton(
            nav_row, text="Show all transactions",
            variable=self.show_all_var,
            command=self._on_show_all_changed
        )
        self.show_all_check.pack(side=tk.LEFT, padx=10)

        # Trans_no limit for 1-to-2 matches
        ttk.Label(nav_row, text="1-to-2 trans_no limit:").pack(side=tk.LEFT, padx=(10, 2))
        self.trans_no_limit_var = tk.IntVar(value=5)
        self.trans_no_limit_spinbox = ttk.Spinbox(
            nav_row, from_=1, to=20, width=4,
            textvariable=self.trans_no_limit_var,
            command=self._on_trans_no_limit_changed
        )
        self.trans_no_limit_spinbox.pack(side=tk.LEFT, padx=2)
        self.trans_no_limit_spinbox.bind('<Return>', self._on_trans_no_limit_changed)

        # Row 2: Action buttons
        action_row = ttk.Frame(action_frame)
        action_row.pack(fill=tk.X)

        self.confirm_button = ttk.Button(
            action_row, text="✓ Confirm Match", style='Action.TButton',
            command=self._on_confirm
        )
        self.confirm_button.pack(side=tk.LEFT, padx=5)

        self.reject_button = ttk.Button(
            action_row, text="✗ Reject", style='Action.TButton',
            command=self._on_reject
        )
        self.reject_button.pack(side=tk.LEFT, padx=5)

        self.skip_button = ttk.Button(
            action_row, text="⏭ Skip", style='Action.TButton',
            command=self._on_skip
        )
        self.skip_button.pack(side=tk.LEFT, padx=5)

        # Spacer
        ttk.Label(action_row, text="    ").pack(side=tk.LEFT)

        ttk.Button(
            action_row, text="Save Progress",
            command=self._on_save
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            action_row, text="Export Results",
            command=self._on_export
        ).pack(side=tk.LEFT, padx=5)

        # Date tolerance control
        ttk.Label(action_row, text="  Date tolerance (days):").pack(side=tk.LEFT, padx=(10, 2))
        self.date_tolerance_var = tk.IntVar(value=self.system.date_tolerance_days)
        self.date_tolerance_spinbox = ttk.Spinbox(
            action_row, from_=1, to=365, width=4,
            textvariable=self.date_tolerance_var
        )
        self.date_tolerance_spinbox.pack(side=tk.LEFT, padx=2)

        ttk.Button(
            action_row, text="Refresh Suggestions",
            command=self._on_refresh
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            action_row, text="Auto-Confirm",
            command=self._on_auto_confirm
        ).pack(side=tk.LEFT, padx=5)

        # Row 3: Consistency check controls
        consistency_row = ttk.Frame(action_frame)
        consistency_row.pack(fill=tk.X, pady=(5, 0))

        ttk.Button(
            consistency_row, text="Check Consistency",
            command=self._on_check_consistency
        ).pack(side=tk.LEFT, padx=5)

        self.prev_issue_button = ttk.Button(
            consistency_row, text="◄ Prev Issue",
            command=self._on_prev_inconsistency,
            state=tk.DISABLED
        )
        self.prev_issue_button.pack(side=tk.LEFT, padx=5)

        self.next_issue_button = ttk.Button(
            consistency_row, text="Next Issue ►",
            command=self._on_next_inconsistency,
            state=tk.DISABLED
        )
        self.next_issue_button.pack(side=tk.LEFT, padx=5)

        # Related records navigation (for stepping through records in same issue)
        self.prev_related_button = ttk.Button(
            consistency_row, text="◄ Related",
            command=self._on_prev_related,
            state=tk.DISABLED
        )
        self.prev_related_button.pack(side=tk.LEFT, padx=2)

        self.related_label = ttk.Label(
            consistency_row, text="", foreground='gray', width=8
        )
        self.related_label.pack(side=tk.LEFT, padx=2)

        self.next_related_button = ttk.Button(
            consistency_row, text="Related ►",
            command=self._on_next_related,
            state=tk.DISABLED
        )
        self.next_related_button.pack(side=tk.LEFT, padx=2)

        self.inconsistency_label = ttk.Label(
            consistency_row, text="", foreground='gray', wraplength=400
        )
        self.inconsistency_label.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        # Track inconsistencies
        self.inconsistencies = []  # List of (match, reason, related_matches) tuples
        self.current_inconsistency_index = 0
        self.current_related_index = 0  # Index within related_matches

        # Row 4: Manual matching controls
        manual_row = ttk.Frame(action_frame)
        manual_row.pack(fill=tk.X, pady=(5, 0))

        ttk.Label(manual_row, text="Manual Match - Trans_no(s):").pack(side=tk.LEFT, padx=5)
        self.trans_no_entry = ttk.Entry(manual_row, width=30)
        self.trans_no_entry.pack(side=tk.LEFT, padx=5)
        self.trans_no_entry.bind('<Return>', lambda e: self._on_create_manual_match())

        self.manual_match_button = ttk.Button(
            manual_row, text="Create Manual Match",
            command=self._on_create_manual_match
        )
        self.manual_match_button.pack(side=tk.LEFT, padx=5)

        ttk.Label(manual_row, text="  |  ").pack(side=tk.LEFT)

        ttk.Label(manual_row, text="Resolved Comment:").pack(side=tk.LEFT, padx=5)
        self.resolved_comment_entry = ttk.Entry(manual_row, width=25)
        self.resolved_comment_entry.pack(side=tk.LEFT, padx=5)

        self.mark_resolved_button = ttk.Button(
            manual_row, text="Mark as Resolved",
            command=self._on_mark_resolved
        )
        self.mark_resolved_button.pack(side=tk.LEFT, padx=5)

        ttk.Label(manual_row, text="  |  ").pack(side=tk.LEFT)

        self.export_csv_button = ttk.Button(
            manual_row, text="Reports",
            command=self._on_export_csvs
        )
        self.export_csv_button.pack(side=tk.LEFT, padx=5)

    def _update_display(self):
        """Update the display for the current match."""
        if not self.suggestions:
            self._show_no_matches()
            return

        # Ensure index is valid
        self.current_index = max(0, min(self.current_index, len(self.suggestions) - 1))

        match = self.suggestions[self.current_index]

        # Check if there's a queued change for this match
        if match.id in self.queued_changes:
            display_status = self.queued_changes[match.id]
        else:
            display_status = match.status

        # Update progress
        self.progress_label.config(
            text=f"Match {self.current_index + 1} of {len(self.suggestions)}"
        )
        self.progress_bar['maximum'] = len(self.suggestions)
        self.progress_bar['value'] = self.current_index + 1

        # Update stats with amounts
        stats = self.system.get_statistics()
        self.stats_label.config(
            text=f"Confirmed: {stats['confirmed_matches']} (£{stats['confirmed_amount']:.2f}) | "
                 f"Pending: {stats['pending_suggestions']} (£{stats['pending_amount']:.2f}) | "
                 f"Rejected: {stats['rejected_suggestions']} | "
                 f"Unmatched Bank: {stats['unmatched_bank']} (£{stats['unmatched_bank_amount']:.2f})"
        )
        self.stats_label.update_idletasks()

        # Update status indicator
        self.status_label.config(text=self.STATUS_LABELS.get(display_status, 'PENDING'))
        self.bank_status_frame.config(bg=self.COLORS.get(display_status, self.COLORS[MatchStatus.PENDING]))
        # Force UI refresh
        self.status_label.update_idletasks()
        self.bank_status_frame.update_idletasks()

        # Update match type
        self.match_type_label.config(text=match.match_type.upper())

        # Update match and bank transaction details
        self.match_id_label.config(text=match.id)
        bank = match.bank_transaction
        self.bank_id_label.config(text=bank.id)
        self.bank_date_label.config(text=bank.date.strftime('%d-%b-%Y'))
        self.bank_type_label.config(text=bank.type)
        self.bank_desc_label.config(text=bank.description)
        self.bank_amount_label.config(text=f"£{bank.amount}")

        # Update member lookup
        member_lookup_text = self.system.get_member_lookup_text(bank.description)
        self.member_lookup_label.config(text=member_lookup_text)

        # Update confidence display
        if match.match_type == "manual":
            self.confidence_label.config(text="Manual Match")
            self.score_breakdown_label.config(text="(Manually matched by user)")
        elif match.match_type == "resolved":
            self.confidence_label.config(text="Manually Resolved")
            comment_text = match.comment[:50] + "..." if len(match.comment) > 50 else match.comment
            self.score_breakdown_label.config(text=f"Comment: {comment_text}")
        else:
            confidence_pct = int(match.confidence_score * 100)
            self.confidence_label.config(text=f"{confidence_pct}%")
            # Score breakdown
            self.score_breakdown_label.config(
                text=f"(Amount: {match.amount_score:.0%} | "
                     f"Date: {match.date_score:.0%} | "
                     f"Name: {match.name_score:.0%})"
            )

        # Update beacon entries display
        self._update_beacon_display(match)

        # Update navigation buttons
        self.prev_button.config(state=tk.NORMAL if self.current_index > 0 else tk.DISABLED)
        self.next_button.config(
            state=tk.NORMAL if self.current_index < len(self.suggestions) - 1 else tk.DISABLED
        )

        # Update action buttons based on match type
        has_beacon = len(match.beacon_entries) > 0
        self.confirm_button.config(state=tk.NORMAL if has_beacon else tk.DISABLED)

    def _update_beacon_display(self, match: MatchSuggestion):
        """Update beacon entries display for current match."""
        # Hide all frames first
        for frame in self.beacon_frames:
            frame.pack_forget()
        self.total_frame.pack_forget()
        self.additional_entries_label.pack_forget()
        self.no_match_label.pack_forget()

        if not match.beacon_entries:
            # No beacon entries - either no match found or manually resolved
            if match.match_type == "resolved":
                self.no_match_label.config(
                    text="Manually Resolved\n\nNo beacon entries linked.\nSee comment for resolution details.",
                    foreground='gray',
                    font=('Segoe UI', 10)
                )
            else:
                # Make "No match found" stand out with larger font
                self.no_match_label.config(
                    text="⚠ NO MATCH FOUND ⚠\n\nUse manual matching to link beacon entries by trans_no,\nor mark as resolved.",
                    foreground='gray',
                    font=('Segoe UI', 12, 'bold')
                )
            self.no_match_label.pack(fill=tk.X, pady=(10, 0))
            return

        # Show first 2 beacon entries
        total_amount = 0
        displayed_count = min(2, len(match.beacon_entries))
        for i in range(displayed_count):
            beacon = match.beacon_entries[i]
            widgets = self.beacon_widgets[i]
            widgets['id'].config(text=beacon.id)
            widgets['trans_no'].config(text=beacon.trans_no)
            widgets['date'].config(text=beacon.date.strftime('%d/%m/%Y'))
            widgets['payee'].config(text=beacon.payee)
            widgets['detail'].config(text=beacon.detail)
            widgets['amount'].config(text=f"£{beacon.amount}")

            self.beacon_frames[i].pack(fill=tk.X, pady=(0, 10))

        # Calculate total from ALL beacon entries
        total_amount = sum(float(b.amount) for b in match.beacon_entries)

        # Show additional entries indicator if more than 2
        if len(match.beacon_entries) > 2:
            extra_entries = match.beacon_entries[2:]
            extra_details = [f"{b.trans_no} (£{b.amount})" for b in extra_entries]
            extra_text = f"+ {len(extra_entries)} more: {', '.join(extra_details)}"
            self.additional_entries_label.config(text=extra_text)
            self.additional_entries_label.pack(fill=tk.X, pady=(0, 5))

        # Show total for matches with 2+ entries
        if len(match.beacon_entries) >= 2:
            self.beacon_total_label.config(text=f"£{total_amount:.2f}")
            self.total_frame.pack(fill=tk.X, pady=(10, 0))

    def _show_no_matches(self):
        """Show message when there are no matches to review."""
        messagebox.showinfo(
            "No Matches",
            "No match suggestions available.\n\n"
            "Either all bank transactions have been matched,\n"
            "or no suitable matches were found."
        )

    def _should_skip_match(self, match):
        """Check if a match should be skipped based on current settings."""
        # Treat MANUAL_MATCH and MANUALLY_RESOLVED as confirmed for skipping purposes
        if self.skip_confirmed_var.get() and match.status in (
            MatchStatus.CONFIRMED, MatchStatus.MANUAL_MATCH, MatchStatus.MANUALLY_RESOLVED
        ):
            return True
        if self.skip_rejected_var.get() and match.status == MatchStatus.REJECTED:
            return True
        return False

    def _on_previous(self):
        """Navigate to previous match."""
        if self.current_index > 0:
            self.current_index -= 1
            # Skip confirmed/rejected matches if checkboxes are checked
            while self.current_index > 0:
                match = self.suggestions[self.current_index]
                if not self._should_skip_match(match):
                    break
                self.current_index -= 1
            self._update_display()

    def _on_next(self):
        """Navigate to next match."""
        if self.current_index < len(self.suggestions) - 1:
            self.current_index += 1
            # Skip confirmed/rejected matches if checkboxes are checked
            while self.current_index < len(self.suggestions) - 1:
                match = self.suggestions[self.current_index]
                if not self._should_skip_match(match):
                    break
                self.current_index += 1
            self._update_display()

    def _on_jump(self, event=None):
        """Jump to a specific match number."""
        try:
            target = int(self.jump_entry.get()) - 1
            if 0 <= target < len(self.suggestions):
                self.current_index = target
                self._update_display()
            else:
                messagebox.showwarning(
                    "Invalid Index",
                    f"Please enter a number between 1 and {len(self.suggestions)}"
                )
        except ValueError:
            messagebox.showwarning("Invalid Input", "Please enter a valid number")

    def _on_confirm(self):
        """Confirm the current match."""
        if not self.suggestions:
            return

        match = self.suggestions[self.current_index]
        print(f"[DEBUG] Confirming match {match.id}, was status={match.status}")

        # Queue the change (will be applied when moving forward or saving)
        self.queued_changes[match.id] = MatchStatus.CONFIRMED
        self._auto_save()

        # Verify the change was applied
        current_match = self.suggestions[self.current_index]
        print(f"[DEBUG] After confirm: match {current_match.id}, now status={current_match.status}")

        self._update_display()

        # Refresh inconsistency check if we were viewing inconsistencies
        if self.inconsistencies:
            self.inconsistencies = self.system.check_consistency()
            self._update_inconsistency_ui()

        # Auto-advance to next (but not when show_all is enabled - let user see status change)
        if not self.show_all_var.get() and self.current_index < len(self.suggestions) - 1:
            self._on_next()

    def _on_reject(self):
        """Reject the current match."""
        if not self.suggestions:
            return

        match = self.suggestions[self.current_index]
        print(f"[DEBUG] Rejecting match {match.id}, was status={match.status}")

        # Remember the bank transaction ID before rejecting
        rejected_bank_id = match.bank_transaction.id

        self.queued_changes[match.id] = MatchStatus.REJECTED
        self._auto_save()

        # Verify the change was applied
        current_match = self.suggestions[self.current_index]
        print(f"[DEBUG] After reject: match {current_match.id}, now status={current_match.status}")

        self._update_display()

        # Refresh inconsistency check if we were viewing inconsistencies
        if self.inconsistencies:
            self.inconsistencies = self.system.check_consistency()
            self._update_inconsistency_ui()

        # Auto-advance: first look for another match for the same bank transaction
        if not self.show_all_var.get() and self.current_index < len(self.suggestions) - 1:
            # Look for next pending match with same bank transaction
            found_same_bank = False
            for i in range(self.current_index + 1, len(self.suggestions)):
                candidate = self.suggestions[i]
                if candidate.bank_transaction.id == rejected_bank_id:
                    if candidate.status == MatchStatus.PENDING:
                        self.current_index = i
                        found_same_bank = True
                        self._update_display()
                        break

            # If no other match for same bank, advance normally
            if not found_same_bank:
                self._on_next()

    def _on_skip(self):
        """Skip the current match."""
        if not self.suggestions:
            return

        match = self.suggestions[self.current_index]
        self.queued_changes[match.id] = MatchStatus.SKIPPED
        self._auto_save()
        self._update_display()

        # Auto-advance
        if self.current_index < len(self.suggestions) - 1:
            self._on_next()

    def _auto_save(self):
        """Auto-save progress without showing a message."""
        self._apply_queued_changes()
        self.system.save_state()

    def _apply_queued_changes(self):
        """Apply all queued status changes."""
        changes_made = False
        updated_match = None  # Track the match we actually updated

        for match_id, new_status in self.queued_changes.items():
            # Find the match at current_index first (most likely case)
            if self.current_index < len(self.suggestions):
                current = self.suggestions[self.current_index]
                if current.id == match_id:
                    self.system.update_match_status(current, new_status)
                    changes_made = True
                    updated_match = current
                    print(f"[DEBUG] Applied {new_status} to {match_id} at current_index {self.current_index}")
                    continue

            # If not at current_index, search for it
            for match in self.suggestions:
                if match.id == match_id:
                    self.system.update_match_status(match, new_status)
                    changes_made = True
                    updated_match = match
                    print(f"[DEBUG] Applied {new_status} to {match_id} (found by search)")
                    break

        self.queued_changes.clear()

        # Re-sort suggestions after status changes to maintain correct order
        if changes_made and self.suggestions:
            # Use the match we actually updated, not the one at current_index
            current_match = updated_match if updated_match else (
                self.suggestions[self.current_index] if self.current_index < len(self.suggestions) else None
            )
            old_index = self.current_index
            self.system._sort_suggestions()
            # Try to maintain position on the same match after re-sort
            if current_match:
                try:
                    self.current_index = self.suggestions.index(current_match)
                    print(f"[DEBUG] Reindex: {old_index} -> {self.current_index}, match {current_match.id} now {current_match.status}")
                except ValueError:
                    self.current_index = min(self.current_index, len(self.suggestions) - 1)
                    print(f"[DEBUG] Match not found after sort, staying at index {self.current_index}")

    def _on_save(self):
        """Save current progress."""
        self._apply_queued_changes()
        self.system.save_state()
        messagebox.showinfo("Saved", "Progress saved successfully!")

    def _on_export(self):
        """Export results to CSV."""
        self._apply_queued_changes()
        self.system.export_results()
        messagebox.showinfo(
            "Exported",
            "Results exported to reconciliation_results.csv"
        )

    def _on_refresh(self):
        """Refresh suggestions after applying changes."""
        self._apply_queued_changes()
        self.system.save_state()

        # Regenerate suggestions with current settings
        include_confirmed = self.show_all_var.get()
        trans_no_limit = self.trans_no_limit_var.get()
        date_tolerance = self.date_tolerance_var.get()
        self.suggestions = self.system.generate_suggestions(
            include_confirmed=include_confirmed,
            trans_no_limit=trans_no_limit,
            date_tolerance_days=date_tolerance
        )
        self.current_index = 0

        self._update_display()
        messagebox.showinfo(
            "Refreshed",
            f"Generated {len(self.suggestions)} match suggestions\n"
            f"(Date tolerance: {date_tolerance} days)"
        )

    def _on_auto_confirm(self):
        """Run auto-confirmation on pending matches."""
        self._apply_queued_changes()

        # Run auto-confirmation
        count = self.system.run_auto_confirm()

        if count > 0:
            # Save state after auto-confirmation
            self.system.save_state()

            # Re-sort suggestions to reflect new confirmed status
            self.system._sort_suggestions()

            self._update_display()
            messagebox.showinfo(
                "Auto-Confirm Complete",
                f"Auto-confirmed {count} high-confidence matches"
            )
        else:
            messagebox.showinfo(
                "Auto-Confirm Complete",
                "No matches met the auto-confirmation thresholds"
            )

    def _parse_search_date(self, date_str: str):
        """Try to parse a date string in various formats.

        Returns datetime if successful, None otherwise.
        Supports: DD/MM/YYYY, DD-MM-YYYY, DD MM YYYY, DD-Mon-YYYY, YYYY-MM-DD
        """
        from datetime import datetime
        formats = [
            '%d/%m/%Y',      # 17/03/2025
            '%d-%m-%Y',      # 17-03-2025
            '%d/%m/%y',      # 17/03/25
            '%d-%m-%y',      # 17-03-25
            '%d %b %Y',      # 17 Mar 2025
            '%d %B %Y',      # 17 March 2025
            '%d-%b-%Y',      # 17-Mar-2025
            '%d-%b-%y',      # 17-Mar-25
            '%Y-%m-%d',      # 2025-03-17
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

    def _detect_search_type(self, search_term: str):
        """Detect the type of search based on the search term.

        Returns tuple of (search_type, parsed_value) where search_type is one of:
        - 'quoted': literal string search (parsed_value = unquoted string)
        - 'match_id': exact Match ID search
        - 'bank_id': exact Bank ID search
        - 'beacon_id': exact Beacon ID search
        - 'date': date search (parsed_value = datetime)
        - 'amount': amount search (parsed_value = Decimal)
        - 'name': name/description search (parsed_value = lowercase search term)
        """
        from decimal import Decimal, InvalidOperation

        term = search_term.strip()

        # 1. Check for quoted string (literal search)
        if term.startswith('"') and term.endswith('"') and len(term) > 2:
            return ('quoted', term[1:-1])

        # 2. Check for ID prefixes (exact match)
        upper_term = term.upper()
        if upper_term.startswith('MATCH_') or upper_term.startswith('MANUAL_') or upper_term.startswith('RESOLVED_'):
            return ('match_id', upper_term)
        if upper_term.startswith('BANK_'):
            return ('bank_id', upper_term)
        if upper_term.startswith('BEACON_'):
            return ('beacon_id', upper_term)
        if upper_term.startswith('TR_'):
            # Trans_no search - remove prefix and search beacon trans_no
            return ('trans_no', term[3:])  # Keep original case for trans_no

        # 3. Check for date
        parsed_date = self._parse_search_date(term)
        if parsed_date:
            return ('date', parsed_date)

        # 4. Check for amount (number, possibly with £ prefix)
        amount_str = term.lstrip('£').strip()
        try:
            # Try to parse as decimal
            amount = Decimal(amount_str)
            return ('amount', amount)
        except InvalidOperation:
            pass

        # 5. Default to name search
        return ('name', term.lower())

    def _on_search(self, event=None):
        """Search for matches by various criteria with auto-detection.

        Supports:
        - "quoted text": Literal string search in description/payee
        - MATCH_*, BANK_*, BEACON_*: Exact ID search
        - Date formats (17/03/2025, etc.): Date search
        - Numbers or £amounts: Amount search
        - Other text: Name/description substring search
        """
        search_term = self.search_entry.get().strip()
        if not search_term:
            self.search_result_label.config(text="Enter search term")
            return

        search_type, parsed_value = self._detect_search_type(search_term)
        self.search_matches = []

        for i, match in enumerate(self.suggestions):
            bank = match.bank_transaction
            beacons = match.beacon_entries

            if search_type == 'quoted':
                # Literal string search in description and payee
                search_lower = parsed_value.lower()
                if search_lower in bank.description.lower():
                    self.search_matches.append(i)
                    continue
                for beacon in beacons:
                    if search_lower in beacon.payee.lower():
                        self.search_matches.append(i)
                        break

            elif search_type == 'match_id':
                # Exact match ID search
                if match.id.upper() == parsed_value:
                    self.search_matches.append(i)

            elif search_type == 'bank_id':
                # Exact bank ID search
                if bank.id.upper() == parsed_value:
                    self.search_matches.append(i)

            elif search_type == 'beacon_id':
                # Exact beacon ID search
                for beacon in beacons:
                    if beacon.id.upper() == parsed_value:
                        self.search_matches.append(i)
                        break

            elif search_type == 'trans_no':
                # Trans_no search - exact match on beacon trans_no
                for beacon in beacons:
                    if beacon.trans_no == parsed_value:
                        self.search_matches.append(i)
                        break

            elif search_type == 'date':
                # Date search - match bank date or any beacon date
                if bank.date.date() == parsed_value.date():
                    self.search_matches.append(i)
                    continue
                for beacon in beacons:
                    if beacon.date.date() == parsed_value.date():
                        self.search_matches.append(i)
                        break

            elif search_type == 'amount':
                # Amount search - match bank amount or any beacon amount
                if bank.amount == parsed_value:
                    self.search_matches.append(i)
                    continue
                for beacon in beacons:
                    if beacon.amount == parsed_value:
                        self.search_matches.append(i)
                        break

            else:  # 'name' - default substring search
                # Search in bank description
                if parsed_value in bank.description.lower():
                    self.search_matches.append(i)
                    continue
                # Search in beacon payees
                for beacon in beacons:
                    if parsed_value in beacon.payee.lower():
                        self.search_matches.append(i)
                        break

        if self.search_matches:
            self.search_index = 0
            self.current_index = self.search_matches[0]
            self._update_display()
            # Show search type in result
            type_labels = {
                'quoted': 'text',
                'match_id': 'Match ID',
                'bank_id': 'Bank ID',
                'beacon_id': 'Beacon ID',
                'trans_no': 'trans_no',
                'date': 'date',
                'amount': 'amount',
                'name': 'name'
            }
            self.search_result_label.config(
                text=f"Found {len(self.search_matches)} ({type_labels[search_type]}) (1/{len(self.search_matches)})",
                foreground='gray'
            )
        else:
            self.search_result_label.config(text="No matches found", foreground='#CC0000')

    def _on_search_next(self):
        """Go to next search result."""
        if not self.search_matches:
            self.search_result_label.config(text="No search results")
            return

        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self.current_index = self.search_matches[self.search_index]
        self._update_display()
        self.search_result_label.config(
            text=f"Found {len(self.search_matches)} matches ({self.search_index + 1}/{len(self.search_matches)})"
        )

    def _on_search_prev(self):
        """Go to previous search result."""
        if not self.search_matches:
            self.search_result_label.config(text="No search results")
            return

        self.search_index = (self.search_index - 1) % len(self.search_matches)
        self.current_index = self.search_matches[self.search_index]
        self._update_display()
        self.search_result_label.config(
            text=f"Found {len(self.search_matches)} matches ({self.search_index + 1}/{len(self.search_matches)})"
        )

    def _on_search_clear(self):
        """Clear search."""
        self.search_entry.delete(0, tk.END)
        self.search_matches = []
        self.search_index = 0
        self.search_result_label.config(text="")

    def _on_show_all_changed(self):
        """Handle show all transactions checkbox change."""
        self._apply_queued_changes()
        self.system.save_state()

        # Regenerate suggestions with new setting
        include_confirmed = self.show_all_var.get()
        trans_no_limit = self.trans_no_limit_var.get()
        date_tolerance = self.date_tolerance_var.get()
        self.suggestions = self.system.generate_suggestions(
            include_confirmed=include_confirmed,
            trans_no_limit=trans_no_limit,
            date_tolerance_days=date_tolerance
        )
        self.current_index = 0

        self._update_display()

    def _on_trans_no_limit_changed(self, event=None):
        """Handle trans_no limit change - regenerate suggestions."""
        self._apply_queued_changes()
        self.system.save_state()

        # Regenerate suggestions with new trans_no limit
        include_confirmed = self.show_all_var.get()
        trans_no_limit = self.trans_no_limit_var.get()
        date_tolerance = self.date_tolerance_var.get()
        self.suggestions = self.system.generate_suggestions(
            include_confirmed=include_confirmed,
            trans_no_limit=trans_no_limit,
            date_tolerance_days=date_tolerance
        )
        self.current_index = 0

        self._update_display()

    def _on_check_consistency(self):
        """Run consistency check and navigate to first inconsistency if found."""
        self._run_consistency_check()

    def _run_consistency_check(self, show_message_if_clean=True):
        """Run consistency check with optional progress dialog.

        Args:
            show_message_if_clean: If True, show a message box when no issues found
        """
        # For large datasets, show progress dialog
        confirmed_count = len(self.system.confirmed_matches)

        if confirmed_count > 100:
            # Create progress dialog
            progress_window = tk.Toplevel(self.master)
            progress_window.title("Checking Consistency")
            progress_window.geometry("400x100")
            progress_window.transient(self.master)
            progress_window.grab_set()

            # Center the dialog
            progress_window.update_idletasks()
            x = self.master.winfo_x() + (self.master.winfo_width() - 400) // 2
            y = self.master.winfo_y() + (self.master.winfo_height() - 100) // 2
            progress_window.geometry(f"+{x}+{y}")

            ttk.Label(progress_window, text="Checking consistency...",
                      font=('Segoe UI', 11)).pack(pady=(15, 5))

            progress_bar = ttk.Progressbar(progress_window, length=350, mode='determinate')
            progress_bar.pack(pady=10)

            def update_progress(current, total, message):
                progress_bar['maximum'] = total
                progress_bar['value'] = current
                progress_window.update()

            self.inconsistencies = self.system.check_consistency(progress_callback=update_progress)
            progress_window.destroy()
        else:
            self.inconsistencies = self.system.check_consistency()

        self.current_inconsistency_index = 0
        self._update_inconsistency_ui()

        if self.inconsistencies:
            # Navigate to first inconsistency
            self._navigate_to_inconsistency(0)
        elif show_message_if_clean:
            messagebox.showinfo("Consistency Check", "No inconsistencies found.")

    def _update_inconsistency_ui(self):
        """Update the inconsistency navigation UI based on current state."""
        if not self.inconsistencies:
            self.prev_issue_button.config(state=tk.DISABLED)
            self.next_issue_button.config(state=tk.DISABLED)
            self.prev_related_button.config(state=tk.DISABLED)
            self.next_related_button.config(state=tk.DISABLED)
            self.related_label.config(text="")
            self.inconsistency_label.config(text="No inconsistencies found", foreground='green')
        else:
            count = len(self.inconsistencies)
            current = self.current_inconsistency_index + 1
            match, reason, related_matches = self.inconsistencies[self.current_inconsistency_index]

            # Truncate very long messages (120 chars)
            if len(reason) > 120:
                reason = reason[:120] + "..."
            self.inconsistency_label.config(
                text=f"Issue {current}/{count}: {reason}",
                foreground='red'
            )

            # Enable/disable issue navigation buttons
            self.prev_issue_button.config(
                state=tk.NORMAL if self.current_inconsistency_index > 0 else tk.DISABLED
            )
            self.next_issue_button.config(
                state=tk.NORMAL if self.current_inconsistency_index < count - 1 else tk.DISABLED
            )

            # Update related records navigation
            num_related = len(related_matches)
            if num_related > 1:
                # Find current position in related matches
                current_match = self.suggestions[self.current_index] if self.current_index < len(self.suggestions) else None
                if current_match:
                    for i, rm in enumerate(related_matches):
                        if rm.id == current_match.id:
                            self.current_related_index = i
                            break

                self.related_label.config(text=f"{self.current_related_index + 1}/{num_related}")
                self.prev_related_button.config(
                    state=tk.NORMAL if self.current_related_index > 0 else tk.DISABLED
                )
                self.next_related_button.config(
                    state=tk.NORMAL if self.current_related_index < num_related - 1 else tk.DISABLED
                )
            else:
                # Only one related match, disable related navigation
                self.related_label.config(text="")
                self.prev_related_button.config(state=tk.DISABLED)
                self.next_related_button.config(state=tk.DISABLED)

        # Force UI refresh
        self.inconsistency_label.update_idletasks()

    def _navigate_to_inconsistency(self, index):
        """Navigate to a specific inconsistency by index."""
        if not self.inconsistencies or index < 0 or index >= len(self.inconsistencies):
            return

        self.current_inconsistency_index = index
        self.current_related_index = 0  # Reset to first related match
        match, reason, related_matches = self.inconsistencies[index]

        # Find the match in the suggestions list
        # First, ensure we're showing all transactions (including confirmed)
        if not self.show_all_var.get():
            self.show_all_var.set(True)
            self._on_show_all_changed()

        # Find the match index in suggestions
        match_index = self.system.find_match_in_suggestions(match)
        if match_index >= 0:
            self.current_index = match_index
            self._update_display()

        self._update_inconsistency_ui()

    def _on_prev_inconsistency(self):
        """Navigate to previous inconsistency (re-checks for accuracy)."""
        # Re-run consistency check to get updated list
        self.inconsistencies = self.system.check_consistency()

        if not self.inconsistencies:
            self._update_inconsistency_ui()
            return

        # Find current match in new inconsistency list or go to previous
        new_index = max(0, self.current_inconsistency_index - 1)
        if new_index >= len(self.inconsistencies):
            new_index = len(self.inconsistencies) - 1

        self._navigate_to_inconsistency(new_index)

    def _on_next_inconsistency(self):
        """Navigate to next inconsistency (re-checks for accuracy)."""
        # Re-run consistency check to get updated list
        self.inconsistencies = self.system.check_consistency()

        if not self.inconsistencies:
            self._update_inconsistency_ui()
            return

        # Move to next or stay at end
        new_index = self.current_inconsistency_index + 1
        if new_index >= len(self.inconsistencies):
            new_index = len(self.inconsistencies) - 1

        self._navigate_to_inconsistency(new_index)

    def _on_prev_related(self):
        """Navigate to previous related match within current inconsistency."""
        if not self.inconsistencies:
            return

        match, reason, related_matches = self.inconsistencies[self.current_inconsistency_index]
        debug_log(f"_on_prev_related: {len(related_matches)} related matches, current_related_index={self.current_related_index}")
        for i, rm in enumerate(related_matches):
            debug_log(f"  related[{i}]: {rm.id}, bank={rm.bank_transaction.id}")
        if self.current_related_index > 0:
            self.current_related_index -= 1
            target_match = related_matches[self.current_related_index]
            debug_log(f"Navigating to related[{self.current_related_index}]: {target_match.id}")
            self._navigate_to_related_match(target_match)

    def _on_next_related(self):
        """Navigate to next related match within current inconsistency."""
        if not self.inconsistencies:
            return

        match, reason, related_matches = self.inconsistencies[self.current_inconsistency_index]
        debug_log(f"_on_next_related: {len(related_matches)} related matches, current_related_index={self.current_related_index}")
        for i, rm in enumerate(related_matches):
            debug_log(f"  related[{i}]: {rm.id}, bank={rm.bank_transaction.id}")
        if self.current_related_index < len(related_matches) - 1:
            self.current_related_index += 1
            target_match = related_matches[self.current_related_index]
            debug_log(f"Navigating to related[{self.current_related_index}]: {target_match.id}")
            self._navigate_to_related_match(target_match)

    def _navigate_to_related_match(self, match):
        """Navigate to a specific related match."""
        debug_log(f"_navigate_to_related_match: looking for {match.id}, bank={match.bank_transaction.id}")

        # Ensure we're showing all transactions
        if not self.show_all_var.get():
            self.show_all_var.set(True)
            self._on_show_all_changed()

        # Find the match index in suggestions
        match_index = self.system.find_match_in_suggestions(match)
        debug_log(f"find_match_in_suggestions returned index={match_index}")
        if match_index >= 0:
            self.current_index = match_index
            actual_match = self.suggestions[self.current_index]
            debug_log(f"Moved to index {match_index}, actual match is {actual_match.id}, bank={actual_match.bank_transaction.id}")
            self._update_display()
        else:
            debug_log(f"WARNING: Match {match.id} not found in suggestions!")

        self._update_inconsistency_ui()

    def _get_current_bank_transaction(self):
        """Get the current bank transaction (from match or direct lookup)."""
        if self.suggestions and self.current_index < len(self.suggestions):
            return self.suggestions[self.current_index].bank_transaction
        return None

    def _on_create_manual_match(self):
        """Create a manual match from trans_no(s) entered by the user."""
        bank_txn = self._get_current_bank_transaction()
        if not bank_txn:
            messagebox.showerror("Error", "No bank transaction selected")
            return

        # Check if this bank transaction is already matched
        if self.suggestions and self.current_index < len(self.suggestions):
            match = self.suggestions[self.current_index]
            if match.status in (MatchStatus.CONFIRMED, MatchStatus.MANUAL_MATCH,
                               MatchStatus.MANUALLY_RESOLVED):
                messagebox.showerror("Error",
                    f"This bank transaction is already {match.status.value}.\n"
                    "Use Reject first if you want to change it.")
                return

        # Get trans_nos from entry
        trans_no_text = self.trans_no_entry.get().strip()
        if not trans_no_text:
            messagebox.showerror("Error", "Please enter one or more trans_no values (comma-separated)")
            return

        # Parse trans_nos
        trans_nos = [t.strip() for t in trans_no_text.split(',') if t.strip()]
        if not trans_nos:
            messagebox.showerror("Error", "Please enter valid trans_no values")
            return

        # Create the manual match
        success, message, match = self.system.create_manual_match(bank_txn, trans_nos)

        if success:
            messagebox.showinfo("Success", message)
            # Clear the entry
            self.trans_no_entry.delete(0, tk.END)
            # Update the current match in suggestions if it exists
            if self.suggestions and self.current_index < len(self.suggestions):
                self.suggestions[self.current_index] = match
            # Refresh display
            self._update_display()
        else:
            messagebox.showerror("Error", message)

    def _on_mark_resolved(self):
        """Mark the current bank transaction as manually resolved."""
        bank_txn = self._get_current_bank_transaction()
        if not bank_txn:
            messagebox.showerror("Error", "No bank transaction selected")
            return

        # Check if this bank transaction is already matched
        if self.suggestions and self.current_index < len(self.suggestions):
            match = self.suggestions[self.current_index]
            if match.status in (MatchStatus.CONFIRMED, MatchStatus.MANUAL_MATCH,
                               MatchStatus.MANUALLY_RESOLVED):
                messagebox.showerror("Error",
                    f"This bank transaction is already {match.status.value}.\n"
                    "Use Reject first if you want to change it.")
                return

        # Get comment from entry
        comment = self.resolved_comment_entry.get().strip()
        if not comment:
            messagebox.showerror("Error", "Please enter a comment explaining how this was resolved")
            return

        # Create the manually resolved entry
        success, message, match = self.system.create_manually_resolved(bank_txn, comment)

        if success:
            messagebox.showinfo("Success", message)
            # Clear the entry
            self.resolved_comment_entry.delete(0, tk.END)
            # Update the current match in suggestions if it exists
            if self.suggestions and self.current_index < len(self.suggestions):
                self.suggestions[self.current_index] = match
            # Refresh display
            self._update_display()
        else:
            messagebox.showerror("Error", message)

    def _on_export_csvs(self):
        """Export matched and unmatched CSVs."""
        import os

        # Get base directory for saving
        base_dir = self.system.base_dir

        # Export matched CSV
        matched_path = os.path.join(base_dir, "matched_transactions.csv")
        matched_count = self.system.export_matched_csv(matched_path)

        # Export unmatched beacon CSV
        unmatched_beacon_path = os.path.join(base_dir, "unmatched_beacons.csv")
        unmatched_beacon_count = self.system.export_unmatched_beacon_csv(unmatched_beacon_path)

        # Export unmatched bank CSV
        unmatched_bank_path = os.path.join(base_dir, "unmatched_bank.csv")
        unmatched_bank_count = self.system.export_unmatched_bank_csv(unmatched_bank_path)

        messagebox.showinfo("Export Complete",
            f"Exported:\n\n"
            f"1. Matched transactions: {matched_count} rows\n"
            f"   → {matched_path}\n\n"
            f"2. Unmatched beacons: {unmatched_beacon_count} rows\n"
            f"   → {unmatched_beacon_path}\n\n"
            f"3. Unmatched bank: {unmatched_bank_count} rows\n"
            f"   → {unmatched_bank_path}")


def main():
    """Main entry point for GUI application."""
    root = tk.Tk()

    # Set icon if available
    try:
        root.iconbitmap('icon.ico')
    except tk.TclError:
        pass

    app = ReconciliationGUI(root)

    # Save on window close
    def on_closing():
        app._auto_save()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
