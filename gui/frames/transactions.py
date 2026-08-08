"""
gui/frames/transactions.py
==========================
Transaction ledger frame.

Displays the full transaction history with:
- Filter controls (account, type, date range, search).
- Sortable Treeview.
- Add transaction dialog (buy, sell, contribution, special allocation, etc.).
"""

from __future__ import annotations

import tkinter as tk
import tkinter.messagebox as mb
from datetime import date, datetime
from tkinter import ttk

from db.database import get_session
from db.models import Account, Asset, Transaction, TransactionType
from gui import theme as th


class TransactionsFrame(ttk.Frame):
    """Full transaction ledger with filters and add dialog."""

    def __init__(self, parent: tk.Widget, app, **kwargs) -> None:
        super().__init__(parent, style="TFrame", **kwargs)
        self.app = app
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header
        header = tk.Frame(self, bg=th.BG_DARK)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 8))
        tk.Label(header, text="Transaction Ledger",
                 font=th.FONT_H1, bg=th.BG_DARK, fg=th.FG_PRIMARY).pack(side="left")
        ttk.Button(header, text="+ Add Transaction",
                   style="Primary.TButton",
                   command=self._add_transaction_dialog).pack(side="right")

        # Filter bar
        filters = tk.Frame(self, bg=th.BG_PANEL)
        filters.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 8))

        # Account filter
        tk.Label(filters, text="Account:", font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(side="left", padx=(12, 4))
        self._acct_filter_var = tk.StringVar(value="All")
        self._acct_combo = ttk.Combobox(filters, textvariable=self._acct_filter_var,
                                        values=["All"], state="readonly", width=18)
        self._acct_combo.pack(side="left", padx=(0, 12))

        # Type filter
        tk.Label(filters, text="Type:", font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(side="left", padx=(0, 4))
        self._type_filter_var = tk.StringVar(value="All")
        ttk.Combobox(
            filters, textvariable=self._type_filter_var,
            values=["All"] + [t.value for t in TransactionType],
            state="readonly", width=16,
        ).pack(side="left", padx=(0, 12))

        # Search
        tk.Label(filters, text="Search:", font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(side="left", padx=(0, 4))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filters())
        ttk.Entry(filters, textvariable=self._search_var, width=20).pack(side="left")

        ttk.Button(filters, text="Apply", command=self._apply_filters).pack(
            side="left", padx=8)

        # Summary labels
        self._count_var = tk.StringVar(value="")
        tk.Label(filters, textvariable=self._count_var,
                 font=th.FONT_SMALL, bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(
            side="right", padx=12)

        # Treeview
        tree_frame = tk.Frame(self, bg=th.BG_PANEL)
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 24))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("date", "account", "ticker", "type", "amount", "shares", "price", "tag", "notes")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        hdefs = [
            ("date",    "Date",        90, "w"),
            ("account", "Account",    130, "w"),
            ("ticker",  "Ticker",      60, "w"),
            ("type",    "Type",       110, "w"),
            ("amount",  "Amount",      90, "e"),
            ("shares",  "Shares",      80, "e"),
            ("price",   "Price",       75, "e"),
            ("tag",     "Tag",         80, "w"),
            ("notes",   "Notes",      160, "w"),
        ]
        for col, label, width, anchor in hdefs:
            self._tree.heading(col, text=label,
                               command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=width, anchor=anchor)

        self._tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

        # Context menu
        self._tree.bind("<Button-3>", self._show_context_menu)
        self._ctx_menu = tk.Menu(self, tearoff=0, bg=th.BG_PANEL, fg=th.FG_PRIMARY)
        self._ctx_menu.add_command(label="Delete Transaction", command=self._delete_selected)

        # Row tag colours
        self._tree.tag_configure("div",  foreground=th.FG_GOLD)
        self._tree.tag_configure("drip", foreground=th.FG_ACCENT)
        self._tree.tag_configure("sell", foreground=th.FG_DANGER)
        self._tree.tag_configure("buy",  foreground=th.FG_SUCCESS)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload all transactions and repopulate filter dropdowns."""
        with get_session() as session:
            accounts = session.query(Account).filter(Account.is_active == True).all()
            acct_names = ["All"] + [a.name for a in accounts]
        self._acct_combo["values"] = acct_names
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Filter the transaction list and redraw the treeview."""
        self._tree.delete(*self._tree.get_children())

        search = self._search_var.get().lower()
        acct_name = self._acct_filter_var.get()
        type_name = self._type_filter_var.get()

        with get_session() as session:
            q = session.query(Transaction)

            if acct_name != "All":
                acct = session.query(Account).filter(Account.name == acct_name).first()
                if acct:
                    q = q.filter(Transaction.account_id == acct.id)

            if type_name != "All":
                q = q.filter(Transaction.transaction_type == TransactionType(type_name))

            txns = q.order_by(Transaction.transaction_date.desc()).all()

            rows = []
            for tx in txns:
                ticker = tx.asset.ticker if tx.asset else ""
                acct_n = tx.account.name if tx.account else ""
                row_str = " ".join([
                    str(tx.transaction_date), acct_n, ticker,
                    tx.transaction_type.value, tx.tag, tx.notes
                ]).lower()

                if search and search not in row_str:
                    continue

                rows.append((tx, ticker, acct_n))

        self._count_var.set(f"{len(rows)} transactions")

        _TYPE_TAG = {
            TransactionType.DIVIDEND: "div",
            TransactionType.DRIP: "drip",
            TransactionType.SELL: "sell",
            TransactionType.BUY: "buy",
        }

        for tx, ticker, acct_n in rows:
            tag = _TYPE_TAG.get(tx.transaction_type, "")
            self._tree.insert(
                "", "end",
                iid=str(tx.id),
                tags=(tag,),
                values=(
                    str(tx.transaction_date),
                    acct_n,
                    ticker,
                    tx.transaction_type.value,
                    f"${tx.amount:,.2f}",
                    f"{tx.shares:.6f}" if tx.shares else "–",
                    f"${tx.price_per_share:.4f}" if tx.price_per_share else "–",
                    tx.tag or "–",
                    (tx.notes or "")[:40],
                ),
            )

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    _sort_reverse: dict[str, bool] = {}

    def _sort_by(self, col: str) -> None:
        """Sort treeview rows by column."""
        items = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        rev = self._sort_reverse.get(col, False)
        items.sort(reverse=rev)
        for idx, (_, k) in enumerate(items):
            self._tree.move(k, "", idx)
        self._sort_reverse[col] = not rev

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, event) -> None:
        row = self._tree.identify_row(event.y)
        if row:
            self._tree.selection_set(row)
            self._ctx_menu.post(event.x_root, event.y_root)

    def _delete_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        if not mb.askyesno("Confirm", "Delete this transaction? This cannot be undone."):
            return
        tx_id = int(sel[0])
        with get_session() as session:
            tx = session.query(Transaction).get(tx_id)
            if tx:
                session.delete(tx)
        self._apply_filters()

    # ------------------------------------------------------------------
    # Add transaction dialog
    # ------------------------------------------------------------------

    def _add_transaction_dialog(self) -> None:
        _TransactionDialog(self, on_save=self._apply_filters)


# ---------------------------------------------------------------------------
# Transaction dialog
# ---------------------------------------------------------------------------

class _TransactionDialog(tk.Toplevel):
    """
    Modal dialog for adding a new transaction.

    Features
    --------
    - Account dropdown auto-populates Ticker dropdown with that account's holdings.
    - Selecting a Ticker auto-fills Price/Share from the last known price and
      computes Shares = Amount ÷ Price in real time.
    - "Recurring Investment" checkbox: when checked, shows the matching
      ScheduledContrib (if any) and pre-fills Amount from it.
    - "Also generate DRIP" checkbox: appears when the selected holding has
      DRIP enabled; creates a companion DRIP transaction using the holding's
      dividend yield × shares × price.
    """

    def __init__(self, parent, on_save) -> None:
        super().__init__(parent)
        self._on_save = on_save
        self.title("Add Transaction")
        self.resizable(False, False)
        self.configure(bg=th.BG_PANEL)
        self.grab_set()

        # internal state
        self._accounts: list[Account] = []
        self._assets_for_account: dict[int, list[Asset]] = {}   # acct_id → assets
        self._selected_asset: Asset | None = None

        self._build()
        self._load_combos()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 16, "pady": 4}

        self._date_var    = tk.StringVar(value=str(date.today()))
        self._acct_var    = tk.StringVar()
        self._ticker_var  = tk.StringVar()
        self._type_var    = tk.StringVar(value=TransactionType.CONTRIBUTION.value)
        self._amount_var  = tk.StringVar(value="0.00")
        self._shares_var  = tk.StringVar(value="0.000000")
        self._price_var   = tk.StringVar(value="0.00")
        self._tag_var     = tk.StringVar()
        self._recur_var   = tk.BooleanVar(value=False)
        self._drip_var    = tk.BooleanVar(value=False)

        row = 0

        # Date
        tk.Label(self, text="Date (YYYY-MM-DD)", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(self, textvariable=self._date_var, width=30).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Account
        tk.Label(self, text="Account", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        self._acct_combo = ttk.Combobox(self, textvariable=self._acct_var,
                                       state="readonly", width=28)
        self._acct_combo.grid(row=row, column=1, sticky="w", **pad)
        self._acct_var.trace_add("write", lambda *_: self._on_account_change())
        row += 1

        # Ticker
        tk.Label(self, text="Ticker", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        self._ticker_combo = ttk.Combobox(self, textvariable=self._ticker_var,
                                         state="readonly", width=28)
        self._ticker_combo.grid(row=row, column=1, sticky="w", **pad)
        self._ticker_var.trace_add("write", lambda *_: self._on_ticker_change())
        row += 1

        # Type
        tk.Label(self, text="Type", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        ttk.Combobox(self, textvariable=self._type_var,
                     values=[t.value for t in TransactionType],
                     state="readonly", width=28).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Amount
        tk.Label(self, text="Amount ($)", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        self._amount_entry = ttk.Entry(self, textvariable=self._amount_var, width=30)
        self._amount_entry.grid(row=row, column=1, sticky="w", **pad)
        self._amount_var.trace_add("write", lambda *_: self._auto_shares())
        row += 1

        # Shares (read-only when ticker selected — auto-computed)
        tk.Label(self, text="Shares", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        self._shares_entry = ttk.Entry(self, textvariable=self._shares_var, width=30)
        self._shares_entry.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Price/Share
        tk.Label(self, text="Price/Share ($)", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        self._price_entry = ttk.Entry(self, textvariable=self._price_var, width=30)
        self._price_entry.grid(row=row, column=1, sticky="w", **pad)
        self._price_var.trace_add("write", lambda *_: self._auto_shares())
        row += 1

        # Tag
        tk.Label(self, text="Tag", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(self, textvariable=self._tag_var, width=30).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Notes
        tk.Label(self, text="Notes", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
        self._notes = tk.Text(self, width=30, height=3, bg=th.BG_ENTRY,
                               fg=th.FG_PRIMARY, insertbackground=th.FG_PRIMARY,
                               relief="flat", font=th.FONT_BODY)
        self._notes.grid(row=row, column=1, **pad)
        row += 1

        # ── Recurring Investment checkbox ────────────────────────────────
        sep = ttk.Separator(self, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=6)
        row += 1

        self._recur_chk = ttk.Checkbutton(
            self, text="🔁  Use amount from Recurring Investment schedule",
            variable=self._recur_var, command=self._on_recur_toggle,
            style="TCheckbutton",
        )
        self._recur_chk.grid(row=row, column=0, columnspan=2, sticky="w", padx=16)
        row += 1

        self._recur_info_var = tk.StringVar(value="")
        self._recur_info_lbl = tk.Label(self, textvariable=self._recur_info_var,
                                       bg=th.BG_PANEL, fg=th.FG_ACCENT,
                                       font=th.FONT_SMALL, wraplength=340, justify="left")
        self._recur_info_lbl.grid(row=row, column=0, columnspan=2, sticky="w", padx=32)
        row += 1

        # ── DRIP checkbox ────────────────────────────────────────────────
        self._drip_chk = ttk.Checkbutton(
            self, text="💧  Also generate DRIP reinvestment transaction",
            variable=self._drip_var,
            style="TCheckbutton",
        )
        self._drip_chk.grid(row=row, column=0, columnspan=2, sticky="w", padx=16)
        self._drip_chk.state(["disabled"])   # enabled only when holding has DRIP on
        row += 1

        self._drip_info_var = tk.StringVar(value="")
        self._drip_info_lbl = tk.Label(self, textvariable=self._drip_info_var,
                                      bg=th.BG_PANEL, fg=th.FG_GOLD,
                                      font=th.FONT_SMALL, wraplength=340, justify="left")
        self._drip_info_lbl.grid(row=row, column=0, columnspan=2, sticky="w", padx=32)
        row += 1

        # Buttons
        btn_row = tk.Frame(self, bg=th.BG_PANEL)
        btn_row.grid(row=row, column=0, columnspan=2, pady=12)
        ttk.Button(btn_row, text="Save", style="Primary.TButton",
                   command=self._save).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # Combo population
    # ------------------------------------------------------------------

    def _load_combos(self) -> None:
        """Load accounts and their holdings from the database."""
        with get_session() as session:
            accounts = session.query(Account).filter(Account.is_active == True).all()
            self._accounts = accounts
            for a in accounts:
                self._assets_for_account[a.id] = list(a.assets)

        names = [a.name for a in self._accounts]
        self._acct_combo["values"] = names
        if names:
            self._acct_var.set(names[0])

    def _on_account_change(self) -> None:
        """When account changes, refresh the ticker dropdown."""
        acct = self._get_selected_account()
        if acct is None:
            self._ticker_combo["values"] = []
            self._ticker_var.set("")
            return
        assets = self._assets_for_account.get(acct.id, [])
        tickers = [a.ticker for a in assets]
        self._ticker_combo["values"] = tickers
        self._ticker_var.set(tickers[0] if tickers else "")

    def _on_ticker_change(self) -> None:
        """Auto-fill price from last known price; update DRIP/recurring hints."""
        self._selected_asset = self._get_selected_asset()
        a = self._selected_asset

        if a is None:
            self._price_var.set("0.00")
            self._drip_chk.state(["disabled"])
            self._drip_var.set(False)
            self._drip_info_var.set("")
            self._recur_info_var.set("")
            return

        # Auto-fill price
        if a.last_price:
            self._price_var.set(f"{a.last_price:.4f}")

        # DRIP hint
        if a.drip_enabled:
            self._drip_chk.state(["!disabled"])
            div_annual = (a.dividend_per_share or 0) * a.shares
            from services.dividend_engine import _PAYMENTS_PER_YEAR
            freq_val = a.dividend_frequency.value if a.dividend_frequency else "Quarterly"
            ppy = _PAYMENTS_PER_YEAR.get(freq_val, 4)
            div_payment = div_annual / ppy if ppy else 0
            drip_shares = div_payment / a.last_price if a.last_price else 0
            self._drip_info_var.set(
                f"Est. {freq_val} dividend: ${div_payment:.4f}  →  "
                f"{drip_shares:.6f} new shares @ ${a.last_price:.2f}"
            )
        else:
            self._drip_chk.state(["disabled"])
            self._drip_var.set(False)
            self._drip_info_var.set("")

        # Recurring hint
        self._refresh_recur_hint()

    def _refresh_recur_hint(self) -> None:
        """Look up any active ScheduledContrib for this account+ticker."""
        a = self._selected_asset
        if a is None:
            self._recur_info_var.set("")
            return
        with get_session() as session:
            from db.models import ScheduledContrib
            sc = (
                session.query(ScheduledContrib)
                .filter(
                    ScheduledContrib.account_id == a.account_id,
                    ScheduledContrib.asset_id == a.id,
                    ScheduledContrib.is_active == True,
                )
                .first()
            )
            if sc:
                self._recur_info_var.set(
                    f"Scheduled: ${sc.amount:.2f} {sc.frequency.value} "
                    f"(started {sc.start_date})"
                )
            else:
                self._recur_info_var.set("No recurring schedule found for this ticker.")

    def _on_recur_toggle(self) -> None:
        """When recurring checkbox is ticked, pre-fill amount from schedule."""
        if not self._recur_var.get():
            return
        a = self._selected_asset
        if a is None:
            return
        with get_session() as session:
            from db.models import ScheduledContrib
            sc = (
                session.query(ScheduledContrib)
                .filter(
                    ScheduledContrib.account_id == a.account_id,
                    ScheduledContrib.asset_id == a.id,
                    ScheduledContrib.is_active == True,
                )
                .first()
            )
            if sc:
                self._amount_var.set(f"{sc.amount:.2f}")
            else:
                mb.showinfo("No Schedule", "No active recurring schedule found for this ticker.",
                            parent=self)
                self._recur_var.set(False)

    # ------------------------------------------------------------------
    # Auto-compute shares
    # ------------------------------------------------------------------

    def _auto_shares(self) -> None:
        """Recompute shares = amount ÷ price whenever either field changes."""
        try:
            amount = float(self._amount_var.get() or 0)
            price  = float(self._price_var.get() or 0)
            if price > 0:
                self._shares_var.set(f"{amount / price:.6f}")
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_selected_account(self) -> Account | None:
        name = self._acct_var.get()
        return next((a for a in self._accounts if a.name == name), None)

    def _get_selected_asset(self) -> Asset | None:
        acct = self._get_selected_account()
        if acct is None:
            return None
        ticker = self._ticker_var.get().strip().upper()
        return next(
            (a for a in self._assets_for_account.get(acct.id, []) if a.ticker == ticker),
            None,
        )

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Validate inputs, write Transaction(s), and close."""
        try:
            tx_date = datetime.strptime(self._date_var.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            mb.showwarning("Validation", "Date must be YYYY-MM-DD.", parent=self)
            return
        try:
            amount = float(self._amount_var.get() or 0)
            shares = float(self._shares_var.get() or 0)
            price  = float(self._price_var.get() or 0)
        except ValueError:
            mb.showwarning("Validation", "Amount, shares, price must be numbers.", parent=self)
            return

        acct = self._get_selected_account()
        if acct is None:
            mb.showwarning("Validation", "Please select an account.", parent=self)
            return

        notes = self._notes.get("1.0", "end-1c")
        asset = self._selected_asset

        with get_session() as session:
            # Primary transaction
            tx = Transaction(
                account_id=acct.id,
                asset_id=asset.id if asset else None,
                transaction_type=TransactionType(self._type_var.get()),
                transaction_date=tx_date,
                amount=amount,
                shares=shares if shares else None,
                price_per_share=price if price else None,
                tag=self._tag_var.get().strip(),
                notes=notes,
            )
            session.add(tx)

            # Optional DRIP companion transaction
            if self._drip_var.get() and asset and asset.drip_enabled and asset.last_price:
                from services.dividend_engine import _PAYMENTS_PER_YEAR
                freq_val = asset.dividend_frequency.value if asset.dividend_frequency else "Quarterly"
                ppy = _PAYMENTS_PER_YEAR.get(freq_val, 4)
                div_annual = (asset.dividend_per_share or 0) * asset.shares
                div_payment = div_annual / ppy if ppy else 0
                drip_shares = div_payment / asset.last_price
                drip_tx = Transaction(
                    account_id=acct.id,
                    asset_id=asset.id,
                    transaction_type=TransactionType.DRIP,
                    transaction_date=tx_date,
                    amount=div_payment,
                    shares=drip_shares,
                    price_per_share=asset.last_price,
                    tag="drip",
                    notes=f"Auto DRIP — {freq_val} dividend reinvestment",
                )
                session.add(drip_tx)

        self._on_save()
        self.destroy()
