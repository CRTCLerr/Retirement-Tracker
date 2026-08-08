"""
gui/frames/dividends.py
=======================
Dividend & DRIP frame.

Shows:
- Upcoming dividend calendar (next 3 months).
- Monthly income bar chart (actual YTD vs projected).
- DRIP activity log.
- Manual dividend processing button.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.messagebox as mb
from datetime import date
from tkinter import ttk

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from db.database import get_session
from db.models import Account, Asset, Transaction, TransactionType
from gui import theme as th
from services.dividend_engine import (
    build_dividend_calendar,
    get_dividend_income_summary,
    process_dividends,
)


class DividendsFrame(ttk.Frame):
    """Dividend calendar, DRIP tracking, and income chart frame."""

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
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        # Header
        header = tk.Frame(self, bg=th.BG_DARK)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(20, 12))
        tk.Label(header, text="Dividends & DRIP",
                 font=th.FONT_H1, bg=th.BG_DARK, fg=th.FG_PRIMARY).pack(side="left")
        ttk.Button(header, text="⚡ Process Dividends Now",
                   style="Primary.TButton",
                   command=self._process_dividends).pack(side="right")
        ttk.Button(header, text="⚡ Force Process (override guard)",
                   command=lambda: self._process_dividends(force=True)).pack(side="right", padx=(0, 8))

        # Left top: upcoming calendar
        cal_panel = tk.Frame(self, bg=th.BG_PANEL)
        cal_panel.grid(row=1, column=0, sticky="nsew", padx=(24, 8), pady=(0, 12))
        cal_panel.columnconfigure(0, weight=1)
        cal_panel.rowconfigure(1, weight=1)

        tk.Label(cal_panel, text="📅 Upcoming Dividends (3 months)",
                 font=th.FONT_H3, bg=th.BG_PANEL, fg=th.FG_PRIMARY).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")

        cal_cols = ("date", "ticker", "account", "shares", "per_share", "estimated", "drip", "source")
        self._cal_tree = ttk.Treeview(cal_panel, columns=cal_cols,
                                      show="headings", selectmode="none")
        hdefs = [
            ("date",      "Date",      85, "w"),
            ("ticker",    "Ticker",    65, "w"),
            ("account",   "Account",  120, "w"),
            ("shares",    "Shares",    75, "e"),
            ("per_share", "$/Share",   65, "e"),
            ("estimated", "Est. $",    80, "e"),
            ("drip",      "DRIP",      45, "center"),
            ("source",    "Source",    65, "center"),
        ]
        for col, label, width, anchor in hdefs:
            self._cal_tree.heading(col, text=label)
            self._cal_tree.column(col, width=width, anchor=anchor)
        self._cal_tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        sb = ttk.Scrollbar(cal_panel, orient="vertical", command=self._cal_tree.yview)
        self._cal_tree.configure(yscrollcommand=sb.set)
        sb.grid(row=1, column=1, sticky="ns", pady=(0, 8))

        # Right top: income chart
        chart_panel = tk.Frame(self, bg=th.BG_PANEL)
        chart_panel.grid(row=1, column=1, sticky="nsew", padx=(0, 24), pady=(0, 12))
        chart_panel.columnconfigure(0, weight=1)
        chart_panel.rowconfigure(1, weight=1)

        tk.Label(chart_panel, text=f"📊 Monthly Dividend Income ({date.today().year})",
                 font=th.FONT_H3, bg=th.BG_PANEL, fg=th.FG_PRIMARY).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")

        self._chart_frame = tk.Frame(chart_panel, bg=th.BG_PANEL)
        self._chart_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._chart_canvas: FigureCanvasTkAgg | None = None

        # Bottom: DRIP activity log
        drip_panel = tk.Frame(self, bg=th.BG_PANEL)
        drip_panel.grid(row=2, column=0, columnspan=2, sticky="nsew",
                        padx=24, pady=(0, 24))
        drip_panel.columnconfigure(0, weight=1)
        drip_panel.rowconfigure(1, weight=1)

        tk.Label(drip_panel, text="🔄 DRIP Activity",
                 font=th.FONT_H3, bg=th.BG_PANEL, fg=th.FG_PRIMARY).grid(
            row=0, column=0, padx=12, pady=8, sticky="w")

        drip_cols = ("date", "ticker", "account", "amount", "shares", "price")
        self._drip_tree = ttk.Treeview(drip_panel, columns=drip_cols,
                                       show="headings", selectmode="none",
                                       height=6)
        dhdefs = [
            ("date",    "Date",      90, "w"),
            ("ticker",  "Ticker",    70, "w"),
            ("account", "Account",  140, "w"),
            ("amount",  "Amount",    90, "e"),
            ("shares",  "Shares",    90, "e"),
            ("price",   "Price",     75, "e"),
        ]
        for col, label, width, anchor in dhdefs:
            self._drip_tree.heading(col, text=label)
            self._drip_tree.column(col, width=width, anchor=anchor)
        self._drip_tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        sb2 = ttk.Scrollbar(drip_panel, orient="vertical", command=self._drip_tree.yview)
        self._drip_tree.configure(yscrollcommand=sb2.set)
        sb2.grid(row=1, column=1, sticky="ns", pady=(0, 8))

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload all dividend data."""
        self._load_calendar()
        self._draw_income_chart()
        self._load_drip_log()

    def _load_calendar(self) -> None:
        self._cal_tree.delete(*self._cal_tree.get_children())
        with get_session() as session:
            events = build_dividend_calendar(session, months_ahead=3)

        for ev in events:
            tag = "real" if ev.get("source") == "real" else "est"
            self._cal_tree.insert("", "end", tags=(tag,), values=(
                str(ev["date"]),
                ev["ticker"],
                ev["account_name"],
                f"{ev['shares']:.4f}",
                f"${ev['div_per_share']:.4f}",
                f"${ev['estimated_amount']:.2f}",
                "✓" if ev["drip"] else "–",
                ev.get("source", "estimated"),
            ))
        self._cal_tree.tag_configure("real", foreground=th.FG_SUCCESS)
        self._cal_tree.tag_configure("est",  foreground=th.FG_SECONDARY)

    def _draw_income_chart(self) -> None:
        if self._chart_canvas:
            self._chart_canvas.get_tk_widget().destroy()
            plt.close("all")

        year = date.today().year
        with get_session() as session:
            monthly = get_dividend_income_summary(session, year)

        months = list(range(1, 13))
        values = [monthly.get(m, 0.0) for m in months]
        labels = ["Jan","Feb","Mar","Apr","May","Jun",
                  "Jul","Aug","Sep","Oct","Nov","Dec"]

        fig, ax = plt.subplots(figsize=(5.5, 3.2), facecolor=th.BG_PANEL)
        ax.set_facecolor(th.BG_PANEL)

        bar_colors = [
            th.FG_ACCENT if v > 0 else th.BORDER for v in values
        ]
        bars = ax.bar(labels, values, color=bar_colors, edgecolor=th.BG_PANEL, linewidth=0.5)

        # Annotate non-zero bars
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(values) * 0.02,
                    f"${val:.0f}",
                    ha="center", va="bottom",
                    color=th.FG_SECONDARY, fontsize=7,
                )

        ax.set_xlabel("Month", color=th.FG_SECONDARY, fontsize=8)
        ax.set_ylabel("Income ($)", color=th.FG_SECONDARY, fontsize=8)
        ax.set_title(f"{year} Dividend Income by Month",
                     color=th.FG_PRIMARY, fontsize=9, pad=6)
        ax.tick_params(colors=th.FG_SECONDARY, labelsize=7)
        ax.spines[:].set_color(th.BORDER)
        ax.grid(axis="y", color=th.CHART_GRID, linewidth=0.5, alpha=0.7)

        fig.tight_layout(pad=1.0)

        canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._chart_canvas = canvas

    def _load_drip_log(self) -> None:
        self._drip_tree.delete(*self._drip_tree.get_children())
        with get_session() as session:
            txns = (
                session.query(Transaction)
                .filter(Transaction.transaction_type == TransactionType.DRIP)
                .order_by(Transaction.transaction_date.desc())
                .limit(200)
                .all()
            )
            for tx in txns:
                ticker = tx.asset.ticker if tx.asset else "–"
                acct   = tx.account.name if tx.account else "–"
                self._drip_tree.insert("", "end", values=(
                    str(tx.transaction_date),
                    ticker,
                    acct,
                    f"${tx.amount:.2f}",
                    f"{tx.shares:.6f}",
                    f"${tx.price_per_share:.4f}" if tx.price_per_share else "–",
                ))

    # ------------------------------------------------------------------
    # Manual dividend processing
    # ------------------------------------------------------------------

    def _process_dividends(self, force: bool = False) -> None:
        """Manually trigger dividend + DRIP processing for all holdings."""
        label = "force-process" if force else "process"
        if not mb.askyesno(
            "Process Dividends",
            f"{'Force-process' if force else 'Process'} dividends for all eligible holdings today?\n\n"
            "DRIP-enabled holdings will have shares reinvested automatically.\n"
            + ("" if force else "\nHoldings already paid this period will be skipped."),
        ):
            return

        processed = 0
        skipped   = 0
        errors: list[str] = []

        with get_session() as session:
            assets: list[Asset] = (
                session.query(Asset)
                .join(Account)
                .filter(Account.is_active == True, Asset.shares > 0,
                        Asset.dividend_per_share > 0)
                .all()
            )
            for asset in assets:
                try:
                    tx = process_dividends(session, asset, force=force)
                    if tx:
                        processed += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    errors.append(f"{asset.ticker}: {exc}")

        parts = [f"Processed: {processed} holding(s)."]
        if skipped:
            parts.append(f"Skipped (already paid this period): {skipped}.")
        if errors:
            parts.append("\nErrors:\n" + "\n".join(errors))
        mb.showinfo("Dividend Processing", "\n".join(parts))
        self.refresh()
