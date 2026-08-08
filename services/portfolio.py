"""
services/portfolio.py
======================
Portfolio aggregation service.

Provides high-level read-only queries that the dashboard and other UI frames
use to display summary statistics without duplicating query logic.

Public API
----------
get_net_worth(session)                      → float
get_account_balances(session)               → list[dict]
get_asset_allocation(session)               → dict[str, float]
get_total_contributions_ytd(session)        → float
get_total_dividends_ytd(session)            → float
get_holdings_summary(session)               → list[dict]
get_scheduled_contribution_summary(session) → dict  (monthly/annual totals + breakdown)
refresh_prices(session)                     → None   (updates last_price on all assets)
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from db.models import Account, Asset, Transaction, TransactionType
from services.market import get_multi_ticker_prices

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Net worth
# ---------------------------------------------------------------------------

def get_net_worth(session: Session) -> float:
    """
    Return total portfolio net worth across all active accounts.

    Uses the cached ``last_price`` on each asset; call :func:`refresh_prices`
    first if you need current market values.
    """
    assets: list[Asset] = (
        session.query(Asset)
        .join(Account)
        .filter(Account.is_active == True)
        .all()
    )
    return sum(a.market_value for a in assets)


# ---------------------------------------------------------------------------
# Account balances
# ---------------------------------------------------------------------------

def get_account_balances(session: Session) -> list[dict]:
    """
    Return a list of account balance summaries, one dict per account.

    Each dict contains:
    ``id``, ``name``, ``type``, ``institution``, ``balance``,
    ``cost_basis``, ``unrealized_gain``, ``asset_count``.
    """
    accounts: list[Account] = (
        session.query(Account).filter(Account.is_active == True).all()
    )
    result = []
    for acc in accounts:
        balance = sum(a.market_value for a in acc.assets)
        cost = sum(a.cost_basis for a in acc.assets)
        result.append(
            {
                "id": acc.id,
                "name": acc.name,
                "type": acc.account_type.value,
                "institution": acc.institution,
                "balance": balance,
                "cost_basis": cost,
                "unrealized_gain": balance - cost,
                "asset_count": len(acc.assets),
            }
        )
    result.sort(key=lambda x: x["balance"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Asset allocation
# ---------------------------------------------------------------------------

def get_asset_allocation(session: Session) -> dict[str, float]:
    """
    Return portfolio allocation by asset class as percentages (0–100).

    Returns ``{"stocks": 65.3, "bonds": 20.1, "reits": 10.0, "cash": 4.6}``.
    """
    assets: list[Asset] = (
        session.query(Asset)
        .join(Account)
        .filter(Account.is_active == True)
        .all()
    )
    totals: dict[str, float] = {}
    grand_total = 0.0

    for a in assets:
        mv = a.market_value
        totals[a.asset_class] = totals.get(a.asset_class, 0.0) + mv
        grand_total += mv

    if grand_total == 0:
        return {}

    return {cls: (val / grand_total) * 100 for cls, val in totals.items()}


# ---------------------------------------------------------------------------
# Year-to-date summaries
# ---------------------------------------------------------------------------

def _ytd_sum(session: Session, tx_type: TransactionType) -> float:
    """Sum transaction amounts for *tx_type* since Jan 1 of the current year."""
    jan1 = date(date.today().year, 1, 1)
    rows = (
        session.query(Transaction)
        .filter(
            Transaction.transaction_type == tx_type,
            Transaction.transaction_date >= jan1,
        )
        .all()
    )
    return sum(tx.amount for tx in rows)


def get_total_contributions_ytd(session: Session) -> float:
    """Return total contributions made so far this calendar year (USD)."""
    return _ytd_sum(session, TransactionType.CONTRIBUTION)


def get_total_dividends_ytd(session: Session) -> float:
    """Return total dividend income received so far this calendar year (USD)."""
    return _ytd_sum(session, TransactionType.DIVIDEND)


# ---------------------------------------------------------------------------
# Holdings summary
# ---------------------------------------------------------------------------

def get_holdings_summary(session: Session, include_price_changes: bool = False) -> list[dict]:
    """
    Return a flat list of all holdings with enriched display columns.

    Parameters
    ----------
    session : Session
    include_price_changes : bool
        When True, makes a live yfinance call to fetch day-change and 30-day
        change for each ticker.  Set False (default) for fast DB-only reads.

    Each dict contains:
    ``ticker``, ``name``, ``account_name``, ``account_type``, ``shares``,
    ``last_price``, ``market_value``, ``cost_basis``, ``unrealized_gain``,
    ``unrealized_gain_pct``, ``dividend_yield``, ``drip``, ``asset_class``,
    ``day_change``, ``day_change_pct``, ``change_30d_pct``.
    """
    from services.market import get_price_changes

    assets: list[Asset] = (
        session.query(Asset)
        .join(Account)
        .filter(Account.is_active == True, Asset.shares > 0)
        .all()
    )

    # Optionally fetch live price-change data for all tickers in one batch call
    changes: dict[str, dict] = {}
    if include_price_changes and assets:
        tickers = list({a.ticker for a in assets})
        changes = get_price_changes(tickers)

    rows = []
    for a in assets:
        mv   = a.market_value
        cost = a.cost_basis
        gain = mv - cost
        # All-time unrealized gain vs entered cost basis
        gain_pct = (gain / cost * 100) if cost > 0 else 0.0

        ch = changes.get(a.ticker, {})
        rows.append(
            {
                "ticker":           a.ticker,
                "name":             a.name,
                "account_name":     a.account.name,
                "account_type":     a.account.account_type.value,
                "shares":           a.shares,
                "last_price":       a.last_price,
                "market_value":     mv,
                "cost_basis":       cost,
                "unrealized_gain":  gain,
                "unrealized_gain_pct": gain_pct,
                "dividend_yield":   a.dividend_yield,
                "drip":             a.drip_enabled,
                "asset_class":      a.asset_class,
                # Live price-change metrics (None if not fetched or unavailable)
                "day_change":       ch.get("day_change"),
                "day_change_pct":   ch.get("day_change_pct"),
                "change_30d_pct":   ch.get("change_30d_pct"),
            }
        )
    rows.sort(key=lambda x: x["market_value"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Scheduled contribution summary (feeds the projection engine)
# ---------------------------------------------------------------------------

_MONTHLY_FACTORS = {
    "Weekly":    52 / 12,
    "Biweekly":  26 / 12,
    "Monthly":   1.0,
    "Quarterly": 1 / 3,
    "Annually":  1 / 12,
}


def get_scheduled_contribution_summary(session: Session) -> dict:
    """
    Aggregate all active recurring investments into monthly and annual totals.

    Returns
    -------
    dict with keys:
    - ``monthly_total``  — sum of all active recurring contributions converted
                           to a monthly equivalent (USD)
    - ``annual_total``   — monthly_total × 12
    - ``breakdown``      — list of dicts per rule:
                           {account_name, ticker, amount, frequency, monthly_eq}
    """
    from db.models import ScheduledContrib

    rows: list[ScheduledContrib] = (
        session.query(ScheduledContrib)
        .filter(ScheduledContrib.is_active == True)
        .all()
    )

    breakdown = []
    monthly_total = 0.0

    for r in rows:
        factor     = _MONTHLY_FACTORS.get(r.frequency.value, 1.0)
        monthly_eq = r.amount * factor
        monthly_total += monthly_eq

        ticker       = r.asset.ticker if r.asset_id and r.asset else "—"
        account_name = r.account.name if r.account else "—"

        breakdown.append({
            "account_name": account_name,
            "ticker":       ticker,
            "amount":       r.amount,
            "frequency":    r.frequency.value,
            "monthly_eq":   monthly_eq,
        })

    breakdown.sort(key=lambda x: x["monthly_eq"], reverse=True)

    return {
        "monthly_total": monthly_total,
        "annual_total":  monthly_total * 12,
        "breakdown":     breakdown,
    }


# ---------------------------------------------------------------------------
# Price refresh
# ---------------------------------------------------------------------------

def refresh_prices(session: Session) -> int:
    """
    Fetch current market prices for all active holdings and update the DB.

    Parameters
    ----------
    session : Session
        Active session (caller owns commit).

    Returns
    -------
    int
        Number of assets updated.
    """
    from datetime import datetime

    assets: list[Asset] = (
        session.query(Asset)
        .join(Account)
        .filter(Account.is_active == True, Asset.shares > 0)
        .all()
    )
    tickers = list({a.ticker for a in assets})
    if not tickers:
        return 0

    prices = get_multi_ticker_prices(tickers)
    now = datetime.utcnow()
    updated = 0

    for asset in assets:
        price = prices.get(asset.ticker)
        if price is not None and price > 0:
            asset.last_price = price
            asset.price_updated_at = now
            updated += 1

    session.flush()
    logger.info("Refreshed prices for %d assets", updated)
    return updated


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------

def get_or_create_profile(session: Session):
    """
    Return the single :class:`~db.models.UserProfile` row, creating it
    with defaults if it does not yet exist.
    """
    from db.models import UserProfile
    profile = session.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1, name="", date_of_birth=None)
        session.add(profile)
        session.flush()
    return profile


def save_profile(session: Session, name: str, dob) -> None:
    """Persist name and date_of_birth to the UserProfile row."""
    from db.models import UserProfile
    from datetime import datetime as _dt
    profile = get_or_create_profile(session)
    profile.name = name
    profile.date_of_birth = dob
    profile.updated_at = _dt.utcnow()
    session.flush()


# ---------------------------------------------------------------------------
# Portfolio snapshots  (daily net-worth history)
# ---------------------------------------------------------------------------

def record_snapshot(session: Session) -> bool:
    """
    Record today's total portfolio value as a :class:`~db.models.PortfolioSnapshot`.

    Only creates one snapshot per calendar day — safe to call on every
    app startup.

    Returns
    -------
    bool
        ``True`` if a new snapshot was recorded, ``False`` if one already
        existed for today.
    """
    import json
    from datetime import date
    from db.models import PortfolioSnapshot

    today = date.today()
    existing = session.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.snapshot_date == today
    ).first()
    if existing:
        return False

    balances = get_account_balances(session)
    total    = sum(b["balance"] for b in balances)
    breakdown = {b["name"]: b["balance"] for b in balances}

    snap = PortfolioSnapshot(
        snapshot_date=today,
        total_value=total,
        account_breakdown=json.dumps(breakdown),
    )
    session.add(snap)
    session.flush()
    logger.info("Portfolio snapshot recorded: $%.2f on %s", total, today)
    return True


def get_snapshot_history(session: Session, days: int = 365) -> list[dict]:
    """
    Return portfolio snapshot history for the past *days* calendar days,
    sorted oldest → newest.

    Parameters
    ----------
    days : int
        How many calendar days back to look (default 365 = 1 year).

    Returns
    -------
    list[dict]
        Each dict has ``date``, ``total_value``, ``account_breakdown`` (dict).
    """
    import json
    from datetime import date, timedelta
    from db.models import PortfolioSnapshot

    since = date.today() - timedelta(days=days)
    rows = (
        session.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.snapshot_date >= since)
        .order_by(PortfolioSnapshot.snapshot_date)
        .all()
    )
    return [
        {
            "date":             r.snapshot_date,
            "total_value":      r.total_value,
            "account_breakdown": json.loads(r.account_breakdown or "{}"),
        }
        for r in rows
    ]
