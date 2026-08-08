"""
services/projection_engine.py
==============================
Retirement projection engine with Monte Carlo simulation.

Public API
----------
run_projection(params)
    Run a full Monte Carlo + deterministic projection.
    Returns a :class:`ProjectionResult` dataclass.

ProjectionParams
    Input dataclass — all tunable assumptions.

ProjectionResult
    Output dataclass — year-by-year data + Monte Carlo percentiles.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    DEFAULT_INFLATION,
    DEFAULT_WITHDRAWAL_RATE,
    MONTE_CARLO_RUNS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input / output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ContributionStream:
    """
    A named cash-flow stream feeding the projection.

    Attributes
    ----------
    label : str
        Human-readable name shown in UI (e.g. ``"Roth IRA schedule"``,
        ``"401k employee"``, ``"401k employer match"``).
    monthly_amount : float
        Monthly equivalent contribution in USD.
    account_type : str
        ``"taxable"``, ``"roth"``, or ``"traditional"`` — used for
        future tax-adjusted modelling (currently informational).
    """
    label: str
    monthly_amount: float
    account_type: str = "roth"


@dataclass
class ProjectionParams:
    """
    All inputs required to run a retirement projection.

    Parameters
    ----------
    current_age : int
    retirement_age : int
    current_portfolio_value : float
        Total current portfolio value in USD.
    monthly_contribution : float
        Legacy single-number monthly contribution.  Ignored when
        ``contribution_streams`` is non-empty.
    contribution_streams : list[ContributionStream]
        Itemised contribution streams (recurring schedule + 401k streams).
        The projection engine sums these automatically.
    expected_annual_return : float
        Mean expected annual return (decimal, e.g. 0.10 for 10 %).
    annual_volatility : float
        Annual return standard deviation (decimal).
    inflation_rate : float
        Annual inflation assumption (decimal, e.g. 0.03).
    withdrawal_rate : float
        Safe withdrawal rate at retirement (decimal, e.g. 0.04).
    simulation_runs : int
        Number of Monte Carlo paths.
    years_in_retirement : int
        How many years to model post-retirement portfolio survival.
    annual_dividend_income : float
        Current annual dividend income (USD).  Compounded forward during
        accumulation at the portfolio's expected return rate and added
        back to portfolio value each year (models DRIP / reinvestment).
    dividend_growth_rate : float
        Annual growth rate for projected dividend income (decimal).
        Defaults to inflation rate assumption.
    one_time_contributions : list[(age, amount)]
        Special one-time deposits at specific ages.
    """

    current_age: int
    retirement_age: int
    current_portfolio_value: float
    monthly_contribution: float = 0.0          # legacy / fallback
    contribution_streams: list = field(default_factory=list)   # list[ContributionStream]
    expected_annual_return: float = 0.10
    annual_volatility: float = 0.17
    inflation_rate: float = DEFAULT_INFLATION
    withdrawal_rate: float = DEFAULT_WITHDRAWAL_RATE
    simulation_runs: int = MONTE_CARLO_RUNS
    years_in_retirement: int = 30
    annual_dividend_income: float = 0.0
    dividend_growth_rate: float = DEFAULT_INFLATION   # default: grow with inflation
    one_time_contributions: list = field(default_factory=list)

    @property
    def total_monthly_contribution(self) -> float:
        """Sum of all contribution streams, or legacy field if no streams defined."""
        if self.contribution_streams:
            return sum(s.monthly_amount for s in self.contribution_streams)
        return self.monthly_contribution


@dataclass
class YearSnapshot:
    """Portfolio state at the end of one calendar year."""
    age: int
    year_index: int          # 0 = current year
    portfolio_value: float
    annual_contribution: float   # total contributions this year
    annual_return_pct: float
    annual_dividend: float       # projected dividend income this year
    is_retirement: bool          # True when age >= retirement_age
    stream_breakdown: dict = field(default_factory=dict)  # label → annual amount


@dataclass
class ProjectionResult:
    """
    Output of :func:`run_projection`.

    Attributes
    ----------
    deterministic : list[YearSnapshot]
        Year-by-year projection using the mean return assumption.
    mc_median : list[float]
        Median portfolio value per year across all Monte Carlo paths.
    mc_p10 : list[float]
        10th-percentile (pessimistic) path.
    mc_p90 : list[float]
        90th-percentile (optimistic) path.
    success_probability : float
        Fraction of MC paths that did not run out of money in retirement.
    retirement_value_median : float
        Median portfolio value at retirement age.
    annual_income_at_retirement : float
        Expected annual safe withdrawal income (median value × withdrawal rate).
    params : ProjectionParams
        The input parameters used.
    """

    deterministic: list[YearSnapshot]
    mc_median: list[float]
    mc_p10: list[float]
    mc_p90: list[float]
    success_probability: float
    retirement_value_median: float
    annual_income_at_retirement: float
    params: ProjectionParams

    def to_json(self) -> str:
        """Serialise to JSON string for storage in :class:`~db.models.ProjectionRun`."""
        data = {
            "params": asdict(self.params),
            "mc_median": self.mc_median,
            "mc_p10": self.mc_p10,
            "mc_p90": self.mc_p90,
            "success_probability": self.success_probability,
            "retirement_value_median": self.retirement_value_median,
            "annual_income_at_retirement": self.annual_income_at_retirement,
            "deterministic": [asdict(s) for s in self.deterministic],
        }
        return json.dumps(data, default=float)

    @classmethod
    def from_json(cls, raw: str) -> "ProjectionResult":
        """Reconstruct a :class:`ProjectionResult` from stored JSON."""
        data = json.loads(raw)
        # Re-hydrate contribution_streams if present
        p = data["params"]
        streams_raw = p.pop("contribution_streams", [])
        params = ProjectionParams(**p)
        params.contribution_streams = [ContributionStream(**s) for s in streams_raw]
        det = [YearSnapshot(**s) for s in data["deterministic"]]
        return cls(
            deterministic=det,
            mc_median=data["mc_median"],
            mc_p10=data["mc_p10"],
            mc_p90=data["mc_p90"],
            success_probability=data["success_probability"],
            retirement_value_median=data["retirement_value_median"],
            annual_income_at_retirement=data["annual_income_at_retirement"],
            params=params,
        )


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def run_projection(params: ProjectionParams) -> ProjectionResult:
    """
    Execute a full retirement projection.

    Algorithm
    ---------
    **Accumulation phase** (current_age → retirement_age):
      * Apply annual return sampled from Normal(μ, σ) for each MC path.
      * Add total annual contributions from all streams.
      * Compound dividend income forward (grows at dividend_growth_rate)
        and add it to the portfolio each year — this models DRIP and
        reinvestment accurately.
      * Add any one-time contributions at the appropriate age.

    **Decumulation phase** (retirement_age → retirement_age + years_in_retirement):
      * Apply annual return.
      * Subtract the annual withdrawal (withdrawal_rate × value at retirement).
      * A path "fails" if value drops to or below zero.

    Parameters
    ----------
    params : ProjectionParams

    Returns
    -------
    ProjectionResult
    """
    rng = np.random.default_rng()

    years_to_retire = params.retirement_age - params.current_age
    total_years     = years_to_retire + params.years_in_retirement

    # -----------------------------------------------------------------------
    # One-time contribution lookup (age → amount)
    # -----------------------------------------------------------------------
    ot_by_age: dict[int, float] = {}
    for age, amount in params.one_time_contributions:
        ot_by_age[age] = ot_by_age.get(age, 0.0) + amount

    # -----------------------------------------------------------------------
    # Annual totals
    # -----------------------------------------------------------------------
    annual_contribution = params.total_monthly_contribution * 12

    # -----------------------------------------------------------------------
    # Monte Carlo simulation
    # Shape: (simulation_runs, total_years + 1)  — column 0 = starting value
    # -----------------------------------------------------------------------
    mc_values = np.zeros((params.simulation_runs, total_years + 1))
    mc_values[:, 0] = params.current_portfolio_value

    # Per-path dividend tracker (starts the same for all paths)
    mc_div = np.full(params.simulation_runs, params.annual_dividend_income)

    for yr in range(total_years):
        age = params.current_age + yr
        in_retirement = age >= params.retirement_age

        returns = rng.normal(
            loc=params.expected_annual_return,
            scale=params.annual_volatility,
            size=params.simulation_runs,
        )

        prev = mc_values[:, yr]

        if not in_retirement:
            ot = ot_by_age.get(age, 0.0)
            # Grow portfolio by return, then add contributions + reinvested dividends
            mc_values[:, yr + 1] = (
                prev * (1.0 + returns)
                + annual_contribution
                + mc_div           # dividend income reinvested each year
                + ot
            )
            # Grow dividend income (DRIP compounds; yield on larger base)
            mc_div = mc_div * (1.0 + params.dividend_growth_rate)
        else:
            retirement_vals  = mc_values[:, years_to_retire]
            fixed_withdrawal = retirement_vals * params.withdrawal_rate
            mc_values[:, yr + 1] = np.maximum(
                prev * (1.0 + returns) - fixed_withdrawal, 0.0
            )

    # Success = paths that never hit zero in retirement
    retirement_slice = mc_values[:, years_to_retire:]
    success_mask     = np.all(retirement_slice > 0, axis=1)
    success_probability = float(success_mask.mean())

    mc_median = np.median(mc_values, axis=0).tolist()
    mc_p10    = np.percentile(mc_values, 10, axis=0).tolist()
    mc_p90    = np.percentile(mc_values, 90, axis=0).tolist()

    # -----------------------------------------------------------------------
    # Deterministic (mean-return) path for the year-by-year table
    # -----------------------------------------------------------------------
    det: list[YearSnapshot] = []
    value = params.current_portfolio_value
    div   = params.annual_dividend_income

    # Build per-stream annual breakdown for display
    stream_breakdown = {s.label: s.monthly_amount * 12 for s in params.contribution_streams}

    for yr in range(total_years + 1):
        age = params.current_age + yr
        in_retirement = age >= params.retirement_age

        snapshot = YearSnapshot(
            age=age,
            year_index=yr,
            portfolio_value=value,
            annual_contribution=annual_contribution if not in_retirement else 0.0,
            annual_return_pct=params.expected_annual_return,
            annual_dividend=div,
            is_retirement=in_retirement,
            stream_breakdown=stream_breakdown if not in_retirement else {},
        )
        det.append(snapshot)

        if yr < total_years:
            ot = ot_by_age.get(age, 0.0)
            if not in_retirement:
                value = (
                    value * (1.0 + params.expected_annual_return)
                    + annual_contribution
                    + div
                    + ot
                )
                div = div * (1.0 + params.dividend_growth_rate)
            else:
                withdrawal = mc_values[0, years_to_retire] * params.withdrawal_rate
                value = max(value * (1.0 + params.expected_annual_return) - withdrawal, 0.0)

    # -----------------------------------------------------------------------
    # Summary statistics
    # -----------------------------------------------------------------------
    retirement_value_median = float(np.median(mc_values[:, years_to_retire]))
    annual_income = retirement_value_median * params.withdrawal_rate

    logger.info(
        "Projection — monthly=$%.0f  div=$%.0f/yr  success=%.1f%%  median@retire=$%.0f",
        params.total_monthly_contribution,
        params.annual_dividend_income,
        success_probability * 100,
        retirement_value_median,
    )

    return ProjectionResult(
        deterministic=det,
        mc_median=mc_median,
        mc_p10=mc_p10,
        mc_p90=mc_p90,
        success_probability=success_probability,
        retirement_value_median=retirement_value_median,
        annual_income_at_retirement=annual_income,
        params=params,
    )
