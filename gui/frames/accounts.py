"""
gui/frames/accounts.py
======================
Accounts & Holdings management frame.

Users can:
- Add / edit / deactivate accounts.
- Add / edit / remove holdings (assets) within an account.
- Trigger a yfinance lookup to auto-populate ticker metadata.
"""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.messagebox as mb
from tkinter import ttk

from db.database import get_session
from db.models import Account, AccountType, Asset, DividendFrequency
from gui import theme as th
from services.market import get_ticker_info


class AccountsFrame(ttk.Frame):
    """Accounts and holdings management frame."""

    def __init__(self, parent: tk.Widget, app, **kwargs) -> None:
        super().__init__(parent, style="TFrame", **kwargs)
        self.app = app
        self._selected_account_id: int | None = None
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)

        # Header
        header = tk.Frame(self, bg=th.BG_DARK)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(20, 12))

        tk.Label(header, text="Accounts & Holdings",
                 font=th.FONT_H1, bg=th.BG_DARK, fg=th.FG_PRIMARY).pack(side="left")

        ttk.Button(header, text="+ Add Account",
                   style="Primary.TButton",
                   command=self._add_account_dialog).pack(side="right")

        # Left: account list
        left = tk.Frame(self, bg=th.BG_PANEL)
        left.grid(row=1, column=0, sticky="nsew", padx=(24, 8), pady=(0, 24))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        tk.Label(left, text="Accounts", font=th.FONT_H3,
                 bg=th.BG_PANEL, fg=th.FG_PRIMARY).grid(row=0, column=0, padx=12, pady=8, sticky="w")

        self._acct_tree = ttk.Treeview(
            left,
            columns=("name", "type", "balance"),
            show="headings",
            selectmode="browse",
        )
        for col, label, width in [
            ("name",    "Account",     180),
            ("type",    "Type",        110),
            ("balance", "Balance",      90),
        ]:
            self._acct_tree.heading(col, text=label)
            self._acct_tree.column(col, width=width, anchor="w" if col != "balance" else "e")

        self._acct_tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._acct_tree.bind("<<TreeviewSelect>>", self._on_account_select)

        sb = ttk.Scrollbar(left, orient="vertical", command=self._acct_tree.yview)
        self._acct_tree.configure(yscrollcommand=sb.set)
        sb.grid(row=1, column=1, sticky="ns", pady=(0, 8))

        # Account action buttons
        btn_row = tk.Frame(left, bg=th.BG_PANEL)
        btn_row.grid(row=2, column=0, columnspan=2, padx=8, pady=8, sticky="ew")
        ttk.Button(btn_row, text="Edit", command=self._edit_account_dialog).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Delete", style="Danger.TButton",
                   command=self._delete_account).pack(side="left", padx=4)

        # Right: tabbed panel — Holdings | Recurring Investments
        right = tk.Frame(self, bg=th.BG_PANEL)
        right.grid(row=1, column=1, sticky="nsew", padx=(0, 24), pady=(0, 24))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self._right_notebook = ttk.Notebook(right)
        self._right_notebook.grid(row=0, column=0, sticky="nsew")

        # ---- Tab 1: Holdings ----------------------------------------
        holdings_tab = tk.Frame(self._right_notebook, bg=th.BG_PANEL)
        holdings_tab.columnconfigure(0, weight=1)
        holdings_tab.rowconfigure(1, weight=1)
        self._right_notebook.add(holdings_tab, text="  Holdings  ")

        hdr_right = tk.Frame(holdings_tab, bg=th.BG_PANEL)
        hdr_right.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        tk.Label(hdr_right, text="Holdings", font=th.FONT_H3,
                 bg=th.BG_PANEL, fg=th.FG_PRIMARY).pack(side="left")

        self._add_holding_btn = ttk.Button(
            hdr_right, text="+ Add Holding",
            style="Primary.TButton",
            command=self._add_holding_dialog,
            state="disabled",
        )
        self._add_holding_btn.pack(side="right")

        self._live_btn = ttk.Button(
            hdr_right, text="⟳ Live Changes",
            command=self._refresh_live_changes,
            state="disabled",
        )
        self._live_btn.pack(side="right", padx=(0, 8))

        self._holding_tree = ttk.Treeview(
            holdings_tab,
            columns=("ticker", "name", "shares", "price", "value",
                     "day_chg", "day_pct", "30d_pct", "yield", "drip"),
            show="headings",
            selectmode="browse",
        )
        hdefs = [
            ("ticker",  "Ticker",   60, "w"),
            ("name",    "Name",    150, "w"),
            ("shares",  "Shares",   75, "e"),
            ("price",   "Price",    70, "e"),
            ("value",   "Value",    90, "e"),
            ("day_chg", "Day $",    70, "e"),
            ("day_pct", "Day %",    65, "e"),
            ("30d_pct", "30-Day %", 70, "e"),
            ("yield",   "Ann Yield",70, "e"),
            ("drip",    "DRIP",     45, "center"),
        ]
        for col, label, width, anchor in hdefs:
            self._holding_tree.heading(col, text=label)
            self._holding_tree.column(col, width=width, anchor=anchor)

        self._holding_tree.tag_configure("up",   foreground=th.FG_SUCCESS)
        self._holding_tree.tag_configure("down", foreground=th.FG_DANGER)
        self._holding_tree.tag_configure("flat", foreground=th.FG_SECONDARY)

        self._holding_tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        sb2 = ttk.Scrollbar(holdings_tab, orient="vertical", command=self._holding_tree.yview)
        self._holding_tree.configure(yscrollcommand=sb2.set)
        sb2.grid(row=1, column=1, sticky="ns", pady=(0, 8))

        btn_row2 = tk.Frame(holdings_tab, bg=th.BG_PANEL)
        btn_row2.grid(row=2, column=0, columnspan=2, padx=8, pady=8, sticky="ew")
        ttk.Button(btn_row2, text="Edit Holding", command=self._edit_holding_dialog).pack(side="left", padx=4)
        ttk.Button(btn_row2, text="Remove Holding", style="Danger.TButton",
                   command=self._remove_holding).pack(side="left", padx=4)

        # ---- Tab 2: Recurring Investments ---------------------------
        recurring_tab = tk.Frame(self._right_notebook, bg=th.BG_PANEL)
        recurring_tab.columnconfigure(0, weight=1)
        recurring_tab.rowconfigure(1, weight=1)
        self._right_notebook.add(recurring_tab, text="  🔁 Recurring Investments  ")

        rec_hdr = tk.Frame(recurring_tab, bg=th.BG_PANEL)
        rec_hdr.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=8)

        tk.Label(rec_hdr, text="Recurring Investments", font=th.FONT_H3,
                 bg=th.BG_PANEL, fg=th.FG_PRIMARY).pack(side="left")

        self._add_recur_btn = ttk.Button(
            rec_hdr, text="+ Add Recurring",
            style="Primary.TButton",
            command=self._add_recurring_dialog,
            state="disabled",
        )
        self._add_recur_btn.pack(side="right")

        # Summary label: total monthly equivalent
        self._recur_summary_var = tk.StringVar(value="")
        tk.Label(rec_hdr, textvariable=self._recur_summary_var,
                 font=th.FONT_SMALL, bg=th.BG_PANEL, fg=th.FG_GOLD).pack(side="right", padx=12)

        self._recur_tree = ttk.Treeview(
            recurring_tab,
            columns=("ticker", "amount", "freq", "monthly_eq", "start", "next", "active"),
            show="headings",
            selectmode="browse",
        )
        rhdefs = [
            ("ticker",     "Ticker",       70, "w"),
            ("amount",     "Per Period $",  90, "e"),
            ("freq",       "Frequency",    100, "w"),
            ("monthly_eq", "Monthly Eq.",   90, "e"),
            ("start",      "Start Date",    90, "w"),
            ("next",       "Next Run",      90, "w"),
            ("active",     "Active",        55, "center"),
        ]
        for col, label, width, anchor in rhdefs:
            self._recur_tree.heading(col, text=label)
            self._recur_tree.column(col, width=width, anchor=anchor)

        self._recur_tree.tag_configure("active",   foreground=th.FG_SUCCESS)
        self._recur_tree.tag_configure("inactive", foreground=th.FG_SECONDARY)

        self._recur_tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        sb3 = ttk.Scrollbar(recurring_tab, orient="vertical", command=self._recur_tree.yview)
        self._recur_tree.configure(yscrollcommand=sb3.set)
        sb3.grid(row=1, column=1, sticky="ns", pady=(0, 8))

        rec_btn_row = tk.Frame(recurring_tab, bg=th.BG_PANEL)
        rec_btn_row.grid(row=2, column=0, columnspan=2, padx=8, pady=8, sticky="ew")
        ttk.Button(rec_btn_row, text="Edit", command=self._edit_recurring_dialog).pack(side="left", padx=4)
        ttk.Button(rec_btn_row, text="Pause/Resume", command=self._toggle_recurring).pack(side="left", padx=4)
        ttk.Button(rec_btn_row, text="Delete", style="Danger.TButton",
                   command=self._delete_recurring).pack(side="left", padx=4)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload accounts from the database."""
        self._acct_tree.delete(*self._acct_tree.get_children())
        with get_session() as session:
            accounts = session.query(Account).filter(Account.is_active == True).all()
            for acc in accounts:
                balance = sum(a.market_value for a in acc.assets)
                self._acct_tree.insert(
                    "", "end",
                    iid=str(acc.id),
                    values=(acc.name, acc.account_type.value, f"${balance:,.2f}"),
                )
        if self._selected_account_id:
            self._load_holdings(self._selected_account_id)

    def _on_account_select(self, _event=None) -> None:
        sel = self._acct_tree.selection()
        if not sel:
            return
        acct_id = int(sel[0])
        self._selected_account_id = acct_id
        self._add_holding_btn.configure(state="normal")
        self._live_btn.configure(state="normal")
        self._add_recur_btn.configure(state="normal")
        self._load_holdings(acct_id)
        self._load_recurring(acct_id)

    def _load_holdings(self, account_id: int, changes: dict | None = None) -> None:
        """
        Populate the holdings treeview for *account_id*.

        Parameters
        ----------
        changes : dict, optional
            Pre-fetched price-change data from :func:`~services.market.get_price_changes`.
            When None the day/30d columns show "–" (no network call made).
        """
        self._holding_tree.delete(*self._holding_tree.get_children())
        with get_session() as session:
            assets = session.query(Asset).filter(Asset.account_id == account_id).all()
            for a in assets:
                ch = (changes or {}).get(a.ticker, {})

                day_chg     = ch.get("day_change")
                day_pct     = ch.get("day_change_pct")
                change_30d  = ch.get("change_30d_pct")

                # Pick a row colour tag based on today's direction
                if day_pct is None:
                    tag = "flat"
                elif day_pct > 0:
                    tag = "up"
                elif day_pct < 0:
                    tag = "down"
                else:
                    tag = "flat"

                day_chg_str  = f"{'+' if day_chg >= 0 else ''}{day_chg:.2f}" if day_chg is not None else "–"
                day_pct_str  = f"{'+' if day_pct >= 0 else ''}{day_pct:.2f}%" if day_pct is not None else "–"
                chg30_str    = f"{'+' if change_30d >= 0 else ''}{change_30d:.2f}%" if change_30d is not None else "–"

                self._holding_tree.insert(
                    "", "end",
                    iid=str(a.id),
                    tags=(tag,),
                    values=(
                        a.ticker,
                        a.name[:20] + "…" if len(a.name) > 20 else a.name,
                        f"{a.shares:.4f}",
                        f"${a.last_price:.2f}",
                        f"${a.market_value:,.2f}",
                        day_chg_str,
                        day_pct_str,
                        chg30_str,
                        f"{a.dividend_yield*100:.2f}%",
                        "✓" if a.drip_enabled else "–",
                    ),
                )

    def _refresh_live_changes(self) -> None:
        """Fetch today's price changes on a background thread and refresh the table."""
        if not self._selected_account_id:
            return
        self._live_btn.configure(state="disabled", text="Loading…")

        def _worker():
            from services.market import get_price_changes
            with get_session() as session:
                from db.models import Asset as _Asset
                assets = session.query(_Asset).filter(
                    _Asset.account_id == self._selected_account_id
                ).all()
                tickers = list({a.ticker for a in assets})
            changes = get_price_changes(tickers)
            self.after(0, self._on_live_done, changes)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_live_done(self, changes: dict) -> None:
        self._load_holdings(self._selected_account_id, changes=changes)
        self._live_btn.configure(state="normal", text="⟳ Live Changes")
        self.app.set_status("Live price changes loaded")

    # ------------------------------------------------------------------
    # Account dialogs
    # ------------------------------------------------------------------

    def _add_account_dialog(self) -> None:
        _AccountDialog(self, app=self.app, account=None, on_save=self.refresh)

    def _edit_account_dialog(self) -> None:
        sel = self._acct_tree.selection()
        if not sel:
            mb.showinfo("Select Account", "Please select an account to edit.")
            return
        acct_id = int(sel[0])
        with get_session() as session:
            acct = session.query(Account).get(acct_id)
            if acct:
                _AccountDialog(self, app=self.app, account=acct, on_save=self.refresh)

    def _delete_account(self) -> None:
        sel = self._acct_tree.selection()
        if not sel:
            return
        if not mb.askyesno("Confirm", "Deactivate this account? Holdings will be preserved."):
            return
        acct_id = int(sel[0])
        with get_session() as session:
            acct = session.query(Account).get(acct_id)
            if acct:
                acct.is_active = False
        self.refresh()

    # ------------------------------------------------------------------
    # Holding dialogs
    # ------------------------------------------------------------------

    def _add_holding_dialog(self) -> None:
        if not self._selected_account_id:
            return
        _HoldingDialog(self, account_id=self._selected_account_id,
                       asset=None, on_save=lambda: self._load_holdings(self._selected_account_id))

    def _edit_holding_dialog(self) -> None:
        sel = self._holding_tree.selection()
        if not sel:
            mb.showinfo("Select Holding", "Please select a holding to edit.")
            return
        asset_id = int(sel[0])
        with get_session() as session:
            asset = session.query(Asset).get(asset_id)
            if asset:
                _HoldingDialog(self, account_id=asset.account_id,
                               asset=asset,
                               on_save=lambda: self._load_holdings(self._selected_account_id))

    def _remove_holding(self) -> None:
        sel = self._holding_tree.selection()
        if not sel:
            return
        if not mb.askyesno("Confirm", "Remove this holding? This cannot be undone."):
            return
        asset_id = int(sel[0])
        with get_session() as session:
            asset = session.query(Asset).get(asset_id)
            if asset:
                session.delete(asset)
        self._load_holdings(self._selected_account_id)

    # ------------------------------------------------------------------
    # Recurring investment data + actions
    # ------------------------------------------------------------------

    _MONTHLY_FACTORS = {
        "Weekly": 52 / 12,
        "Biweekly": 26 / 12,
        "Monthly": 1.0,
        "Quarterly": 1 / 3,
        "Annually": 1 / 12,
    }

    def _load_recurring(self, account_id: int) -> None:
        """Populate the recurring investments treeview for *account_id*."""
        from db.models import ScheduledContrib
        from datetime import date

        self._recur_tree.delete(*self._recur_tree.get_children())
        total_monthly = 0.0

        with get_session() as session:
            rows = (
                session.query(ScheduledContrib)
                .filter(ScheduledContrib.account_id == account_id)
                .order_by(ScheduledContrib.start_date)
                .all()
            )
            for r in rows:
                ticker = r.asset.ticker if r.asset_id and r.asset else "—"
                factor = self._MONTHLY_FACTORS.get(r.frequency.value, 1.0)
                monthly_eq = r.amount * factor
                if r.is_active:
                    total_monthly += monthly_eq

                # Next expected run date
                last = r.last_run_date or r.start_date
                next_run = "—"
                try:
                    from datetime import timedelta
                    check = date.today()
                    # Walk forward until a due date is found (max 400 days out)
                    for _ in range(400):
                        if _is_due_on(r, check):
                            next_run = str(check)
                            break
                        check += timedelta(days=1)
                except Exception:
                    pass

                tag = "active" if r.is_active else "inactive"
                self._recur_tree.insert("", "end", iid=str(r.id), tags=(tag,), values=(
                    ticker,
                    f"${r.amount:.2f}",
                    r.frequency.value,
                    f"${monthly_eq:.2f}/mo",
                    str(r.start_date),
                    next_run,
                    "✓" if r.is_active else "Paused",
                ))

        self._recur_summary_var.set(
            f"Total: ${total_monthly:.2f}/mo  (${total_monthly * 12:.0f}/yr)"
        )

    def _add_recurring_dialog(self) -> None:
        if not self._selected_account_id:
            return
        _RecurringDialog(
            self, account_id=self._selected_account_id, contrib=None,
            on_save=lambda: self._load_recurring(self._selected_account_id),
        )

    def _edit_recurring_dialog(self) -> None:
        sel = self._recur_tree.selection()
        if not sel:
            mb.showinfo("Select", "Please select a recurring investment to edit.")
            return
        from db.models import ScheduledContrib
        rid = int(sel[0])
        with get_session() as session:
            contrib = session.query(ScheduledContrib).get(rid)
            if contrib:
                _RecurringDialog(
                    self, account_id=contrib.account_id, contrib=contrib,
                    on_save=lambda: self._load_recurring(self._selected_account_id),
                )

    def _toggle_recurring(self) -> None:
        sel = self._recur_tree.selection()
        if not sel:
            return
        from db.models import ScheduledContrib
        rid = int(sel[0])
        with get_session() as session:
            r = session.query(ScheduledContrib).get(rid)
            if r:
                r.is_active = not r.is_active
        self._load_recurring(self._selected_account_id)

    def _delete_recurring(self) -> None:
        sel = self._recur_tree.selection()
        if not sel:
            return
        if not mb.askyesno("Confirm", "Delete this recurring investment rule?"):
            return
        from db.models import ScheduledContrib
        rid = int(sel[0])
        with get_session() as session:
            r = session.query(ScheduledContrib).get(rid)
            if r:
                session.delete(r)
        self._load_recurring(self._selected_account_id)


# ---------------------------------------------------------------------------
# Helper: is a ScheduledContrib due on a specific date?
# (duplicated from scheduler to avoid circular import)
# ---------------------------------------------------------------------------

def _is_due_on(contrib, check_date) -> bool:
    """Return True if *contrib* would fire on *check_date*."""
    from datetime import timedelta
    from db.models import Frequency

    if not contrib.is_active:
        return False
    if check_date < contrib.start_date:
        return False
    if contrib.end_date and check_date > contrib.end_date:
        return False

    last = contrib.last_run_date or (contrib.start_date - timedelta(days=1))
    delta = (check_date - last).days
    freq = contrib.frequency

    if freq == Frequency.WEEKLY:
        return delta >= 7
    if freq == Frequency.BIWEEKLY:
        return delta >= 14
    if freq == Frequency.MONTHLY:
        return (
            check_date.day == contrib.start_date.day
            and (check_date.year, check_date.month) > (last.year, last.month)
        )
    if freq == Frequency.QUARTERLY:
        months = (check_date.year - last.year) * 12 + check_date.month - last.month
        return months >= 3 and check_date.day >= contrib.start_date.day
    if freq == Frequency.ANNUALLY:
        return (
            check_date.month == contrib.start_date.month
            and check_date.day == contrib.start_date.day
            and check_date.year > last.year
        )
    return False

class _AccountDialog(tk.Toplevel):
    """Modal dialog for creating or editing an account."""

    def __init__(self, parent, app, account: Account | None, on_save) -> None:
        super().__init__(parent)
        self.app = app
        self._account = account
        self._on_save = on_save

        self.title("Edit Account" if account else "New Account")
        self.resizable(False, False)
        self.configure(bg=th.BG_PANEL)
        self.grab_set()

        self._build()
        if account:
            self._populate(account)

    def _build(self) -> None:
        pad = {"padx": 16, "pady": 6}

        tk.Label(self, text="Account Name", font=th.FONT_BODY,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).grid(row=0, column=0, sticky="w", **pad)
        self._name_var = tk.StringVar()
        ttk.Entry(self, textvariable=self._name_var, width=30).grid(row=0, column=1, **pad)

        tk.Label(self, text="Type", font=th.FONT_BODY,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).grid(row=1, column=0, sticky="w", **pad)
        self._type_var = tk.StringVar(value=AccountType.BROKERAGE.value)
        ttk.Combobox(self, textvariable=self._type_var,
                     values=[t.value for t in AccountType],
                     state="readonly", width=28).grid(row=1, column=1, **pad)

        tk.Label(self, text="Institution", font=th.FONT_BODY,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).grid(row=2, column=0, sticky="w", **pad)
        self._inst_var = tk.StringVar()
        ttk.Entry(self, textvariable=self._inst_var, width=30).grid(row=2, column=1, **pad)

        tk.Label(self, text="Notes", font=th.FONT_BODY,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).grid(row=3, column=0, sticky="w", **pad)
        self._notes = tk.Text(self, width=30, height=3, bg=th.BG_ENTRY,
                              fg=th.FG_PRIMARY, insertbackground=th.FG_PRIMARY,
                              relief="flat", font=th.FONT_BODY)
        self._notes.grid(row=3, column=1, **pad)

        btn_row = tk.Frame(self, bg=th.BG_PANEL)
        btn_row.grid(row=4, column=0, columnspan=2, pady=12)
        ttk.Button(btn_row, text="Save", style="Primary.TButton",
                   command=self._save).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="left", padx=6)

    def _populate(self, acct: Account) -> None:
        self._name_var.set(acct.name)
        self._type_var.set(acct.account_type.value)
        self._inst_var.set(acct.institution or "")
        self._notes.insert("1.0", acct.notes or "")

    def _save(self) -> None:
        name = self._name_var.get().strip()
        if not name:
            mb.showwarning("Validation", "Account name is required.", parent=self)
            return
        acct_type = AccountType(self._type_var.get())
        institution = self._inst_var.get().strip()
        notes = self._notes.get("1.0", "end-1c")

        with get_session() as session:
            if self._account:
                acct = session.query(Account).get(self._account.id)
                acct.name = name
                acct.account_type = acct_type
                acct.institution = institution
                acct.notes = notes
            else:
                session.add(Account(
                    name=name, account_type=acct_type,
                    institution=institution, notes=notes,
                ))
        self._on_save()
        self.destroy()


# ---------------------------------------------------------------------------
# Holding dialog (add / edit)
# ---------------------------------------------------------------------------

class _HoldingDialog(tk.Toplevel):
    """Modal dialog for adding or editing a holding."""

    def __init__(self, parent, account_id: int, asset: Asset | None, on_save) -> None:
        super().__init__(parent)
        self._account_id = account_id
        self._asset = asset
        self._on_save = on_save
        self._lookup_thread: threading.Thread | None = None

        self.title("Edit Holding" if asset else "Add Holding")
        self.resizable(False, False)
        self.configure(bg=th.BG_PANEL)
        self.grab_set()
        self._build()
        if asset:
            self._populate(asset)

    def _build(self) -> None:
        pad = {"padx": 16, "pady": 5}

        # Ticker row with lookup button
        tk.Label(self, text="Ticker", bg=th.BG_PANEL, fg=th.FG_SECONDARY,
                 font=th.FONT_BODY).grid(row=0, column=0, sticky="w", **pad)
        self._ticker_var = tk.StringVar()
        ttk.Entry(self, textvariable=self._ticker_var, width=14).grid(row=0, column=1, sticky="w", **pad)
        self._lookup_btn = ttk.Button(self, text="🔍 Lookup", command=self._lookup_ticker)
        self._lookup_btn.grid(row=0, column=2, padx=8, pady=5)
        self._lookup_status = tk.Label(self, text="", bg=th.BG_PANEL, fg=th.FG_SECONDARY, font=th.FONT_SMALL)
        self._lookup_status.grid(row=0, column=3, padx=4)

        fields = [
            ("Name",                    "_name_var",     1, tk.StringVar),
            ("Asset Class",             "_class_var",    2, None),
            ("Shares",                  "_shares_var",   3, tk.StringVar),
            ("Cost Basis ($)",          "_cost_var",     4, tk.StringVar),
            ("Last Price ($)",          "_price_var",    5, tk.StringVar),
            ("Annual Div Yield (%)",    "_yield_var",    6, tk.StringVar),
            ("Annual Div/Share ($)",    "_dps_var",      7, tk.StringVar),
            ("Div Frequency",           "_freq_var",     8, None),
        ]

        for label, attr, row, var_type in fields:
            tk.Label(self, text=label, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
                     font=th.FONT_BODY).grid(row=row, column=0, sticky="w", **pad)
            if attr == "_class_var":
                self._class_var = tk.StringVar(value="stocks")
                ttk.Combobox(self, textvariable=self._class_var,
                             values=["stocks", "bonds", "reits", "cash"],
                             state="readonly", width=20).grid(row=row, column=1, sticky="w", **pad)
            elif attr == "_freq_var":
                self._freq_var = tk.StringVar(value="Quarterly")
                freq_cb = ttk.Combobox(self, textvariable=self._freq_var,
                             values=[f.value for f in DividendFrequency],
                             state="readonly", width=20)
                freq_cb.grid(row=row, column=1, sticky="w", **pad)
                # When frequency changes, recompute the per-payment preview
                self._freq_var.trace_add("write", lambda *_: self._update_per_payment_label())
            else:
                setattr(self, attr, var_type())
                entry = ttk.Entry(self, textvariable=getattr(self, attr), width=22)
                entry.grid(row=row, column=1, sticky="w", **pad)
                # Recompute preview when DPS or price changes
                if attr in ("_dps_var", "_price_var"):
                    getattr(self, attr).trace_add("write", lambda *_: self._update_per_payment_label())

        # Per-payment preview (read-only derived field)
        tk.Label(self, text="Per-Payment Div/Share",
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY,
                 font=th.FONT_BODY).grid(row=9, column=0, sticky="w", **pad)
        self._per_payment_var = tk.StringVar(value="—")
        tk.Label(self, textvariable=self._per_payment_var,
                 bg=th.BG_PANEL, fg=th.FG_GOLD,
                 font=th.FONT_BODY_BOLD).grid(row=9, column=1, sticky="w", **pad)

        # DRIP checkbox
        self._drip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="DRIP Enabled", variable=self._drip_var).grid(
            row=10, column=1, sticky="w", padx=16, pady=4)

        # Disclaimer: yfinance is end-of-day / 15-min delayed, not real-time
        tk.Label(
            self,
            text="ℹ  Prices are end-of-day / 15-min delayed (yfinance).\n"
                 "   Yield & Annual Div/Share are computed from trailing 12-month history.",
            font=th.FONT_SMALL,
            bg=th.BG_PANEL,
            fg=th.FG_SECONDARY,
            justify="left",
        ).grid(row=11, column=0, columnspan=4, padx=16, pady=(2, 6), sticky="w")

        btn_row = tk.Frame(self, bg=th.BG_PANEL)
        btn_row.grid(row=12, column=0, columnspan=4, pady=12)
        ttk.Button(btn_row, text="Save", style="Primary.TButton",
                   command=self._save).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="left", padx=6)

    def _populate(self, asset: Asset) -> None:
        self._ticker_var.set(asset.ticker)
        self._name_var.set(asset.name)
        self._class_var.set(asset.asset_class)
        self._shares_var.set(str(asset.shares))
        self._cost_var.set(str(asset.cost_basis))
        self._price_var.set(str(asset.last_price))
        self._yield_var.set(str(round(asset.dividend_yield * 100, 4)))
        self._dps_var.set(str(asset.dividend_per_share))
        self._freq_var.set(asset.dividend_frequency.value if asset.dividend_frequency else "Quarterly")
        self._drip_var.set(asset.drip_enabled)
        self._update_per_payment_label()

    def _update_per_payment_label(self) -> None:
        """Recompute and display the per-payment dividend per share."""
        _PAYMENTS = {
            "Weekly": 52, "Monthly": 12, "Quarterly": 4,
            "Semi-Annual": 2, "Annual": 1,
        }
        try:
            annual_dps = float(self._dps_var.get() or 0)
            freq = self._freq_var.get()
            payments = _PAYMENTS.get(freq, 4)
            per_payment = annual_dps / payments if payments else 0.0
            self._per_payment_var.set(f"${per_payment:.4f}  ({freq})")
        except (ValueError, AttributeError):
            # _per_payment_var may not exist yet during widget construction
            pass

    def _lookup_ticker(self) -> None:
        ticker = self._ticker_var.get().strip().upper()
        if not ticker:
            return
        self._lookup_btn.configure(state="disabled")
        self._lookup_status.configure(text="Looking up…", fg=th.FG_SECONDARY)

        def _worker():
            info = get_ticker_info(ticker)
            self.after(0, self._apply_lookup, info)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_lookup(self, info: dict) -> None:
        self._ticker_var.set(self._ticker_var.get().upper())
        self._name_var.set(info.get("name", ""))
        self._class_var.set(info.get("asset_class", "stocks"))
        price = info.get("current_price")
        if price:
            self._price_var.set(f"{price:.4f}")
        # dividend_yield is the TTM decimal (annual_dps / price)
        yld = info.get("dividend_yield", 0.0)
        self._yield_var.set(f"{yld*100:.4f}")
        # dividend_rate is the TTM annual DPS (sum of last 12 months of payments)
        dps = info.get("dividend_rate", 0.0)
        self._dps_var.set(f"{dps:.4f}")
        self._freq_var.set(info.get("dividend_frequency", "Quarterly"))
        self._update_per_payment_label()
        self._lookup_btn.configure(state="normal")
        self._lookup_status.configure(
            text="✓ Done  (TTM yield & price via history)",
            fg=th.FG_SUCCESS,
        )

    def _save(self) -> None:
        ticker = self._ticker_var.get().strip().upper()
        if not ticker:
            mb.showwarning("Validation", "Ticker is required.", parent=self)
            return
        try:
            shares    = float(self._shares_var.get() or 0)
            cost      = float(self._cost_var.get() or 0)
            price     = float(self._price_var.get() or 0)
            yld       = float(self._yield_var.get() or 0) / 100
            dps       = float(self._dps_var.get() or 0)
            freq_str  = self._freq_var.get()
            freq      = DividendFrequency(freq_str) if freq_str else None
        except ValueError as exc:
            mb.showwarning("Validation", f"Invalid numeric value: {exc}", parent=self)
            return

        with get_session() as session:
            if self._asset:
                a = session.query(Asset).get(self._asset.id)
            else:
                a = Asset(account_id=self._account_id)
                session.add(a)

            a.ticker = ticker
            a.name = self._name_var.get().strip()
            a.asset_class = self._class_var.get()
            a.shares = shares
            a.cost_basis = cost
            a.last_price = price
            a.dividend_yield = yld
            a.dividend_per_share = dps
            a.dividend_frequency = freq
            a.drip_enabled = self._drip_var.get()

        self._on_save()
        self.destroy()


# ---------------------------------------------------------------------------
# Recurring investment dialog (add / edit)
# ---------------------------------------------------------------------------

class _RecurringDialog(tk.Toplevel):
    """
    Modal dialog for adding or editing a recurring investment rule.

    A recurring investment ties a dollar amount + frequency to a specific
    asset (ticker) inside an account.  The scheduler will auto-create
    contribution transactions on the due dates.
    """

    _FREQ_OPTIONS = ["Weekly", "Biweekly", "Monthly", "Quarterly", "Annually"]

    def __init__(self, parent, account_id: int, contrib, on_save) -> None:
        super().__init__(parent)
        self._account_id = account_id
        self._contrib    = contrib   # ScheduledContrib | None
        self._on_save    = on_save

        self.title("Edit Recurring Investment" if contrib else "Add Recurring Investment")
        self.resizable(False, False)
        self.configure(bg=th.BG_PANEL)
        self.grab_set()
        self._build()
        if contrib:
            self._populate(contrib)
        else:
            self._update_monthly_preview()

    def _build(self) -> None:
        pad = {"padx": 16, "pady": 6}

        # Ticker selector (populated from account's assets)
        tk.Label(self, text="Ticker / Asset", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=0, column=0, sticky="w", **pad)
        self._ticker_var = tk.StringVar()
        self._ticker_combo = ttk.Combobox(self, textvariable=self._ticker_var,
                                          state="readonly", width=22)
        self._ticker_combo.grid(row=0, column=1, sticky="w", **pad)
        self._load_tickers()

        # Amount per period
        tk.Label(self, text="Amount per Period ($)", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=1, column=0, sticky="w", **pad)
        self._amount_var = tk.StringVar(value="0.00")
        self._amount_var.trace_add("write", lambda *_: self._update_monthly_preview())
        ttk.Entry(self, textvariable=self._amount_var, width=24).grid(row=1, column=1, sticky="w", **pad)

        # Frequency
        tk.Label(self, text="Frequency", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=2, column=0, sticky="w", **pad)
        self._freq_var = tk.StringVar(value="Biweekly")
        self._freq_var.trace_add("write", lambda *_: self._update_monthly_preview())
        ttk.Combobox(self, textvariable=self._freq_var,
                     values=self._FREQ_OPTIONS,
                     state="readonly", width=22).grid(row=2, column=1, sticky="w", **pad)

        # Start date
        tk.Label(self, text="Start Date (YYYY-MM-DD)", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=3, column=0, sticky="w", **pad)
        from datetime import date
        self._start_var = tk.StringVar(value=str(date.today()))
        ttk.Entry(self, textvariable=self._start_var, width=24).grid(row=3, column=1, sticky="w", **pad)

        # End date (optional)
        tk.Label(self, text="End Date (optional)", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=4, column=0, sticky="w", **pad)
        self._end_var = tk.StringVar(value="")
        ttk.Entry(self, textvariable=self._end_var, width=24).grid(row=4, column=1, sticky="w", **pad)

        # Notes
        tk.Label(self, text="Notes", bg=th.BG_PANEL,
                 fg=th.FG_SECONDARY, font=th.FONT_BODY).grid(row=5, column=0, sticky="w", **pad)
        self._notes = tk.Text(self, width=26, height=2, bg=th.BG_ENTRY,
                              fg=th.FG_PRIMARY, insertbackground=th.FG_PRIMARY,
                              relief="flat", font=th.FONT_BODY)
        self._notes.grid(row=5, column=1, **pad)

        # Monthly equivalent preview
        tk.Frame(self, bg=th.BORDER, height=1).grid(row=6, column=0, columnspan=2,
                                                     sticky="ew", padx=16, pady=4)
        self._preview_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self._preview_var,
                 bg=th.BG_PANEL, fg=th.FG_GOLD,
                 font=th.FONT_BODY_BOLD).grid(row=7, column=0, columnspan=2, pady=4)

        btn_row = tk.Frame(self, bg=th.BG_PANEL)
        btn_row.grid(row=8, column=0, columnspan=2, pady=12)
        ttk.Button(btn_row, text="Save", style="Primary.TButton",
                   command=self._save).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="left", padx=6)

    def _load_tickers(self) -> None:
        """Populate ticker dropdown from the account's holdings."""
        with get_session() as session:
            assets = session.query(Asset).filter(Asset.account_id == self._account_id).all()
            tickers = [a.ticker for a in assets]
        self._ticker_combo["values"] = tickers
        if tickers:
            self._ticker_var.set(tickers[0])
        # Map ticker → asset_id
        with get_session() as session:
            self._ticker_to_id = {
                a.ticker: a.id
                for a in session.query(Asset).filter(Asset.account_id == self._account_id).all()
            }

    _MONTHLY_FACTORS = {
        "Weekly": 52 / 12, "Biweekly": 26 / 12, "Monthly": 1.0,
        "Quarterly": 1 / 3, "Annually": 1 / 12,
    }

    def _update_monthly_preview(self) -> None:
        try:
            amount = float(self._amount_var.get() or 0)
            freq   = self._freq_var.get()
            factor = self._MONTHLY_FACTORS.get(freq, 1.0)
            monthly = amount * factor
            annual  = monthly * 12
            self._preview_var.set(
                f"≈ ${monthly:.2f}/month  •  ${annual:.2f}/year"
            )
        except (ValueError, AttributeError):
            pass

    def _populate(self, contrib) -> None:
        if contrib.asset_id:
            with get_session() as session:
                asset = session.query(Asset).get(contrib.asset_id)
                if asset:
                    self._ticker_var.set(asset.ticker)
        self._amount_var.set(str(contrib.amount))
        self._freq_var.set(contrib.frequency.value)
        self._start_var.set(str(contrib.start_date))
        self._end_var.set(str(contrib.end_date) if contrib.end_date else "")
        self._notes.insert("1.0", contrib.notes or "")
        self._update_monthly_preview()

    def _save(self) -> None:
        from datetime import datetime
        from db.models import Frequency, ScheduledContrib

        try:
            amount = float(self._amount_var.get() or 0)
            if amount <= 0:
                raise ValueError("Amount must be > 0")
        except ValueError as exc:
            mb.showwarning("Validation", str(exc), parent=self)
            return

        try:
            start = datetime.strptime(self._start_var.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            mb.showwarning("Validation", "Start date must be YYYY-MM-DD.", parent=self)
            return

        end = None
        if self._end_var.get().strip():
            try:
                end = datetime.strptime(self._end_var.get().strip(), "%Y-%m-%d").date()
            except ValueError:
                mb.showwarning("Validation", "End date must be YYYY-MM-DD or blank.", parent=self)
                return

        freq_str = self._freq_var.get()
        try:
            freq = Frequency(freq_str)
        except ValueError:
            mb.showwarning("Validation", f"Unknown frequency: {freq_str}", parent=self)
            return

        ticker   = self._ticker_var.get()
        asset_id = self._ticker_to_id.get(ticker) if ticker else None
        notes    = self._notes.get("1.0", "end-1c")

        with get_session() as session:
            if self._contrib:
                r = session.query(ScheduledContrib).get(self._contrib.id)
            else:
                r = ScheduledContrib(account_id=self._account_id)
                session.add(r)

            r.asset_id  = asset_id
            r.amount    = amount
            r.frequency = freq
            r.start_date = start
            r.end_date   = end
            r.notes      = notes
            r.is_active  = True

        self._on_save()
        self.destroy()

