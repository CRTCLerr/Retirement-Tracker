"""
gui/frames/dashboard.py
========================
The dashboard frame — the first screen the user sees.

Displays:
- Total net worth (headline metric)
- Per-account balance cards
- Asset allocation donut chart
- YTD contributions and dividend income
- Quick price-refresh button
"""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.messagebox as mb
from tkinter import ttk

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from db.database import get_session
from gui import theme as th
from services.portfolio import (
    get_account_balances,
    get_asset_allocation,
    get_net_worth,
    get_total_contributions_ytd,
    get_total_dividends_ytd,
    refresh_prices,
)


class DashboardFrame(ttk.Frame):
    """
    Dashboard overview frame.

    Shows headline portfolio metrics, per-account balances, an allocation
    donut chart, and YTD summaries.
    """

    def __init__(self, parent: tk.Widget, app, **kwargs) -> None:
        super().__init__(parent, style="TFrame", **kwargs)
        self.app = app
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Construct all child widgets."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)

        # ------ Header bar ------------------------------------------
        header = tk.Frame(self, bg=th.BG_DARK)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 0))

        tk.Label(
            header, text="Portfolio Dashboard",
            font=th.FONT_H1, bg=th.BG_DARK, fg=th.FG_PRIMARY,
        ).pack(side="left")

        self._refresh_btn = ttk.Button(
            header, text="⟳  Refresh Prices", style="Primary.TButton",
            command=self._refresh_prices_async,
        )
        self._refresh_btn.pack(side="right")

        # ------ Top metric cards ------------------------------------
        top = tk.Frame(self, bg=th.BG_DARK)
        top.grid(row=1, column=0, sticky="ew", padx=24, pady=16)
        top.columnconfigure((0, 1, 2, 3, 4), weight=1)

        self._net_worth_var  = tk.StringVar(value="$0.00")
        self._day_chg_var    = tk.StringVar(value="–")
        self._month_chg_var  = tk.StringVar(value="–")
        self._contrib_var    = tk.StringVar(value="$0.00")
        self._div_var        = tk.StringVar(value="$0.00")

        self._make_metric_card(top, 0, "💼 Net Worth",          self._net_worth_var, th.FG_ACCENT)
        self._make_metric_card(top, 1, "📅 Today's Change",     self._day_chg_var,   th.FG_PRIMARY)
        self._make_metric_card(top, 2, "📆 30-Day Change",      self._month_chg_var, th.FG_PRIMARY)
        self._make_metric_card(top, 3, "📥 Contributions YTD",  self._contrib_var,   th.FG_SUCCESS)
        self._make_metric_card(top, 4, "💰 Dividends YTD",      self._div_var,       th.FG_GOLD)

        self._day_chg_label   = top.winfo_children()[1].winfo_children()[1]
        self._month_chg_label = top.winfo_children()[2].winfo_children()[1]

        # ------ Middle body: accounts + allocation chart ------------
        body = tk.Frame(self, bg=th.BG_DARK)
        body.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        acct_panel = tk.Frame(body, bg=th.BG_PANEL)
        acct_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tk.Label(acct_panel, text="Accounts",
                 font=th.FONT_H3, bg=th.BG_PANEL, fg=th.FG_PRIMARY,
                 ).pack(anchor="w", padx=16, pady=(12, 6))
        ttk.Separator(acct_panel, orient="horizontal").pack(fill="x", padx=16)
        self._acct_scroll_frame = tk.Frame(acct_panel, bg=th.BG_PANEL)
        self._acct_scroll_frame.pack(fill="both", expand=True, padx=8, pady=8)

        chart_panel = tk.Frame(body, bg=th.BG_PANEL, width=320)
        chart_panel.grid(row=0, column=1, sticky="nsew")
        chart_panel.grid_propagate(False)
        tk.Label(chart_panel, text="Asset Allocation",
                 font=th.FONT_H3, bg=th.BG_PANEL, fg=th.FG_PRIMARY,
                 ).pack(anchor="w", padx=16, pady=(12, 4))
        self._chart_frame = tk.Frame(chart_panel, bg=th.BG_PANEL)
        self._chart_frame.pack(fill="both", expand=True)
        self._chart_canvas: FigureCanvasTkAgg | None = None

        # ------ Bottom: portfolio history chart ---------------------
        hist_panel = tk.Frame(self, bg=th.BG_PANEL)
        hist_panel.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 16))
        hist_panel.columnconfigure(0, weight=1)
        hist_panel.rowconfigure(1, weight=1)

        hist_header = tk.Frame(hist_panel, bg=th.BG_PANEL)
        hist_header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        tk.Label(hist_header, text="📈 Portfolio Value History",
                 font=th.FONT_H3, bg=th.BG_PANEL, fg=th.FG_PRIMARY).pack(side="left", padx=8)

        # Period selector buttons
        self._hist_period = tk.StringVar(value="30d")
        for label, val in [("30 Days", "30d"), ("1 Year", "1y"), ("All Time", "all")]:
            ttk.Radiobutton(
                hist_header, text=label, variable=self._hist_period, value=val,
                command=self._draw_history_chart,
            ).pack(side="left", padx=4)

        tk.Label(hist_header,
                 text="ℹ️  Based on daily snapshots recorded each time the app opens",
                 font=th.FONT_SMALL, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
                 ).pack(side="right", padx=12)

        self._hist_frame = tk.Frame(hist_panel, bg=th.BG_PANEL)
        self._hist_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self._hist_canvas: FigureCanvasTkAgg | None = None

    def _make_metric_card(
        self,
        parent: tk.Frame,
        col: int,
        label: str,
        var: tk.StringVar,
        value_color: str,
    ) -> None:
        """Build a single top metric card."""
        card = tk.Frame(parent, bg=th.BG_PANEL, bd=0)
        card.grid(row=0, column=col, sticky="ew", padx=(0, 12) if col < 3 else 0, pady=4)

        tk.Label(
            card, text=label,
            font=th.FONT_SMALL, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
        ).pack(anchor="w", padx=16, pady=(12, 2))

        tk.Label(
            card, textvariable=var,
            font=(th.FONT_FAMILY, 20, "bold"), bg=th.BG_PANEL, fg=value_color,
        ).pack(anchor="w", padx=16, pady=(0, 12))

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload all dashboard data from the database (no live price call)."""
        try:
            with get_session() as session:
                net_worth  = get_net_worth(session)
                accounts   = get_account_balances(session)
                allocation = get_asset_allocation(session)
                contrib    = get_total_contributions_ytd(session)
                dividends  = get_total_dividends_ytd(session)

            self._net_worth_var.set(f"${net_worth:,.2f}")
            self._contrib_var.set(f"${contrib:,.2f}")
            self._div_var.set(f"${dividends:,.2f}")
            self._populate_accounts(accounts)
            self._draw_allocation_chart(allocation)
            self._draw_history_chart()

        except Exception as exc:
            mb.showerror("Dashboard Error", str(exc))

    def _populate_accounts(self, accounts: list[dict], changes: dict | None = None) -> None:
        """
        Rebuild the per-account balance list.

        Parameters
        ----------
        changes : dict, optional
            Ticker → price-change dict from :func:`~services.market.get_price_changes`.
            When provided, shows day-change per account.
        """
        for widget in self._acct_scroll_frame.winfo_children():
            widget.destroy()

        if not accounts:
            tk.Label(
                self._acct_scroll_frame, text="No accounts yet. Add one in Accounts.",
                font=th.FONT_BODY, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
            ).pack(pady=24)
            return

        for acct in accounts:
            row = tk.Frame(self._acct_scroll_frame, bg=th.BG_PANEL)
            row.pack(fill="x", padx=8, pady=3)

            tk.Label(
                row, text=f"🏦 {acct['name']}",
                font=th.FONT_BODY_BOLD, bg=th.BG_PANEL, fg=th.FG_PRIMARY,
            ).pack(side="left")

            tk.Label(
                row, text=acct["type"],
                font=th.FONT_SMALL, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
            ).pack(side="left", padx=8)

            tk.Label(
                row, text=f"${acct['balance']:,.2f}",
                font=th.FONT_BODY_BOLD, bg=th.BG_PANEL, fg=th.FG_PRIMARY,
            ).pack(side="right")

            tk.Frame(self._acct_scroll_frame, bg=th.BORDER, height=1).pack(
                fill="x", padx=8
            )

    def _draw_allocation_chart(self, allocation: dict[str, float]) -> None:
        """Draw / redraw the donut allocation chart."""
        if self._chart_canvas:
            self._chart_canvas.get_tk_widget().destroy()
            plt.close("all")

        if not allocation:
            tk.Label(
                self._chart_frame, text="No holdings data",
                font=th.FONT_BODY, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
            ).pack(expand=True)
            return

        _COLORS = {
            "stocks": th.CHART_LINE1,
            "bonds":  th.FG_SUCCESS,
            "reits":  th.FG_GOLD,
            "cash":   th.FG_SECONDARY,
        }
        labels  = list(allocation.keys())
        sizes   = list(allocation.values())
        colors  = [_COLORS.get(lbl, "#888888") for lbl in labels]

        fig, ax = plt.subplots(figsize=(3.2, 3.2), facecolor=th.BG_PANEL)
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=labels,
            colors=colors,
            autopct="%1.1f%%",
            startangle=90,
            pctdistance=0.78,
            wedgeprops={"linewidth": 2, "edgecolor": th.BG_PANEL},
        )
        for t in texts:
            t.set_color(th.FG_SECONDARY)
            t.set_fontsize(8)
        for at in autotexts:
            at.set_color(th.FG_PRIMARY)
            at.set_fontsize(8)

        # Donut hole
        centre_circle = plt.Circle((0, 0), 0.55, fc=th.BG_PANEL)
        ax.add_patch(centre_circle)
        ax.set_aspect("equal")

        fig.tight_layout(pad=0.5)

        canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._chart_canvas = canvas

    # ------------------------------------------------------------------
    # Async price refresh
    # ------------------------------------------------------------------

    def _refresh_prices_async(self) -> None:
        """
        Fetch live prices and day/30-day change metrics on a background thread.

        1. Updates cached ``last_price`` on all assets in the DB.
        2. Pulls day-change and 30-day change for every ticker.
        3. Updates the Today's Change and 30-Day Change metric cards.
        """
        self._refresh_btn.configure(state="disabled", text="Refreshing…")

        def _worker():
            try:
                from services.market import get_price_changes
                from db.models import Asset, Account as _Account

                # Update stored prices
                with get_session() as session:
                    count = refresh_prices(session)

                # Fetch change metrics for all active tickers
                with get_session() as session:
                    assets = (
                        session.query(Asset)
                        .join(_Account)
                        .filter(_Account.is_active == True, Asset.shares > 0)
                        .all()
                    )
                    tickers  = list({a.ticker for a in assets})
                    shares_map = {a.ticker: a.shares for a in assets}

                changes = get_price_changes(tickers)

                # Aggregate portfolio-level day $ and 30d %
                total_day_usd  = 0.0
                total_prev_val = 0.0
                total_30d_prev = 0.0
                total_cur_val  = 0.0

                for ticker, ch in changes.items():
                    shares = shares_map.get(ticker, 0.0)
                    if ch.get("day_change") is not None:
                        total_day_usd  += ch["day_change"] * shares
                    if ch.get("prev_close") is not None:
                        total_prev_val += ch["prev_close"] * shares
                    if ch.get("price") is not None:
                        total_cur_val  += ch["price"] * shares
                    if ch.get("price_30d_ago") is not None:
                        total_30d_prev += ch["price_30d_ago"] * shares

                day_pct  = (total_day_usd / total_prev_val * 100) if total_prev_val else None
                chg_30d  = ((total_cur_val - total_30d_prev) / total_30d_prev * 100) if total_30d_prev else None

                self.after(0, self._on_refresh_done, count, total_day_usd, day_pct, chg_30d)
            except Exception as exc:
                self.after(0, lambda e=exc: mb.showerror("Refresh Error", str(e)))
                self.after(0, self._reset_refresh_btn)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_refresh_done(
        self,
        count: int,
        day_usd: float,
        day_pct: float | None,
        chg_30d: float | None,
    ) -> None:
        self.app.set_status(f"Prices updated for {count} asset(s)")
        self._reset_refresh_btn()

        # Update Today's Change card
        if day_pct is not None:
            sign = "+" if day_usd >= 0 else ""
            color = th.FG_SUCCESS if day_usd >= 0 else th.FG_DANGER
            self._day_chg_var.set(f"{sign}${day_usd:,.2f}  ({sign}{day_pct:.2f}%)")
        else:
            color = th.FG_SECONDARY
            self._day_chg_var.set("–")

        # Update 30-Day Change card
        if chg_30d is not None:
            sign30 = "+" if chg_30d >= 0 else ""
            color30 = th.FG_SUCCESS if chg_30d >= 0 else th.FG_DANGER
            self._month_chg_var.set(f"{sign30}{chg_30d:.2f}%")
        else:
            color30 = th.FG_SECONDARY
            self._month_chg_var.set("–")

        # Re-colour the value labels dynamically
        try:
            self._day_chg_label.configure(fg=color)
            self._month_chg_label.configure(fg=color30)
        except Exception:
            pass

        self.refresh()

    def _draw_history_chart(self) -> None:
        """Draw portfolio value history chart for the selected period."""
        if self._hist_canvas:
            self._hist_canvas.get_tk_widget().destroy()
            plt.close("all")

        period = self._hist_period.get()
        days = {"30d": 30, "1y": 365, "all": 3650}.get(period, 30)

        try:
            from services.portfolio import get_snapshot_history
            with get_session() as session:
                history = get_snapshot_history(session, days=days)
        except Exception:
            history = []

        if not history:
            tk.Label(
                self._hist_frame,
                text="No history yet — snapshots are recorded each time the app opens.",
                font=th.FONT_BODY, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
            ).pack(expand=True, pady=16)
            return

        dates  = [h["date"] for h in history]
        values = [h["total_value"] for h in history]

        fig, ax = plt.subplots(figsize=(9, 2.4), facecolor=th.BG_PANEL)
        ax.set_facecolor(th.BG_PANEL)

        ax.plot(dates, values, color=th.CHART_LINE1, linewidth=1.8, zorder=3)
        ax.fill_between(dates, values, alpha=0.15, color=th.CHART_LINE1)

        # Mark today's value
        ax.scatter([dates[-1]], [values[-1]], color=th.FG_GOLD, s=40, zorder=5)
        ax.annotate(
            f"${values[-1]:,.0f}",
            xy=(dates[-1], values[-1]),
            xytext=(-4, 8), textcoords="offset points",
            color=th.FG_GOLD, fontsize=8, ha="right",
        )

        # Colour the fill green/red based on overall direction
        fill_color = th.FG_SUCCESS if values[-1] >= values[0] else th.FG_DANGER
        ax.fill_between(dates, values, alpha=0.10, color=fill_color)

        ax.tick_params(colors=th.FG_SECONDARY, labelsize=7)
        ax.spines[:].set_color(th.BORDER)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", color=th.CHART_GRID, linewidth=0.5, alpha=0.6)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))

        period_label = {"30d": "Last 30 Days", "1y": "Last 12 Months", "all": "All Time"}.get(period, "")
        ax.set_title(f"Portfolio Value — {period_label}", color=th.FG_PRIMARY, fontsize=9, pad=4)

        fig.tight_layout(pad=0.8)

        canvas = FigureCanvasTkAgg(fig, master=self._hist_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._hist_canvas = canvas

    def _reset_refresh_btn(self) -> None:
        self._refresh_btn.configure(state="normal", text="⟳  Refresh Prices")
