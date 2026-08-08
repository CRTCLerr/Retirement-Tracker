"""
gui/frames/projection.py
========================
Retirement projection frame.

Allows the user to set all projection inputs, run a Monte Carlo simulation,
and view:
- Year-by-year portfolio value chart (median + confidence band).
- Summary metrics (success probability, median value, income estimate).
- A sortable year-by-year data table.
- Saved projection runs.
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
import tkinter.messagebox as mb
from datetime import date
from tkinter import ttk

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config import (
    DEFAULT_INFLATION,
    DEFAULT_WITHDRAWAL_RATE,
    MONTE_CARLO_RUNS,
)
from db.database import get_session
from db.models import ProjectionRun
from gui import theme as th
from services.portfolio import get_net_worth, get_total_dividends_ytd
from services.projection_engine import ProjectionParams, ProjectionResult, run_projection


class ProjectionFrame(ttk.Frame):
    """Monte Carlo retirement projection frame."""

    def __init__(self, parent: tk.Widget, app, **kwargs) -> None:
        super().__init__(parent, style="TFrame", **kwargs)
        self.app = app
        self._result: ProjectionResult | None = None
        self._chart_canvas: FigureCanvasTkAgg | None = None
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=0)   # inputs sidebar
        self.columnconfigure(1, weight=1)   # chart + table
        self.rowconfigure(0, weight=1)

        self._build_inputs_panel()
        self._build_results_panel()

    def _build_inputs_panel(self) -> None:
        """Left panel: projection parameter inputs."""
        panel = tk.Frame(self, bg=th.BG_PANEL, width=300)
        panel.grid(row=0, column=0, sticky="nsew", padx=(24, 8), pady=24)
        panel.grid_propagate(False)

        # Make the panel scrollable so nothing gets cut off
        canvas = tk.Canvas(panel, bg=th.BG_PANEL, highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        self._inputs_inner = tk.Frame(canvas, bg=th.BG_PANEL)
        self._inputs_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self._inputs_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        inner = self._inputs_inner

        tk.Label(inner, text="📈 Projection Inputs",
                 font=th.FONT_H3, bg=th.BG_PANEL, fg=th.FG_PRIMARY).pack(
            anchor="w", padx=16, pady=(16, 8))
        ttk.Separator(inner, orient="horizontal").pack(fill="x", padx=16, pady=(0, 8))

        def _field(label: str, default: str, attr: str) -> tk.StringVar:
            row = tk.Frame(inner, bg=th.BG_PANEL)
            row.pack(fill="x", padx=16, pady=3)
            tk.Label(row, text=label, font=th.FONT_SMALL,
                     bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(anchor="w")
            var = tk.StringVar(value=default)
            ttk.Entry(row, textvariable=var, width=24).pack(fill="x", pady=2)
            setattr(self, attr, var)
            return var

        def _section(title: str) -> None:
            tk.Frame(inner, bg=th.BORDER, height=1).pack(fill="x", padx=16, pady=(10, 4))
            tk.Label(inner, text=title, font=th.FONT_SMALL,
                     bg=th.BG_PANEL, fg=th.FG_ACCENT).pack(anchor="w", padx=16)

        _field("Current Age",                "30",   "_age_var")
        _field("Retirement Age",             "65",   "_ret_age_var")
        _field("Expected Annual Return (%)", "10.0", "_return_var")
        _field("Annual Volatility (%)",      "17.0", "_vol_var")
        _field("Inflation Rate (%)",         f"{DEFAULT_INFLATION*100:.1f}",        "_infl_var")
        _field("Withdrawal Rate (%)",        f"{DEFAULT_WITHDRAWAL_RATE*100:.1f}",  "_wd_var")
        _field("Years in Retirement",        "30",   "_ret_years_var")
        _field("Simulation Runs",            str(MONTE_CARLO_RUNS), "_sims_var")

        # ── Recurring schedule (auto-loaded) ─────────────────────────────
        _section("🔁 Recurring Schedule (auto)")
        contrib_row = tk.Frame(inner, bg=th.BG_PANEL)
        contrib_row.pack(fill="x", padx=16, pady=3)
        self._contrib_var = tk.StringVar(value="$0.00/mo")
        tk.Label(contrib_row, textvariable=self._contrib_var,
                 font=th.FONT_BODY_BOLD, bg=th.BG_PANEL, fg=th.FG_GOLD).pack(side="left")
        ttk.Button(contrib_row, text="⟳",
                   command=self._load_from_portfolio).pack(side="right")
        self._contrib_detail_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._contrib_detail_var,
                 font=th.FONT_SMALL, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
                 justify="left", wraplength=260).pack(anchor="w", padx=16)

        # ── 401k section ──────────────────────────────────────────────────
        _section("🏢 Workplace 401k")

        salary_row = tk.Frame(inner, bg=th.BG_PANEL)
        salary_row.pack(fill="x", padx=16, pady=3)
        tk.Label(salary_row, text="Gross Annual Salary ($)", font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(anchor="w")
        self._salary_var = tk.StringVar(value="68598")
        ttk.Entry(salary_row, textvariable=self._salary_var, width=24).pack(fill="x", pady=2)
        self._salary_var.trace_add("write", lambda *_: self._refresh_401k_preview())

        pct_row = tk.Frame(inner, bg=th.BG_PANEL)
        pct_row.pack(fill="x", padx=16, pady=3)
        tk.Label(pct_row, text="Your Contribution (%)", font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(anchor="w")
        self._k401_pct_var = tk.StringVar(value="6.0")
        ttk.Entry(pct_row, textvariable=self._k401_pct_var, width=24).pack(fill="x", pady=2)
        self._k401_pct_var.trace_add("write", lambda *_: self._refresh_401k_preview())

        match_row = tk.Frame(inner, bg=th.BG_PANEL)
        match_row.pack(fill="x", padx=16, pady=3)
        tk.Label(match_row, text="Employer Match (%)", font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(anchor="w")
        self._match_pct_var = tk.StringVar(value="3.0")
        ttk.Entry(match_row, textvariable=self._match_pct_var, width=24).pack(fill="x", pady=2)
        self._match_pct_var.trace_add("write", lambda *_: self._refresh_401k_preview())

        profit_row = tk.Frame(inner, bg=th.BG_PANEL)
        profit_row.pack(fill="x", padx=16, pady=3)
        tk.Label(profit_row, text="Profit Sharing (%)", font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(anchor="w")
        self._profit_pct_var = tk.StringVar(value="4.0")
        ttk.Entry(profit_row, textvariable=self._profit_pct_var, width=24).pack(fill="x", pady=2)
        self._profit_pct_var.trace_add("write", lambda *_: self._refresh_401k_preview())

        self._k401_preview_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._k401_preview_var,
                 font=th.FONT_SMALL, bg=th.BG_PANEL, fg=th.FG_ACCENT,
                 justify="left", wraplength=260).pack(anchor="w", padx=16, pady=(2, 0))

        # ── Extra one-off ─────────────────────────────────────────────────
        _section("➕ Other Monthly (optional)")
        extra_row = tk.Frame(inner, bg=th.BG_PANEL)
        extra_row.pack(fill="x", padx=16, pady=3)
        tk.Label(extra_row, text="Extra Monthly ($)", font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(anchor="w")
        self._extra_var = tk.StringVar(value="0.00")
        ttk.Entry(extra_row, textvariable=self._extra_var, width=24).pack(fill="x", pady=2)

        # ── Total preview ─────────────────────────────────────────────────
        tk.Frame(inner, bg=th.BORDER, height=1).pack(fill="x", padx=16, pady=(10, 4))
        self._total_preview_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._total_preview_var,
                 font=th.FONT_BODY_BOLD, bg=th.BG_PANEL, fg=th.FG_PRIMARY,
                 justify="left", wraplength=260).pack(anchor="w", padx=16, pady=(0, 4))

        tk.Frame(inner, bg=th.BORDER, height=1).pack(fill="x", padx=16, pady=4)
        ttk.Button(inner, text="▶  Run Projection",
                   style="Primary.TButton",
                   command=self._run_async).pack(padx=16, pady=8, fill="x")

        self._run_status = tk.Label(inner, text="", font=th.FONT_SMALL,
                                    bg=th.BG_PANEL, fg=th.FG_SECONDARY)
        self._run_status.pack(anchor="w", padx=16)

        tk.Frame(inner, bg=th.BORDER, height=1).pack(fill="x", padx=16, pady=8)
        ttk.Button(inner, text="💾 Save This Run",
                   command=self._save_run).pack(padx=16, pady=4, fill="x")
        ttk.Button(inner, text="📋 Load Saved Run",
                   command=self._load_saved_run_dialog).pack(padx=16, pady=4, fill="x")

        # Initial preview
        self._refresh_401k_preview()

    def _build_results_panel(self) -> None:
        """Right panel: chart, summary metrics, and year table."""
        panel = tk.Frame(self, bg=th.BG_DARK)
        panel.grid(row=0, column=1, sticky="nsew", padx=(0, 24), pady=24)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        panel.rowconfigure(3, weight=1)

        # Summary metrics row
        metrics = tk.Frame(panel, bg=th.BG_PANEL)
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        metrics.columnconfigure((0, 1, 2, 3), weight=1)

        self._success_var = tk.StringVar(value="—")
        self._median_var  = tk.StringVar(value="—")
        self._income_var  = tk.StringVar(value="—")
        self._p10_var     = tk.StringVar(value="—")

        def _metric(col, icon_label, var, color):
            f = tk.Frame(metrics, bg=th.BG_PANEL)
            f.grid(row=0, column=col, padx=8, pady=8, sticky="ew")
            tk.Label(f, text=icon_label, font=th.FONT_SMALL,
                     bg=th.BG_PANEL, fg=th.FG_SECONDARY).pack(anchor="w", padx=8)
            tk.Label(f, textvariable=var,
                     font=(th.FONT_FAMILY, 18, "bold"),
                     bg=th.BG_PANEL, fg=color).pack(anchor="w", padx=8)

        _metric(0, "✅ Success Probability", self._success_var, th.FG_SUCCESS)
        _metric(1, "📊 Median at Retirement", self._median_var, th.FG_ACCENT)
        _metric(2, "💵 Annual Income Est.",   self._income_var, th.FG_GOLD)
        _metric(3, "⚠️  Pessimistic (P10)",   self._p10_var,    th.FG_WARNING)

        # Chart
        self._chart_frame = tk.Frame(panel, bg=th.BG_PANEL)
        self._chart_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))

        # Year-by-year table
        table_label = tk.Frame(panel, bg=th.BG_DARK)
        table_label.grid(row=2, column=0, sticky="ew")
        tk.Label(table_label, text="Year-by-Year Projection",
                 font=th.FONT_H3, bg=th.BG_DARK, fg=th.FG_PRIMARY).pack(
            anchor="w", padx=4, pady=(4, 0))

        tbl_frame = tk.Frame(panel, bg=th.BG_PANEL)
        tbl_frame.grid(row=3, column=0, sticky="nsew")
        tbl_frame.columnconfigure(0, weight=1)
        tbl_frame.rowconfigure(0, weight=1)

        tbl_cols = ("age", "value", "contrib", "return_pct", "dividend", "phase")
        self._tbl = ttk.Treeview(tbl_frame, columns=tbl_cols,
                                 show="headings", selectmode="none", height=8)
        thdefs = [
            ("age",        "Age",         50, "center"),
            ("value",      "Portfolio",  110, "e"),
            ("contrib",    "Annual Contrib",100,"e"),
            ("return_pct", "Return %",    70, "e"),
            ("dividend",   "Dividends",   90, "e"),
            ("phase",      "Phase",       80, "center"),
        ]
        for col, label, width, anchor in thdefs:
            self._tbl.heading(col, text=label)
            self._tbl.column(col, width=width, anchor=anchor)
        self._tbl.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        sb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._tbl.yview)
        self._tbl.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns", pady=8)

        self._tbl.tag_configure("retire", foreground=th.FG_GOLD)

    # ------------------------------------------------------------------
    # Auto-fill from portfolio + scheduled contributions
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Load contribution schedule and portfolio value on frame visit."""
        self._load_from_portfolio()

    def _load_from_portfolio(self) -> None:
        """
        Read all active ScheduledContrib rows, compute the monthly total,
        and display it with a per-ticker breakdown.  Also reads net worth
        and YTD dividends for context.
        """
        try:
            from services.portfolio import get_scheduled_contribution_summary
            with get_session() as session:
                net_worth  = get_net_worth(session)
                annual_div = get_total_dividends_ytd(session)
                sched      = get_scheduled_contribution_summary(session)

            monthly = sched["monthly_total"]
            self._contrib_var.set(f"${monthly:.2f}/mo  (${sched['annual_total']:.0f}/yr)")
            self._scheduled_monthly = monthly

            lines = []
            for b in sched["breakdown"]:
                lines.append(
                    f"  {b['ticker']}  {b['frequency']}  ${b['amount']:.2f}"
                    f"  → ${b['monthly_eq']:.2f}/mo"
                )
            self._contrib_detail_var.set(
                "\n".join(lines) if lines else "No recurring investments set up yet."
            )
            self._refresh_401k_preview()
            self.app.set_status(
                f"Portfolio: ${net_worth:,.0f}  •  "
                f"Scheduled: ${monthly:.2f}/mo  •  "
                f"Div YTD: ${annual_div:,.0f}"
            )
        except Exception as exc:
            self._contrib_detail_var.set(f"Could not load schedule: {exc}")

    def _refresh_401k_preview(self) -> None:
        """Recompute 401k dollar amounts whenever salary/% fields change."""
        try:
            salary      = float(self._salary_var.get() or 0)
            emp_pct     = float(self._k401_pct_var.get() or 0) / 100
            match_pct   = float(self._match_pct_var.get() or 0) / 100
            profit_pct  = float(self._profit_pct_var.get() or 0) / 100

            emp_annual    = salary * emp_pct
            match_annual  = salary * match_pct
            profit_annual = salary * profit_pct
            k401_total    = emp_annual + match_annual + profit_annual

            self._k401_preview_var.set(
                f"  You:     ${emp_annual:,.0f}/yr  (${emp_annual/12:.0f}/mo)\n"
                f"  Match:   ${match_annual:,.0f}/yr  (${match_annual/12:.0f}/mo)\n"
                f"  Profit:  ${profit_annual:,.0f}/yr  (${profit_annual/12:.0f}/mo)\n"
                f"  Total:   ${k401_total:,.0f}/yr"
            )

            scheduled = getattr(self, "_scheduled_monthly", 0.0)
            extra     = float(self._extra_var.get() or 0)
            grand     = scheduled + k401_total / 12 + extra
            self._total_preview_var.set(
                f"Grand total: ${grand:,.2f}/mo  (${grand*12:,.0f}/yr)"
            )
        except (ValueError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Run projection
    # ------------------------------------------------------------------

    def _run_async(self) -> None:
        self._run_status.configure(text="Running…", fg=th.FG_SECONDARY)

        def _worker():
            try:
                params = self._parse_params()
                result = run_projection(params)
                self.after(0, self._on_result, result)
            except Exception as exc:
                self.after(0, self._run_status.configure,
                           {"text": f"Error: {exc}", "fg": th.FG_DANGER})

        threading.Thread(target=_worker, daemon=True).start()

    def _parse_params(self) -> ProjectionParams:
        """
        Read and validate all inputs into a :class:`ProjectionParams`.

        Builds itemised :class:`ContributionStream` objects for:
        - Recurring investment schedule (per-ticker biweekly rules)
        - 401k employee contribution
        - 401k employer match
        - 401k profit sharing
        - Any extra monthly override
        """
        from services.portfolio import get_scheduled_contribution_summary
        from services.projection_engine import ContributionStream

        def _f(var): return float(var.get().replace(",", "").replace("$", "").split("/")[0].strip())
        def _i(var): return int(float(var.get()))

        current_age    = _i(self._age_var)
        retirement_age = _i(self._ret_age_var)
        if current_age >= retirement_age:
            raise ValueError("Retirement age must be greater than current age.")

        with get_session() as session:
            portfolio_value = get_net_worth(session)
            annual_div      = get_total_dividends_ytd(session)
            sched           = get_scheduled_contribution_summary(session)

        streams: list[ContributionStream] = []

        # Recurring schedule
        if sched["monthly_total"] > 0:
            streams.append(ContributionStream(
                label="Recurring schedule",
                monthly_amount=sched["monthly_total"],
                account_type="roth",
            ))

        # 401k streams
        try:
            salary     = float(self._salary_var.get() or 0)
            emp_pct    = float(self._k401_pct_var.get() or 0) / 100
            match_pct  = float(self._match_pct_var.get() or 0) / 100
            profit_pct = float(self._profit_pct_var.get() or 0) / 100

            if salary > 0:
                if emp_pct > 0:
                    streams.append(ContributionStream(
                        label="401k (your 6%)",
                        monthly_amount=salary * emp_pct / 12,
                        account_type="roth",
                    ))
                if match_pct > 0:
                    streams.append(ContributionStream(
                        label="401k employer match",
                        monthly_amount=salary * match_pct / 12,
                        account_type="traditional",
                    ))
                if profit_pct > 0:
                    streams.append(ContributionStream(
                        label="401k profit sharing",
                        monthly_amount=salary * profit_pct / 12,
                        account_type="traditional",
                    ))
        except ValueError:
            pass

        # Extra override
        extra = float(self._extra_var.get() or 0)
        if extra > 0:
            streams.append(ContributionStream(
                label="Extra / other",
                monthly_amount=extra,
                account_type="taxable",
            ))

        return ProjectionParams(
            current_age=current_age,
            retirement_age=retirement_age,
            current_portfolio_value=portfolio_value,
            contribution_streams=streams,
            expected_annual_return=_f(self._return_var) / 100,
            annual_volatility=_f(self._vol_var) / 100,
            inflation_rate=_f(self._infl_var) / 100,
            withdrawal_rate=_f(self._wd_var) / 100,
            simulation_runs=_i(self._sims_var),
            years_in_retirement=_i(self._ret_years_var),
            annual_dividend_income=annual_div,
            dividend_growth_rate=_f(self._infl_var) / 100,
        )

    def _on_result(self, result: ProjectionResult) -> None:
        self._result = result
        self._run_status.configure(text="✓ Complete", fg=th.FG_SUCCESS)
        self._update_metrics(result)
        self._draw_chart(result)
        self._populate_table(result)

    # ------------------------------------------------------------------
    # Results display
    # ------------------------------------------------------------------

    def _update_metrics(self, r: ProjectionResult) -> None:
        p = r.params
        years_to_retire = p.retirement_age - p.current_age
        p10_at_retire   = r.mc_p10[years_to_retire] if len(r.mc_p10) > years_to_retire else 0

        sp = r.success_probability
        color = th.FG_SUCCESS if sp >= 0.8 else th.FG_WARNING if sp >= 0.5 else th.FG_DANGER

        self._success_var.set(f"{sp:.1%}")
        self._median_var.set(f"${r.retirement_value_median:,.0f}")
        self._income_var.set(f"${r.annual_income_at_retirement:,.0f}/yr")
        self._p10_var.set(f"${p10_at_retire:,.0f}")

    def _draw_chart(self, r: ProjectionResult) -> None:
        if self._chart_canvas:
            self._chart_canvas.get_tk_widget().destroy()
            plt.close("all")

        p = r.params
        years = list(range(len(r.mc_median)))
        ages  = [p.current_age + y for y in years]
        retire_idx = p.retirement_age - p.current_age

        fig, ax = plt.subplots(figsize=(7, 3.6), facecolor=th.BG_PANEL)
        ax.set_facecolor(th.BG_PANEL)

        # Confidence band (p10 – p90)
        ax.fill_between(ages, r.mc_p10, r.mc_p90,
                        color=th.CHART_FILL, alpha=0.35, label="P10–P90 band")

        # Lines
        ax.plot(ages, r.mc_p90, color=th.CHART_LINE2, linewidth=1, linestyle="--", alpha=0.7, label="P90")
        ax.plot(ages, r.mc_median, color=th.CHART_LINE1, linewidth=2, label="Median")
        ax.plot(ages, r.mc_p10, color=th.CHART_LINE3, linewidth=1, linestyle="--", alpha=0.7, label="P10")

        # Retirement line
        if retire_idx < len(ages):
            ax.axvline(ages[retire_idx], color=th.FG_GOLD, linewidth=1.2,
                       linestyle=":", alpha=0.8, label=f"Retire @ {p.retirement_age}")

        ax.set_xlabel("Age", color=th.FG_SECONDARY, fontsize=9)
        ax.set_ylabel("Portfolio Value ($)", color=th.FG_SECONDARY, fontsize=9)
        ax.set_title(
            f"Monte Carlo Projection  •  {p.simulation_runs:,} runs  •  "
            f"{r.success_probability:.1%} success",
            color=th.FG_PRIMARY, fontsize=9, pad=6,
        )
        ax.tick_params(colors=th.FG_SECONDARY, labelsize=8)
        ax.spines[:].set_color(th.BORDER)
        ax.grid(color=th.CHART_GRID, linewidth=0.5, alpha=0.6)

        # Format y-axis as $M / $K
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M" if x >= 1e6 else f"${x/1e3:.0f}K")
        )

        legend = ax.legend(fontsize=7, facecolor=th.BG_PANEL,
                           edgecolor=th.BORDER, labelcolor=th.FG_SECONDARY)

        fig.tight_layout(pad=1.0)

        canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._chart_canvas = canvas

    def _populate_table(self, r: ProjectionResult) -> None:
        self._tbl.delete(*self._tbl.get_children())
        for snap in r.deterministic:
            tag = "retire" if snap.is_retirement else ""
            phase = "Retirement" if snap.is_retirement else "Accumulation"
            self._tbl.insert("", "end", tags=(tag,), values=(
                snap.age,
                f"${snap.portfolio_value:,.0f}",
                f"${snap.annual_contribution:,.0f}",
                f"{snap.annual_return_pct*100:.1f}%",
                f"${snap.annual_dividend:,.0f}",
                phase,
            ))

    # ------------------------------------------------------------------
    # Save / load runs
    # ------------------------------------------------------------------

    def _save_run(self) -> None:
        if not self._result:
            mb.showinfo("No Result", "Run a projection first.")
            return
        r = self._result
        p = r.params
        years_to_retire = p.retirement_age - p.current_age
        p10_at_retire   = r.mc_p10[years_to_retire] if len(r.mc_p10) > years_to_retire else 0

        with get_session() as session:
            run = ProjectionRun(
                current_age=p.current_age,
                retirement_age=p.retirement_age,
                monthly_contribution=p.monthly_contribution,
                expected_return=p.expected_annual_return,
                volatility=p.annual_volatility,
                inflation=p.inflation_rate,
                withdrawal_rate=p.withdrawal_rate,
                simulation_runs=p.simulation_runs,
                median_value=r.retirement_value_median,
                p10_value=p10_at_retire,
                p90_value=r.mc_p90[years_to_retire] if len(r.mc_p90) > years_to_retire else 0,
                success_probability=r.success_probability,
                result_json=r.to_json(),
                label=f"Run {date.today()}",
            )
            session.add(run)
        mb.showinfo("Saved", "Projection run saved successfully.")

    def _load_saved_run_dialog(self) -> None:
        _SavedRunsDialog(self, on_load=self._load_saved_result)

    def _load_saved_result(self, result: ProjectionResult) -> None:
        self._on_result(result)


# ---------------------------------------------------------------------------
# Saved runs picker dialog
# ---------------------------------------------------------------------------

class _SavedRunsDialog(tk.Toplevel):
    """Dialog to browse and load previously saved projection runs."""

    def __init__(self, parent, on_load) -> None:
        super().__init__(parent)
        self._on_load = on_load
        self.title("Saved Projection Runs")
        self.geometry("600x350")
        self.configure(bg=th.BG_PANEL)
        self.grab_set()
        self._build()
        self._load()

    def _build(self) -> None:
        cols = ("date", "age", "retire_age", "median", "success", "label")
        self._tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        hdefs = [
            ("date",       "Date",         120, "w"),
            ("age",        "Age",           40, "center"),
            ("retire_age", "Retire",        55, "center"),
            ("median",     "Median $",      90, "e"),
            ("success",    "Success",       70, "e"),
            ("label",      "Label",        150, "w"),
        ]
        for col, label, width, anchor in hdefs:
            self._tree.heading(col, text=label)
            self._tree.column(col, width=width, anchor=anchor)
        self._tree.pack(fill="both", expand=True, padx=12, pady=12)

        btn_row = tk.Frame(self, bg=th.BG_PANEL)
        btn_row.pack(pady=8)
        ttk.Button(btn_row, text="Load Selected", style="Primary.TButton",
                   command=self._load_selected).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Close", command=self.destroy).pack(side="left", padx=6)

    def _load(self) -> None:
        with get_session() as session:
            runs = session.query(ProjectionRun).order_by(
                ProjectionRun.run_date.desc()).limit(50).all()
            self._runs = {str(r.id): r.result_json for r in runs}
            for r in runs:
                self._tree.insert("", "end", iid=str(r.id), values=(
                    str(r.run_date)[:19],
                    r.current_age,
                    r.retirement_age,
                    f"${r.median_value:,.0f}",
                    f"{r.success_probability:.1%}",
                    r.label,
                ))

    def _load_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        raw = self._runs.get(sel[0])
        if raw:
            result = ProjectionResult.from_json(raw)
            self._on_load(result)
        self.destroy()
