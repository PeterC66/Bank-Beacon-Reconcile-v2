"""
Bank Beacon Reconciliation GUI v2
Bank-centric split-panel interface for reconciling transactions.

v2 design:
- Left panel: Bank entry details with Prev/Next navigation (date order)
- Right panel: Beacon candidate details, one at a time, ranked by confidence
- Default shows un-reconciled bank entries only (toggle to show all)
- Rejected pairings shown at bottom of candidate list, greyed out
- 1-to-2 candidates shown as a pair with single Reconcile button
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sys
import os

from reconciliation_system import (
    ReconciliationSystem, BeaconCandidate, Reconciliation,
    BankTransaction, BeaconEntry, VERSION, debug_log
)


class ReconciliationGUI:
    """Main GUI for bank reconciliation v2."""

    # Color scheme
    COLORS = {
        'reconciled': '#D4EDDA',       # Green
        'unreconciled': '#FFF3CD',     # Yellow/amber
        'resolved': '#B8DAFF',         # Blue
        'rejected': '#F8D7DA',         # Red/pink
        'no_candidates': '#E2E3E5',    # Gray
    }

    def __init__(self, master: tk.Tk, data_dir: str = None):
        self.master = master
        self.master.title(f"Bank Beacon Reconciliation v{VERSION}")  # Updated after system loads
        self.master.geometry("1300x750")
        self.master.minsize(1000, 650)

        # Determine directories
        code_dir = os.path.dirname(os.path.abspath(__file__))
        if data_dir is None:
            # Check if command line arg provided
            if len(sys.argv) > 1:
                data_dir = sys.argv[1].strip().rstrip('"').rstrip("'")
                data_dir = os.path.abspath(data_dir)
            else:
                data_dir = code_dir

        # Initialize reconciliation system
        self.system = ReconciliationSystem(data_dir=data_dir, code_dir=code_dir)
        self.system.load_data()

        # Update window title
        self.master.title(f"{self.system._get_title()} v{VERSION}")

        bank_count = len(self.system.bank_transactions)
        beacon_count = len(self.system.beacon_entries)

        if bank_count == 0:
            messagebox.showwarning(
                "Loading Issue",
                f"Loaded {bank_count} bank transactions.\n\n"
                f"Data folder: {self.system.data_dir}\n\n"
                f"Expected file: {self.system.config['bank_file']}\n\n"
                f"Please ensure the bank file exists and has the correct format."
            )
        elif beacon_count == 0:
            messagebox.showinfo(
                "No Beacon File",
                f"Loaded {bank_count} bank transactions, no beacon entries.\n\n"
                f"Beacon file not found or empty. Reconciliation will work "
                f"with bank entries only (no comparison report)."
            )

        # Bank navigation state
        self.show_all_bank = False  # False = un-reconciled only
        self.bank_list: list = []  # Current filtered bank list
        self.bank_index: int = 0   # Current index into bank_list

        # Right panel: beacon candidates for current bank entry
        self.candidates: list = []
        self.candidate_index: int = 0

        # Search state
        self.bank_search_matches: list = []
        self.bank_search_index: int = 0
        self.beacon_search_results: list = []  # BeaconEntry objects from search
        self.beacon_search_active: bool = False

        # Consistency check state
        self.inconsistencies: list = []  # [(Reconciliation, reason), ...] - active (non-ignored)
        self.ignored_inconsistencies_shown: list = []  # Temporarily shown ignored issues
        self.showing_ignored: bool = False
        self.inconsistency_index: int = 0

        # Build bank list
        self._rebuild_bank_list()

        # Setup GUI
        self._setup_styles()
        self._create_widgets()
        self._update_display()

        # Bind Enter key for quick reconcile
        self.master.bind('<Return>', self._on_enter_key)

        # Show startup summary
        if bank_count > 0 and beacon_count > 0:
            stats = self.system.get_statistics()
            self.master.after(100, lambda: messagebox.showinfo(
                "Data Loaded",
                f"Loaded {bank_count} bank transactions\n"
                f"Loaded {beacon_count} beacon entries\n\n"
                f"Reconciled: {stats['reconciled_count']}\n"
                f"Manually resolved: {stats['resolved_count']}\n"
                f"Un-reconciled: {stats['unreconciled_count']}"
            ))

    # -------------------------------------------------------------------
    # Bank list management
    # -------------------------------------------------------------------

    def _rebuild_bank_list(self):
        """Rebuild the filtered bank entry list."""
        if self.show_all_bank:
            self.bank_list = list(self.system.get_bank_entries_sorted())
        else:
            self.bank_list = list(self.system.get_unreconciled_bank_entries())

        # Clamp index
        if self.bank_list:
            self.bank_index = max(0, min(self.bank_index, len(self.bank_list) - 1))
        else:
            self.bank_index = 0

    def _current_bank(self):
        """Get the current bank transaction, or None."""
        if self.bank_list and 0 <= self.bank_index < len(self.bank_list):
            return self.bank_list[self.bank_index]
        return None

    def _current_candidate(self):
        """Get the current beacon candidate, or None."""
        if self.candidates and 0 <= self.candidate_index < len(self.candidates):
            return self.candidates[self.candidate_index]
        return None

    def _refresh_candidates(self):
        """Refresh beacon candidates for current bank entry."""
        bank = self._current_bank()
        if bank and not self.system.is_bank_reconciled(bank.id):
            self.candidates = self.system.get_candidates_for_bank(bank)
        else:
            self.candidates = []
        self.candidate_index = 0
        self.beacon_search_active = False

    # -------------------------------------------------------------------
    # Styles
    # -------------------------------------------------------------------

    def _setup_styles(self):
        """Configure ttk styles."""
        style = ttk.Style()
        style.configure('Title.TLabel', font=('Segoe UI', 14, 'bold'))
        style.configure('Header.TLabel', font=('Segoe UI', 11, 'bold'))
        style.configure('Amount.TLabel', font=('Segoe UI', 13, 'bold'))
        style.configure('Status.TLabel', font=('Segoe UI', 10, 'bold'))
        style.configure('Nav.TButton', font=('Segoe UI', 10))
        style.configure('Action.TButton', font=('Segoe UI', 10, 'bold'), padding=8)
        style.configure('Value.TLabel', font=('Segoe UI', 12))
        style.configure('Rejected.TLabel', font=('Segoe UI', 10), foreground='#999999')
        style.configure('Small.TLabel', font=('Segoe UI', 9))

    # -------------------------------------------------------------------
    # Widget creation
    # -------------------------------------------------------------------

    def _create_widgets(self):
        """Create all GUI widgets."""
        # Outer frame with scrollbar
        outer_frame = ttk.Frame(self.master)
        outer_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(outer_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        main_frame = ttk.Frame(self.canvas, padding="8")
        self.canvas_window = self.canvas.create_window((0, 0), window=main_frame, anchor="nw")

        def configure_scroll(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def configure_canvas_width(event):
            self.canvas.itemconfig(self.canvas_window, width=event.width)

        main_frame.bind("<Configure>", configure_scroll)
        self.canvas.bind("<Configure>", configure_canvas_width)

        # Mousewheel scrolling
        def on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def on_mousewheel_linux(event):
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")

        self.canvas.bind_all("<MouseWheel>", on_mousewheel)
        self.canvas.bind_all("<Button-4>", on_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", on_mousewheel_linux)

        # --- Stats bar ---
        self._create_stats_bar(main_frame)

        # --- Main content: bank (left) + beacon (right) ---
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 5))
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(0, weight=1)

        self._create_bank_panel(content_frame)
        self._create_beacon_panel(content_frame)

        # --- Member beacon transactions panel ---
        self._create_member_panel(main_frame)

        # --- Action bar ---
        self._create_action_bar(main_frame)

    def _create_stats_bar(self, parent):
        """Create the stats bar at top."""
        stats_frame = ttk.Frame(parent)
        stats_frame.pack(fill=tk.X, pady=(0, 5))

        # Version
        ttk.Label(stats_frame, text=f"v{VERSION}", style='Small.TLabel',
                  foreground='gray').pack(side=tk.LEFT, padx=(0, 15))

        # Stats labels
        self.stats_label = ttk.Label(stats_frame, text="", style='Small.TLabel')
        self.stats_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Bank navigation counter
        self.bank_counter_label = ttk.Label(stats_frame, text="", style='Small.TLabel')
        self.bank_counter_label.pack(side=tk.RIGHT)

    # -------------------------------------------------------------------
    # Left panel: Bank entry
    # -------------------------------------------------------------------

    def _create_bank_panel(self, parent):
        """Create bank entry panel (left side)."""
        bank_outer = ttk.LabelFrame(parent, text="Bank Entry", padding="10")
        bank_outer.grid(row=0, column=0, sticky='nsew', padx=(0, 4))

        # Navigation row
        nav_row = ttk.Frame(bank_outer)
        nav_row.pack(fill=tk.X, pady=(0, 8))

        self.bank_prev_btn = ttk.Button(nav_row, text="< Prev Bank",
                                         command=self._on_bank_prev, style='Nav.TButton')
        self.bank_prev_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.bank_next_btn = ttk.Button(nav_row, text="Next Bank >",
                                         command=self._on_bank_next, style='Nav.TButton')
        self.bank_next_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Show all toggle
        self.show_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(nav_row, text="Show all",
                         variable=self.show_all_var,
                         command=self._on_show_all_changed).pack(side=tk.LEFT, padx=5)

        self.bank_nav_label = ttk.Label(nav_row, text="0 / 0", style='Small.TLabel')
        self.bank_nav_label.pack(side=tk.RIGHT)

        ttk.Button(nav_row, text="Reset", command=self._on_reset,
                   style='Nav.TButton').pack(side=tk.RIGHT, padx=(0, 5))

        # Go-to entry (jump to Nth entry in current list)
        self.goto_entry = ttk.Entry(nav_row, width=4)
        self.goto_entry.pack(side=tk.RIGHT, padx=(0, 2))
        self.goto_entry.bind('<Return>', self._on_goto)
        ttk.Label(nav_row, text="Go:", style='Small.TLabel').pack(side=tk.RIGHT, padx=(5, 0))

        # Status indicator
        self.bank_status_frame = tk.Frame(bank_outer, height=28)
        self.bank_status_frame.pack(fill=tk.X, pady=(0, 8))
        self.bank_status_frame.pack_propagate(False)

        self.bank_status_label = ttk.Label(self.bank_status_frame, text="UN-RECONCILED",
                                            style='Status.TLabel')
        self.bank_status_label.pack(side=tk.LEFT, padx=5, pady=2)

        self.bank_rec_type_label = ttk.Label(self.bank_status_frame, text="",
                                              style='Small.TLabel', foreground='gray')
        self.bank_rec_type_label.pack(side=tk.RIGHT, padx=5, pady=2)

        # Details grid - right-justified so values are closer to beacon panel
        details = ttk.Frame(bank_outer)
        details.pack(fill=tk.BOTH, expand=True)
        details.columnconfigure(0, weight=1)  # Push content right

        row = 0
        ttk.Label(details, text="Bank ID:", style='Header.TLabel').grid(row=row, column=1, sticky='e', pady=3)
        self.bank_id_label = ttk.Label(details, text="", foreground='gray')
        self.bank_id_label.grid(row=row, column=2, sticky='e', padx=(10, 0), pady=3)

        row += 1
        ttk.Label(details, text="Date:", style='Header.TLabel').grid(row=row, column=1, sticky='e', pady=3)
        self.bank_date_label = ttk.Label(details, text="")
        self.bank_date_label.grid(row=row, column=2, sticky='e', padx=(10, 0), pady=3)

        row += 1
        ttk.Label(details, text="Type:", style='Header.TLabel').grid(row=row, column=1, sticky='e', pady=3)
        self.bank_type_label = ttk.Label(details, text="")
        self.bank_type_label.grid(row=row, column=2, sticky='e', padx=(10, 0), pady=3)

        row += 1
        ttk.Label(details, text="Description:", style='Header.TLabel').grid(row=row, column=1, sticky='ne', pady=3)
        self.bank_desc_label = ttk.Label(details, text="", wraplength=350, style='Value.TLabel',
                                          justify=tk.RIGHT)
        self.bank_desc_label.grid(row=row, column=2, sticky='e', padx=(10, 0), pady=3)

        row += 1
        ttk.Label(details, text="Member:", style='Header.TLabel').grid(row=row, column=1, sticky='ne', pady=3)
        self.member_lookup_label = ttk.Label(details, text="", wraplength=350,
                                              foreground='#006600', justify=tk.RIGHT)
        self.member_lookup_label.grid(row=row, column=2, sticky='e', padx=(10, 0), pady=3)

        row += 1
        ttk.Label(details, text="Amount:", style='Header.TLabel').grid(row=row, column=1, sticky='e', pady=3)
        self.bank_amount_label = ttk.Label(details, text="", style='Amount.TLabel',
                                            foreground='#0066CC')
        self.bank_amount_label.grid(row=row, column=2, sticky='e', padx=(10, 0), pady=3)

        # Reconciled beacon info (shown when bank is reconciled)
        self.reconciled_info_frame = ttk.LabelFrame(bank_outer, text="Reconciled With", padding="5")
        self.reconciled_info_label = ttk.Label(self.reconciled_info_frame, text="",
                                                wraplength=400, justify=tk.LEFT)
        self.reconciled_info_label.pack(fill=tk.X)
        self.reconciled_comment_label = ttk.Label(self.reconciled_info_frame, text="",
                                                   foreground='#666666', wraplength=400)
        self.reconciled_comment_label.pack(fill=tk.X)
        self.reconciled_comment_label.bind('<Button-1>', self._on_edit_resolved_comment)

        # Bank search
        search_frame = ttk.Frame(bank_outer)
        search_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(search_frame, text="Search:", style='Small.TLabel').pack(side=tk.LEFT)
        self.bank_search_entry = ttk.Entry(search_frame, width=20)
        self.bank_search_entry.pack(side=tk.LEFT, padx=3)
        self.bank_search_entry.bind('<Return>', self._on_bank_search)
        ttk.Button(search_frame, text="Find", command=self._on_bank_search).pack(side=tk.LEFT, padx=1)
        ttk.Button(search_frame, text="Clear", command=self._on_bank_search_clear).pack(side=tk.LEFT, padx=1)
        self.bank_search_result = ttk.Label(search_frame, text="", foreground='gray',
                                             style='Small.TLabel')
        self.bank_search_result.pack(side=tk.LEFT, padx=5)
        # Search format hint
        ttk.Label(bank_outer, text='[surname | "exact name" | £12.50 | 17/03/25 | #memno | BANK_001]',
                  foreground='#666666', font=('Segoe UI', 8)).pack(fill=tk.X)

    # -------------------------------------------------------------------
    # Right panel: Beacon candidate
    # -------------------------------------------------------------------

    def _create_beacon_panel(self, parent):
        """Create beacon candidate panel (right side)."""
        beacon_outer = ttk.LabelFrame(parent, text="Beacon Candidate", padding="10")
        beacon_outer.grid(row=0, column=1, sticky='nsew', padx=(4, 0))

        # Navigation row
        nav_row = ttk.Frame(beacon_outer)
        nav_row.pack(fill=tk.X, pady=(0, 8))

        self.beacon_prev_btn = ttk.Button(nav_row, text="< Prev Candidate",
                                           command=self._on_candidate_prev, style='Nav.TButton')
        self.beacon_prev_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.beacon_nav_label = tk.Label(nav_row, text="0 / 0",
                                          font=('Segoe UI', 10), fg='gray')
        self.beacon_nav_label.pack(side=tk.LEFT, padx=(0, 5))

        self.beacon_next_btn = ttk.Button(nav_row, text="Next Candidate >",
                                           command=self._on_candidate_next, style='Nav.TButton')
        self.beacon_next_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Confidence / type indicator
        score_row = ttk.Frame(beacon_outer)
        score_row.pack(fill=tk.X, pady=(0, 5))

        self.confidence_label = ttk.Label(score_row, text="", style='Status.TLabel')
        self.confidence_label.pack(side=tk.LEFT)

        self.match_type_label = ttk.Label(score_row, text="", style='Small.TLabel',
                                           foreground='gray')
        self.match_type_label.pack(side=tk.LEFT, padx=10)

        self.score_breakdown_label = ttk.Label(score_row, text="", foreground='gray',
                                                style='Small.TLabel')
        self.score_breakdown_label.pack(side=tk.RIGHT)

        # Rejected indicator
        self.rejected_indicator = ttk.Label(beacon_outer, text="REJECTED PAIRING",
                                             foreground='#CC0000',
                                             font=('Segoe UI', 10, 'bold'))

        # Beacon entry 1
        self.beacon1_frame = ttk.LabelFrame(beacon_outer, text="Beacon Entry 1", padding="5")
        self.beacon1_widgets = self._create_beacon_entry_widgets(self.beacon1_frame)

        # Beacon entry 2 (for 1-to-2 matches)
        self.beacon2_frame = ttk.LabelFrame(beacon_outer, text="Beacon Entry 2", padding="5")
        self.beacon2_widgets = self._create_beacon_entry_widgets(self.beacon2_frame)

        # Total row (for 1-to-2)
        self.total_frame = ttk.Frame(beacon_outer)
        ttk.Label(self.total_frame, text="Total:", style='Header.TLabel').pack(side=tk.LEFT)
        self.beacon_total_label = ttk.Label(self.total_frame, text="", style='Amount.TLabel',
                                             foreground='#0066CC')
        self.beacon_total_label.pack(side=tk.LEFT, padx=10)

        # No candidates message
        self.no_candidates_label = ttk.Label(beacon_outer, text="",
                                              font=('Segoe UI', 11), foreground='gray',
                                              justify='center')

        # Amount mismatch suggestion (clickable)
        self.amount_mismatch_label = tk.Label(
            beacon_outer, text="", font=('Segoe UI', 10),
            fg='#0066CC', cursor='hand2', justify='center', wraplength=400)
        self.amount_mismatch_label.bind('<Button-1>', self._on_amount_mismatch_click)
        self._amount_mismatch_beacon = None  # Store suggested beacon for click handler

        # Beacon search
        beacon_search_area = ttk.Frame(beacon_outer)
        beacon_search_area.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))
        search_frame = ttk.Frame(beacon_search_area)
        search_frame.pack(fill=tk.X)
        ttk.Label(search_frame, text="Search:", style='Small.TLabel').pack(side=tk.LEFT)
        self.beacon_search_entry = ttk.Entry(search_frame, width=20)
        self.beacon_search_entry.pack(side=tk.LEFT, padx=3)
        self.beacon_search_entry.bind('<Return>', self._on_beacon_search)
        ttk.Button(search_frame, text="Find", command=self._on_beacon_search).pack(side=tk.LEFT, padx=1)
        self.beacon_bypass_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_frame, text="All beacons",
                         variable=self.beacon_bypass_var).pack(side=tk.LEFT, padx=3)
        self.cheque_filter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_frame, text="Cheque",
                         variable=self.cheque_filter_var,
                         command=self._on_cheque_filter_changed).pack(side=tk.LEFT, padx=3)
        ttk.Button(search_frame, text="Clear", command=self._on_beacon_search_clear).pack(side=tk.LEFT, padx=1)
        self.beacon_search_result = ttk.Label(search_frame, text="", foreground='gray',
                                               style='Small.TLabel')
        self.beacon_search_result.pack(side=tk.LEFT, padx=5)
        # Search format hint
        ttk.Label(beacon_search_area, text='[surname | "exact name" | £12.50 | 17/03/25 | #memno | 7656 (trans no) | BEACON_001]',
                  foreground='#666666', font=('Segoe UI', 8)).pack(fill=tk.X)

    def _create_beacon_entry_widgets(self, frame):
        """Create widgets for a single beacon entry display."""
        widgets = {}
        details = ttk.Frame(frame)
        details.pack(fill=tk.X)

        row = 0
        ttk.Label(details, text="Trans No:").grid(row=row, column=0, sticky='w', pady=2)
        widgets['trans_no'] = ttk.Label(details, text="")
        widgets['trans_no'].grid(row=row, column=1, sticky='w', padx=10, pady=2)

        row += 1
        ttk.Label(details, text="Date:").grid(row=row, column=0, sticky='w', pady=2)
        widgets['date'] = ttk.Label(details, text="")
        widgets['date'].grid(row=row, column=1, sticky='w', padx=10, pady=2)

        row += 1
        ttk.Label(details, text="Payee:").grid(row=row, column=0, sticky='w', pady=2)
        widgets['payee'] = ttk.Label(details, text="", wraplength=280, style='Value.TLabel')
        widgets['payee'].grid(row=row, column=1, sticky='w', padx=10, pady=2)

        row += 1
        ttk.Label(details, text="Detail:").grid(row=row, column=0, sticky='w', pady=2)
        widgets['detail'] = ttk.Label(details, text="", wraplength=280, style='Value.TLabel')
        widgets['detail'].grid(row=row, column=1, sticky='w', padx=10, pady=2)

        row += 1
        ttk.Label(details, text="Member 1:").grid(row=row, column=0, sticky='w', pady=2)
        widgets['member_1'] = ttk.Label(details, text="", foreground='#006600')
        widgets['member_1'].grid(row=row, column=1, sticky='w', padx=10, pady=2)

        row += 1
        ttk.Label(details, text="Member 2:").grid(row=row, column=0, sticky='w', pady=2)
        widgets['member_2'] = ttk.Label(details, text="", foreground='#006600')
        widgets['member_2'].grid(row=row, column=1, sticky='w', padx=10, pady=2)

        row += 1
        ttk.Label(details, text="Amount:").grid(row=row, column=0, sticky='w', pady=2)
        widgets['amount'] = ttk.Label(details, text="", foreground='#0066CC',
                                       font=('Segoe UI', 11, 'bold'))
        widgets['amount'].grid(row=row, column=1, sticky='w', padx=10, pady=2)

        row += 1
        ttk.Label(details, text="ID:").grid(row=row, column=0, sticky='w', pady=2)
        widgets['id'] = ttk.Label(details, text="", foreground='gray')
        widgets['id'].grid(row=row, column=1, sticky='w', padx=10, pady=2)

        return widgets

    # -------------------------------------------------------------------
    # Member beacon transactions panel
    # -------------------------------------------------------------------

    def _create_member_panel(self, parent):
        """Create the member beacon transactions panel below the main panels."""
        self.member_panel = ttk.LabelFrame(parent, text="Member's Beacon Transactions",
                                            padding="5")
        self.member_panel.pack(fill=tk.X, pady=(5, 0))

        self.member_panel_header = ttk.Label(self.member_panel, text="",
                                              style='Small.TLabel', foreground='#006600')
        self.member_panel_header.pack(fill=tk.X)

        # Treeview for beacon transactions
        tree_frame = ttk.Frame(self.member_panel)
        tree_frame.pack(fill=tk.X)

        columns = ('trans_no', 'date', 'amount', 'payee', 'detail', 'status')
        self.member_tree = ttk.Treeview(tree_frame, columns=columns, show='headings',
                                         height=6, selectmode='browse')
        self.member_tree.heading('trans_no', text='Trans No')
        self.member_tree.heading('date', text='Date')
        self.member_tree.heading('amount', text='Amount')
        self.member_tree.heading('payee', text='Payee')
        self.member_tree.heading('detail', text='Detail')
        self.member_tree.heading('status', text='Status')

        self.member_tree.column('trans_no', width=55, minwidth=45)
        self.member_tree.column('date', width=68, minwidth=58)
        self.member_tree.column('amount', width=58, minwidth=45)
        self.member_tree.column('payee', width=130, minwidth=60)
        self.member_tree.column('detail', width=100, minwidth=50)
        self.member_tree.column('status', width=85, minwidth=60)

        tree_scroll = ttk.Scrollbar(tree_frame, orient='vertical',
                                     command=self.member_tree.yview)
        self.member_tree.configure(yscrollcommand=tree_scroll.set)
        self.member_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Tags for row styling (reconciled/unreconciled x odd/even)
        self.member_tree.tag_configure('reconciled', foreground='#006600')
        self.member_tree.tag_configure('unreconciled', foreground='#333333')
        self.member_tree.tag_configure('reconciled_alt', foreground='#006600', background='#F0F0F0')
        self.member_tree.tag_configure('unreconciled_alt', foreground='#333333', background='#F0F0F0')

        # Bind click
        self.member_tree.bind('<Double-1>', self._on_member_tree_click)

        # Store beacon_id for each tree item (for click navigation)
        self._member_tree_beacon_ids = {}

    def _update_member_panel(self):
        """Update the member beacon transactions panel."""
        # Clear existing rows
        for item in self.member_tree.get_children():
            self.member_tree.delete(item)
        self._member_tree_beacon_ids = {}
        self.member_panel_header.config(text="")

        bank = self._current_bank()
        if not bank:
            return

        # Determine which member number(s) to show
        mem_nos = []  # Resolved numeric member numbers
        source_label = ""

        # Check if we have a beacon candidate or reconciled beacon
        rec = self.system.get_reconciliation_for_bank(bank.id)
        if rec and rec.status != 'manually_resolved' and rec.beacon_ids:
            # Reconciled - use beacon's resolved mem_nos
            beacons = self.system.get_beacon_entries_for_reconciliation(rec)
            for b in beacons:
                if b.mem_no_1 and b.mem_no_1 not in mem_nos:
                    mem_nos.append(b.mem_no_1)
                if b.mem_no_2 and b.mem_no_2 not in mem_nos:
                    mem_nos.append(b.mem_no_2)
        elif rec and rec.status == 'manually_resolved':
            pass  # Will fall through to bank mem_nos below
        elif self.beacon_search_active:
            # Beacon search active - use member from displayed search result
            if (self.beacon_search_results and
                    0 <= self.candidate_index < len(self.beacon_search_results)):
                beacon = self.beacon_search_results[self.candidate_index]
                if beacon.mem_no_1 and beacon.mem_no_1 not in mem_nos:
                    mem_nos.append(beacon.mem_no_1)
                if beacon.mem_no_2 and beacon.mem_no_2 not in mem_nos:
                    mem_nos.append(beacon.mem_no_2)
        else:
            # Not reconciled - use current candidate's mem_nos
            candidate = self._current_candidate()
            if candidate:
                for b in candidate.beacon_entries:
                    if b.mem_no_1 and b.mem_no_1 not in mem_nos:
                        mem_nos.append(b.mem_no_1)
                    if b.mem_no_2 and b.mem_no_2 not in mem_nos:
                        mem_nos.append(b.mem_no_2)

        # Fall back to bank entry's mem_nos if nothing from beacons
        if not mem_nos and bank.mem_nos:
            valid = [n for n in bank.mem_nos if n in self.system.member_lookup]
            mem_nos = valid
            if mem_nos:
                source_label = " (from bank description)"

        # Tier-2 suggestion fallback: collect from beacon and bank when no confirmed member
        suggested_nos = []
        if not mem_nos:
            # Gather suggestions from current beacon candidate(s)
            rec = self.system.get_reconciliation_for_bank(bank.id)
            if rec and rec.status != 'manually_resolved' and rec.beacon_ids:
                beacons = self.system.get_beacon_entries_for_reconciliation(rec)
                for b in beacons:
                    for s in b.suggested_mem_nos:
                        if s not in suggested_nos and s in self.system.member_lookup:
                            suggested_nos.append(s)
            elif self.beacon_search_active:
                if (self.beacon_search_results and
                        0 <= self.candidate_index < len(self.beacon_search_results)):
                    b = self.beacon_search_results[self.candidate_index]
                    for s in b.suggested_mem_nos:
                        if s not in suggested_nos and s in self.system.member_lookup:
                            suggested_nos.append(s)
            else:
                candidate = self._current_candidate()
                if candidate:
                    for b in candidate.beacon_entries:
                        for s in b.suggested_mem_nos:
                            if s not in suggested_nos and s in self.system.member_lookup:
                                suggested_nos.append(s)
            # Also from bank description
            for s in bank.suggested_mem_nos:
                if s not in suggested_nos and s in self.system.member_lookup:
                    suggested_nos.append(s)

        if not mem_nos and not suggested_nos:
            self.member_panel_header.config(text="No member identified")
            return

        # Build header from confirmed or suggested member numbers
        if mem_nos:
            header_parts = []
            for num in mem_nos:
                info = self.system.member_lookup.get(num)
                if info:
                    header_parts.append(f"{info['forename']} {info['surname']} (#{num})")
                else:
                    header_parts.append(f"#{num}")
            self.member_panel_header.config(
                text=", ".join(header_parts) + source_label
            )
        else:
            # Tier-2 suggestions only
            header_parts = []
            for num in suggested_nos:
                info = self.system.member_lookup.get(num)
                if info:
                    header_parts.append(f"{info['forename']} {info['surname']} (#{num})")
                else:
                    header_parts.append(f"#{num}")
            self.member_panel_header.config(
                text=", ".join(header_parts) + " (suggested)"
            )

        # Populate tree with all beacon entries for confirmed or suggested members
        display_nos = mem_nos if mem_nos else suggested_nos
        seen_beacon_ids = set()
        row_num = 0
        for mem_no in display_nos:
            beacons = self.system.get_beacon_entries_for_member_no(mem_no)
            for beacon in beacons:
                if beacon.id in seen_beacon_ids:
                    continue
                seen_beacon_ids.add(beacon.id)
                # Determine reconciled status
                bank_id = self.system.get_bank_id_for_beacon(beacon.id)
                if bank_id:
                    status = f"Reconciled ({bank_id})"
                    tag = 'reconciled_alt' if row_num % 2 else 'reconciled'
                else:
                    status = "Un-reconciled"
                    tag = 'unreconciled_alt' if row_num % 2 else 'unreconciled'

                detail_text = beacon.detail[:30] if beacon.detail else ""
                item_id = self.member_tree.insert('', 'end', values=(
                    beacon.trans_no,
                    beacon.date.strftime('%d/%m/%Y'),
                    f"{chr(163)}{beacon.amount}",
                    beacon.payee,
                    detail_text,
                    status
                ), tags=(tag,))
                self._member_tree_beacon_ids[item_id] = (beacon.id, bank_id)
                row_num += 1

    def _on_member_tree_click(self, event):
        """Handle double-click on a row in the member transactions tree."""
        selection = self.member_tree.selection()
        if not selection:
            return

        item_id = selection[0]
        beacon_id, bank_id = self._member_tree_beacon_ids.get(item_id, (None, None))

        if not bank_id:
            return  # Un-reconciled, do nothing

        # Navigate to the reconciled bank entry
        if not self.show_all_bank:
            self.show_all_var.set(True)
            self._on_show_all_changed()

        for i, bank in enumerate(self.bank_list):
            if bank.id == bank_id:
                self.bank_index = i
                self._refresh_candidates()
                self._update_display()
                break

    # -------------------------------------------------------------------
    # Action bar
    # -------------------------------------------------------------------

    def _create_action_bar(self, parent):
        """Create the action buttons bar at bottom."""
        action_frame = ttk.LabelFrame(parent, text="Actions", padding="5")
        action_frame.pack(fill=tk.X, pady=(5, 0))

        # Row 1: Primary actions
        row1 = ttk.Frame(action_frame)
        row1.pack(fill=tk.X, pady=(0, 4))

        self.reconcile_btn = ttk.Button(row1, text="Reconcile",
                                         style='Action.TButton',
                                         command=self._on_reconcile)
        self.reconcile_btn.pack(side=tk.LEFT, padx=3)

        self.unreconcile_btn = ttk.Button(row1, text="Un-reconcile",
                                           command=self._on_unreconcile)
        self.unreconcile_btn.pack(side=tk.LEFT, padx=3)

        ttk.Separator(row1, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=8)

        self.reject_btn = ttk.Button(row1, text="Reject Pairing",
                                      command=self._on_reject_pairing)
        self.reject_btn.pack(side=tk.LEFT, padx=3)

        self.unreject_btn = ttk.Button(row1, text="Un-reject Pairing",
                                        command=self._on_unreject_pairing)
        self.unreject_btn.pack(side=tk.LEFT, padx=3)

        ttk.Separator(row1, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(row1, text="Auto-Reconcile",
                    command=self._on_auto_reconcile).pack(side=tk.LEFT, padx=3)

        ttk.Separator(row1, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(row1, text="Reports",
                    command=self._on_reports).pack(side=tk.LEFT, padx=3)

        # Row 2: Consistency check
        row2_consistency = ttk.Frame(action_frame)
        row2_consistency.pack(fill=tk.X, pady=(0, 4))

        ttk.Button(row2_consistency, text="Check Consistency",
                    command=self._on_consistency_check).pack(side=tk.LEFT, padx=3)
        self.inconsistency_prev_btn = ttk.Button(row2_consistency, text="< Issue",
                                                   command=self._on_inconsistency_prev,
                                                   state=tk.DISABLED)
        self.inconsistency_prev_btn.pack(side=tk.LEFT, padx=1)
        self.inconsistency_next_btn = ttk.Button(row2_consistency, text="Issue >",
                                                   command=self._on_inconsistency_next,
                                                   state=tk.DISABLED)
        self.inconsistency_next_btn.pack(side=tk.LEFT, padx=1)
        self.ignore_issue_btn = ttk.Button(row2_consistency, text="Ignore",
                                            command=self._on_ignore_issue,
                                            state=tk.DISABLED)
        self.ignore_issue_btn.pack(side=tk.LEFT, padx=3)
        self.show_ignored_label = ttk.Label(row2_consistency, text="",
                                             foreground='#666666', cursor='hand2',
                                             style='Small.TLabel')
        self.show_ignored_label.pack(side=tk.LEFT, padx=5)
        self.show_ignored_label.bind('<Button-1>', lambda e: self._on_show_ignored())
        self.inconsistency_label = ttk.Label(row2_consistency, text="", foreground='gray',
                                              style='Small.TLabel')
        self.inconsistency_label.pack(side=tk.LEFT, padx=3, fill=tk.X, expand=True)

        # Row 3: Manual match + resolved
        row2 = ttk.Frame(action_frame)
        row2.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(row2, text="Manual trans_no(s):").pack(side=tk.LEFT, padx=3)
        self.trans_no_entry = ttk.Entry(row2, width=25)
        self.trans_no_entry.pack(side=tk.LEFT, padx=3)
        self.trans_no_entry.bind('<Return>', lambda e: self._on_manual_match())
        ttk.Button(row2, text="Manual Match",
                    command=self._on_manual_match).pack(side=tk.LEFT, padx=3)

        ttk.Separator(row2, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(row2, text="Comment:").pack(side=tk.LEFT, padx=3)
        self.resolved_entry = ttk.Entry(row2, width=25)
        self.resolved_entry.pack(side=tk.LEFT, padx=3)
        self.resolved_entry.bind('<Return>', lambda e: self._on_mark_resolved())
        ttk.Button(row2, text="Mark Resolved",
                    command=self._on_mark_resolved).pack(side=tk.LEFT, padx=3)

        ttk.Separator(row2, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # Config controls
        ttk.Label(row2, text="Date tol:").pack(side=tk.LEFT, padx=(3, 1))
        self.date_tol_var = tk.IntVar(value=self.system.date_tolerance_days)
        ttk.Spinbox(row2, from_=1, to=60, width=3,
                     textvariable=self.date_tol_var,
                     command=self._on_config_changed).pack(side=tk.LEFT, padx=1)

        ttk.Label(row2, text="Trans limit:").pack(side=tk.LEFT, padx=(5, 1))
        self.trans_limit_var = tk.IntVar(value=self.system.trans_no_limit)
        ttk.Spinbox(row2, from_=1, to=20, width=3,
                     textvariable=self.trans_limit_var,
                     command=self._on_config_changed).pack(side=tk.LEFT, padx=1)

    # -------------------------------------------------------------------
    # Display updates
    # -------------------------------------------------------------------

    def _update_display(self):
        """Update both panels and stats."""
        self._update_stats()
        self._update_bank_panel()
        self._update_beacon_panel()
        self._update_member_panel()
        self._update_action_states()

    def _update_stats(self):
        """Update the stats bar."""
        stats = self.system.get_statistics()
        self.stats_label.config(
            text=f"Reconciled: {stats['reconciled_count']} "
                 f"({chr(163)}{stats['reconciled_amount']:.2f})  |  "
                 f"Un-reconciled: {stats['unreconciled_count']} "
                 f"({chr(163)}{stats['unreconciled_amount']:.2f})  |  "
                 f"Resolved: {stats['resolved_count']} "
                 f"({chr(163)}{stats['resolved_amount']:.2f})"
        )
        if self.bank_list:
            self.bank_counter_label.config(
                text=f"Bank {self.bank_index + 1} / {len(self.bank_list)}"
            )
        else:
            self.bank_counter_label.config(text="No entries")

    def _update_bank_panel(self):
        """Update the left panel with current bank entry."""
        bank = self._current_bank()

        # Navigation label
        if self.bank_list:
            nav_suffix = '  (all)' if self.show_all_bank else '  (un-reconciled)'
            if self.bank_search_matches:
                nav_suffix = f'  (search {self.bank_search_index + 1}/{len(self.bank_search_matches)})'
            self.bank_nav_label.config(
                text=f"{self.bank_index + 1} / {len(self.bank_list)}{nav_suffix}"
            )
        else:
            self.bank_nav_label.config(text="No entries")

        # Navigation buttons - use search bounds if search active
        if self.bank_search_matches:
            self.bank_prev_btn.config(
                state=tk.NORMAL if self.bank_search_index > 0 else tk.DISABLED)
            self.bank_next_btn.config(
                state=tk.NORMAL if self.bank_search_index < len(self.bank_search_matches) - 1 else tk.DISABLED)
        else:
            self.bank_prev_btn.config(state=tk.NORMAL if self.bank_index > 0 else tk.DISABLED)
            self.bank_next_btn.config(
                state=tk.NORMAL if self.bank_index < len(self.bank_list) - 1 else tk.DISABLED
            )

        if not bank:
            self.bank_id_label.config(text="--")
            self.bank_date_label.config(text="--")
            self.bank_type_label.config(text="--")
            self.bank_desc_label.config(text="No bank entries to show")
            self.member_lookup_label.config(text="")
            self.bank_amount_label.config(text="")
            self.bank_status_label.config(text="")
            self.bank_status_frame.config(bg='#EEEEEE')
            self.reconciled_info_frame.pack_forget()
            self.bank_rec_type_label.config(text="")
            return

        # Populate fields
        self.bank_id_label.config(text=bank.id)
        self.bank_date_label.config(text=bank.date.strftime('%d-%b-%Y'))
        self.bank_type_label.config(text=bank.type)
        self.bank_desc_label.config(text=bank.description)
        self.bank_amount_label.config(text=f"{chr(163)}{bank.amount}")
        self.member_lookup_label.config(
            text=self.system.get_member_lookup_text(bank.description)
        )

        # Status
        rec = self.system.get_reconciliation_for_bank(bank.id)
        if rec:
            if rec.status == 'manually_resolved':
                self.bank_status_label.config(text="MANUALLY RESOLVED")
                self.bank_status_frame.config(bg=self.COLORS['resolved'])
                self.bank_rec_type_label.config(text=rec.match_type)
                # Show comment
                self.reconciled_info_frame.pack(fill=tk.X, pady=(8, 0))
                self.reconciled_info_label.config(text="No beacon entries (resolved)")
                comment_text = f"Comment: {rec.comment}  [click to edit]" if rec.comment else "[click to add comment]"
                self.reconciled_comment_label.config(
                    text=comment_text, cursor='hand2'
                )
            else:
                self.bank_status_label.config(text="RECONCILED")
                self.bank_status_frame.config(bg=self.COLORS['reconciled'])
                self.bank_rec_type_label.config(text=rec.match_type)
                # Show reconciled beacon info
                beacons = self.system.get_beacon_entries_for_reconciliation(rec)
                if beacons:
                    lines = []
                    for b in beacons:
                        lines.append(
                            f"{b.trans_no}  {b.date.strftime('%d/%m/%Y')}  "
                            f"{b.payee}  {chr(163)}{b.amount}"
                        )
                    self.reconciled_info_frame.pack(fill=tk.X, pady=(8, 0))
                    self.reconciled_info_label.config(text="\n".join(lines))
                    comment_text = f"Comment: {rec.comment}  [click to edit]" if rec.comment else "[click to add comment]"
                    self.reconciled_comment_label.config(
                        text=comment_text, cursor='hand2'
                    )
                else:
                    self.reconciled_info_frame.pack_forget()
        else:
            self.bank_status_label.config(text="UN-RECONCILED")
            self.bank_status_frame.config(bg=self.COLORS['unreconciled'])
            self.bank_rec_type_label.config(text="")
            self.reconciled_info_frame.pack_forget()

    def _update_beacon_panel(self):
        """Update the right panel with current beacon candidate."""
        # Hide everything first
        self.beacon1_frame.pack_forget()
        self.beacon2_frame.pack_forget()
        self.total_frame.pack_forget()
        self.no_candidates_label.pack_forget()
        self.amount_mismatch_label.pack_forget()
        self._amount_mismatch_beacon = None
        self.rejected_indicator.pack_forget()

        bank = self._current_bank()

        # Handle beacon search results mode (check BEFORE reconciled check)
        if self.beacon_search_active and self.beacon_search_results:
            self._show_beacon_search_result()
            return

        # If bank is reconciled, show reconciled beacon info instead
        if bank and self.system.is_bank_reconciled(bank.id):
            rec = self.system.get_reconciliation_for_bank(bank.id)
            if rec and rec.status == 'manually_resolved':
                self.no_candidates_label.config(text="Manually resolved\n(see left panel)")
                self.no_candidates_label.pack(fill=tk.BOTH, expand=True, pady=20)
            elif rec:
                beacons = self.system.get_beacon_entries_for_reconciliation(rec)
                if beacons:
                    self._populate_beacon_widgets(self.beacon1_widgets, beacons[0])
                    self.beacon1_frame.pack(fill=tk.X, pady=(0, 5))
                    if len(beacons) > 1:
                        self._populate_beacon_widgets(self.beacon2_widgets, beacons[1])
                        self.beacon2_frame.pack(fill=tk.X, pady=(0, 5))
                        total = sum(b.amount for b in beacons)
                        self.beacon_total_label.config(text=f"{chr(163)}{total}")
                        self.total_frame.pack(fill=tk.X, pady=(5, 0))
            # Nav info
            self.beacon_nav_label.config(text="Reconciled", fg='gray',
                                          font=('Segoe UI', 10))
            self.confidence_label.config(text="")
            self.match_type_label.config(text="")
            self.score_breakdown_label.config(text="")
            self.beacon_prev_btn.config(state=tk.DISABLED)
            self.beacon_next_btn.config(state=tk.DISABLED)
            return

        # Normal candidate mode
        if not self.candidates:
            self.no_candidates_label.config(
                text="No beacon candidates found\n\n"
                     "Use manual trans_no match\nor mark as resolved"
            )
            self.no_candidates_label.pack(fill=tk.BOTH, expand=True, pady=20)

            # Check for amount-mismatch suggestion
            if bank:
                suggestion = self.system.find_amount_mismatch_suggestion(bank)
                if suggestion:
                    beacon, name_score, date_score = suggestion
                    diff = beacon.amount - bank.amount
                    sign = '+' if diff > 0 else ''
                    self._amount_mismatch_beacon = beacon
                    self.amount_mismatch_label.config(
                        text=f"Similar match with different amount:\n"
                             f"{beacon.payee} {chr(163)}{beacon.amount} "
                             f"({sign}{chr(163)}{diff})\n"
                             f"[Click to view]"
                    )
                    self.amount_mismatch_label.pack(pady=(0, 10))

            self.beacon_nav_label.config(text="0 / 0", fg='gray',
                                          font=('Segoe UI', 10))
            self.confidence_label.config(text="")
            self.match_type_label.config(text="")
            self.score_breakdown_label.config(text="")
            self.beacon_prev_btn.config(state=tk.DISABLED)
            self.beacon_next_btn.config(state=tk.DISABLED)
            return

        # Show current candidate
        candidate = self._current_candidate()
        if not candidate:
            return

        # Navigation - highlight in red+bold when multiple candidates
        nav_text = f"{self.candidate_index + 1} / {len(self.candidates)}"
        if len(self.candidates) > 1:
            self.beacon_nav_label.config(text=nav_text, fg='#CC0000',
                                          font=('Segoe UI', 10, 'bold'))
        else:
            self.beacon_nav_label.config(text=nav_text, fg='gray',
                                          font=('Segoe UI', 10))
        self.beacon_prev_btn.config(
            state=tk.NORMAL if self.candidate_index > 0 else tk.DISABLED
        )
        self.beacon_next_btn.config(
            state=tk.NORMAL if self.candidate_index < len(self.candidates) - 1 else tk.DISABLED
        )

        # Confidence
        pct = int(candidate.confidence_score * 100)
        self.confidence_label.config(text=f"{pct}% confidence")
        self.match_type_label.config(text=candidate.match_type)
        self.score_breakdown_label.config(
            text=f"Amt: {candidate.amount_score:.0%}  "
                 f"Date: {candidate.date_score:.0%}  "
                 f"Name: {candidate.name_score:.0%}"
        )

        # Rejected indicator
        if candidate.is_rejected:
            self.rejected_indicator.pack(fill=tk.X, pady=(0, 5))

        # Beacon entry 1
        self._populate_beacon_widgets(self.beacon1_widgets, candidate.beacon_entries[0])
        self.beacon1_frame.pack(fill=tk.X, pady=(0, 5))

        # Beacon entry 2 (1-to-2)
        if len(candidate.beacon_entries) > 1:
            self._populate_beacon_widgets(self.beacon2_widgets, candidate.beacon_entries[1])
            self.beacon2_frame.pack(fill=tk.X, pady=(0, 5))
            total = sum(b.amount for b in candidate.beacon_entries)
            self.beacon_total_label.config(text=f"{chr(163)}{total}")
            self.total_frame.pack(fill=tk.X, pady=(5, 0))

    def _populate_beacon_widgets(self, widgets, beacon: BeaconEntry):
        """Fill a set of beacon widgets with data from a BeaconEntry."""
        trans_text = beacon.trans_no
        if beacon.payment_method.lower() == 'cheque':
            trans_text += "  (CHQ)"
        widgets['trans_no'].config(text=trans_text)
        widgets['date'].config(text=beacon.date.strftime('%d/%m/%Y'))
        widgets['payee'].config(text=beacon.payee)
        widgets['detail'].config(text=beacon.detail)
        widgets['member_1'].config(text=self.system.get_beacon_member_display(beacon, 1))
        widgets['member_2'].config(text=self.system.get_beacon_member_display(beacon, 2))
        widgets['amount'].config(text=f"{chr(163)}{beacon.amount}")
        widgets['id'].config(text=beacon.id)

    def _show_beacon_search_result(self):
        """Show beacon search results in the right panel."""
        if not self.beacon_search_results:
            return
        idx = min(self.candidate_index, len(self.beacon_search_results) - 1)
        beacon = self.beacon_search_results[idx]

        self.beacon_nav_label.config(
            text=f"Search {idx + 1} / {len(self.beacon_search_results)}",
            fg='gray', font=('Segoe UI', 10)
        )
        self.beacon_prev_btn.config(state=tk.NORMAL if idx > 0 else tk.DISABLED)
        self.beacon_next_btn.config(
            state=tk.NORMAL if idx < len(self.beacon_search_results) - 1 else tk.DISABLED
        )

        # Check if this beacon is reconciled
        bank_id = self.system.get_bank_id_for_beacon(beacon.id)
        if bank_id:
            self.confidence_label.config(
                text=f"RECONCILED with {bank_id}  [click to go]",
                foreground='#006600', cursor='hand2'
            )
            self.confidence_label.bind('<Button-1>',
                                        lambda e, bid=bank_id: self._navigate_to_bank(bid))
            self.match_type_label.config(text="")
            self.score_breakdown_label.config(text="")
        else:
            self.confidence_label.config(text="Search result", foreground='',
                                          cursor='')
            self.confidence_label.unbind('<Button-1>')
            self.match_type_label.config(text="")
            self.score_breakdown_label.config(text="")

        self._populate_beacon_widgets(self.beacon1_widgets, beacon)
        self.beacon1_frame.pack(fill=tk.X, pady=(0, 5))

    def _update_action_states(self):
        """Enable/disable action buttons based on current state."""
        bank = self._current_bank()
        is_reconciled = bank and self.system.is_bank_reconciled(bank.id)
        has_candidate = self._current_candidate() is not None
        candidate = self._current_candidate()

        # Reconcile: enabled if bank not reconciled and there's a candidate
        # Also enabled during beacon search if the displayed beacon is not reconciled
        can_reconcile = False
        if bank and not is_reconciled:
            if self.beacon_search_active and self.beacon_search_results:
                idx = min(self.candidate_index, len(self.beacon_search_results) - 1)
                search_beacon = self.beacon_search_results[idx]
                # Only allow if the beacon is not already reconciled
                can_reconcile = search_beacon.id not in self.system._reconciled_beacon_ids
            elif has_candidate:
                can_reconcile = True
        self.reconcile_btn.config(
            state=tk.NORMAL if can_reconcile else tk.DISABLED
        )

        # Un-reconcile: enabled if bank IS reconciled
        self.unreconcile_btn.config(
            state=tk.NORMAL if is_reconciled else tk.DISABLED
        )

        # Reject: enabled if bank not reconciled and there's a non-rejected candidate
        can_reject = (bank and not is_reconciled and candidate
                      and not candidate.is_rejected)
        self.reject_btn.config(state=tk.NORMAL if can_reject else tk.DISABLED)

        # Un-reject: enabled if candidate is rejected
        can_unreject = (bank and not is_reconciled and candidate
                        and candidate.is_rejected)
        self.unreject_btn.config(state=tk.NORMAL if can_unreject else tk.DISABLED)

    # -------------------------------------------------------------------
    # Bank navigation
    # -------------------------------------------------------------------

    def _on_bank_prev(self):
        """Navigate to previous bank entry (or previous search result)."""
        if self.bank_search_matches:
            if self.bank_search_index > 0:
                self.bank_search_index -= 1
                self.bank_index = self.bank_search_matches[self.bank_search_index]
                self._refresh_candidates()
                self._update_display()
                self.bank_search_result.config(
                    text=f"{self.bank_search_index + 1} / {len(self.bank_search_matches)}"
                )
        elif self.bank_index > 0:
            self.bank_index -= 1
            self._refresh_candidates()
            self._update_display()

    def _on_bank_next(self):
        """Navigate to next bank entry (or next search result)."""
        if self.bank_search_matches:
            if self.bank_search_index < len(self.bank_search_matches) - 1:
                self.bank_search_index += 1
                self.bank_index = self.bank_search_matches[self.bank_search_index]
                self._refresh_candidates()
                self._update_display()
                self.bank_search_result.config(
                    text=f"{self.bank_search_index + 1} / {len(self.bank_search_matches)}"
                )
        elif self.bank_index < len(self.bank_list) - 1:
            self.bank_index += 1
            self._refresh_candidates()
            self._update_display()

    def _on_show_all_changed(self):
        """Toggle showing all vs un-reconciled only."""
        self.show_all_bank = self.show_all_var.get()
        # Stay on the same bank entry
        current_bank = self._current_bank()
        self._rebuild_bank_list()
        if current_bank and self.bank_list:
            found = False
            for i, b in enumerate(self.bank_list):
                if b.id == current_bank.id:
                    self.bank_index = i
                    found = True
                    break
            if not found:
                # Entry not in new list (e.g. reconciled entry not in un-reconciled view)
                # Find nearest by date
                for i, b in enumerate(self.bank_list):
                    if b.date >= current_bank.date:
                        self.bank_index = i
                        break
                else:
                    self.bank_index = len(self.bank_list) - 1
        self._refresh_candidates()
        self._update_display()

    def _on_reset(self):
        """Reset all searches and toggles to default state."""
        # Clear bank search
        self.bank_search_entry.delete(0, tk.END)
        self.bank_search_matches = []
        self.bank_search_index = 0
        self.bank_search_result.config(text="")

        # Clear beacon search
        self.beacon_search_entry.delete(0, tk.END)
        self.beacon_search_results = []
        self.beacon_search_active = False
        self.beacon_search_result.config(text="")

        # Turn off Show All (back to un-reconciled only)
        self.show_all_var.set(False)
        self.show_all_bank = False

        # Turn off All Beacons and Cheque filter
        self.beacon_bypass_var.set(False)
        self.cheque_filter_var.set(False)

        # Rebuild and refresh
        self._rebuild_bank_list()
        self._refresh_candidates()
        self._update_display()

    def _on_goto(self, event=None):
        """Jump to the Nth entry in the current bank list."""
        text = self.goto_entry.get().strip()
        if not text:
            return
        try:
            n = int(text)
        except ValueError:
            return
        if not self.bank_list:
            return
        # Clamp to valid range (1-based input)
        idx = max(0, min(n - 1, len(self.bank_list) - 1))
        self.bank_index = idx
        # Clear any active bank search so nav label shows normal mode
        self.bank_search_matches = []
        self.bank_search_index = 0
        self.bank_search_result.config(text="")
        self.goto_entry.delete(0, tk.END)
        self._refresh_candidates()
        self._update_display()

    def _on_amount_mismatch_click(self, event=None):
        """Navigate to the amount-mismatch suggested beacon."""
        if not self._amount_mismatch_beacon:
            return
        beacon = self._amount_mismatch_beacon
        # Show as a temporary candidate
        self.beacon_search_results = [beacon]
        self.beacon_search_active = True
        self.candidate_index = 0
        self.beacon_search_result.config(
            text=f"Amount mismatch: {beacon.id}", foreground='#CC8800')
        self._update_beacon_panel()
        self._update_action_states()
        self._update_member_panel()

    # -------------------------------------------------------------------
    # Candidate navigation
    # -------------------------------------------------------------------

    def _on_candidate_prev(self):
        """Navigate to previous beacon candidate."""
        if self.beacon_search_active:
            if self.candidate_index > 0:
                self.candidate_index -= 1
                self._update_beacon_panel()
                self._update_action_states()
                self._update_member_panel()
            return

        if self.candidate_index > 0:
            self.candidate_index -= 1
            self._update_beacon_panel()
            self._update_action_states()
            self._update_member_panel()

    def _on_candidate_next(self):
        """Navigate to next beacon candidate."""
        if self.beacon_search_active:
            if self.candidate_index < len(self.beacon_search_results) - 1:
                self.candidate_index += 1
                self._update_beacon_panel()
                self._update_action_states()
                self._update_member_panel()
            return

        if self.candidate_index < len(self.candidates) - 1:
            self.candidate_index += 1
            self._update_beacon_panel()
            self._update_action_states()
            self._update_member_panel()

    # -------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------

    def _navigate_to_bank(self, bank_id: str):
        """Navigate to a specific bank entry by ID. Used for search result navigation."""
        # Clear beacon search
        self.beacon_search_entry.delete(0, tk.END)
        self.beacon_search_results = []
        self.beacon_search_active = False
        self.beacon_search_result.config(text="")

        # Ensure show-all is on so reconciled entries are visible
        if not self.show_all_bank:
            self.show_all_var.set(True)
            self._on_show_all_changed()

        for i, bank in enumerate(self.bank_list):
            if bank.id == bank_id:
                self.bank_index = i
                self._refresh_candidates()
                self._update_display()
                break

    def _on_enter_key(self, event=None):
        """Handle Enter key: reconcile if exactly 1 non-rejected candidate, else do nothing.

        Do nothing if: focus is in an Entry widget, bank is reconciled,
        search is active, or there isn't exactly 1 candidate.
        """
        # Don't intercept Enter when typing in an Entry or Spinbox
        focus = self.master.focus_get()
        if isinstance(focus, (ttk.Entry, tk.Entry, ttk.Spinbox)):
            return

        bank = self._current_bank()
        if not bank:
            return
        if self.system.is_bank_reconciled(bank.id):
            return
        if self.beacon_search_active:
            return

        non_rejected = [c for c in self.candidates if not c.is_rejected]
        if len(non_rejected) == 1:
            self._on_reconcile()

    def _on_reconcile(self):
        """Reconcile current bank entry with current candidate (or search result)."""
        bank = self._current_bank()
        if not bank:
            return

        # If beacon search is active, reconcile with the displayed search result
        if self.beacon_search_active and self.beacon_search_results:
            idx = min(self.candidate_index, len(self.beacon_search_results) - 1)
            beacon = self.beacon_search_results[idx]
            # Use manual match with the beacon's trans_no
            success, message = self.system.reconcile_manual(bank, [beacon.trans_no])
            if success:
                # Clear search and move on
                self.beacon_search_entry.delete(0, tk.END)
                self.beacon_search_results = []
                self.beacon_search_active = False
                self.beacon_search_result.config(text="")
                self._rebuild_bank_list()
                self._refresh_candidates()
                self._update_display()
            else:
                messagebox.showerror("Reconcile Failed", message)
            return

        candidate = self._current_candidate()
        if not candidate:
            return

        success, message = self.system.reconcile(bank, candidate)
        if success:
            # Move to next un-reconciled bank entry
            self._rebuild_bank_list()
            self._refresh_candidates()
            self._update_display()
        else:
            messagebox.showerror("Reconcile Failed", message)

    def _on_unreconcile(self):
        """Un-reconcile current bank entry."""
        bank = self._current_bank()
        if not bank:
            return

        success, message = self.system.unreconcile(bank.id)
        if success:
            self._rebuild_bank_list()
            # Stay on same bank entry
            for i, b in enumerate(self.bank_list):
                if b.id == bank.id:
                    self.bank_index = i
                    break
            self._refresh_candidates()
            self._update_display()
        else:
            messagebox.showerror("Un-reconcile Failed", message)

    def _on_reject_pairing(self):
        """Reject current pairing (bank + beacon candidate)."""
        bank = self._current_bank()
        candidate = self._current_candidate()
        if not bank or not candidate:
            return

        for beacon in candidate.beacon_entries:
            self.system.reject_pairing(bank.id, beacon.id)

        # Refresh candidates (rejected will move to bottom)
        self._refresh_candidates()
        self._update_display()

    def _on_unreject_pairing(self):
        """Un-reject current pairing."""
        bank = self._current_bank()
        candidate = self._current_candidate()
        if not bank or not candidate:
            return

        for beacon in candidate.beacon_entries:
            self.system.unreject_pairing(bank.id, beacon.id)

        # Refresh candidates
        self._refresh_candidates()
        self._update_display()

    def _on_auto_reconcile(self):
        """Run auto-reconcile."""
        count = self.system.auto_reconcile()
        self._rebuild_bank_list()
        self._refresh_candidates()
        self._update_display()

        if count > 0:
            messagebox.showinfo("Auto-Reconcile",
                                f"Auto-reconciled {count} entries.\n\n"
                                f"Use Un-reconcile to undo any incorrect matches.")
        else:
            messagebox.showinfo("Auto-Reconcile",
                                "No entries met the auto-reconcile thresholds.")

    def _on_manual_match(self):
        """Create manual match from trans_no(s)."""
        bank = self._current_bank()
        if not bank:
            messagebox.showerror("Error", "No bank entry selected")
            return

        if self.system.is_bank_reconciled(bank.id):
            messagebox.showerror("Error", "Bank entry is already reconciled.\n"
                                 "Un-reconcile first if you want to change it.")
            return

        text = self.trans_no_entry.get().strip()
        if not text:
            messagebox.showerror("Error", "Enter one or more trans_no values\n"
                                 "(comma-separated, or range e.g. 8128-8133)")
            return

        trans_nos = self._expand_trans_no_input(text)
        success, message = self.system.reconcile_manual(bank, trans_nos)

        if success:
            self.trans_no_entry.delete(0, tk.END)
            self._rebuild_bank_list()
            self._refresh_candidates()
            self._update_display()
        else:
            messagebox.showerror("Manual Match Failed", message)

    @staticmethod
    def _expand_trans_no_input(text: str) -> list:
        """Expand trans_no input, supporting comma-separated values and numeric ranges.

        Examples:
            "8128-8133" -> ["8128", "8129", "8130", "8131", "8132", "8133"]
            "TRN001, TRN002" -> ["TRN001", "TRN002"]
            "8128-8130, 8135" -> ["8128", "8129", "8130", "8135"]
        """
        result = []
        parts = [p.strip() for p in text.split(',') if p.strip()]
        for part in parts:
            if '-' in part:
                # Try to parse as numeric range
                pieces = part.split('-', 1)
                try:
                    start = int(pieces[0].strip())
                    end = int(pieces[1].strip())
                    if start <= end and (end - start) < 1000:  # Sanity limit
                        result.extend(str(n) for n in range(start, end + 1))
                    else:
                        result.append(part)  # Not a valid range, use as-is
                except ValueError:
                    result.append(part)  # Not numeric, use as-is (e.g. "TRN-001")
            else:
                result.append(part)
        return result

    def _on_mark_resolved(self):
        """Mark current bank entry as manually resolved, or update resolved comment."""
        bank = self._current_bank()
        if not bank:
            messagebox.showerror("Error", "No bank entry selected")
            return

        comment = self.resolved_entry.get().strip()
        if not comment:
            messagebox.showerror("Error", "Please enter a comment explaining the resolution")
            return

        # Check if already reconciled/resolved - if so, update the comment
        rec = self.system.get_reconciliation_for_bank(bank.id)
        if rec:
            success, message = self.system.update_resolved_comment(bank.id, comment)
            if success:
                self.resolved_entry.delete(0, tk.END)
                self._update_display()
            else:
                messagebox.showerror("Update Comment Failed", message)
            return

        success, message = self.system.mark_resolved(bank, comment)

        if success:
            self.resolved_entry.delete(0, tk.END)
            self._rebuild_bank_list()
            self._refresh_candidates()
            self._update_display()
        else:
            messagebox.showerror("Mark Resolved Failed", message)

    def _on_edit_resolved_comment(self, event=None):
        """Populate resolved entry with existing comment for editing."""
        bank = self._current_bank()
        if not bank:
            return
        rec = self.system.get_reconciliation_for_bank(bank.id)
        if rec:
            self.resolved_entry.delete(0, tk.END)
            if rec.comment:
                self.resolved_entry.insert(0, rec.comment)
            self.resolved_entry.focus_set()

    def _on_config_changed(self):
        """Handle date tolerance or trans_no limit change."""
        self.system.date_tolerance_days = self.date_tol_var.get()
        self.system.trans_no_limit = self.trans_limit_var.get()
        self._refresh_candidates()
        self._update_display()

    # -------------------------------------------------------------------
    # Bank search
    # -------------------------------------------------------------------

    def _on_bank_search(self, event=None):
        """Search bank entries."""
        term = self.bank_search_entry.get().strip()
        if not term:
            return

        indices = self.system.search_bank_entries(term)
        if not indices:
            self.bank_search_result.config(text="No matches", foreground='#CC0000')
            self.bank_search_matches = []
            return

        # Map system indices to bank_list indices
        bank_id_to_list_idx = {b.id: i for i, b in enumerate(self.bank_list)}
        self.bank_search_matches = []
        for sys_idx in indices:
            bank_id = self.system.bank_transactions[sys_idx].id
            if bank_id in bank_id_to_list_idx:
                self.bank_search_matches.append(bank_id_to_list_idx[bank_id])

        if not self.bank_search_matches:
            # Results exist but not in current view - determine why
            # Check if any matched entries are outside date range
            outside_range = 0
            for sys_idx in indices:
                bank = self.system.bank_transactions[sys_idx]
                if not self.system.is_bank_in_date_range(bank):
                    outside_range += 1
            if outside_range > 0:
                self.bank_search_result.config(
                    text=f"{len(indices)} found (outside date range)",
                    foreground='#CC8800'
                )
            else:
                self.bank_search_result.config(
                    text=f"{len(indices)} found (try Show All)",
                    foreground='#CC8800'
                )
            return

        self.bank_search_index = 0
        self.bank_index = self.bank_search_matches[0]
        self._refresh_candidates()
        self._update_display()
        self.bank_search_result.config(
            text=f"1 / {len(self.bank_search_matches)}", foreground='gray'
        )

    def _on_bank_search_clear(self):
        """Clear bank search."""
        self.bank_search_entry.delete(0, tk.END)
        self.bank_search_matches = []
        self.bank_search_index = 0
        self.bank_search_result.config(text="")

    # -------------------------------------------------------------------
    # Beacon search
    # -------------------------------------------------------------------

    def _on_beacon_search(self, event=None):
        """Search beacon entries (right panel)."""
        term = self.beacon_search_entry.get().strip()
        if not term:
            return

        bypass = self.beacon_bypass_var.get()
        results = self.system.search_beacon_entries(term, available_only=not bypass)

        if not results:
            self.beacon_search_result.config(text="No matches", foreground='#CC0000')
            self.beacon_search_results = []
            self.beacon_search_active = False
            return

        self.beacon_search_results = results
        self.beacon_search_active = True
        self.candidate_index = 0
        self._update_beacon_panel()
        self._update_action_states()
        self._update_member_panel()
        self.beacon_search_result.config(
            text=f"Found {len(results)}", foreground='gray'
        )

    def _on_cheque_filter_changed(self):
        """Handle cheque filter toggle."""
        if self.cheque_filter_var.get():
            # Cheque toggle ON: respect "All beacons" checkbox
            bypass = self.beacon_bypass_var.get()
            results = self.system.get_cheque_beacon_entries(available_only=not bypass)
            if not results:
                self.beacon_search_result.config(text="No cheques", foreground='#CC0000')
                self.beacon_search_results = []
                self.beacon_search_active = False
                self.cheque_filter_var.set(False)
                return
            self.beacon_search_results = results
            self.beacon_search_active = True
            self.candidate_index = 0
            self._update_beacon_panel()
            self._update_action_states()
            self._update_member_panel()
            self.beacon_search_result.config(
                text=f"Found {len(results)} cheques", foreground='gray'
            )
        else:
            # Cheque toggle OFF: return to candidates (don't clear search box)
            self._cancel_beacon_search()

    def _cancel_beacon_search(self):
        """Cancel active beacon search without clearing the search box."""
        self.cheque_filter_var.set(False)
        self.beacon_search_results = []
        self.beacon_search_active = False
        self.beacon_search_result.config(text="")
        self._refresh_candidates()
        self._update_display()

    def _on_beacon_search_clear(self):
        """Clear beacon search and return to candidates view."""
        self.beacon_search_entry.delete(0, tk.END)
        self._cancel_beacon_search()

    # -------------------------------------------------------------------
    # Consistency check
    # -------------------------------------------------------------------

    def _on_consistency_check(self):
        """Run consistency check on all reconciliations."""
        all_issues = self.system.check_consistency()
        self.showing_ignored = False

        # Separate active vs ignored
        self.inconsistencies = [
            (rec, reason) for rec, reason in all_issues
            if not self.system.is_inconsistency_ignored(rec.bank_id, reason)
        ]
        self.ignored_inconsistencies_shown = [
            (rec, reason) for rec, reason in all_issues
            if self.system.is_inconsistency_ignored(rec.bank_id, reason)
        ]
        self.inconsistency_index = 0

        ignored_count = len(self.ignored_inconsistencies_shown)
        if not self.inconsistencies:
            self.inconsistency_label.config(text="")
            self.inconsistency_prev_btn.config(state=tk.DISABLED)
            self.inconsistency_next_btn.config(state=tk.DISABLED)
            self.ignore_issue_btn.config(state=tk.DISABLED)
            msg = "No inconsistencies found."
            if ignored_count:
                msg += f" ({ignored_count} ignored)"
            self._update_show_ignored_label()
            messagebox.showinfo("Consistency Check", msg)
            return

        self._update_show_ignored_label()
        self._update_inconsistency_nav()
        self._navigate_to_inconsistency(0)

    def _update_show_ignored_label(self):
        """Update the 'Show N ignored' label."""
        ignored_count = len(self.ignored_inconsistencies_shown)
        if ignored_count > 0:
            if self.showing_ignored:
                self.show_ignored_label.config(
                    text=f"Hide {ignored_count} ignored",
                    foreground='#666666'
                )
            else:
                self.show_ignored_label.config(
                    text=f"Show {ignored_count} ignored",
                    foreground='#666666'
                )
        else:
            self.show_ignored_label.config(text="")

    def _on_show_ignored(self):
        """Toggle display of ignored inconsistencies."""
        if not self.ignored_inconsistencies_shown:
            return

        self.showing_ignored = not self.showing_ignored
        if self.showing_ignored:
            # Append ignored issues to the navigation list
            self.inconsistencies = self.inconsistencies + self.ignored_inconsistencies_shown
        else:
            # Remove ignored issues from navigation
            self.inconsistencies = [
                (rec, reason) for rec, reason in self.inconsistencies
                if not self.system.is_inconsistency_ignored(rec.bank_id, reason)
            ]
            # Adjust index if it's now out of range
            if self.inconsistency_index >= len(self.inconsistencies):
                self.inconsistency_index = max(0, len(self.inconsistencies) - 1)

        self._update_show_ignored_label()
        if self.inconsistencies:
            self._update_inconsistency_nav()
        else:
            self.inconsistency_label.config(text="")
            self.inconsistency_prev_btn.config(state=tk.DISABLED)
            self.inconsistency_next_btn.config(state=tk.DISABLED)
            self.ignore_issue_btn.config(state=tk.DISABLED)

    def _on_ignore_issue(self):
        """Ignore the currently displayed inconsistency."""
        if not self.inconsistencies or self.inconsistency_index >= len(self.inconsistencies):
            return

        rec, reason = self.inconsistencies[self.inconsistency_index]

        if self.system.is_inconsistency_ignored(rec.bank_id, reason):
            # Currently ignored - un-ignore it
            self.system.unignore_inconsistency(rec.bank_id, reason)
            # Move from ignored list to active
            self.ignored_inconsistencies_shown = [
                (r, rsn) for r, rsn in self.ignored_inconsistencies_shown
                if not (r.bank_id == rec.bank_id and rsn == reason)
            ]
        else:
            # Ignore it
            self.system.ignore_inconsistency(rec.bank_id, reason)
            # Remove from active list, add to ignored
            self.ignored_inconsistencies_shown.append((rec, reason))
            self.inconsistencies.pop(self.inconsistency_index)
            if self.inconsistency_index >= len(self.inconsistencies):
                self.inconsistency_index = max(0, len(self.inconsistencies) - 1)

        self._update_show_ignored_label()
        if self.inconsistencies:
            self._update_inconsistency_nav()
            if self.inconsistencies:
                self._navigate_to_inconsistency(self.inconsistency_index)
        else:
            self.inconsistency_label.config(text="No active issues remaining")
            self.inconsistency_prev_btn.config(state=tk.DISABLED)
            self.inconsistency_next_btn.config(state=tk.DISABLED)
            self.ignore_issue_btn.config(state=tk.DISABLED)

    def _update_inconsistency_nav(self):
        """Update inconsistency navigation UI."""
        if not self.inconsistencies:
            self.inconsistency_label.config(text="")
            self.inconsistency_prev_btn.config(state=tk.DISABLED)
            self.inconsistency_next_btn.config(state=tk.DISABLED)
            self.ignore_issue_btn.config(state=tk.DISABLED)
            return

        rec, reason = self.inconsistencies[self.inconsistency_index]
        is_ignored = self.system.is_inconsistency_ignored(rec.bank_id, reason)

        prefix = "[IGNORED] " if is_ignored else ""
        self.inconsistency_label.config(
            text=f"Issue {self.inconsistency_index + 1}/{len(self.inconsistencies)}: "
                 f"{prefix}{reason}",
            foreground='#999999' if is_ignored else '#CC0000'
        )
        self.inconsistency_prev_btn.config(
            state=tk.NORMAL if self.inconsistency_index > 0 else tk.DISABLED
        )
        self.inconsistency_next_btn.config(
            state=tk.NORMAL if self.inconsistency_index < len(self.inconsistencies) - 1 else tk.DISABLED
        )
        self.ignore_issue_btn.config(
            state=tk.NORMAL,
            text="Un-ignore" if is_ignored else "Ignore"
        )

    def _navigate_to_inconsistency(self, index):
        """Navigate to the bank entry involved in an inconsistency."""
        if not self.inconsistencies or index >= len(self.inconsistencies):
            return

        self.inconsistency_index = index
        rec, reason = self.inconsistencies[index]

        # Find the bank entry in the current list
        # Make sure show_all is on so we can navigate to reconciled entries
        if not self.show_all_bank:
            self.show_all_var.set(True)
            self._on_show_all_changed()

        for i, bank in enumerate(self.bank_list):
            if bank.id == rec.bank_id:
                self.bank_index = i
                self._refresh_candidates()
                self._update_display()
                break

        self._update_inconsistency_nav()

    def _on_inconsistency_prev(self):
        """Navigate to previous inconsistency."""
        if self.inconsistency_index > 0:
            self._navigate_to_inconsistency(self.inconsistency_index - 1)

    def _on_inconsistency_next(self):
        """Navigate to next inconsistency."""
        if self.inconsistency_index < len(self.inconsistencies) - 1:
            self._navigate_to_inconsistency(self.inconsistency_index + 1)

    # -------------------------------------------------------------------
    # Reports
    # -------------------------------------------------------------------

    def _on_reports(self):
        """Generate all reports."""
        data_dir = self.system.data_dir

        reconciled_path = os.path.join(data_dir, "report_reconciled.csv")
        unreconciled_bank_path = os.path.join(data_dir, "report_unreconciled_bank.csv")
        unreconciled_beacon_path = os.path.join(data_dir, "report_unreconciled_beacon.csv")
        resolved_path = os.path.join(data_dir, "report_resolved.csv")
        stats_path = os.path.join(data_dir, "report_stats.txt")
        inconsistencies_path = os.path.join(data_dir, "report_inconsistencies.csv")
        unresolved_memno_path = os.path.join(data_dir, "report_unresolved_memno.csv")

        r1 = self.system.export_reconciled_csv(reconciled_path)
        r2 = self.system.export_unreconciled_bank_csv(unreconciled_bank_path)
        r3 = self.system.export_unreconciled_beacon_csv(unreconciled_beacon_path)
        r4 = self.system.export_resolved_csv(resolved_path)
        self.system.export_stats_summary(stats_path)
        r6 = self.system.export_inconsistencies_csv(inconsistencies_path)
        r7 = self.system.export_unresolved_memno_csv(unresolved_memno_path)

        comparison_msg = ""
        if self.system.backup_file:
            # Also generate comparison report if a beacon CSV exists
            beacon_csv = os.path.join(data_dir, self.system.config.get('beacon_file', 'Beacon_Entries.csv'))
            if os.path.exists(beacon_csv):
                comp_path = os.path.join(data_dir, "report_comparison.csv")
                self.system.export_comparison_report(beacon_csv, comp_path)
                result = self.system.compare_with_beacon_csv(beacon_csv)
                comparison_msg = (
                    f"\n8. Comparison report: {len(result['in_both'])} matched, "
                    f"{len(result['only_in_excel'])} only in Excel, "
                    f"{len(result['only_in_csv'])} only in CSV, "
                    f"{len(result['differences'])} with differences"
                )

        messagebox.showinfo(
            "Reports Generated",
            f"Reports saved to:\n{data_dir}\n\n"
            f"1. Reconciled: {r1} rows\n"
            f"2. Un-reconciled bank: {r2} rows\n"
            f"3. Un-reconciled beacon: {r3} rows\n"
            f"4. Manually resolved: {r4} rows\n"
            f"5. Stats summary\n"
            f"6. Inconsistencies: {r6} rows\n"
            f"7. Unresolved memnos: {r7} rows"
            f"{comparison_msg}\n\n"
            f"Version: {VERSION}"
        )


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

def main():
    """Main entry point for GUI application."""
    data_dir = None
    if len(sys.argv) > 1:
        data_dir = sys.argv[1].strip().rstrip('"').rstrip("'")
        data_dir = os.path.abspath(data_dir)

    root = tk.Tk()

    try:
        root.iconbitmap('icon.ico')
    except tk.TclError:
        pass

    app = ReconciliationGUI(root, data_dir=data_dir)

    def on_closing():
        app.system.save_state()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
